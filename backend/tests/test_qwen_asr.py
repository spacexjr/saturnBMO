"""Testes do cliente Qwen3-ASR/Ollama (sem depender do modelo real)."""

from __future__ import annotations

import asyncio
import struct

import pytest

from bmo_backend.audio import pcm16_to_wav, split_wav
from bmo_backend.qwen_asr import QwenAsrStt
from bmo_backend.stt import FallbackStt, SttResult, SttUnavailable, build_stt


def tone(seconds: float, rate: int = 16000) -> bytes:
    return b"".join(
        struct.pack("<h", int(4000 * (1 if i % 2 else -1)))
        for i in range(int(seconds * rate))
    )


def client(**overrides) -> QwenAsrStt:
    config = {
        "model": "frozenlab/qwen3-asr:0.6b",
        "base_url": "http://127.0.0.1:11434",
        "language": "pt-BR",
        "timeout_s": 5,
        "max_audio_s": 3,
    }
    config.update(overrides)
    return QwenAsrStt(config)


def test_parse_response_extracts_text_and_language():
    text, language = QwenAsrStt.parse_response(
        "language Portuguese<asr_text>E bem, que horas são agora"
    )
    assert text == "E bem, que horas são agora"
    assert language == "pt"


def test_parse_response_without_marker_does_not_invent_text():
    assert QwenAsrStt.parse_response("") == ("", "")
    text, language = QwenAsrStt.parse_response("language Portuguese")
    assert text == ""
    assert language == "pt"


def test_prepare_pcm_resamples_and_limits_duration():
    stt = client(max_audio_s=1)
    pcm = tone(2.0, rate=48000)
    prepared, original_ms, used_ms = stt._prepare_pcm(pcm, 48000)
    _, rate, channels = split_wav(pcm16_to_wav(prepared))
    assert rate == 16000
    assert channels == 1
    assert original_ms == 2000
    assert used_ms <= 1000


def test_transcribe_uses_ollama_chat_and_reports_metrics(monkeypatch):
    stt = client()
    calls = []

    async def fake_post(payload):
        calls.append(payload)
        return {
            "message": {
                "content": "language Portuguese<asr_text>Ei BMO, toque uma música"
            }
        }

    monkeypatch.setattr(stt, "_post_chat", fake_post)
    result = asyncio.run(stt.transcribe(tone(0.8)))
    assert result.text == "Ei BMO, toque uma música"
    assert result.language == "pt"
    assert result.engine == "qwen3-asr"
    assert result.duration_ms == 800
    assert result.latency_ms >= 0
    assert calls and calls[0]["model"] == "frozenlab/qwen3-asr:0.6b"
    assert calls[0]["stream"] is False
    assert calls[0]["messages"][0]["images"]
    # A mensagem de áudio não pode levar texto inventado.
    assert calls[0]["messages"][0]["content"] == ""


def test_transcribe_reports_ollama_unavailable(monkeypatch):
    stt = client()

    async def offline(payload):
        raise SttUnavailable("Ollama fora do ar")

    monkeypatch.setattr(stt, "_post_chat", offline)
    with pytest.raises(SttUnavailable):
        asyncio.run(stt.transcribe(tone(0.5)))
    assert stt.available() is False


def test_fallback_uses_engine_reported_by_primary():
    class Primary:
        def available(self):
            return True

        def status(self):
            return {"engine": "qwen3-asr", "available": True}

        async def transcribe(self, pcm, sample_rate=16000):
            return SttResult("texto", "pt", 100, latency_ms=20, engine="qwen3-asr")

        async def close(self):
            return None

    fallback = FallbackStt(Primary(), None)
    result = asyncio.run(fallback.transcribe(tone(0.2)))
    assert result.text == "texto"
    assert fallback.last_engine == "qwen3-asr"


def test_build_stt_accepts_qwen_alias_without_network():
    stt = build_stt({"engine": "qwen3-asr", "fallback": {"enabled": False}})
    assert stt.__class__.__name__ == "QwenAsrStt"
