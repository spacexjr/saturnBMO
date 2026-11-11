"""Configuração da integração musical.

Os valores padrão também aparecem em ``bmo_backend.config.DEFAULT_CONFIG`` para
que ``config.json`` continue sendo a fonte única de configuração do backend.
Este módulo apenas normaliza a seção ``music`` e nunca contém credenciais.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MopidyConfig:
    rpc_url: str = "http://127.0.0.1:6680/mopidy/rpc"
    # O primeiro play pode aguardar o yt-dlp resolver o áudio.
    timeout_s: float = 20.0
    confirm_timeout_s: float = 10.0
    # Unidade systemd de usuário usada por mopidy_start. Sem sudo.
    service_unit: str = "mopidy"
    start_timeout_s: float = 20.0


@dataclass
class YtMusicConfig:
    enabled: bool = True
    auth_file: str = ""
    cookies_file: str = ""
    language: str = "pt"
    location: str = "BR"
    max_results: int = 10
    timeout_s: float = 25.0


@dataclass
class StreamConfig:
    enabled: bool = True
    public_base_url: str = ""
    secret_file: str = ""
    # Opcional: cookies do YouTube para o yt-dlp em faixas restritas.
    # Por padrão herda music.ytmusic.cookies_file em build_music_manager.
    cookies_file: str = ""
    cache_ttl_s: int = 1800
    timeout_s: float = 30.0


@dataclass
class MusicConfig:
    enabled: bool = True
    max_queue_items: int = 200
    max_playlist_tracks: int = 100
    mopidy: MopidyConfig = field(default_factory=MopidyConfig)
    ytmusic: YtMusicConfig = field(default_factory=YtMusicConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MusicConfig":
        data = data or {}
        mopidy = data.get("mopidy") or {}
        ytmusic = data.get("ytmusic") or {}
        stream = data.get("stream") or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            max_queue_items=max(1, min(int(data.get("max_queue_items", 200)), 1000)),
            max_playlist_tracks=max(1, min(int(data.get("max_playlist_tracks", 100)), 500)),
            mopidy=MopidyConfig(
                rpc_url=str(mopidy.get("rpc_url") or "http://127.0.0.1:6680/mopidy/rpc"),
                timeout_s=float(mopidy.get("timeout_s", 20)),
                confirm_timeout_s=float(mopidy.get("confirm_timeout_s", 10)),
                service_unit=str(mopidy.get("service_unit") or "mopidy"),
                start_timeout_s=max(2.0, float(mopidy.get("start_timeout_s", 20))),
            ),
            ytmusic=YtMusicConfig(
                enabled=bool(ytmusic.get("enabled", True)),
                auth_file=str(ytmusic.get("auth_file") or ""),
                cookies_file=str(ytmusic.get("cookies_file") or ""),
                language=str(ytmusic.get("language") or "pt"),
                location=str(ytmusic.get("location") or "BR"),
                max_results=max(1, min(int(ytmusic.get("max_results", 10)), 50)),
                timeout_s=float(ytmusic.get("timeout_s", 25)),
            ),
            stream=StreamConfig(
                enabled=bool(stream.get("enabled", True)),
                public_base_url=str(stream.get("public_base_url") or "").rstrip("/"),
                secret_file=str(stream.get("secret_file") or ""),
                cookies_file=str(stream.get("cookies_file") or ""),
                cache_ttl_s=max(0, int(stream.get("cache_ttl_s", 1800))),
                timeout_s=float(stream.get("timeout_s", 30)),
            ),
        )
