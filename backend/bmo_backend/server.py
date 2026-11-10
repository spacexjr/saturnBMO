"""Servidor local do BMO: HTTP + WebSocket.

Execute com:  python -m bmo_backend
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Awaitable, Callable

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .actions import ALLOWED_ACTIONS, detect_local_intent, parse_authorized_action
from .acoustic_wakeword import AcousticWakeWord
from .agent import AgentResult, ToolAgent
from .api.music_routes import build_music_routers
from .apps import AppManager
from .audio import EnergyVad, pcm16_to_wav
from .config import DATA_DIR, load_config, public_config, resolve_runtime_paths
from .discovery import start_discovery
from .files import Workspace, WorkspaceError
from .folder_picker import FolderPicker, FolderPickerError
from .llm import LlmError, LlmUnavailable, OllamaBrain, sanitize_reply
from .media import MediaError, MediaService
from .music import build_music_manager
from .music.manager import MusicError
from .protocol import (
    PROTOCOL_VERSION,
    SERVICE_VERSION,
    ProtocolError,
    now_ms,
    validate_audio_start,
    validate_client_message,
    validate_confirmation,
    validate_location,
    validate_text,
)
from .stt import SttError, SttUnavailable, build_stt
from .sysinfo import SystemInfo
from .toolkit import PendingConfirmation, ToolRegistry, result_text
from .tts import TtsError, TtsService, TtsUnavailable
from .wakeword import WakeWordDetector, normalize_text
from .weather import (
    WeatherError,
    WeatherService,
    WeatherUnavailable,
    detect_weather_intent,
)
from .web import WebService

log = logging.getLogger("bmo.server")

# Respostas aceitas para confirmar ou cancelar uma exclusão pendente.
_AFFIRMATIVE = re.compile(
    r"^(sim|sim confirmo|confirmo|confirmado|pode|pode excluir|pode apagar|"
    r"isso|claro|com certeza|yes|ok)\b"
)
_NEGATIVE = re.compile(
    r"^(nao|cancela|cancelar|deixa|deixa pra la|deixa para la|no|nunca|para)\b"
)


# ---------------------------------------------------------------------------
# Serviços compartilhados
# ---------------------------------------------------------------------------


class Services:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        stt: Any = None,
        tts: Any = None,
        weather: Any = None,
        brain_factory: Callable[[], Any] | None = None,
        workspace: Any = None,
        apps: Any = None,
        media: Any = None,
        music: Any = None,
        web: Any = None,
        system: Any = None,
        registry: Any = None,
        picker: Any = None,
        agent_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.config = config
        self.stt = stt if stt is not None else build_stt(config["stt"])
        self.tts = tts if tts is not None else TtsService(config["tts"])
        self.weather = (
            weather if weather is not None
            else WeatherService(config.get("weather", {}))
        )
        self.brain_factory = brain_factory or (lambda: OllamaBrain(config["llm"]))
        self.wake = WakeWordDetector(
            config["wakeword"].get("phrases"),
            enabled=bool(config["wakeword"].get("enabled", True)),
        )
        self.wake_acoustic = self._build_acoustic_detector(config["wakeword"])
        self.wake_mode = self._resolve_wake_mode(config["wakeword"])

        tools_cfg = config.get("tools", {}) or {}
        self.tools_enabled = bool(tools_cfg.get("enabled", True))
        access_file = tools_cfg.get("access_file")
        self.workspace = (
            workspace
            if workspace is not None
            else Workspace(Path(access_file) if access_file else None)
        )
        self.apps = apps if apps is not None else AppManager(tools_cfg.get("apps", {}))
        self.media = media if media is not None else MediaService(tools_cfg.get("media", {}))
        self.music = (
            music
            if music is not None
            else build_music_manager(
                config.get("music", {}),
                server_port=int(config.get("server", {}).get("port", 8765)),
            )
        )
        web_cfg = dict(tools_cfg.get("web", {}) or {})
        web_cfg.setdefault("allow_private_urls", bool(tools_cfg.get("allow_private_urls", False)))
        self.web = web if web is not None else WebService(web_cfg)
        self.system = system if system is not None else SystemInfo(tools_cfg.get("system", {}))
        self.registry = (
            registry
            if registry is not None
            else ToolRegistry(
                workspace=self.workspace,
                apps=self.apps,
                media=self.media,
                web=self.web,
                system=self.system,
                music=self.music,
                config=tools_cfg,
            )
        )
        self.folder = picker if picker is not None else FolderPicker(self.workspace)
        self.agent_factory = agent_factory or self._default_agent_factory

        self.started_at = time.time()
        self.audio_cache: dict[str, tuple[bytes, float]] = {}
        self.http_brains: dict[str, Any] = {}
        self._status_cache: dict[str, Any] | None = None
        self._status_at = 0.0
        self.stt_available = False
        self.llm_available: bool | None = None
        self.tts_available = self.tts.available()

    def _build_acoustic_detector(self, cfg: dict[str, Any]) -> AcousticWakeWord | None:
        """Carrega o detector acústico se configurado e disponível.

        Falhas não derrubam o backend: caem de volta para o modo transcrição.
        """
        mode = str(cfg.get("mode", "transcript")).lower()
        if not bool(cfg.get("enabled", True)) or mode not in {"acoustic", "hybrid"}:
            return None
        model = cfg.get("acoustic_model")
        mel = cfg.get("mel_model")
        embedding = cfg.get("embedding_model")
        if not model or not mel or not embedding:
            log.warning("Wakeword acústico habilitado, mas caminhos dos modelos ausentes.")
            return None
        try:
            detector = AcousticWakeWord(
                model_path=model,
                mel_path=mel,
                embedding_path=embedding,
                threshold=float(cfg.get("threshold", 0.75)),
                cooldown_s=float(cfg.get("cooldown_s", 2.0)),
                hop_s=float(cfg.get("hop_ms", 100)) / 1000.0,
                min_consecutive=int(cfg.get("min_consecutive", 1)),
            )
            log.info("Detector acústico carregado: %s (modo %s)", model, mode)
            return detector
        except Exception as exc:  # noqa: BLE001
            log.warning("Detector acústico indisponível (%s); usando transcrição: %s", model, exc)
            return None

    def _resolve_wake_mode(self, cfg: dict[str, Any]) -> str:
        """Retorna o modo efetivo, considerando o detector realmente carregado."""
        mode = str(cfg.get("mode", "transcript")).lower()
        if mode not in {"transcript", "acoustic", "hybrid"}:
            log.warning("Modo de wakeword inválido (%s); usando transcript.", mode)
            return "transcript"
        if mode in {"acoustic", "hybrid"} and self.wake_acoustic is None:
            log.warning("Modo de wakeword '%s' sem detector acústico; usando transcript.", mode)
            return "transcript"
        return mode

    def _default_agent_factory(self) -> Any:
        llm_cfg = dict(self.config.get("llm", {}))
        llm_cfg["max_tool_steps"] = int(
            (self.config.get("tools", {}) or {}).get("max_tool_steps", 5)
        )
        return ToolAgent(
            llm_cfg,
            self.registry,
            system_prompt=str(llm_cfg.get("system_prompt", "")),
            history_messages=int(llm_cfg.get("history_messages", 12)),
        )

    def make_agent(self) -> Any | None:
        if not self.tools_enabled:
            return None
        try:
            return self.agent_factory()
        except Exception as exc:  # noqa: BLE001
            log.warning("Agente de ferramentas indisponível: %s", exc)
            return None

    def wake_status(self) -> dict[str, Any]:
        cfg = self.config.get("wakeword", {})
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "mode": self.wake_mode,
            "configured_mode": cfg.get("mode", "transcript"),
            "acoustic": self.wake_acoustic is not None,
            "threshold": cfg.get("threshold"),
            "phrases": cfg.get("phrases", []),
            "note": cfg.get("note", ""),
        }

    def capabilities(self) -> list[str]:
        base = ["text", "audio", "tts", "vad", "location", "get_time", "get_date", "get_weather"]
        if self.tools_enabled:
            base.extend(["tools", "internet", "desktop", "media", "files", "folder", "system_info"])
        if self.music is not None:
            base.extend(["music", "youtube_music", "music_queue"])
        return base

    async def refresh_status(self, force: bool = False) -> dict[str, Any]:
        if not force and self._status_cache and time.time() - self._status_at < 10:
            return self._status_cache
        brain = self.brain_factory()
        try:
            llm_ok = await brain.available()
        except Exception:  # noqa: BLE001
            llm_ok = False
        self.llm_available = llm_ok
        try:
            self.stt_available = bool(self.stt.available())
        except Exception:  # noqa: BLE001
            self.stt_available = False
        self.tts_available = bool(self.tts.available())
        self._status_cache = {
            "llm": {**self._brain_status(), "available": llm_ok},
            "stt": self.stt.status(),
            "tts": self.tts.status(),
        }
        self._status_at = time.time()
        return self._status_cache

    def _brain_status(self) -> dict[str, Any]:
        brain = self.brain_factory()
        if hasattr(brain, "status"):
            try:
                return dict(brain.status())
            except Exception:  # noqa: BLE001
                pass
        return {"provider": "desconhecido"}

    def brain_for(self, key: str) -> Any:
        brain = self.http_brains.get(key)
        if brain is None:
            brain = self.brain_factory()
            self.http_brains[key] = brain
        return brain

    def cache_audio(self, wav: bytes) -> str:
        audio_id = uuid.uuid4().hex
        ttl = float(self.config["security"].get("audio_cache_ttl_s", 300))
        self.audio_cache[audio_id] = (wav, time.time() + ttl)
        self._purge_audio_cache()
        return audio_id

    def _purge_audio_cache(self) -> None:
        now = time.time()
        for key in [k for k, (_, exp) in self.audio_cache.items() if exp < now]:
            self.audio_cache.pop(key, None)

    def get_audio(self, audio_id: str) -> bytes | None:
        item = self.audio_cache.get(audio_id)
        if not item or item[1] < time.time():
            self.audio_cache.pop(audio_id, None)
            return None
        return item[0]


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------


def _header_token(headers: Any) -> str:
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (headers.get("x-bmo-token") or "").strip()


def token_matches(config: dict[str, Any], token: str) -> bool:
    expected = str(config.get("_token", ""))
    return bool(expected) and bool(token) and secrets.compare_digest(expected, token)


async def require_auth(request: Request) -> None:
    services: Services = request.app.state.services
    token = _header_token(request.headers)
    if not token_matches(services.config, token):
        raise HTTPException(
            status_code=401,
            detail="Token ausente ou inválido. Configure o token em Ajustes.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class BodyTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default="http", max_length=64)
    speak: bool = True
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class FolderRequest(BaseModel):
    path: str = Field(default="", max_length=4096)


def _error_response(code: str, message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_app(config: dict[str, Any] | None = None, services: Services | None = None,
               enable_discovery: bool = False) -> FastAPI:
    config = config or load_config()
    services = services or Services(config)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log.info("BMO Backend %s iniciado (protocolo %s).", SERVICE_VERSION, PROTOCOL_VERSION)
        results = await services.refresh_status(force=True)
        log.info(
            "Serviços: LLM=%s STT=%s TTS=%s",
            "ok" if results["llm"]["available"] else "indisponível",
            "ok" if results["stt"]["available"] else "indisponível",
            "ok" if results["tts"]["available"] else "indisponível",
        )
        if enable_discovery:
            application.state.discovery = await start_discovery(config)
        try:
            yield
        finally:
            transport = getattr(application.state, "discovery", None)
            if transport is not None:
                transport.close()

    app = FastAPI(
        title="BMO Backend",
        version=SERVICE_VERSION,
        description="Backend local do BMO (voz, STT, LLM e TTS no PC).",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.services = services
    app.state.config = config

    music_router, music_stream_router = build_music_routers(require_auth)
    app.include_router(music_router)
    app.include_router(music_stream_router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "bmo-backend",
            "version": SERVICE_VERSION,
            "protocol": PROTOCOL_VERSION,
        }

    @app.get("/api/v1/info", dependencies=[Depends(require_auth)])
    async def info() -> dict[str, Any]:
        status = await services.refresh_status()
        return {
            "service": "bmo-backend",
            "version": SERVICE_VERSION,
            "protocol": PROTOCOL_VERSION,
            "session_id": uuid.uuid4().hex[:12],
            "uptime_s": int(time.time() - services.started_at),
            "server_time": datetime.now(timezone.utc).isoformat(),
            "llm": status["llm"],
            "stt": status["stt"],
            "tts": status["tts"],
            "audio": {
                "sample_rate": int(config["audio"]["sample_rate"]),
                "channels": 1,
                "format": "pcm_s16le",
                "frame_ms": int(config["audio"]["frame_ms"]),
            },
            "wakeword": services.wake_status(),
            "music": await services.music.status() if services.music is not None else {
                "enabled": False
            },
            "tools": {
                "enabled": services.tools_enabled,
                "names": services.registry.names() if services.tools_enabled else [],
                "folder": services.workspace.status(),
            },
            "capabilities": services.capabilities(),
            "allowed_commands": config["security"].get("allowed_commands", []),
        }

    @app.get("/api/v1/diagnostics", dependencies=[Depends(require_auth)])
    async def diagnostics() -> dict[str, Any]:
        status = await services.refresh_status(force=True)
        log_file = Path(config["paths"]["log_file"])
        lines: list[str] = []
        if log_file.exists():
            try:
                with log_file.open("r", encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()[-80:]
            except OSError:
                lines = []
        return {
            "config": public_config(config),
            "services": status,
            "recent_log": [line.rstrip() for line in lines],
        }

    @app.get("/api/v1/folder", dependencies=[Depends(require_auth)])
    async def folder_status() -> dict[str, Any]:
        return services.folder.status()

    @app.post("/api/v1/folder", dependencies=[Depends(require_auth)])
    async def folder_authorize(request: FolderRequest) -> Any:
        path = request.path.strip()
        if not path:
            return _error_response("empty_path", "Informe o caminho da pasta.", 422)
        try:
            state = services.workspace.authorize(path)
        except WorkspaceError as exc:
            return _error_response("invalid_folder", str(exc), 400)
        return state.as_dict()

    @app.post("/api/v1/folder/select", dependencies=[Depends(require_auth)])
    async def folder_select(request: FolderRequest | None = None) -> Any:
        start = request.path.strip() if request and request.path else None
        try:
            return await services.folder.select(start)
        except FolderPickerError as exc:
            return _error_response("picker_error", str(exc), 503)

    @app.post("/api/v1/folder/revoke", dependencies=[Depends(require_auth)])
    async def folder_revoke() -> dict[str, Any]:
        return services.folder.revoke()

    @app.get("/api/v1/tools", dependencies=[Depends(require_auth)])
    async def tools_status() -> dict[str, Any]:
        return services.registry.status()

    @app.get("/api/v1/media", dependencies=[Depends(require_auth)])
    async def media_status() -> Any:
        try:
            return await services.media.current()
        except MediaError as exc:
            # Preserva o endpoint antigo, mas usa o Mopidy quando o MPRIS não
            # tem player ativo. Assim o app Android continua compatível.
            if services.music is not None:
                try:
                    return await services.music.get_state()
                except MusicError:
                    pass
            return JSONResponse(
                status_code=503,
                content={"available": False, "error": str(exc)},
            )

    @app.get("/api/v1/audio/{audio_id}.wav", dependencies=[Depends(require_auth)])
    async def get_audio(audio_id: str):
        if len(audio_id) > 40 or not audio_id.isalnum():
            raise HTTPException(status_code=404, detail="Áudio não encontrado.")
        wav = services.get_audio(audio_id)
        if wav is None:
            raise HTTPException(status_code=404, detail="Áudio expirado ou inexistente.")
        return Response(content=wav, media_type="audio/wav")

    @app.post("/api/v1/text", dependencies=[Depends(require_auth)])
    async def text(request: BodyTextRequest):
        text_value = request.text.strip()
        if not text_value:
            return _error_response("empty_text", "O texto está vazio.", 422)
        if len(text_value) > int(config["security"].get("max_text_chars", 1000)):
            return _error_response("text_too_long", "Texto muito longo.", 422)
        if (request.latitude is None) != (request.longitude is None):
            return _error_response(
                "invalid_location",
                "Envie latitude e longitude juntas.",
                422,
            )
        brain = services.brain_for(request.session_id or "http")
        action = detect_local_intent(text_value)
        weather_intent = None if action is not None else detect_weather_intent(text_value)
        try:
            if action is not None:
                answer = action.text
                command = action.action
            elif weather_intent is not None:
                answer = await services.weather.answer(
                    weather_intent,
                    latitude=request.latitude,
                    longitude=request.longitude,
                )
                command = "get_weather"
            else:
                answer = sanitize_reply(await brain.reply(text_value))
                parsed = parse_authorized_action(answer, config["security"].get("allowed_commands"))
                command = parsed.action if parsed is not None else None
                if parsed is not None:
                    answer = parsed.text
            audio_payload = None
            if request.speak and services.tts.available():
                audio = await services.tts.synthesize(answer)
                audio_id = services.cache_audio(audio.wav)
                audio_payload = {
                    "url": f"/api/v1/audio/{audio_id}.wav",
                    "format": "wav",
                    "sample_rate": audio.sample_rate,
                    "channels": audio.channels,
                    "duration_ms": int(audio.duration_s * 1000),
                    "engine": audio.engine,
                }
            return {
                "id": uuid.uuid4().hex[:12],
                "text": answer,
                "action": command,
                "audio": audio_payload,
                "audio_available": audio_payload is not None,
            }
        except LlmUnavailable as exc:
            return _error_response("llm_unavailable", str(exc), 503)
        except WeatherUnavailable as exc:
            return _error_response("weather_unavailable", str(exc), 503)
        except WeatherError as exc:
            return _error_response("weather_error", str(exc), 503)
        except (LlmError, TtsError, TtsUnavailable) as exc:
            return _error_response("processing_error", str(exc), 500)

    # Permite usar o BodyTextRequest definido abaixo no fechamento.
    @app.post("/api/v1/reset", dependencies=[Depends(require_auth)])
    async def reset(request: Request, session_id: str = "http") -> dict[str, Any]:
        brain = services.brain_for(session_id)
        if hasattr(brain, "reset"):
            brain.reset()
        return {"ok": True, "message": "Histórico da sessão apagado."}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        services_ws: Services = websocket.app.state.services
        supplied = _header_token(websocket.headers) or (websocket.query_params.get("token") or "")
        if not token_matches(config, supplied):
            with contextlib.suppress(Exception):
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "unauthorized",
                            "message": "Token ausente ou inválido.",
                        },
                        ensure_ascii=False,
                    )
                )
                await websocket.close(code=4401)
            return
        session = BmoSession(websocket, services_ws)
        await session.run()

    # Sobrescreve a anotação para o FastAPI reconhecer o modelo.
    app.openapi_schema = None
    return app


# ---------------------------------------------------------------------------
# Sessão WebSocket
# ---------------------------------------------------------------------------


class BmoSession:
    def __init__(self, websocket: WebSocket, services: Services) -> None:
        self.ws = websocket
        self.services = services
        self.config = services.config
        self.session_id = uuid.uuid4().hex[:12]
        self.state = "idle"
        self.capture_active = False
        self.bypass_wake_once = False
        self.location: tuple[float, float] | None = None
        self.seq = 0
        self.generation = 0
        self._closed = False
        self._response_task: asyncio.Task | None = None
        self._utterance_task: asyncio.Task | None = None
        self._idle_task: asyncio.Task | None = None
        self._recovery_task: asyncio.Task | None = None
        self._ignore_audio_until = 0.0
        self._brain = services.brain_factory()
        self._agent = services.make_agent()
        self.pending_confirmation: PendingConfirmation | None = None
        audio_cfg = self.config["audio"]
        self.vad = EnergyVad(
            sample_rate=int(audio_cfg["sample_rate"]),
            frame_ms=int(audio_cfg.get("frame_ms", 20)),
            min_rms=float(audio_cfg.get("vad_min_rms", 0.012)),
            start_ms=int(audio_cfg.get("vad_start_ms", 180)),
            end_silence_ms=int(audio_cfg.get("vad_end_silence_ms", 700)),
            pre_roll_ms=int(audio_cfg.get("vad_pre_roll_ms", 300)),
            min_utterance_ms=int(audio_cfg.get("min_utterance_ms", 350)),
            max_utterance_s=float(audio_cfg.get("max_utterance_s", 15)),
        )

    # -- envio -------------------------------------------------------------

    async def send(self, payload: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            await self.ws.send_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        except Exception:  # noqa: BLE001 - desconexão é tratada no loop
            self._closed = True

    def _event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        self.seq += 1
        return {"type": event_type, "seq": self.seq, "ts": now_ms(), **fields}

    async def event(self, event_type: str, **fields: Any) -> None:
        await self.send(self._event(event_type, **fields))

    async def set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        await self.event("state", state=state, detail=detail)

    def resting_state(self) -> str:
        return "listening" if self.capture_active else "idle"

    # -- loop --------------------------------------------------------------

    async def run(self) -> None:
        await self.event(
            "hello",
            protocol=PROTOCOL_VERSION,
            server_version=SERVICE_VERSION,
            session_id=self.session_id,
            audio={
                "format": "pcm_s16le",
                "sample_rate": int(self.config["audio"]["sample_rate"]),
                "channels": 1,
                "frame_ms": int(self.config["audio"]["frame_ms"]),
            },
            wakeword=self.services.wake_status(),
            tools={
                "enabled": self.services.tools_enabled,
                "folder": self.services.workspace.status(),
            },
            capabilities=self.services.capabilities(),
        )
        await self.set_state("idle", "Conectado. Toque em Ouvir para começar.")
        try:
            while not self._closed:
                message = await self.ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if "text" in message and message["text"] is not None:
                    raw = message["text"]
                    max_bytes = int(self.config["server"].get("max_ws_message_bytes", 262144))
                    if len(raw.encode("utf-8")) > max_bytes:
                        await self.send_error("message_too_large", "Mensagem muito grande.", fatal=True)
                        break
                    try:
                        payload = json.loads(raw)
                        payload = validate_client_message(payload)
                    except json.JSONDecodeError:
                        await self.send_error("invalid_json", "JSON inválido.", fatal=False)
                        continue
                    except ProtocolError as exc:
                        await self.send_error(exc.code, exc.message, fatal=False)
                        continue
                    await self.handle_control(payload)
                elif "bytes" in message and message["bytes"] is not None:
                    await self.handle_audio(message["bytes"])
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro na sessão %s: %s", self.session_id, exc)
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        self._closed = True
        for task in (
            self._response_task,
            self._utterance_task,
            self._idle_task,
            self._recovery_task,
        ):
            if task and not task.done():
                task.cancel()
        if hasattr(self._brain, "close"):
            with contextlib.suppress(Exception):
                await self._brain.close()

    # -- controle ----------------------------------------------------------

    async def _store_location(self, payload: dict[str, Any]) -> bool:
        if "latitude" not in payload and "longitude" not in payload:
            return False
        try:
            location = validate_location(payload)
        except ProtocolError as exc:
            await self.send_error(exc.code, exc.message)
            return False
        self.location = (location["latitude"], location["longitude"])
        return True

    async def handle_control(self, payload: dict[str, Any]) -> None:
        msg_type = payload["type"]
        if msg_type == "hello":
            protocol = payload.get("protocol")
            if protocol and protocol != PROTOCOL_VERSION:
                await self.send_error(
                    "unsupported_protocol",
                    f"Protocolo {protocol} não suportado. Use {PROTOCOL_VERSION}.",
                    fatal=True,
                )
                await self.ws.close(code=4400)
            else:
                await self._store_location(payload)
                await self.event("hello.ok", protocol=PROTOCOL_VERSION, session_id=self.session_id)
        elif msg_type == "ping":
            await self.event("pong", echo=payload.get("ts"), server_ts=now_ms())
        elif msg_type == "location":
            if await self._store_location(payload):
                await self.event(
                    "location.ok",
                    latitude=self.location[0] if self.location else None,
                    longitude=self.location[1] if self.location else None,
                )
        elif msg_type == "activate":
            self.bypass_wake_once = True
            self._ignore_audio_until = 0.0
            self.vad.reset()
            self._reset_acoustic()
            await self.event("wakeword.activated", manual=True, message="Pode falar, estou ouvindo.")
            if not self.capture_active:
                await self.set_state("listening", "Ouvindo uma vez. O microfone do app precisa estar ativo.")
            else:
                await self.set_state("listening", "Pode falar, estou ouvindo.")
        elif msg_type == "audio.start":
            try:
                audio_cfg = validate_audio_start(
                    payload, expected_rate=int(self.config["audio"]["sample_rate"])
                )
            except ProtocolError as exc:
                await self.send_error(exc.code, exc.message)
                return
            self.capture_active = True
            self.vad.reset()
            self._reset_acoustic()
            await self.event("audio.ready", **audio_cfg)
            if self.state not in {"thinking", "speaking"}:
                await self.set_state(self.resting_state(), "Microfone ativo. Diga 'Ei, BMO'.")
        elif msg_type == "audio.end":
            self.capture_active = False
            self._reset_acoustic()
            events = self.vad.flush()
            await self._process_vad_events(events)
            if self.state not in {"thinking", "speaking"}:
                await self.set_state("idle", "Microfone pausado.")
        elif msg_type == "text":
            try:
                text_value = validate_text(
                    payload, int(self.config["security"].get("max_text_chars", 1000))
                )
            except ProtocolError as exc:
                await self.send_error(exc.code, exc.message)
                return
            await self.event("transcript", text=text_value, final=True, source="texto")
            await self.start_response(text_value)
        elif msg_type == "confirmation":
            try:
                data = validate_confirmation(payload)
            except ProtocolError as exc:
                await self.send_error(exc.code, exc.message)
                return
            pending = self.pending_confirmation
            if pending is None or pending.id != data["id"]:
                await self.send_error(
                    "confirmation_invalid",
                    "Nenhuma confirmação pendente com esse identificador.",
                )
                return
            await self.start_response("sim, confirmo" if data["approved"] else "não, cancelo")
        elif msg_type == "interrupt":
            await self.interrupt(reason="user")
        elif msg_type == "playback.started":
            await self.set_state("speaking", "Reproduzindo áudio.")
        elif msg_type == "playback.done":
            self._cancel_idle_timer()
            self._ignore_audio_until = time.monotonic() + 0.4
            self.vad.reset()
            self._reset_acoustic()
            if self.state in {"speaking", "thinking", "error"}:
                await self.set_state(self.resting_state(), "Pronto para ouvir.")
        elif msg_type == "reset":
            if hasattr(self._brain, "reset"):
                self._brain.reset()
            if self._agent is not None and hasattr(self._agent, "reset"):
                self._agent.reset()
            self.pending_confirmation = None
            await self.event("history.reset")
            await self.set_state(self.resting_state(), "Histórico apagado.")

    # -- áudio -------------------------------------------------------------

    async def handle_audio(self, data: bytes) -> None:
        if not data:
            return
        if len(data) > 1_048_576:
            await self.send_error("audio_frame_too_large", "Bloco de áudio maior que 1 MiB.", fatal=True)
            return
        if not self.capture_active:
            return
        if self.state in {"thinking", "speaking"}:
            self.vad.reset()
            return
        if time.monotonic() < self._ignore_audio_until:
            self.vad.reset()
            return
        if self.services.wake_acoustic is not None:
            loop = asyncio.get_running_loop()
            detections = await loop.run_in_executor(
                None, self.services.wake_acoustic.feed, data
            )
            for detection in detections:
                await self._on_acoustic_detection(detection)
        events = self.vad.feed(data)
        await self._process_vad_events(events)

    def _reset_acoustic(self) -> None:
        detector = self.services.wake_acoustic
        if detector is not None and hasattr(detector, "reset"):
            with contextlib.suppress(Exception):
                detector.reset()

    async def _on_acoustic_detection(self, detection: Any) -> None:
        """Ativação pelo classificador acústico (independente do LLM/STT)."""
        if self.state in {"thinking", "speaking"}:
            return
        if self.bypass_wake_once:
            return
        self.bypass_wake_once = True
        await self.event(
            "wakeword.detected",
            source="acoustic",
            phrase="saturnbmo",
            score=round(float(getattr(detection, "score", 0.0)), 4),
            message="Palavra de ativação detectada.",
        )
        await self.set_state("listening", "Pode falar, estou ouvindo.")

    async def _process_vad_events(self, events: list[Any]) -> None:
        for event in events:
            if event.kind == "speech_start":
                await self.event("vad", speaking=True)
            elif event.kind == "speech_end" and event.utterance:
                await self.event("vad", speaking=False)
                if self._utterance_task and not self._utterance_task.done():
                    continue
                self._utterance_task = asyncio.create_task(self.handle_utterance(event.utterance))

    async def handle_utterance(self, pcm: bytes) -> None:
        gen = self.generation
        await self.set_state("thinking", "Transcrevendo a fala...")
        try:
            result = await self.services.stt.transcribe(
                pcm, sample_rate=int(self.config["audio"]["sample_rate"])
            )
        except SttUnavailable as exc:
            await self.send_error("stt_unavailable", str(exc))
            await self._recover_after_error()
            return
        except SttError as exc:
            await self.send_error("stt_error", str(exc))
            await self._recover_after_error()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha inesperada no STT")
            await self.send_error("stt_error", f"Falha no reconhecimento de fala: {exc}")
            await self._recover_after_error()
            return
        if gen != self.generation:
            return
        text = result.text.strip()
        await self.event("transcript", text=text, final=True, source="audio",
                         duration_ms=result.duration_ms)
        if not text:
            await self.event("wakeword.not_detected", reason="empty",
                             message="Não entendi. Diga 'Ei, BMO' e sua pergunta.")
            await self.set_state(self.resting_state(), "Não entendi. Pode repetir?")
            return

        wake_enabled = bool(self.config["wakeword"]["enabled"])
        wake_mode = self.services.wake_mode
        transcript_required = (
            wake_enabled and wake_mode in {"transcript", "hybrid"} and not self.bypass_wake_once
        )
        acoustic_only = (
            wake_enabled and wake_mode == "acoustic" and not self.bypass_wake_once
        )
        match = self.services.wake.detect(text) if wake_enabled else None

        if acoustic_only:
            # No modo acústico puro não há fallback por transcrição.
            await self.event(
                "wakeword.not_detected",
                reason="acoustic",
                transcript=text,
                message="Não ouvi a palavra de ativação. Diga 'Ei, BMO' ou toque em Falar.",
            )
            await self.set_state(self.resting_state(), "Aguardando 'Ei, BMO'.")
            return

        if transcript_required:
            if not match or not match.detected:
                await self.event(
                    "wakeword.not_detected",
                    transcript=text,
                    message="Não ouvi 'Ei, BMO'. Diga a palavra de ativação ou toque em Falar.",
                )
                await self.set_state(self.resting_state(), "Aguardando 'Ei, BMO'.")
                return
            await self.event(
                "wakeword.detected",
                source="transcript",
                phrase=match.matched_phrase,
                transcript=text,
            )
            if not match.remaining_text:
                self.bypass_wake_once = True
                await self.event("assistant.text.delta", text="Pode falar!", id="wake-ack")
                await self.event("assistant.text.done", text="Pode falar!", id="wake-ack",
                                 audio_available=False)
                await self.set_state(self.resting_state(), "Ouvindo...")
                return
            text = match.remaining_text
        elif match is not None and match.detected and match.remaining_text:
            # Ativação acústica: se o STT também transcreveu a frase de chamada,
            # remova-a para o LLM receber apenas a pergunta.
            text = match.remaining_text
        self.bypass_wake_once = False
        await self.event("request.accepted", text=text)
        await self.start_response(text)

    # -- resposta ----------------------------------------------------------

    async def start_response(self, text: str) -> None:
        if self._response_task and not self._response_task.done():
            await self.interrupt(reason="new_request")
        self._response_task = asyncio.create_task(self.respond(text))

    async def respond(self, user_text: str) -> None:
        self.generation += 1
        gen = self.generation
        assistant_id = uuid.uuid4().hex[:12]
        await self.set_state("thinking", "Pensando...")
        await self.event("activity", activity="processing", status="start", label="Pensando")
        try:
            if self.pending_confirmation is not None:
                if await self._handle_confirmation_reply(user_text, assistant_id, gen):
                    return
            local = detect_local_intent(user_text)
            weather_intent = None if local is not None else detect_weather_intent(user_text)
            if local is not None:
                answer = local.text
                await self.event("assistant.text.delta", text=answer, id=assistant_id)
            elif weather_intent is not None:
                try:
                    answer = await self.services.weather.answer(
                        weather_intent,
                        latitude=self.location[0] if self.location else None,
                        longitude=self.location[1] if self.location else None,
                    )
                except (WeatherUnavailable, WeatherError) as exc:
                    await self.send_error("weather_error", str(exc))
                    await self._recover_after_error()
                    return
                await self.event("assistant.text.delta", text=answer, id=assistant_id)
            elif self._agent is not None:
                try:
                    result = await self._agent.run(user_text, self.event)
                except LlmUnavailable as exc:
                    await self.send_error("llm_unavailable", str(exc))
                    await self._recover_after_error()
                    return
                except LlmError as exc:
                    await self.send_error("llm_error", str(exc))
                    await self._recover_after_error()
                    return
                if gen != self.generation:
                    return
                if result.pending is not None:
                    self.pending_confirmation = result.pending
                answer = result.text
                if not answer:
                    await self.send_error("empty_answer", "O modelo não retornou resposta.")
                    await self._recover_after_error()
                    return
                await self.event("assistant.text.delta", text=answer, id=assistant_id)
                if result.pending is not None:
                    # Não sinalize sucesso antes da confirmação do usuário.
                    await self.event(
                        "assistant.text.done",
                        text=answer,
                        id=assistant_id,
                        audio_available=self.services.tts.available(),
                    )
                    if self.services.tts.available():
                        await self.speak(answer, assistant_id, gen)
                    return
            else:
                pieces: list[str] = []
                try:
                    async for piece in self._brain.stream_reply(user_text):
                        if gen != self.generation:
                            return
                        pieces.append(piece)
                        await self.event("assistant.text.delta", text=piece, id=assistant_id)
                    answer = sanitize_reply("".join(pieces))
                except LlmUnavailable as exc:
                    await self.send_error("llm_unavailable", str(exc))
                    await self._recover_after_error()
                    return
                except LlmError as exc:
                    await self.send_error("llm_error", str(exc))
                    await self._recover_after_error()
                    return
                if not answer:
                    await self.send_error("empty_answer", "O modelo não retornou resposta.")
                    await self._recover_after_error()
                    return
                authorized = parse_authorized_action(
                    answer, self.config["security"].get("allowed_commands")
                )
                if authorized is not None:
                    answer = authorized.text
            if gen != self.generation:
                return
            await self.event("activity", activity="success", status="done", label="Pronto")
            await self.event(
                "assistant.text.done",
                text=answer,
                id=assistant_id,
                audio_available=self.services.tts.available(),
            )
            if self.services.tts.available():
                await self.speak(answer, assistant_id, gen)
            else:
                await self.event(
                    "audio.unavailable",
                    reason="tts_unavailable",
                    message="O TTS local não está disponível. A resposta foi mostrada em texto.",
                )
                await self.set_state(self.resting_state(), "Resposta exibida sem áudio.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro ao gerar resposta: %s", exc)
            await self.event("activity", activity="error", status="error", label="Erro")
            await self.send_error("internal_error", "Ocorreu um erro ao gerar a resposta.")
            await self._recover_after_error()

    async def _handle_confirmation_reply(
        self, user_text: str, assistant_id: str, gen: int
    ) -> bool:
        """Executa ou cancela uma exclusão pendente a partir da fala/texto.

        Retorna True quando a mensagem era uma resposta de confirmação e já foi
        tratada (a resposta normal não deve continuar).
        """
        pending = self.pending_confirmation
        if pending is None:
            return False
        normalized = normalize_text(user_text)
        affirmative = bool(_AFFIRMATIVE.match(normalized))
        negative = bool(_NEGATIVE.match(normalized))
        if not affirmative and not negative:
            # A pessoa mudou de assunto: a exclusão não é executada.
            self.pending_confirmation = None
            await self.event(
                "confirmation.result",
                id=pending.id,
                approved=False,
                ok=False,
                message="Confirmação abandonada.",
            )
            return False

        self.pending_confirmation = None
        if negative:
            answer = "Tudo bem, cancelei a exclusão."
            await self.event(
                "confirmation.result",
                id=pending.id,
                approved=False,
                ok=True,
                message=answer,
            )
            await self.event("activity", activity="success", status="done", label="Cancelado")
        else:
            await self.event(
                "activity",
                activity=pending.activity,
                status="start",
                label="Executando exclusão",
            )
            result = await self.services.registry.execute_confirmed(pending)
            if result.ok:
                path = result.data.get("path", "")
                answer = f"Pronto. Excluí '{path}' da pasta autorizada."
                await self.event("activity", activity="success", status="done", label="Exclusão concluída")
            else:
                detail = result.data.get("error", "erro desconhecido")
                answer = f"Não consegui excluir: {detail}"
                await self.event("activity", activity="error", status="error", label="Falha na exclusão")
            await self.event(
                "confirmation.result",
                id=pending.id,
                approved=True,
                ok=result.ok,
                message=answer,
            )
        if gen != self.generation:
            return True
        await self.event("assistant.text.delta", text=answer, id=assistant_id)
        await self.event(
            "assistant.text.done",
            text=answer,
            id=assistant_id,
            audio_available=self.services.tts.available(),
        )
        if self.services.tts.available():
            await self.speak(answer, assistant_id, gen)
        else:
            await self.set_state(self.resting_state(), "Resposta exibida sem áudio.")
        return True

    async def speak(self, text: str, assistant_id: str, gen: int) -> None:
        try:
            audio = await self.services.tts.synthesize(text)
        except TtsUnavailable as exc:
            await self.event("audio.unavailable", reason="tts_unavailable", message=str(exc))
            await self._recover_after_error()
            return
        except TtsError as exc:
            await self.send_error("tts_error", str(exc))
            await self.event("audio.unavailable", reason="tts_error", message=str(exc))
            await self._recover_after_error()
            return
        if gen != self.generation:
            return
        audio_id = uuid.uuid4().hex[:12]
        await self.set_state("speaking", "Falando...")
        await self.event(
            "audio.start",
            id=audio_id,
            assistant_id=assistant_id,
            format="pcm_s16le",
            sample_rate=audio.sample_rate,
            channels=audio.channels,
            duration_ms=int(audio.duration_s * 1000),
            engine=audio.engine,
        )
        chunk_bytes = max(2, int(audio.sample_rate * audio.channels * 2 * 0.1))
        try:
            for offset in range(0, len(audio.pcm), chunk_bytes):
                if gen != self.generation or self._closed:
                    return
                await self.ws.send_bytes(audio.pcm[offset : offset + chunk_bytes])
                # Envia um pouco mais rápido que o tempo real, mantendo a fila curta.
                await asyncio.sleep(0.02)
            await self.event("audio.end", id=audio_id)
            self._schedule_idle_after_playback(audio.duration_s + 3.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao enviar áudio: %s", exc)

    def _schedule_idle_after_playback(self, seconds: float) -> None:
        self._cancel_idle_timer()

        async def reset_later() -> None:
            try:
                await asyncio.sleep(seconds)
                if self.state == "speaking":
                    self.vad.reset()
                    self._ignore_audio_until = time.monotonic() + 0.4
                    await self.set_state(self.resting_state(), "Pronto para ouvir.")
            except asyncio.CancelledError:
                pass

        self._idle_task = asyncio.create_task(reset_later())

    def _cancel_idle_timer(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    async def interrupt(self, reason: str) -> None:
        self.generation += 1
        for task in (self._response_task, self._utterance_task):
            if task and not task.done():
                task.cancel()
        self._response_task = None
        self._utterance_task = None
        self._cancel_idle_timer()
        self.vad.reset()
        self._reset_acoustic()
        self._ignore_audio_until = time.monotonic() + 0.4
        await self.event("audio.stop", reason=reason)
        await self.set_state(self.resting_state(), "Fala interrompida." if reason == "user" else "Pronto.")

    async def _recover_after_error(self) -> None:
        if self._recovery_task and not self._recovery_task.done():
            return

        async def recover() -> None:
            try:
                await asyncio.sleep(2.5)
                if self.state == "error":
                    self.vad.reset()
                    await self.set_state(self.resting_state(), "Pronto para tentar de novo.")
            except asyncio.CancelledError:
                pass

        self._recovery_task = asyncio.create_task(recover())

    async def send_error(self, code: str, message: str, fatal: bool = False) -> None:
        log.warning("Erro na sessão %s: %s - %s", self.session_id, code, message)
        await self.set_state("error", message)
        await self.event("error", code=code, message=message, fatal=fatal)


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------


def configure_logging(config: dict[str, Any]) -> None:
    level = getattr(logging, str(config["server"].get("log_level", "INFO")).upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)
    log_path = Path(config["paths"]["log_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.setLevel(level)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backend local do BMO")
    parser.add_argument("--config", help="caminho do config.json")
    parser.add_argument("--host", help="endereço de escuta (padrão: config)")
    parser.add_argument("--port", type=int, help="porta (padrão: config)")
    parser.add_argument("--print-token", action="store_true", help="imprime o token local e sai")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.print_token:
        print(config["_token"])
        return
    if args.host:
        config["server"]["host"] = args.host
    if args.port:
        config["server"]["port"] = args.port
    configure_logging(config)
    app = create_app(config, enable_discovery=True)
    log.info(
        "API em http://%s:%s (token em %s)",
        config["server"]["host"],
        config["server"]["port"],
        DATA_DIR / "token",
    )
    uvicorn.run(
        app,
        host=str(config["server"]["host"]),
        port=int(config["server"]["port"]),
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
