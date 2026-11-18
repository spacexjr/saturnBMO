#!/usr/bin/env python3
"""Verificação real do Qwen3-ASR local no Ollama.

Exemplos::

    ollama pull frozenlab/qwen3-asr:0.6b
    backend/.venv/bin/python scripts/check_asr.py --text "Ei BMO, que horas são?"
    backend/.venv/bin/python scripts/check_asr.py --wav /tmp/pergunta.wav

O script não usa serviços pagos nem inventa transcrição: ele fala o texto
informado com o Piper/espeak-ng local, envia o WAV ao Ollama e imprime o que o
modelo realmente devolveu. Sai com código 1 quando o áudio não é transcrito.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from bmo_backend.config import BACKEND_DIR as CONFIG_BACKEND_DIR, load_config  # noqa: E402
from bmo_backend.qwen_asr import QwenAsrStt  # noqa: E402
from bmo_backend.stt import SttError, SttUnavailable  # noqa: E402

DEFAULT_TEXT = "Ei BMO, que horas são agora?"


def synthesize(text: str, output: Path, config: dict) -> None:
    """Gera um WAV de fala em português usando o TTS local disponível."""
    tts = config.get("tts", {})
    piper = Path(str(tts.get("piper_binary") or ""))
    voice = Path(str(tts.get("voice_model") or ""))
    if piper.is_file() and voice.is_file():
        proc = subprocess.run(
            [str(piper), "--model", str(voice), "--output_file", str(output)],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode == 0 and output.is_file() and output.stat().st_size > 44:
            return
        detail = proc.stderr.decode("utf-8", "ignore")[-300:]
        raise SystemExit(f"Piper falhou ao gerar o áudio: {detail}")

    espeak = shutil.which(str(tts.get("espeak_binary") or "espeak-ng"))
    if espeak:
        proc = subprocess.run(
            [espeak, "-v", str(tts.get("espeak_voice") or "pt-br"), "-w", str(output), text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode == 0 and output.is_file() and output.stat().st_size > 44:
            return
    raise SystemExit(
        "Nenhum TTS local disponível para gerar o áudio de teste. "
        "Use --wav com um arquivo WAV PCM 16-bit mono."
    )


def load_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise SystemExit("O WAV precisa ser PCM 16-bit.")
        return wav.readframes(wav.getnframes()), wav.getframerate()


async def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    cfg = dict(config.get("stt", {}))
    if args.model:
        cfg["model"] = args.model
    if args.base_url:
        cfg["base_url"] = args.base_url
    if args.language:
        cfg["language"] = args.language
    stt = QwenAsrStt(cfg)

    print(f"Ollama: {stt.base_url}")
    print(f"Modelo ASR: {stt.model}")
    if not await stt.refresh_availability(force=True):
        print(f"ERRO: {stt.status().get('last_error')}")
        print("Dica: ollama serve  &&  ollama pull frozenlab/qwen3-asr:0.6b")
        return 2

    if args.wav:
        wav_path = Path(args.wav).expanduser()
        if not wav_path.is_file():
            raise SystemExit(f"WAV não encontrado: {wav_path}")
        pcm, rate = load_wav(wav_path)
        print(f"Áudio: {wav_path} ({rate} Hz)")
    else:
        with tempfile.TemporaryDirectory(prefix="bmo-asr-check-") as tmp:
            wav_path = Path(tmp) / "fala.wav"
            synthesize(args.text, wav_path, config)
            pcm, rate = load_wav(wav_path)
            print(f"Áudio gerado por TTS local: {wav_path} ({rate} Hz)")

    try:
        result = await stt.transcribe(pcm, sample_rate=rate)
    except SttUnavailable as exc:
        print(f"ERRO: {exc}")
        return 2
    except SttError as exc:
        print(f"ERRO: {exc}")
        return 1

    print(f"Idioma: {result.language}")
    print(f"Áudio: {result.duration_ms} ms")
    print(f"Latência: {result.latency_ms} ms")
    print(f"Motor: {result.engine}")
    print(f"Transcrição: {result.text!r}")
    if not result.text.strip():
        print("ERRO: o modelo não devolveu texto para este áudio.")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica o Qwen3-ASR local no Ollama")
    parser.add_argument("--wav", help="WAV PCM 16-bit para transcrever")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="texto falado pelo TTS local")
    parser.add_argument("--model", help="modelo Ollama (padrão: config.json)")
    parser.add_argument("--base-url", help="URL do Ollama (padrão: http://127.0.0.1:11434)")
    parser.add_argument("--language", help="idioma esperado (padrão: pt-BR)")
    parser.add_argument("--config", help="caminho alternativo do config.json")
    args = parser.parse_args()
    # Garante que o import use o backend do repositório mesmo fora dele.
    if not CONFIG_BACKEND_DIR.exists():  # pragma: no cover - sanidade
        raise SystemExit("Diretório backend não encontrado.")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
