"""Teste de campo do detector acústico usando o microfone do PC.

Não depende de PyAudio: usa ``arecord`` (ALSA/PipeWire) em PCM s16le mono
16 kHz. Serve para validar o modelo sem o aplicativo Android.

Exemplos:
    python -m bmo_backend.wakeword_cli --list-devices
    python -m bmo_backend.wakeword_cli --device plughw:2,0
    python -m bmo_backend.wakeword_cli --device "USB HIFI AUDIO" --threshold 0.6
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .acoustic_wakeword import AcousticWakeWord

DEFAULT_ASSETS = Path(__file__).resolve().parents[2] / "assets" / "wakeword"


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
            # Formato: "card 2: Generic_1 [...], device 0: ALC897 Analog [...]"
            try:
                card = line.split("card", 1)[1].split(":", 1)[0].strip()
                device = line.split("device", 1)[1].split(":", 1)[0].strip()
                return f"plughw:{card},{device}"
            except (IndexError, ValueError):
                continue
    print(f"Dispositivo não encontrado: {value}", file=sys.stderr)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor de wake word do saturnBMO")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--device", default=None, help="Índice ALSA, plughw:C,D ou trecho do nome")
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--cooldown", type=float, default=2.0)
    parser.add_argument("--hop-ms", type=float, default=100.0)
    args = parser.parse_args()

    if args.list_devices:
        return list_devices()

    device = resolve_device(args.device)
    model = args.model or args.assets / "saturnbmo.onnx"
    detector = AcousticWakeWord(
        model_path=model,
        mel_path=args.assets / "melspectrogram.onnx",
        embedding_path=args.assets / "embedding_model.onnx",
        threshold=args.threshold,
        cooldown_s=args.cooldown,
        hop_s=args.hop_ms / 1000.0,
    )

    cmd = ["arecord", "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw", "-q"]
    if device:
        cmd[1:1] = ["-D", device]
    print("Monitorando", device or "dispositivo padrão", "- Ctrl+C para sair")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    try:
        while True:
            chunk = proc.stdout.read(3200)  # 100 ms
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


if __name__ == "__main__":
    raise SystemExit(main())
