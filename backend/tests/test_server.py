import copy
import math
import struct
import time

import pytest
from fastapi.testclient import TestClient

from bmo_backend.audio import pcm16_to_wav, split_wav
from bmo_backend.config import DEFAULT_CONFIG, resolve_runtime_paths
from bmo_backend.server import Services, create_app
from bmo_backend.stt import SttResult
from bmo_backend.tts import TtsAudio

TOKEN = "token-de-teste"


class FakeBrain:
    def __init__(self):
        self.history = []

    async def available(self):
        return True

    def status(self):
        return {"provider": "fake", "model": "fake-pt"}

    def reset(self):
        self.history.clear()

    async def stream_reply(self, text):
        self.history.append(text)
        for piece in ["Olá! ", "Eu sou o BMO."]:
            yield piece

    async def reply(self, text):
        return "Olá! Eu sou o BMO."


class FakeStt:
    def __init__(self, text="Ei, BMO, que horas são?"):
        self.text = text

    def available(self):
        return True

    def status(self):
        return {"engine": "fake", "available": True}

    async def transcribe(self, pcm, sample_rate=16000):
        return SttResult(text=self.text, language="pt", duration_ms=1000)


class FakeTts:
    def __init__(self):
        rate = 22050
        pcm = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / rate)))
            for i in range(int(rate * 0.4))
        )
        self.audio = TtsAudio(
            wav=pcm16_to_wav(pcm, rate),
            pcm=pcm,
            sample_rate=rate,
            channels=1,
            duration_s=0.4,
            engine="fake",
        )

    def available(self):
        return True

    def status(self):
        return {"engine": "fake", "available": True}

    async def synthesize(self, text):
        return self.audio


class FakeWeather:
    def __init__(self):
        self.calls = []

    async def answer(self, intent, latitude=None, longitude=None):
        self.calls.append((intent, latitude, longitude))
        return f"Clima de teste para {intent.kind}."


def make_config(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["_token"] = TOKEN
    cfg["paths"]["log_file"] = str(tmp_path / "bmo.log")
    cfg["security"]["audio_cache_ttl_s"] = 60
    resolve_runtime_paths(cfg)
    return cfg


def make_app(tmp_path, stt_text="Ei, BMO, que horas são?"):
    cfg = make_config(tmp_path)
    stt = FakeStt(stt_text)
    weather = FakeWeather()
    services = Services(
        cfg,
        stt=stt,
        tts=FakeTts(),
        weather=weather,
        brain_factory=lambda: FakeBrain(),
    )
    app = create_app(cfg, services=services)
    return app, services, stt


def tone(seconds, rate=16000, amplitude=0.25, freq=220.0):
    return b"".join(
        struct.pack("<h", int(32767 * amplitude * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(int(seconds * rate))
    )


def silence(seconds, rate=16000):
    return b"\x00\x00" * int(seconds * rate)


def test_health_is_public_and_info_requires_token(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["protocol"] == "bmo/1"
        assert client.get("/api/v1/info").status_code == 401
        info = client.get("/api/v1/info", headers={"Authorization": f"Bearer {TOKEN}"})
        assert info.status_code == 200
        data = info.json()
        assert data["llm"]["available"] is True
        assert data["audio"]["sample_rate"] == 16000
        assert data["allowed_commands"] == ["get_time", "get_date"]


def test_http_text_roundtrip_with_local_time_and_audio(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/api/v1/text",
            headers=headers,
            json={"text": "Ei BMO, que horas são?", "session_id": "teste"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "get_time"
        assert "Agora são" in data["text"]
        assert data["audio_available"] is True
        audio = client.get(data["audio"]["url"], headers=headers)
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        assert audio.content.startswith(b"RIFF")


def test_http_llm_roundtrip(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/api/v1/text",
            headers=headers,
            json={"text": "Oi BMO, tudo bem?", "session_id": "chat", "speak": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert "BMO" in data["text"]
        assert data["audio_available"] is False


def test_http_weather_roundtrip(tmp_path):
    app, services, _ = make_app(tmp_path)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/api/v1/text",
            headers=headers,
            json={
                "text": "Ei BMO, vai chover hoje?",
                "session_id": "clima",
                "speak": False,
                "latitude": -23.5505,
                "longitude": -46.6333,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "get_weather"
        assert data["text"] == "Clima de teste para rain."
        assert services.weather.calls[-1][1:] == (-23.5505, -46.6333)


def test_http_weather_rejects_partial_location(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/api/v1/text",
            headers=headers,
            json={
                "text": "Ei BMO, vai chover hoje?",
                "speak": False,
                "latitude": -23.5505,
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_location"


def test_websocket_text_events(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert hello["protocol"] == "bmo/1"
            state = ws.receive_json()
            assert state["type"] == "state"
            ws.send_json({"type": "hello", "protocol": "bmo/1"})
            assert ws.receive_json()["type"] == "hello.ok"
            ws.send_json({"type": "text", "text": "Oi BMO"})
            seen = []
            got_audio = False
            for _ in range(80):
                message = ws.receive()
                if message.get("text"):
                    import json

                    event = json.loads(message["text"])
                    seen.append(event["type"])
                    if event["type"] == "audio.end":
                        break
                elif message.get("bytes"):
                    got_audio = True
            assert "transcript" in seen
            assert "assistant.text.done" in seen
            assert "audio.start" in seen
            assert "audio.end" in seen
            assert got_audio


def test_websocket_weather_uses_location(tmp_path):
    app, services, _ = make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.receive_json()  # hello
            ws.receive_json()  # state
            ws.send_json(
                {
                    "type": "hello",
                    "protocol": "bmo/1",
                    "latitude": -23.5505,
                    "longitude": -46.6333,
                }
            )
            assert ws.receive_json()["type"] == "hello.ok"
            ws.send_json(
                {
                    "type": "location",
                    "latitude": -25.74,
                    "longitude": -52.12,
                    "accuracy": 12.5,
                }
            )
            assert ws.receive_json()["type"] == "location.ok"
            ws.send_json({"type": "text", "text": "Ei BMO, vai chover hoje?"})
            for _ in range(40):
                event = ws.receive_json()
                if event["type"] == "assistant.text.done":
                    break
            intent, latitude, longitude = services.weather.calls[-1]
            assert intent.kind == "rain"
            assert (latitude, longitude) == (-25.74, -52.12)


def test_websocket_rejects_bad_token(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws", headers={"Authorization": "Bearer errado"}) as ws:
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "unauthorized"


def test_websocket_audio_vad_wakeword_and_response(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.receive_json()  # hello
            ws.receive_json()  # state idle
            ws.send_json(
                {
                    "type": "audio.start",
                    "format": "pcm_s16le",
                    "sample_rate": 16000,
                    "channels": 1,
                }
            )
            assert ws.receive_json()["type"] == "audio.ready"
            pcm = tone(0.9) + silence(1.2)
            for offset in range(0, len(pcm), 640):
                ws.send_bytes(pcm[offset : offset + 640])
            seen = []
            got_audio = False
            for _ in range(80):
                message = ws.receive()
                if message.get("text"):
                    import json

                    event = json.loads(message["text"])
                    seen.append(event["type"])
                    if event["type"] == "wakeword.detected":
                        assert event["phrase"] in {"ei bmo", "bmo"}
                    if event["type"] == "audio.end":
                        break
                elif message.get("bytes"):
                    got_audio = True
            assert "vad" in seen
            assert "transcript" in seen
            assert "wakeword.detected" in seen
            assert "assistant.text.done" in seen
            assert "audio.start" in seen
            assert got_audio
