"""Proxy local autenticado para fluxos do YouTube Music.

O Mopidy consome este endpoint no próprio PC. A URL é assinada com HMAC para
que a rota de streaming não fique aberta a qualquer cliente da rede, sem
depender do token do Android (o Mopidy não tem esse token).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ..config import DATA_DIR
from .stream_resolver import ResolvedStream, StreamResolutionError, StreamResolver

log = logging.getLogger("bmo.music.stream_proxy")

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
_PASS_HEADERS = {
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "etag",
    "last-modified",
    "cache-control",
}


def valid_video_id(video_id: str) -> bool:
    return bool(_VIDEO_ID.fullmatch(video_id or ""))


class StreamSigner:
    def __init__(self, secret_file: str | Path | None, *, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        path = Path(secret_file) if secret_file else DATA_DIR / "music_stream.secret"
        self.secret_file = path
        self._secret_value: bytes | None = None

    def _secret(self) -> bytes:
        if self._secret_value is None:
            self._secret_value = self._load_or_create_secret(self.secret_file)
        return self._secret_value

    @staticmethod
    def _load_or_create_secret(path: Path) -> bytes:
        if path.exists():
            data = path.read_bytes().strip()
            if data:
                return data
        path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(48).encode("ascii")
        path.write_bytes(value + b"\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return value

    def sign(self, video_id: str) -> str:
        if not valid_video_id(video_id):
            raise ValueError("Identificador de vídeo inválido.")
        return hmac.new(self._secret(), video_id.encode("ascii"), hashlib.sha256).hexdigest()[:40]

    def verify(self, video_id: str, signature: str) -> bool:
        if not valid_video_id(video_id) or not signature:
            return False
        expected = self.sign(video_id)
        return hmac.compare_digest(expected, signature)

    def stream_uri(self, video_id: str) -> str:
        return (
            f"{self.base_url}/api/music/stream/{video_id}"
            f"?sig={self.sign(video_id)}"
        )

    def video_id_from_uri(self, uri: str) -> str | None:
        if not uri:
            return None
        marker = "/api/music/stream/"
        if marker not in uri:
            return None
        tail = uri.split(marker, 1)[1].split("?", 1)[0]
        return tail if valid_video_id(tail) else None


def _upstream_headers(resolved: ResolvedStream, request: Request) -> dict[str, str]:
    headers = dict(resolved.headers)
    headers.pop("Host", None)
    headers["Accept-Encoding"] = "identity"
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]
    return headers


async def proxy_stream(
    video_id: str,
    signature: str,
    request: Request,
    *,
    signer: StreamSigner,
    resolver: StreamResolver,
) -> Response:
    if not signer.verify(video_id, signature):
        raise HTTPException(status_code=403, detail="Assinatura de áudio inválida.")
    if not resolver.config.enabled:
        raise HTTPException(status_code=503, detail="A resolução de áudio está desativada.")
    try:
        resolved = await resolver.resolve(video_id)
    except StreamResolutionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    headers = _upstream_headers(resolved, request)
    timeout = httpx.Timeout(resolver.config.timeout_s, connect=10.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    if request.method == "HEAD":
        try:
            upstream = await client.head(resolved.url, headers=headers)
            forwarded = {
                key: value
                for key, value in upstream.headers.items()
                if key.lower() in _PASS_HEADERS
            }
            await upstream.aclose()
            await client.aclose()
            return Response(status_code=upstream.status_code, headers=forwarded)
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(
                status_code=502, detail=f"Falha ao acessar o fluxo de áudio: {exc}"
            ) from exc

    request_obj = client.build_request("GET", resolved.url, headers=headers)
    try:
        upstream = await client.send(request_obj, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502, detail=f"Falha ao acessar o fluxo de áudio: {exc}"
        ) from exc

    forwarded = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in _PASS_HEADERS
    }
    if upstream.status_code >= 400:
        body = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        return Response(
            content=body[:500],
            status_code=upstream.status_code,
            headers={"content-type": upstream.headers.get("content-type", "text/plain")},
        )

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    media_type = forwarded.pop("content-type", "audio/mp4")
    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        media_type=media_type,
        headers=forwarded,
    )


def stream_status(signer: StreamSigner | None, resolver: StreamResolver | None) -> dict[str, Any]:
    return {
        "enabled": bool(signer and resolver and resolver.config.enabled),
        "resolver": resolver.status() if resolver else {"enabled": False},
        "signed_urls": bool(signer),
    }
