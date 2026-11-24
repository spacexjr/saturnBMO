"""Teste de campo do detector acústico do saturnBMO.

Usa ``arecord`` (ALSA/PipeWire) em PCM s16le mono 16 kHz, sem PyAudio.
Também aceita um WAV PCM 16-bit mono para validar o modelo offline.

Exemplos:
    python -m bmo_backend.wakeword_cli --list-devices
    python -m bmo_backend.wakeword_cli --device plughw:2,0
    python -m bmo_backend.wakeword_cli --device "USB HIFI AUDIO"
    python -m bmo_backend.wakeword_cli --wav teste.wav --threshold 0.95
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

from .acoustic_wakeword import WINDOW_SAMPLES, AcousticWakeWord
from .config import BACKEND_DIR, load_config, resolve_runtime_paths

SAMPLE_RATE = 16000
CHUNK_BYTES = 3200


def list_devices() -> int:
    if not shutil.which("arecord"):
        print("arecord não encontrado. Instale alsa-utils.", file=sys.stderr)
        return 1
    subprocess.run(["arecord", "-l"], check=False)
    return 0


def resolve_device(value: str | None) -> str | None:
    if not value:
        return None
    if value.isdigit() or ":" in value or value.startswith("plughw") or value.startswith("hw:"):
        return value
    out = subprocess.run(["arecord", "-l"], capture_output=True, text=True, check=False).stdout
    needle = value.lower()
    for line in out.splitlines():
        if needle in line.lower():
            try:
                card = line.split("card", 1)[1].split(":", 1)[0].strip()
                device = line.split("device", 1)[1].split(":", 1)[0].strip()
                return f"plughw:{card},{device}"
            except (IndexError, ValueError):
                continue
    print(f"Dispositivo não encontrado: {value}", file=sys.stderr)
    return None


def build_detector(args: argparse.Namespace) -> AcousticWakeWord:
    config = load_config(args.config or (BACKEND_DIR / "config.json"))
    resolve_runtime_paths(config)
    wakeword = config.get("wakeword", {})

    model = args.model or wakeword.get("acoustic_model")
    mel = args.mel or wakeword.get("mel_model")
    embedding = args.embedding or wakeword.get("embedding_model")
    if not model or not mel or not embedding:
        raise SystemExit("Caminhos dos modelos ausentes. Informe --model, --mel e --embedding.")

    return AcousticWakeWord(
        model_path=model,
        mel_path=mel,
        embedding_path=embedding,
        threshold=args.threshold
        if args.threshold is not None
        else float(wakeword.get("threshold", 0.95)),
        cooldown_s=args.cooldown
        if args.cooldown is not None
        else float(wakeword.get("cooldown_s", 2.5)),
        hop_s=args.hop_ms / 1000.0,
        min_consecutive=args.min_consecutive
        if args.min_consecutive is not None
        else int(wakeword.get("min_consecutive", 3)),
    )


def run_wav(path: Path, detector: AcousticWakeWord) -> int:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise SystemExit("O WAV precisa ser PCM 16-bit mono.")
        if wav.getframerate() != SAMPLE_RATE:
            raise SystemExit(f"O WAV precisa ter {SAMPLE_RATE} Hz.")
        frames = wav.readframes(wav.getnframes())
    if len(frames) < WINDOW_SAMPLES * 2:
        frames = b"\x00" * (WINDOW_SAMPLES * 2 - len(frames)) + frames
    frames += b"\x00" * (SAMPLE_RATE * 2 * 2)

    total = 0
    detections = 0
    for offset in range(0, len(frames), CHUNK_BYTES):
        chunk = frames[offset : offset + CHUNK_BYTES]
        total += len(chunk) // 2
        for detection in detector.feed(chunk):
            detections += 1
            print(
                f"Detectado em {total / SAMPLE_RATE:.2f}s "
                f"(score={detection.score:.3f})"
            )
    print(f"Processado {total / SAMPLE_RATE:.2f}s; detecções: {detections}")
    return 0 if detections else 1


def run_microphone(device: str | None, detector: AcousticWakeWord) -> int:
    cmd = ["arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw", "-q"]
    if device:
        cmd[1:1] = ["-D", device]
    print("Monitorando", device or "dispositivo padrão", "- Ctrl+C para sair")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    try:
        while True:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                print("arecord encerrou.", file=sys.stderr)
                return 1
            for detection in detector.feed(chunk):
                stamp = time.strftime("%H:%M:%S")
                print(f"[{stamp}] BMO detectado  score={detection.score:.3f}")
    except KeyboardInterrupt:
        print("\nEncerrado.")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor de wake word do saturnBMO")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--device", help="Índice ALSA, plughw:C,D ou trecho do nome")
    parser.add_argument("--wav", type=Path, help="WAV PCM 16-bit mono 16 kHz para teste offline")
    parser.add_argument("--config", type=Path, help="config.json alternativo")
    parser.add_argument("--model", type=Path, help="classificador ONNX")
    parser.add_argument("--mel", type=Path, help="melspectrogram.onnx")
    parser.add_argument("--embedding", type=Path, help="embedding_model.onnx")
    parser.add_argument("--threshold", type=float, help="score mínimo (padrão: config.json)")
    parser.add_argument("--cooldown", type=float, help="cooldown em segundos")
    parser.add_argument("--hop-ms", type=float, default=100.0, help="intervalo entre inferências")
    parser.add_argument("--min-consecutive", type=int, help="janelas consecutivas acima do limiar")
    args = parser.parse_args()

    if args.list_devices:
        return list_devices()

    detector = build_detector(args)
    if args.wav:
        return run_wav(args.wav, detector)

    device = resolve_device(args.device)
    if args.device and not device:
        return 2
    return run_microphone(device, detector)


if __name__ == "__main__":
    raise SystemExit(main())
