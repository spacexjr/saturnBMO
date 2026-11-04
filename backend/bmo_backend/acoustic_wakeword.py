"""Detector acústico de wake word do saturnBMO.

Executa o pipeline congelado do livekit-wakeword inteiramente local:

    PCM 16 kHz -> melspectrogram.onnx -> embedding_model.onnx -> saturnbmo.onnx

Os três arquivos ONNX ficam em ``assets/wakeword/``. O detector NÃO depende do
LLM, do Whisper ou de serviços externos. Ele recebe os mesmos blocos PCM que o
aplicativo Android já envia ao backend.

Formato de entrada do classificador: (1, 16, 96) float32.
Formato de saída: (1, 1) float32, score 0..1.

O áudio bruto NÃO pode ser passado diretamente ao classificador: é obrigatório
extrair mel (76 quadros) + embedding (16 passos) antes.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
WINDOW_SECONDS = 2.0
WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_SECONDS)
MEL_WINDOW = 76
MEL_STRIDE = 8
EMBEDDING_STEPS = 16
EMBEDDING_DIM = 96


@dataclass
class AcousticDetection:
    score: float
    timestamp: float


class AcousticWakeWord:
    """Detector incremental com janela deslizante e cooldown.

    Args:
        model_path: classificador ONNX exportado (saturnbmo.onnx).
        mel_path: melspectrogram.onnx do livekit-wakeword.
        embedding_path: embedding_model.onnx do livekit-wakeword.
        threshold: score mínimo para ativar (0..1). Maior = menos falsos positivos.
        cooldown_s: tempo mínimo entre ativações.
        hop_s: intervalo entre inferências (100 ms = baixa latência).
        min_consecutive: número de inferências consecutivas acima do limiar.
    """

    def __init__(
        self,
        model_path: str | Path,
        mel_path: str | Path,
        embedding_path: str | Path,
        *,
        threshold: float = 0.5,
        cooldown_s: float = 2.0,
        hop_s: float = 0.1,
        min_consecutive: int = 1,
    ) -> None:
        import onnxruntime as ort

        for label, path in (
            ("classificador", model_path),
            ("mel", mel_path),
            ("embedding", embedding_path),
        ):
            if not Path(path).is_file():
                raise FileNotFoundError(f"Modelo {label} não encontrado: {path}")

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._mel = ort.InferenceSession(str(mel_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self._emb = ort.InferenceSession(
            str(embedding_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._clf = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._mel_input = self._mel.get_inputs()[0].name
        self._emb_input = self._emb.get_inputs()[0].name
        self._clf_input = self._clf.get_inputs()[0].name

        self.threshold = float(threshold)
        self.cooldown_s = float(cooldown_s)
        self.hop_samples = max(1, int(hop_s * SAMPLE_RATE))
        self.min_consecutive = max(1, int(min_consecutive))

        self._buffer: deque[np.ndarray] = deque()
        self._buffered = 0
        self._since_infer = 0
        self._last_detection = 0.0
        self._consecutive = 0
        self._running = True

    # -- controle ---------------------------------------------------------

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def reset(self) -> None:
        self._buffer.clear()
        self._buffered = 0
        self._since_infer = 0
        self._consecutive = 0

    @property
    def running(self) -> bool:
        return self._running

    # -- áudio ------------------------------------------------------------

    def feed(self, pcm: bytes) -> list[AcousticDetection]:
        """Recebe PCM s16le mono 16 kHz e retorna detecções."""
        if not self._running or not pcm or len(pcm) < 2:
            return []
        if len(pcm) % 2:
            pcm = pcm[:-1]
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        return self.feed_samples(samples)

    def feed_samples(self, samples: np.ndarray) -> list[AcousticDetection]:
        if not self._running or samples.size == 0:
            return []

        self._buffer.append(samples.astype(np.float32, copy=False))
        self._buffered += samples.size
        while self._buffered > WINDOW_SAMPLES:
            excess = self._buffered - WINDOW_SAMPLES
            head = self._buffer[0]
            if head.size <= excess:
                self._buffer.popleft()
                self._buffered -= head.size
            else:
                self._buffer[0] = head[excess:]
                self._buffered -= excess

        if self._buffered < WINDOW_SAMPLES:
            return []

        self._since_infer += samples.size
        if self._since_infer < self.hop_samples:
            return []
        self._since_infer = 0

        window = np.concatenate(self._buffer, axis=0)
        score = self.predict(window)
        now = time.monotonic()
        detections: list[AcousticDetection] = []

        if score >= self.threshold:
            self._consecutive += 1
        else:
            self._consecutive = 0

        if self._consecutive >= self.min_consecutive and now - self._last_detection >= self.cooldown_s:
            self._last_detection = now
            self._consecutive = 0
            detections.append(AcousticDetection(score=float(score), timestamp=now))
            # Evita reativar com a cauda da mesma palavra.
            self.reset()
        return detections

    # -- inferência -------------------------------------------------------

    def predict(self, audio: np.ndarray) -> float:
        """Executa o pipeline completo em uma janela de exatamente 2 s."""
        audio = np.asarray(audio, dtype=np.float32).flatten()
        if audio.size < WINDOW_SAMPLES:
            padded = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
            padded[-audio.size :] = audio
            audio = padded
        elif audio.size > WINDOW_SAMPLES:
            audio = audio[-WINDOW_SAMPLES:]

        mel = self._mel.run(None, {self._mel_input: audio[np.newaxis, :]})[0]
        if mel.ndim == 4:
            mel = mel[:, 0, :, :]
        mel = mel / 10.0 + 2.0

        frames = mel[0]
        n_windows = max(0, (frames.shape[0] - MEL_WINDOW) // MEL_STRIDE + 1)
        if n_windows == 0:
            return 0.0
        windows = np.stack(
            [frames[i * MEL_STRIDE : i * MEL_STRIDE + MEL_WINDOW] for i in range(n_windows)],
            axis=0,
        )
        embeddings = self._emb.run(None, {self._emb_input: windows[..., np.newaxis]})[0]
        embeddings = embeddings.reshape(-1, EMBEDDING_DIM)
        if embeddings.shape[0] < EMBEDDING_STEPS:
            pad = np.zeros((EMBEDDING_STEPS - embeddings.shape[0], EMBEDDING_DIM), dtype=np.float32)
            embeddings = np.concatenate([pad, embeddings], axis=0)
        seq = embeddings[-EMBEDDING_STEPS:][np.newaxis, :, :].astype(np.float32)
        output = self._clf.run(None, {self._clf_input: seq})[0]
        return float(np.asarray(output).reshape(-1)[0])
