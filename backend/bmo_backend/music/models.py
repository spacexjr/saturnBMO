"""Modelos de dados da integração musical do BMO.

Todos os objetos são serializáveis em JSON e usam nomes estáveis consumidos
pelo backend, pelas ferramentas do LLM e pelo aplicativo Android.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def thumbnail_url(thumbnails: list[dict[str, Any]] | None) -> str:
    """Escolhe a maior miniatura disponível sem depender da ordem da API."""
    if not thumbnails:
        return ""
    best = max(
        thumbnails,
        key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0),
    )
    return str(best.get("url") or "")


def duration_ms_from_seconds(value: Any) -> int | None:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    return seconds * 1000 if seconds >= 0 else None


def join_artists(item: dict[str, Any]) -> str:
    artists = item.get("artists") or []
    names = [str(artist.get("name") or "").strip() for artist in artists if isinstance(artist, dict)]
    names = [name for name in names if name]
    if names:
        return ", ".join(names)
    artist = item.get("artist")
    if isinstance(artist, str):
        return artist.strip()
    if isinstance(artist, dict):
        return str(artist.get("name") or "").strip()
    author = item.get("author")
    return str(author or "").strip()


@dataclass
class Track:
    id: str
    title: str
    artist: str = ""
    album: str = ""
    duration_ms: int | None = None
    thumbnail: str = ""
    source: str = "youtube_music"
    video_id: str = ""
    url: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data.get("video_id"):
            data["video_id"] = self.id
        return data


@dataclass
class MediaItem:
    """Resultado de pesquisa ou item de biblioteca (música, álbum etc.)."""

    id: str
    type: str
    title: str
    artist: str = ""
    album: str = ""
    duration_ms: int | None = None
    thumbnail: str = ""
    author: str = ""
    item_count: int | None = None
    year: str = ""
    video_id: str = ""
    url: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.type in {"song", "video"} and not data.get("video_id"):
            data["video_id"] = self.id
        return data

    def as_track(self) -> Track:
        return Track(
            id=self.video_id or self.id,
            video_id=self.video_id or self.id,
            title=self.title,
            artist=self.artist,
            album=self.album,
            duration_ms=self.duration_ms,
            thumbnail=self.thumbnail,
        )


@dataclass
class QueueItem:
    index: int
    tlid: int | None
    track_id: str
    title: str
    artist: str = ""
    album: str = ""
    duration_ms: int | None = None
    uri: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlaybackState:
    status: str = "stopped"
    volume: float | None = None
    volume_percent: int | None = None
    track: Track | None = None
    position_ms: int = 0
    duration_ms: int | None = None
    queue_length: int = 0
    player: str = "mopidy"
    available: bool = True
    verified: bool = False
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        track = self.track or Track(id="", title="")
        length_s = None
        if self.duration_ms is not None:
            length_s = round(self.duration_ms / 1000, 1)
        data = {
            # Compatível com /api/v1/media e com o app Android já existente.
            "player": self.player,
            "is_bitchord": False,
            "status": self.status,
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "length_s": length_s,
            "art_url": track.thumbnail,
            "volume": self.volume,
            "volume_percent": self.volume_percent,
            "available": self.available,
            "verified": self.verified,
            "position_ms": self.position_ms,
            "duration_ms": self.duration_ms,
            "queue_length": self.queue_length,
            "track": track.as_dict() if track.id or track.title else None,
            "message": self.message,
        }
        data.update(self.extra)
        return data
