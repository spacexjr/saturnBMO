"""Cliente do YouTube Music baseado em ``ytmusicapi``.

Responsabilidades:
- pesquisa de músicas, artistas, álbuns e playlists;
- metadados de faixas;
- biblioteca pessoal (playlists e músicas curtidas), quando há autenticação.

A resolução do fluxo de áudio NÃO é feita aqui: ``ytmusicapi`` não decifra as
URLs de streaming. O arquivo ``stream_resolver.py`` usa yt-dlp para isso,
mantendo o Mopidy como player.

Credenciais nunca são escritas no código. O arquivo de autenticação do navegador
(``browser.json``) é criado pelo próprio usuário e fica fora do Git.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from .config import YtMusicConfig
from .models import MediaItem, Track, duration_ms_from_seconds, join_artists, thumbnail_url

log = logging.getLogger("bmo.music.ytmusic")

_FILTER_ALIASES = {
    "songs": "songs",
    "song": "songs",
    "musicas": "songs",
    "músicas": "songs",
    "tracks": "songs",
    "track": "songs",
    "artists": "artists",
    "artist": "artists",
    "artistas": "artists",
    "albums": "albums",
    "album": "albums",
    "álbuns": "albums",
    "playlists": "playlists",
    "playlist": "playlists",
    "all": None,
    "tudo": None,
    "": None,
}


class YTMusicError(RuntimeError):
    pass


class YTMusicUnavailable(YTMusicError):
    pass


class YTMusicAuthRequired(YTMusicError):
    pass


def _album_name(item: dict[str, Any]) -> str:
    album = item.get("album")
    if isinstance(album, dict):
        return str(album.get("name") or "")
    return str(album or "")


def _normalize_item(item: dict[str, Any]) -> MediaItem | None:
    kind = str(item.get("resultType") or "").lower()
    thumb = thumbnail_url(item.get("thumbnails"))
    if kind in {"song", "video"}:
        video_id = str(item.get("videoId") or "")
        if not video_id:
            return None
        title = str(item.get("title") or "").strip()
        if not title:
            return None
        return MediaItem(
            id=video_id,
            type="song",
            title=title,
            artist=join_artists(item),
            album=_album_name(item),
            duration_ms=duration_ms_from_seconds(item.get("duration_seconds")),
            thumbnail=thumb,
            video_id=video_id,
        )
    if kind == "artist":
        artist = item.get("artist")
        if isinstance(artist, dict):
            artist_name = str(artist.get("name") or "")
            artist_id = str(artist.get("id") or "")
        else:
            artist_name = str(artist or item.get("title") or "")
            artist_id = ""
        browse_id = str(item.get("browseId") or artist_id)
        if not browse_id or not artist_name:
            return None
        return MediaItem(
            id=browse_id,
            type="artist",
            title=artist_name,
            artist=artist_name,
            thumbnail=thumb,
            author=str(item.get("subscribers") or ""),
        )
    if kind == "album":
        browse_id = str(item.get("browseId") or "")
        title = str(item.get("title") or "").strip()
        if not browse_id or not title:
            return None
        return MediaItem(
            id=browse_id,
            type="album",
            title=title,
            artist=join_artists(item),
            thumbnail=thumb,
            year=str(item.get("year") or ""),
        )
    if kind in {"playlist", "community_playlist", "featured_playlist"}:
        playlist_id = str(item.get("browseId") or item.get("playlistId") or "")
        title = str(item.get("title") or "").strip()
        if not playlist_id or not title:
            return None
        count = item.get("itemCount")
        try:
            item_count = int(count) if count is not None else None
        except (TypeError, ValueError):
            item_count = None
        return MediaItem(
            id=playlist_id,
            type="playlist",
            title=title,
            author=str(item.get("author") or ""),
            thumbnail=thumb,
            item_count=item_count,
        )
    return None


def _normalize_many(items: list[dict[str, Any]] | None) -> list[MediaItem]:
    results: list[MediaItem] = []
    seen: set[tuple[str, str]] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_item(item)
        if normalized is None:
            continue
        key = (normalized.type, normalized.id)
        if key in seen:
            continue
        seen.add(key)
        results.append(normalized)
    return results


class YTMusicClient:
    def __init__(self, config: YtMusicConfig) -> None:
        self.config = config
        self.enabled = bool(config.enabled)
        self._instance: Any = None
        self._lock = threading.Lock()
        self._init_error: str | None = None

    def auth_status(self) -> dict[str, Any]:
        auth_file = Path(self.config.auth_file) if self.config.auth_file else None
        authenticated = bool(auth_file and auth_file.is_file())
        return {
            "enabled": self.enabled,
            "authenticated": authenticated,
            "mode": "browser" if authenticated else "anonymous",
        }

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            import ytmusicapi  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            self._init_error = f"ytmusicapi não instalado: {exc}"
            return False
        return True

    def _build(self) -> Any:
        if not self.enabled:
            raise YTMusicUnavailable("A integração com o YouTube Music está desativada.")
        try:
            from ytmusicapi import YTMusic
        except Exception as exc:  # noqa: BLE001
            raise YTMusicUnavailable(
                "ytmusicapi não está instalado. Rode: pip install -r requirements.txt"
            ) from exc
        auth: str | None = None
        if self.config.auth_file:
            path = Path(self.config.auth_file)
            if path.is_file():
                auth = str(path)
            else:
                # Busca e metadados funcionam sem login. A biblioteca pessoal
                # (playlists curtidas) continua exigindo autenticação e
                # reporta isso ao usuário quando for chamada.
                log.warning(
                    "Autenticação do YouTube Music não encontrada em %s; "
                    "usando modo anônimo.",
                    path,
                )
        try:
            return YTMusic(auth=auth, language=self.config.language, location=self.config.location)
        except Exception as exc:  # noqa: BLE001
            raise YTMusicError(f"Não foi possível iniciar o ytmusicapi: {exc}") from exc

    def _get(self) -> Any:
        # Deve ser chamado com self._lock já adquirido por _run.
        if self._instance is None:
            self._instance = self._build()
        return self._instance

    async def _run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        def call() -> Any:
            with self._lock:
                instance = self._get()
                return func(instance, *args, **kwargs)

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(call), timeout=self.config.timeout_s
            )
        except asyncio.TimeoutError as exc:
            raise YTMusicError("O YouTube Music demorou demais para responder.") from exc
        except (YTMusicError, YTMusicUnavailable):
            raise
        except Exception as exc:  # noqa: BLE001
            message = str(exc).strip() or exc.__class__.__name__
            raise YTMusicError(f"Falha ao consultar o YouTube Music: {message}") from exc

    async def search(
        self, query: str, filter: str = "songs", limit: int | None = None
    ) -> list[MediaItem]:
        clean = (query or "").strip()
        if not clean:
            raise YTMusicError("Informe o que pesquisar.")
        normalized_filter = str(filter or "songs").strip().lower()
        if normalized_filter not in _FILTER_ALIASES:
            raise YTMusicError(
                "Filtro inválido. Use songs, artists, albums, playlists ou all."
            )
        api_filter = _FILTER_ALIASES[normalized_filter]
        max_results = max(1, min(int(limit or self.config.max_results), 50))

        if api_filter is None:
            items = await self._run(
                lambda yt: yt.search(clean, limit=max_results * 2, ignore_spelling=True)
            )
            return _normalize_many(items)[:max_results]

        items = await self._run(
            lambda yt: yt.search(
                clean,
                filter=api_filter,
                limit=max_results * 2,
                ignore_spelling=True,
            )
        )
        normalized = _normalize_many(items)
        if normalized:
            return normalized[:max_results]

        # Algumas combinações de filtro do ytmusicapi retornam lista vazia
        # enquanto a busca geral funciona. Nesse caso filtramos localmente,
        # sem inventar resultados.
        items = await self._run(
            lambda yt: yt.search(clean, limit=max_results * 3, ignore_spelling=True)
        )
        wanted_type = "song" if api_filter == "songs" else api_filter.rstrip("s")
        filtered = [item for item in _normalize_many(items) if item.type == wanted_type]
        return filtered[:max_results]

    async def get_track(self, video_id: str) -> Track:
        clean = (video_id or "").strip()
        if not clean:
            raise YTMusicError("Informe o identificador da faixa.")
        data = await self._run(lambda yt: yt.get_song(clean))
        if not isinstance(data, dict):
            raise YTMusicError("O YouTube Music não devolveu metadados da faixa.")
        details = data.get("videoDetails") or {}
        if not details:
            status = (data.get("playabilityStatus") or {}).get("status")
            reason = (data.get("playabilityStatus") or {}).get("reason")
            raise YTMusicError(
                f"Faixa indisponível no YouTube Music ({status or 'sem detalhes'}"
                f"{': ' + reason if reason else ''})."
            )
        title = str(details.get("title") or "").strip()
        if not title:
            raise YTMusicError("Faixa sem título nos metadados.")
        thumbnails = (details.get("thumbnail") or {}).get("thumbnails") or []
        return Track(
            id=clean,
            video_id=clean,
            title=title,
            artist=str(details.get("author") or ""),
            album="",
            duration_ms=duration_ms_from_seconds(details.get("lengthSeconds")),
            thumbnail=thumbnail_url(thumbnails),
            url=f"https://music.youtube.com/watch?v={clean}",
        )

    async def get_playlist(self, playlist_id: str, limit: int | None = None) -> dict[str, Any]:
        clean = (playlist_id or "").strip()
        if not clean:
            raise YTMusicError("Informe o identificador da playlist.")
        max_tracks = max(1, min(int(limit or 100), 500))
        data = await self._run(lambda yt: yt.get_playlist(clean, limit=max_tracks))
        if not isinstance(data, dict):
            raise YTMusicError("Playlist inválida ou indisponível.")
        tracks: list[Track] = []
        for item in data.get("tracks") or []:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("videoId") or "")
            title = str(item.get("title") or "").strip()
            if not video_id or not title:
                continue
            tracks.append(
                Track(
                    id=video_id,
                    video_id=video_id,
                    title=title,
                    artist=join_artists(item),
                    album=_album_name(item),
                    duration_ms=duration_ms_from_seconds(item.get("duration_seconds")),
                    thumbnail=thumbnail_url(item.get("thumbnails")),
                    url=f"https://music.youtube.com/watch?v={video_id}",
                )
            )
        return {
            "id": clean,
            "type": "playlist",
            "title": str(data.get("title") or ""),
            "author": str(data.get("author") or ""),
            "thumbnail": thumbnail_url(data.get("thumbnails")),
            "track_count": len(tracks),
            "tracks": [track.as_dict() for track in tracks],
        }

    async def library_playlists(self, limit: int | None = None) -> list[MediaItem]:
        max_results = max(1, min(int(limit or self.config.max_results), 100))
        try:
            items = await self._run(lambda yt: yt.get_library_playlists(limit=max_results))
        except YTMusicError as exc:
            raise YTMusicAuthRequired(
                "Para listar suas playlists pessoais, configure a autenticação do "
                "YouTube Music em music.ytmusic.auth_file."
            ) from exc
        if items is None:
            raise YTMusicAuthRequired(
                "O YouTube Music não devolveu a biblioteca. Verifique a autenticação."
            )
        return _normalize_many(items)[:max_results]

    async def liked_songs(self, limit: int | None = None) -> list[Track]:
        max_results = max(1, min(int(limit or 25), 500))
        try:
            data = await self._run(lambda yt: yt.get_liked_songs(limit=max_results))
        except YTMusicError as exc:
            raise YTMusicAuthRequired(
                "Para acessar as músicas curtidas, configure a autenticação do "
                "YouTube Music em music.ytmusic.auth_file."
            ) from exc
        if not isinstance(data, dict):
            raise YTMusicAuthRequired(
                "O YouTube Music não devolveu as músicas curtidas. Verifique a autenticação."
            )
        tracks: list[Track] = []
        for item in data.get("tracks") or []:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("videoId") or "")
            title = str(item.get("title") or "").strip()
            if not video_id or not title:
                continue
            tracks.append(
                Track(
                    id=video_id,
                    video_id=video_id,
                    title=title,
                    artist=join_artists(item),
                    album=_album_name(item),
                    duration_ms=duration_ms_from_seconds(item.get("duration_seconds")),
                    thumbnail=thumbnail_url(item.get("thumbnails")),
                    url=f"https://music.youtube.com/watch?v={video_id}",
                )
            )
        return tracks

    async def get_album(self, browse_id: str) -> dict[str, Any]:
        clean = (browse_id or "").strip()
        if not clean:
            raise YTMusicError("Informe o identificador do álbum.")
        data = await self._run(lambda yt: yt.get_album(clean))
        if not isinstance(data, dict):
            raise YTMusicError("Álbum inválido ou indisponível.")
        tracks = [
            {
                "id": str(item.get("videoId") or ""),
                "title": str(item.get("title") or ""),
                "artist": join_artists(item),
                "duration_ms": duration_ms_from_seconds(item.get("duration_seconds")),
            }
            for item in data.get("tracks") or []
            if isinstance(item, dict) and item.get("videoId")
        ]
        return {
            "id": clean,
            "type": "album",
            "title": str(data.get("title") or ""),
            "artist": join_artists(data),
            "year": str(data.get("year") or ""),
            "thumbnail": thumbnail_url(data.get("thumbnails")),
            "tracks": tracks,
        }
