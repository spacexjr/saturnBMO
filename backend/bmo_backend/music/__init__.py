"""Integração musical do SaturnBMO (Mopidy + YouTube Music + Ollama)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import BACKEND_DIR
from .config import MusicConfig
from .manager import (
    MusicError,
    MusicManager,
    MusicPlaybackError,
    MusicUnavailable,
)
from .mopidy_client import MopidyClient, MopidyError, MopidyTimeout, MopidyUnavailable
from .queue import QueueError, QueueService, TrackRegistry
from .stream_proxy import StreamSigner
from .stream_resolver import StreamResolutionError, StreamResolver
from .ytmusic_client import YTMusicAuthRequired, YTMusicClient, YTMusicError

__all__ = [
    "MusicConfig",
    "MusicError",
    "MusicManager",
    "MusicPlaybackError",
    "MusicUnavailable",
    "MopidyClient",
    "MopidyError",
    "MopidyTimeout",
    "MopidyUnavailable",
    "QueueError",
    "QueueService",
    "StreamResolutionError",
    "StreamResolver",
    "StreamSigner",
    "TrackRegistry",
    "YTMusicAuthRequired",
    "YTMusicClient",
    "YTMusicError",
    "build_music_manager",
]


def _resolve_path(value: str) -> str:
    if not value:
        return ""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    return str(path)


def build_music_manager(
    config: dict[str, Any] | None,
    *,
    server_port: int = 8765,
) -> MusicManager | None:
    """Monta o gerenciador musical a partir da seção ``music`` da config.

    Não abre conexões de rede nem carrega credenciais neste momento; tudo é
    validado sob demanda. Assim o backend continua iniciando mesmo quando o
    Mopidy ou o YouTube Music estão indisponíveis.
    """

    settings = MusicConfig.from_dict(config)
    if not settings.enabled:
        return None
    settings.ytmusic.auth_file = _resolve_path(settings.ytmusic.auth_file)
    settings.ytmusic.cookies_file = _resolve_path(settings.ytmusic.cookies_file)
    settings.stream.cookies_file = _resolve_path(
        settings.stream.cookies_file or settings.ytmusic.cookies_file
    )
    settings.stream.secret_file = _resolve_path(settings.stream.secret_file)
    base_url = settings.stream.public_base_url or f"http://127.0.0.1:{int(server_port)}"
    mopidy = MopidyClient(settings.mopidy.rpc_url, timeout_s=settings.mopidy.timeout_s)
    ytmusic = YTMusicClient(settings.ytmusic)
    resolver = StreamResolver(settings.stream)
    signer = StreamSigner(settings.stream.secret_file or None, base_url=base_url)
    return MusicManager(settings, mopidy, ytmusic, resolver, signer)
