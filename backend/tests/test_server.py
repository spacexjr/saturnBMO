import copy
import json
import math
import struct
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bmo_backend.agent import AgentResult
from bmo_backend.audio import pcm16_to_wav, split_wav
from bmo_backend.config import DEFAULT_CONFIG, resolve_runtime_paths
from bmo_backend.server import Services, create_app
from bmo_backend.stt import SttResult
from bmo_backend.toolkit import PendingConfirmation, ToolResult
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
    # Os testes usam o cérebro falso; ferramentas ficam desligadas por padrão.
    # Testes específicos de ferramentas ligam e injetam seus próprios serviços.
    cfg["tools"]["enabled"] = False
    cfg["tools"]["access_file"] = str(tmp_path / "access.json")
    # Evita carregar os ONNX em todos os testes; testes acústicos são separados.
    cfg["wakeword"]["mode"] = "transcript"
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


def _receive_until(ws, predicate, limit=400):
    """Lê texto/binário do WebSocket até `predicate(event)` ser verdadeiro."""
    events = []
    got_audio = False
    for _ in range(limit):
        message = ws.receive()
        if message.get("text"):
            event = json.loads(message["text"])
            events.append(event)
            if predicate(event):
                break
        elif message.get("bytes"):
            got_audio = True
    return events, got_audio


def test_ten_consecutive_questions_return_to_standby(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.receive_json()  # hello
            ws.receive_json()  # state idle
            for index in range(10):
                ws.send_json({"type": "text", "text": f"Pergunta número {index}"})
                events, got_audio = _receive_until(
                    ws, lambda event: event["type"] == "audio.end"
                )
                kinds = [event["type"] for event in events]
                assert "assistant.text.done" in kinds, kinds
                assert "audio.start" in kinds, kinds
                assert got_audio, f"rodada {index} sem áudio"
                assert "audio.unavailable" not in kinds
                assert "error" not in kinds

                ws.send_json({"type": "playback.done"})
                after, _ = _receive_until(
                    ws,
                    lambda event: event["type"] == "state"
                    and event["state"] in {"listening", "idle"},
                )
                assert after, f"rodada {index} não voltou ao repouso"


class FaceAgent:
    def __init__(self):
        self.calls = []

    def reset(self):
        self.calls.clear()

    async def run(self, text, emit):
        self.calls.append(text)
        await emit(
            "face",
            expression="feliz",
            label="Feliz",
            tool="change_face",
            hold_ms=8000,
        )
        return AgentResult(text="Fico feliz com isso!")


def make_face_app(tmp_path):
    cfg = make_config(tmp_path)
    cfg["tools"]["enabled"] = True
    services = Services(
        cfg,
        stt=FakeStt(),
        tts=FakeTts(),
        weather=FakeWeather(),
        brain_factory=lambda: FakeBrain(),
        registry=FakeRegistry(),
        agent_factory=FaceAgent,
    )
    app = create_app(cfg, services=services)
    return app, services


def test_face_event_is_forwarded_and_restored_after_playback(tmp_path):
    app, _ = make_face_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.receive_json()  # hello
            ws.receive_json()  # state idle
            ws.send_json({"type": "text", "text": "Estou muito feliz hoje"})
            events, _ = _receive_until(ws, lambda event: event["type"] == "audio.end")
            face = next(event for event in events if event["type"] == "face")
            assert face["expression"] == "happy"
            assert face["label"] == "Feliz"
            assert face["tool"] == "change_face"
            assert face["hold_ms"] == 8000

            ws.send_json({"type": "playback.done"})
            after, _ = _receive_until(
                ws, lambda event: event["type"] == "face.restore"
            )
            restore = after[-1]
            assert restore["type"] == "face.restore"
            assert restore["expression"] == "happy"
            assert restore["reason"] == "playback_done"


class PlainAgent:
    """Agente que só responde texto: nunca chama ``change_face``."""

    def __init__(self):
        self.calls = []

    def reset(self):
        self.calls.clear()

    async def run(self, text, emit):
        self.calls.append(text)
        return AgentResult(text="Pronto, já mudei a cara!")


def make_plain_agent_app(tmp_path):
    cfg = make_config(tmp_path)
    cfg["tools"]["enabled"] = True
    services = Services(
        cfg,
        stt=FakeStt(),
        tts=FakeTts(),
        weather=FakeWeather(),
        brain_factory=lambda: FakeBrain(),
        registry=FakeRegistry(),
        agent_factory=PlainAgent,
    )
    return create_app(cfg, services=services)


def test_direct_face_request_applies_without_tool_call(tmp_path):
    """Pedido explícito de rosto não pode depender do LLM chamar a ferramenta."""
    app = make_plain_agent_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.receive_json()  # hello
            ws.receive_json()  # state idle
            ws.send_json({"type": "text", "text": "Ei, BMO, mude sua cara para feliz"})
            events, _ = _receive_until(ws, lambda event: event["type"] == "audio.end")
            faces = [event for event in events if event["type"] == "face"]
            assert len(faces) == 1, [event["type"] for event in events]
            assert faces[0]["expression"] == "happy"
            assert faces[0]["label"] == "Feliz"
            assert faces[0]["tool"] == "change_face"
            texts = [event for event in events if event["type"] == "assistant.text.done"]
            assert texts and texts[-1]["text"] == "Pronto, já mudei a cara!"

            ws.send_json({"type": "playback.done"})
            after, _ = _receive_until(
                ws, lambda event: event["type"] == "face.restore"
            )
            restore = after[-1]
            assert restore["expression"] == "happy"
            assert restore["reason"] == "playback_done"


class WrongFaceAgent:
    """Agente que sempre pede uma expressão diferente da solicitada."""

    def __init__(self):
        self.calls = []

    def reset(self):
        self.calls.clear()

    async def run(self, text, emit):
        self.calls.append(text)
        await emit("face", expression="sad", label="Triste", tool="change_face", hold_ms=8000)
        return AgentResult(text="Ok!")


def make_wrong_face_app(tmp_path):
    cfg = make_config(tmp_path)
    cfg["tools"]["enabled"] = True
    services = Services(
        cfg,
        stt=FakeStt(),
        tts=FakeTts(),
        weather=FakeWeather(),
        brain_factory=lambda: FakeBrain(),
        registry=FakeRegistry(),
        agent_factory=WrongFaceAgent,
    )
    return create_app(cfg, services=services)


def test_explicit_face_request_beats_model_choice(tmp_path):
    """Se o usuário pede "feliz", o modelo não pode trocar para outra cara."""
    app = make_wrong_face_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.receive_json()  # hello
            ws.receive_json()  # state idle
            ws.send_json({"type": "text", "text": "Ei, BMO, fique feliz"})
            events, _ = _receive_until(ws, lambda event: event["type"] == "audio.end")
            faces = [event for event in events if event["type"] == "face"]
            assert [event["expression"] for event in faces] == ["happy"]
            assert faces[0]["label"] == "Feliz"


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


# ---------------------------------------------------------------------------
# Wake word efetivo, pasta autorizada e confirmação de ferramentas
# ---------------------------------------------------------------------------


def test_wake_mode_falls_back_without_acoustic_detector():
    services = Services.__new__(Services)
    services.wake_acoustic = None
    assert services._resolve_wake_mode({"mode": "acoustic"}) == "transcript"
    assert services._resolve_wake_mode({"mode": "hybrid"}) == "transcript"
    assert services._resolve_wake_mode({"mode": "transcript"}) == "transcript"
    assert services._resolve_wake_mode({"mode": "invalido"}) == "transcript"

    services.wake_acoustic = object()
    assert services._resolve_wake_mode({"mode": "acoustic"}) == "acoustic"
    assert services._resolve_wake_mode({"mode": "hybrid"}) == "hybrid"
    assert services._resolve_wake_mode({"mode": "transcript"}) == "transcript"


def test_info_exposes_effective_wakeword_mode(tmp_path):
    app, services, _ = make_app(tmp_path)
    services.wake_mode = "hybrid"
    services.config["wakeword"]["mode"] = "hybrid"
    with TestClient(app) as client:
        info = client.get("/api/v1/info", headers={"Authorization": f"Bearer {TOKEN}"})
        assert info.status_code == 200
        wake = info.json()["wakeword"]
        assert wake["mode"] == "hybrid"
        assert wake["configured_mode"] == "hybrid"
        assert wake["acoustic"] is False


def test_folder_endpoints_authorize_and_revoke(tmp_path):
    app, services, _ = make_app(tmp_path)
    chosen = tmp_path / "minha-pasta"
    chosen.mkdir()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as client:
        status = client.get("/api/v1/folder", headers=headers)
        assert status.status_code == 200
        assert status.json()["authorized"] is False

        saved = client.post("/api/v1/folder", headers=headers, json={"path": str(chosen)})
        assert saved.status_code == 200
        assert Path(saved.json()["path"]) == chosen.resolve()
        assert saved.json()["authorized"] is True

        reloaded = client.get("/api/v1/folder", headers=headers)
        assert reloaded.json()["path"] == str(chosen.resolve())

        revoked = client.post("/api/v1/folder/revoke", headers=headers)
        assert revoked.status_code == 200
        assert revoked.json()["authorized"] is False

        tools = client.get("/api/v1/tools", headers=headers)
        assert tools.status_code == 200
        assert "delete_file" in tools.json()["tools"]


class FakeRegistry:
    def __init__(self):
        self.confirmed = []

    def names(self):
        return ["delete_file"]

    def status(self):
        return {"enabled": True, "tools": ["delete_file"]}

    async def execute_confirmed(self, pending):
        self.confirmed.append(pending)
        return ToolResult(True, {"ok": True, "path": pending.arguments.get("path", "")})


class FakeAgent:
    def __init__(self, pending):
        self.pending = pending
        self.calls = []

    def reset(self):
        self.calls.clear()

    async def run(self, text, emit):
        self.calls.append(text)
        await emit(
            "confirmation.request",
            id=self.pending.id,
            tool=self.pending.tool,
            prompt=self.pending.prompt,
        )
        return AgentResult(text=self.pending.prompt, pending=self.pending)


def make_tools_app(tmp_path):
    cfg = make_config(tmp_path)
    cfg["tools"]["enabled"] = True
    stt = FakeStt()
    weather = FakeWeather()
    registry = FakeRegistry()
    pending = PendingConfirmation(
        id="conf123",
        tool="delete_file",
        arguments={"path": "segredo.txt"},
        prompt="Confirma excluir 'segredo.txt'?",
        activity="editing_file",
    )
    agent = FakeAgent(pending)
    services = Services(
        cfg,
        stt=stt,
        tts=FakeTts(),
        weather=weather,
        brain_factory=lambda: FakeBrain(),
        registry=registry,
        agent_factory=lambda: agent,
    )
    app = create_app(cfg, services=services)
    return app, services, registry, agent


def test_websocket_requires_confirmation_before_destructive_tool(tmp_path):
    app, _, registry, agent = make_tools_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.receive_json()  # hello
            ws.receive_json()  # state
            ws.send_json({"type": "text", "text": "apague o arquivo segredo"})
            seen = []
            confirmation_id = None
            for _ in range(120):
                message = ws.receive()
                if not message.get("text"):
                    continue
                event = __import__("json").loads(message["text"])
                seen.append(event["type"])
                if event["type"] == "confirmation.request":
                    confirmation_id = event["id"]
                if event["type"] == "audio.end" and "confirmation.request" in seen:
                    break
            assert agent.calls == ["apague o arquivo segredo"]
            assert "confirmation.request" in seen
            assert registry.confirmed == []

            ws.send_json(
                {"type": "confirmation", "id": confirmation_id, "approved": True}
            )
            confirmed_seen = []
            for _ in range(120):
                message = ws.receive()
                if not message.get("text"):
                    continue
                event = __import__("json").loads(message["text"])
                confirmed_seen.append(event)
                if event["type"] == "assistant.text.done" and event.get("id") != "wake-ack":
                    break
            assert registry.confirmed
            assert registry.confirmed[0].arguments == {"path": "segredo.txt"}
            kinds = [event["type"] for event in confirmed_seen]
            assert "confirmation.result" in kinds
            result = next(event for event in confirmed_seen if event["type"] == "confirmation.result")
            assert result["approved"] is True and result["ok"] is True


def test_websocket_cancel_confirmation_sends_no_execution(tmp_path):
    app, _, registry, _ = make_tools_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.receive_json()
            ws.receive_json()
            ws.send_json({"type": "text", "text": "apague o arquivo segredo"})
            confirmation_id = None
            for _ in range(120):
                message = ws.receive()
                if not message.get("text"):
                    continue
                event = __import__("json").loads(message["text"])
                if event["type"] == "confirmation.request":
                    confirmation_id = event["id"]
                if event["type"] == "audio.end" and confirmation_id:
                    break
            ws.send_json(
                {"type": "confirmation", "id": confirmation_id, "approved": False}
            )
            for _ in range(120):
                message = ws.receive()
                if not message.get("text"):
                    continue
                event = __import__("json").loads(message["text"])
                if event["type"] == "confirmation.result":
                    break
            assert registry.confirmed == []
