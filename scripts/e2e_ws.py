#!/usr/bin/env python3
"""Teste de integração ponta a ponta via WebSocket, usando serviços reais.

Uso:
    .venv/bin/python ../scripts/e2e_ws.py --text "Ei, BMO, conte uma piada curta."

O script sintetiza a fala com o Piper do PC (simulando o microfone do
Android), envia PCM 16 kHz em blocos, imprime os eventos recebidos e salva o
áudio da resposta em /tmp/bmo-resposta.wav.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import websockets

from bmo_backend.config import load_config
from bmo_backend.tts import TtsService


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=None)
    parser.add_argument("--text", default="Ei, BMO, conte uma piada curta.")
    parser.add_argument("--audio", help="WAV já existente em vez de sintetizar")
    parser.add_argument("--output", default="/tmp/bmo-resposta.wav")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Simula o toque em 'Falar agora' (activate) para testar STT/LLM/ferramentas sem depender da wake word.",
    )
    args = parser.parse_args()

    config = load_config()
    token = args.token or config["_token"]

    if args.audio:
        source = Path(args.audio)
    else:
        tts = TtsService(config["tts"])
        audio = await tts.synthesize(args.text)
        source = Path(tempfile.mkstemp(suffix=".wav")[1])
        source.write_bytes(audio.wav)
        print(f"[teste] Fala sintetizada ({audio.duration_s:.1f}s, {audio.sample_rate} Hz)")

    converted = Path(tempfile.mkstemp(suffix=".wav")[1])
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", str(converted)],
        check=True,
    )
    with wave.open(str(converted), "rb") as wav:
        pcm = wav.readframes(wav.getnframes())
    print(f"[teste] PCM: {len(pcm)} bytes")

    uri = f"ws://{args.host}:{args.port}/ws"
    headers = {"Authorization": f"Bearer {token}"}
    async with websockets.connect(uri, additional_headers=headers, max_size=4 * 1024 * 1024) as ws:
        hello = json.loads(await ws.recv())
        print(f"[teste] Protocolo: {hello.get('protocol')} sessão {hello.get('session_id')}")
        state = json.loads(await ws.recv())
        print(f"[teste] Estado inicial: {state.get('state')}")

        await ws.send(json.dumps({
            "type": "audio.start", "format": "pcm_s16le", "sample_rate": 16000, "channels": 1,
        }))
        while True:
            ready = json.loads(await ws.recv())
            if ready.get("type") == "audio.ready":
                break
        print(f"[teste] Áudio pronto: {ready.get('type')}")
        if args.activate:
            await ws.send(json.dumps({"type": "activate"}))
            print("[teste] Ativação manual enviada (sem wake word).")

        frame = 640  # 20 ms a 16 kHz mono PCM16
        for offset in range(0, len(pcm), frame):
            await ws.send(pcm[offset:offset + frame])
            await asyncio.sleep(0.005)
        await ws.send(json.dumps({"type": "audio.end"}))

        audio_chunks: list[bytes] = []
        audio_rate = 22050
        transcript = ""
        response = ""
        faces: list[dict] = []
        restores: list[dict] = []
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                print("[teste] ERRO: timeout aguardando resposta")
                return 2
            if isinstance(message, bytes):
                audio_chunks.append(message)
                continue
            event = json.loads(message)
            etype = event.get("type")
            if etype == "transcript":
                transcript = event.get("text", "")
                print(f"[teste] Transcrição: {transcript!r}")
            elif etype == "assistant.text.delta":
                response += event.get("text", "")
            elif etype == "assistant.text.done":
                response = event.get("text", response)
                print(f"[teste] Resposta: {response!r}")
            elif etype == "audio.start":
                audio_rate = int(event.get("sample_rate", audio_rate))
                print(f"[teste] Evento: audio.start {audio_rate} Hz")
            elif etype == "face":
                faces.append(event)
                print(
                    "[teste] Rosto aplicado: "
                    f"{event.get('expression')} ({event.get('label')}) via {event.get('tool')}"
                )
            elif etype == "face.restore":
                restores.append(event)
                print(f"[teste] Rosto restaurado: {event.get('expression')} motivo {event.get('reason')}")
            elif etype in {"state", "wakeword.detected", "wakeword.not_detected",
                           "error", "audio.end", "audio.unavailable"}:
                detail = event.get("detail") or event.get("message") or ""
                print(f"[teste] Evento: {etype} {event.get('state','')} {detail}".rstrip())
            if etype == "audio.end":
                break
            if etype == "audio.unavailable":
                break

        if audio_chunks:
            pcm_out = b"".join(audio_chunks)
            with wave.open(args.output, "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(audio_rate)
                out.writeframes(pcm_out)
            print(f"[teste] Áudio da resposta salvo em {args.output} ({len(pcm_out)} bytes)")

            # Todo o PCM já foi recebido: é o mesmo ponto em que o app Android
            # termina de esvaziar o AudioTrack e avisa o backend.
            print("[teste] Simulando fim da reprodução (playback.done).")
            await ws.send(json.dumps({"type": "playback.done"}))
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=20)
                except asyncio.TimeoutError:
                    break
                if isinstance(message, bytes):
                    continue
                event = json.loads(message)
                etype = event.get("type")
                if etype == "face.restore":
                    restores.append(event)
                    print(
                        f"[teste] Rosto restaurado: {event.get('expression')} "
                        f"motivo {event.get('reason')}"
                    )
                    continue
                if etype == "state":
                    print(f"[teste] Evento: state {event.get('state')}")
                    if event.get("state") in {"listening", "idle"}:
                        break
        else:
            print("[teste] Nenhum áudio de resposta recebido (veja audio.unavailable).")
        ok = bool(transcript) and bool(response) and bool(audio_chunks)
        print("[teste] RESULTADO:", "OK" if ok else "FALHOU")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
