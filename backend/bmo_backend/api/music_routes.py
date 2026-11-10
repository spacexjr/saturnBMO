"""Rotas HTTP de música do SaturnBMO.

Todas as rotas de controle exigem o mesmo token Bearer do restante da API. A
única exceção é o proxy de áudio assinado por HMAC consumido pelo Mopidy local.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..music.manager import MusicError, MusicPlaybackError, MusicUnavailable
from ..music.mopidy_client import MopidyError
from ..music.stream_proxy import proxy_stream

log = logging.getLogger("bmo.music.api")

AuthDependency = Callable[[Request], Awaitable[None]]


class PlayRequest(BaseModel):
    track_id: str = Field(..., min_length=1, max_length=64)


class VolumeRequest(BaseModel):
    volume: int = Field(..., ge=0, le=100, description="Volume em porcentagem (0-100).")


class QueueAddRequest(BaseModel):
    track_id: str = Field(..., min_length=1, max_length=64)


class QueueRemoveRequest(BaseModel):
    index: int = Field(..., ge=0, le=10000)


def _music(request: Request) -> Any:
    services = getattr(request.app.state, "services", None)
    return getattr(services, "music", None)


def _error(code: str, message: str, status_code: int, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


async def _guard(coro: Awaitable[Any]) -> Any:
    try:
        return await coro
    except MusicPlaybackError as exc:
        return _error(
            "playback_not_confirmed",
            str(exc),
            409,
            state=exc.state.as_dict() if exc.state is not None else None,
        )
    except MusicUnavailable as exc:
        return _error("music_unavailable", str(exc), 503)
    except MusicError as exc:
        return _error("music_error", str(exc), 400)
    except MopidyError as exc:
        return _error("mopidy_error", str(exc), 503)
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha inesperada em rota de música")
        return _error("music_internal_error", f"Falha ao controlar a música: {exc}", 500)


def build_music_routers(auth_dependency: AuthDependency) -> tuple[APIRouter, APIRouter]:
    router = APIRouter(
        prefix="/api/music",
        tags=["music"],
        dependencies=[Depends(auth_dependency)],
    )
    stream_router = APIRouter(tags=["music"])

    @router.get("/state")
    async def state(request: Request) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.get_state())

    @router.get("/now-playing")
    async def now_playing(request: Request) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.now_playing())

    @router.get("/queue")
    async def queue(request: Request) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.queue_list())

    @router.post("/queue/add")
    async def queue_add(request: Request, body: QueueAddRequest) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.queue_add(body.track_id))

    @router.post("/queue/remove")
    async def queue_remove(request: Request, body: QueueRemoveRequest) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.queue_remove(body.index))

    @router.post("/queue/clear")
    async def queue_clear(request: Request) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.queue_clear())

    @router.get("/search")
    async def search(
        request: Request,
        q: str = Query(..., min_length=1, max_length=200),
        filter: str = Query("songs", max_length=20),
        limit: int = Query(10, ge=1, le=20),
    ) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.search(q, filter=filter, limit=limit))

    @router.get("/playlists")
    async def playlists(
        request: Request,
        limit: int = Query(25, ge=1, le=100),
    ) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.playlist_list(limit=limit))

    @router.post("/play")
    async def play(request: Request, body: PlayRequest) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.play(body.track_id))

    @router.post("/pause")
    async def pause(request: Request) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.pause())

    @router.post("/resume")
    async def resume(request: Request) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.resume())

    @router.post("/next")
    async def next_track(request: Request) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.next())

    @router.post("/previous")
    async def previous_track(request: Request) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.previous())

    @router.post("/stop")
    async def stop(request: Request) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.stop())

    @router.post("/volume")
    async def volume(request: Request, body: VolumeRequest) -> Any:
        music = _music(request)
        if music is None:
            return _error("music_disabled", "A integração musical está desativada.", 503)
        return await _guard(music.set_volume(body.volume))

    @stream_router.get("/api/music/stream/{video_id}")
    async def stream(video_id: str, request: Request, sig: str = "") -> Any:
        music = _music(request)
        if music is None:
            raise HTTPException(status_code=503, detail="Integração musical desativada.")
        return await proxy_stream(
            video_id,
            sig,
            request,
            signer=music.signer,
            resolver=music.resolver,
        )

    @stream_router.head("/api/music/stream/{video_id}")
    async def stream_head(video_id: str, request: Request, sig: str = "") -> Any:
        music = _music(request)
        if music is None:
            raise HTTPException(status_code=503, detail="Integração musical desativada.")
        return await proxy_stream(
            video_id,
            sig,
            request,
            signer=music.signer,
            resolver=music.resolver,
        )

    return router, stream_router
