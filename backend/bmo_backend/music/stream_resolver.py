"""Resolução de URLs de áudio do YouTube Music para o Mopidy.

O ``ytmusicapi`` fornece busca, metadados e biblioteca, mas não decifra as URLs
de streaming. O yt-dlp faz essa etapa. A URL resolvida expira, por isso o BMO
nunca a entrega diretamente ao Mopidy: ele enfileira uma URL local assinada
(``/api/music/stream/<video_id>``), e o proxy resolve o fluxo na hora do play.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import StreamConfig

log = logging.getLogger("bmo.music.stream")


class StreamResolutionError(RuntimeError):
    pass


@dataclass
class ResolvedStream:
    url: str
    headers: dict[str, str]
    expires_at: float
    title: str = ""
    duration_ms: int | None = None


class StreamResolver:
    def __init__(self, config: StreamConfig) -> None:
        self.config = config
        self._cache: dict[str, ResolvedStream] = {}
        self._lock = asyncio.Lock()

    def available(self) -> bool:
        try:
            import yt_dlp  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return self.config.enabled

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "resolver": "yt-dlp",
            "installed": self.available(),
            "cache_ttl_s": self.config.cache_ttl_s,
        }

    def _validate(self, video_id: str) -> str:
        clean = (video_id or "").strip()
        if not clean or len(clean) > 32 or not all(
            char.isalnum() or char in "-_" for char in clean
        ):
            raise StreamResolutionError("Identificador de vídeo inválido.")
        return clean

    def _cache_get(self, video_id: str) -> ResolvedStream | None:
        item = self._cache.get(video_id)
        if item is None:
            return None
        if item.expires_at <= time.time():
            self._cache.pop(video_id, None)
            return None
        return item

    def _extract_sync(self, video_id: str) -> ResolvedStream:
        if not self.config.enabled:
            raise StreamResolutionError("A resolução de áudio está desativada.")
        try:
            import yt_dlp
        except Exception as exc:  # noqa: BLE001
            raise StreamResolutionError(
                "yt-dlp não está instalado; não é possível tocar YouTube Music. "
                "Rode: pip install -r requirements.txt"
            ) from exc

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "socket_timeout": self.config.timeout_s,
            "retries": 2,
            "extractor_retries": 1,
        }
        cookies = self.config.cookies_file
        if cookies:
            cookie_path = Path(cookies)
            if not cookie_path.is_file():
                raise StreamResolutionError(
                    "O arquivo de cookies configurado para o yt-dlp não existe."
                )
            options["cookiefile"] = str(cookie_path)

        url = f"https://music.youtube.com/watch?v={video_id}"
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # noqa: BLE001
            # Não inclui a URL assinada nem cookies no log.
            raise StreamResolutionError(
                f"O YouTube Music não liberou o áudio desta faixa: {exc}"
            ) from exc
        if not isinstance(info, dict):
            raise StreamResolutionError("O resolvedor não devolveu dados da faixa.")
        stream_url = info.get("url")
        if not stream_url and info.get("requested_formats"):
            stream_url = (info.get("requested_formats") or [{}])[0].get("url")
        if not stream_url:
            raise StreamResolutionError("Nenhum fluxo de áudio foi encontrado para esta faixa.")
        headers = {
            str(key): str(value)
            for key, value in (info.get("http_headers") or {}).items()
            if value
        }
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        )
        ttl = max(60, int(self.config.cache_ttl_s))
        duration = info.get("duration")
        try:
            duration_ms = int(float(duration) * 1000) if duration is not None else None
        except (TypeError, ValueError):
            duration_ms = None
        return ResolvedStream(
            url=str(stream_url),
            headers=headers,
            expires_at=time.time() + ttl,
            title=str(info.get("title") or ""),
            duration_ms=duration_ms,
        )

    async def resolve(self, video_id: str) -> ResolvedStream:
        clean = self._validate(video_id)
        cached = self._cache_get(clean)
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._cache_get(clean)
            if cached is not None:
                return cached
            try:
                resolved = await asyncio.wait_for(
                    asyncio.to_thread(self._extract_sync, clean),
                    timeout=self.config.timeout_s + 5,
                )
            except asyncio.TimeoutError as exc:
                raise StreamResolutionError(
                    "A resolução do áudio demorou demais. Tente novamente."
                ) from exc
            self._cache[clean] = resolved
            # Limita o cache para não crescer indefinidamente.
            if len(self._cache) > 200:
                self._cache = {
                    key: value
                    for key, value in self._cache.items()
                    if value.expires_at > time.time()
                }
            return resolved
