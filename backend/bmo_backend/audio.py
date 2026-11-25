"""Processamento de áudio PCM, VAD e conversão WAV."""

from __future__ import annotations

import io
import math
import struct
import wave
from array import array
from collections import deque
from dataclasses import dataclass
from sys import byteorder


def pcm16_rms(data: bytes) -> float:
    """Retorna RMS normalizado (0.0 a 1.0) de PCM 16-bit little endian."""
    if not data:
        return 0.0
    if len(data) % 2:
        data = data[:-1]
    samples = array("h")
    samples.frombytes(data)
    if byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    mean_square = sum(float(sample) * float(sample) for sample in samples) / len(samples)
    return min(1.0, math.sqrt(mean_square) / 32768.0)


def pcm16_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return out.getvalue()


def split_wav(wav_bytes: bytes) -> tuple[bytes, int, int]:
    """Retorna (pcm, sample_rate, channels) de um WAV PCM."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError("somente WAV PCM 16-bit é suportado")
        return wav.readframes(wav.getnframes()), wav.getframerate(), wav.getnchannels()


def wav_duration(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        rate = wav.getframerate()
        return wav.getnframes() / rate if rate else 0.0


@dataclass
class VadEvent:
    kind: str  # "speech_start" | "speech_end"
    utterance: bytes = b""


class EnergyVad:
    """VAD simples por energia, com pré-buffer e piso de ruído adaptativo.

    Não é um VAD neural. Funciona bem em ambiente doméstico com ruído
    moderado; o limiar pode ser ajustado em config.json.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 20,
        min_rms: float = 0.012,
        start_ms: int = 180,
        end_silence_ms: int = 700,
        pre_roll_ms: int = 300,
        min_utterance_ms: int = 350,
        max_utterance_s: float = 15.0,
        calibration_ms: int = 250,
        noise_window_ms: int = 2500,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_bytes = max(2, int(sample_rate * frame_ms / 1000) * 2)
        self.min_rms = min_rms
        self.start_frames = max(1, math.ceil(start_ms / frame_ms))
        self.end_frames = max(1, math.ceil(end_silence_ms / frame_ms))
        self.pre_roll: deque[bytes] = deque(maxlen=max(1, math.ceil(pre_roll_ms / frame_ms)))
        self.min_utterance_bytes = int(sample_rate * min_utterance_ms / 1000) * 2
        self.max_utterance_bytes = int(sample_rate * max_utterance_s) * 2
        # O piso de ruído é estimado pelo percentil 20 das últimas 2,5 s de
        # energia. Diferente da média móvel antiga, ele é atualizado também
        # durante a fala e não "trava" quando o ruído de fundo já começa acima
        # do mínimo: sem isto, qualquer ambiente barulhento virava fala
        # contínua, o VAD cortava trechos de ~1 s e cada trecho ia para o ASR.
        self.calibration_frames = max(1, math.ceil(calibration_ms / frame_ms))
        self.noise_frames = max(self.calibration_frames, math.ceil(noise_window_ms / frame_ms))
        self._energies: deque[float] = deque(maxlen=self.noise_frames)
        self._calibration_left = self.calibration_frames
        self.reset()

    def reset(self) -> None:
        self._pending = bytearray()
        self._speaking = False
        self._speech_run = 0
        self._silence_run = 0
        self._utterance = bytearray()
        self.pre_roll.clear()
        self._energies.clear()
        self._calibration_left = self.calibration_frames
        self.noise_floor = 0.0

    @property
    def speaking(self) -> bool:
        return self._speaking

    def _update_noise_floor(self) -> None:
        if not self._energies:
            self.noise_floor = 0.0
            return
        ordered = sorted(self._energies)
        index = min(len(ordered) - 1, int(len(ordered) * 0.2))
        self.noise_floor = ordered[index]

    def _threshold(self) -> float:
        # Exige energia acima do ruído ambiente. O teto (6x o mínimo) evita que
        # um ambiente muito barulhento esconda a fala; o piso (min_rms) evita
        # que o silêncio absoluto gere detecções.
        return max(self.min_rms, min(self.noise_floor * 3.0, self.min_rms * 6.0))

    def feed(self, data: bytes) -> list[VadEvent]:
        if not data:
            return []
        self._pending.extend(data)
        events: list[VadEvent] = []
        while len(self._pending) >= self.frame_bytes:
            frame = bytes(self._pending[: self.frame_bytes])
            del self._pending[: self.frame_bytes]
            events.extend(self._process_frame(frame))
        return events

    def _process_frame(self, frame: bytes) -> list[VadEvent]:
        energy = pcm16_rms(frame)
        self._energies.append(energy)
        self._update_noise_floor()
        threshold = self._threshold()
        is_speech = energy >= threshold

        if not self._speaking:
            self.pre_roll.append(frame)
            if self._calibration_left > 0:
                # Calibração inicial: aprende o ruído ambiente antes de aceitar
                # que um pico isolado seja fala.
                self._calibration_left -= 1
                return []
            if not is_speech:
                return []
            self._speech_run += 1
            if self._speech_run < self.start_frames:
                return []
            self._speaking = True
            self._silence_run = 0
            self._utterance = bytearray()
            for item in self.pre_roll:
                self._utterance.extend(item)
            self.pre_roll.clear()
            return [VadEvent("speech_start")]

        self._utterance.extend(frame)
        if is_speech:
            self._silence_run = 0
        else:
            self._silence_run += 1

        if len(self._utterance) >= self.max_utterance_bytes:
            return [self._finish()]
        if self._silence_run >= self.end_frames:
            return [self._finish()]
        return []

    def flush(self) -> list[VadEvent]:
        """Finaliza a fala atual ao receber audio.end."""
        if self._pending:
            frame = bytes(self._pending)
            self._pending.clear()
            if self._speaking:
                self._utterance.extend(frame)
        if self._speaking:
            return [self._finish()]
        return []

    def _finish(self) -> VadEvent:
        utterance = bytes(self._utterance)
        self._speaking = False
        self._speech_run = 0
        self._silence_run = 0
        self._utterance = bytearray()
        self.pre_roll.clear()
        if len(utterance) < self.min_utterance_bytes:
            return VadEvent("speech_end", b"")
        return VadEvent("speech_end", utterance)


def silence_pcm(ms: int, sample_rate: int = 16000) -> bytes:
    return struct.pack("<h", 0) * int(sample_rate * ms / 1000)
