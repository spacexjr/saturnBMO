"""Fachada de música do BMO.

Combina:
- Mopidy (player e fila reais, via JSON-RPC);
- YouTube Music (busca, metadados e biblioteca via ytmusicapi);
- proxy local assinado (áudio resolvido pelo yt-dlp para o Mopidy).

Nenhuma resposta de sucesso é inventada: comandos de transporte só retornam
sucesso depois de consultar o estado real do Mopidy.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Iterable

from .config import MusicConfig
from .mopidy_client import MopidyClient, MopidyError, MopidyTimeout, MopidyUnavailable
from .models import MediaItem, PlaybackState, QueueItem, Track
from .queue import QueueError, QueueService, TrackRegistry
from .stream_proxy import StreamSigner, stream_status, valid_video_id
from .stream_resolver import StreamResolutionError, StreamResolver
from .ytmusic_client import (
    YTMusicAuthRequired,
    YTMusicClient,
    YTMusicError,
    YTMusicUnavailable,
)

log = logging.getLogger("bmo.music")


class MusicError(RuntimeError):
    pass


class MusicUnavailable(MusicError):
    pass


class MusicPlaybackError(MusicError):
    def __init__(self, message: str, state: PlaybackState | None = None) -> None:
        super().__init__(message)
        self.state = state


class MusicManager:
    def __init__(
        self,
        config: MusicConfig,
        mopidy: MopidyClient,
        ytmusic: YTMusicClient,
        resolver: StreamResolver,
        signer: StreamSigner,
        *,
        registry: TrackRegistry | None = None,
    ) -> None:
        self.config = config
        self.enabled = bool(config.enabled)
        self.mopidy = mopidy
        self.ytmusic = ytmusic
        self.resolver = resolver
        self.signer = signer
        self.registry = registry or TrackRegistry()
        self.queue = QueueService(
            mopidy,
            ytmusic,
            signer,
            self.registry,
            max_items=config.max_queue_items,
        )

    # -- diagnóstico ---------------------------------------------------------

    async def status(self) -> dict[str, Any]:
        mopidy_info: dict[str, Any] = {
            "url": self.config.mopidy.rpc_url,
            "reachable": False,
            "version": "",
        }
        try:
            mopidy_info["version"] = await self.mopidy.version()
            mopidy_info["reachable"] = True
        except MopidyError as exc:
            mopidy_info["error"] = str(exc)
        return {
            "enabled": self.enabled,
            "mopidy": mopidy_info,
            "ytmusic": self.ytmusic.auth_status(),
            "stream": stream_status(self.signer, self.resolver),
            "queue_limit": self.config.max_queue_items,
        }

    async def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            await self.mopidy.version()
            return True
        except MopidyError:
            return False

    # -- estado --------------------------------------------------------------

    async def _current_track(self) -> Track | None:
        raw = await self.mopidy.current_track()
        if not raw:
            return None
        uri = str(raw.get("uri") or "")
        video_id = self.signer.video_id_from_uri(uri) or ""
        if video_id:
            cached = await self.registry.get(video_id)
            if cached is not None:
                return cached
        length = raw.get("length")
        try:
            duration_ms = int(length) if length is not None else None
        except (TypeError, ValueError):
            duration_ms = None
        return Track(
            id=video_id or uri,
            video_id=video_id,
            title=str(raw.get("name") or "").strip(),
            artist=str(raw.get("artist") or "").strip(),
            album=str(raw.get("album") or "").strip(),
            duration_ms=duration_ms,
        )

    async def _state(self) -> PlaybackState:
        try:
            status = await self.mopidy.playback_state()
            current = await self._current_track()
            position = await self.mopidy.time_position()
            volume = await self.mopidy.volume()
            queue_length = await self.mopidy.tracklist_length()
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        except MopidyError as exc:
            raise MusicError(str(exc)) from exc
        duration = current.duration_ms if current else None
        volume_percent = int(volume) if volume is not None else None
        return PlaybackState(
            status=status,
            volume=round(volume / 100, 2) if volume is not None else None,
            volume_percent=volume_percent,
            track=current,
            position_ms=position,
            duration_ms=duration,
            queue_length=queue_length,
            verified=current is not None,
        )

    async def get_state(self) -> dict[str, Any]:
        state = await self._state()
        data = state.as_dict()
        data["ok"] = True
        return data

    async def now_playing(self) -> dict[str, Any]:
        state = await self._state()
        data = state.as_dict()
        data["ok"] = True
        data["now_playing"] = data.get("track")
        return data

    # -- pesquisa ------------------------------------------------------------

    async def search(
        self, query: str, filter: str = "songs", limit: int | None = None
    ) -> dict[str, Any]:
        if not self.enabled:
            raise MusicUnavailable("A integração musical está desativada.")
        if not self.ytmusic.enabled:
            raise MusicUnavailable("A integração com o YouTube Music está desativada.")
        try:
            items = await self.ytmusic.search(query, filter=filter, limit=limit)
        except YTMusicError as exc:
            raise MusicUnavailable(str(exc)) from exc
        return {
            "ok": True,
            "query": (query or "").strip(),
            "filter": filter,
            "count": len(items),
            "results": [item.as_dict() for item in items],
        }

    # -- reprodução ----------------------------------------------------------

    async def _wait_playing(self, target_video_id: str) -> PlaybackState:
        deadline = time.monotonic() + self.config.mopidy.confirm_timeout_s
        last: PlaybackState | None = None
        while True:
            last = await self._state()
            current_id = (last.track.video_id if last.track else "") or ""
            if last.status == "playing" and current_id == target_video_id:
                last.verified = True
                return last
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.35)
        detail = "O Mopidy não confirmou a reprodução da faixa."
        if last is not None:
            detail += f" Estado atual: {last.status}."
        raise MusicPlaybackError(detail, last)

    async def _wait_status(self, expected: set[str], *, timeout: float | None = None) -> PlaybackState:
        deadline = time.monotonic() + (
            timeout if timeout is not None else self.config.mopidy.confirm_timeout_s
        )
        last: PlaybackState | None = None
        while True:
            last = await self._state()
            if last.status in expected:
                last.verified = True
                return last
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.3)
        detail = f"O Mopidy não confirmou o estado {', '.join(sorted(expected))}."
        if last is not None:
            detail += f" Estado atual: {last.status}."
        raise MusicPlaybackError(detail, last)

    async def _start_track(self, track: Track) -> PlaybackState:
        video_id = track.video_id or track.id
        if not valid_video_id(video_id):
            raise MusicError("Identificador de faixa inválido.")
        if not self.resolver.available():
            raise MusicUnavailable(
                "O resolvedor de áudio (yt-dlp) não está disponível. "
                "Instale as dependências do backend."
            )
        uri = self.signer.stream_uri(video_id)
        try:
            await self.mopidy.tracklist_clear()
            added = await self.mopidy.tracklist_add([uri])
            await self.registry.remember(track)
            tlid = None
            if added and isinstance(added[0], dict):
                tlid = added[0].get("tlid")
            try:
                await self.mopidy.play(int(tlid) if tlid is not None else None)
            except MopidyTimeout:
                # O primeiro play pode aguardar o proxy/yt-dlp. A confirmação
                # real continua sendo feita por _wait_playing abaixo.
                log.warning("Mopidy demorou no play; conferindo o estado real.")
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        except MopidyError as exc:
            raise MusicError(str(exc)) from exc
        return await self._wait_playing(video_id)

    async def play(self, track_id: str) -> dict[str, Any]:
        if not self.enabled:
            raise MusicUnavailable("A integração musical está desativada.")
        try:
            track = await self.queue.track_for(track_id)
        except (YTMusicError, QueueError) as exc:
            raise MusicError(str(exc)) from exc
        state = await self._start_track(track)
        data = state.as_dict()
        data.update(
            {
                "ok": True,
                "action": "play",
                "message": f"Reproduzindo {track.title}.",
            }
        )
        return data

    async def pause(self) -> dict[str, Any]:
        try:
            await self.mopidy.pause()
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        except MopidyError as exc:
            raise MusicError(str(exc)) from exc
        state = await self._wait_status({"paused"})
        data = state.as_dict()
        data.update({"ok": True, "action": "pause", "message": "Música pausada."})
        return data

    async def resume(self) -> dict[str, Any]:
        try:
            await self.mopidy.play()
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        except MopidyError as exc:
            raise MusicError(str(exc)) from exc
        state = await self._wait_status({"playing"})
        data = state.as_dict()
        data.update({"ok": True, "action": "resume", "message": "Música retomada."})
        return data

    async def stop(self) -> dict[str, Any]:
        try:
            await self.mopidy.stop()
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        except MopidyError as exc:
            raise MusicError(str(exc)) from exc
        state = await self._wait_status({"stopped"})
        data = state.as_dict()
        data.update({"ok": True, "action": "stop", "message": "Música parada."})
        return data

    async def _skip(self, action: str) -> dict[str, Any]:
        before = await self._state()
        before_id = (before.track.video_id if before.track else "") or ""
        try:
            if action == "next":
                await self.mopidy.next()
            else:
                await self.mopidy.previous()
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        except MopidyError as exc:
            raise MusicError(str(exc)) from exc

        deadline = time.monotonic() + min(2.5, self.config.mopidy.confirm_timeout_s)
        last: PlaybackState | None = None
        while True:
            last = await self._state()
            current_id = (last.track.video_id if last.track else "") or ""
            if current_id and current_id != before_id:
                last.verified = True
                data = last.as_dict()
                data.update(
                    {
                        "ok": True,
                        "action": action,
                        "message": "Próxima música."
                        if action == "next"
                        else "Música anterior.",
                    }
                )
                return data
            if action == "next" and last.status == "stopped":
                # Fim da fila: o Mopidy parou de verdade, então não há troca
                # de faixa para confirmar, mas o resultado é verificável.
                last.verified = True
                data = last.as_dict()
                data.update({"ok": True, "action": action, "message": "Fim da fila."})
                return data
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.25)

        detail = (
            "O Mopidy não confirmou a próxima música."
            if action == "next"
            else "Não há uma música anterior para tocar."
        )
        if last is not None:
            detail += f" Estado atual: {last.status}."
        raise MusicPlaybackError(detail, last)

    async def next(self) -> dict[str, Any]:
        return await self._skip("next")

    async def previous(self) -> dict[str, Any]:
        return await self._skip("previous")

    # -- volume --------------------------------------------------------------

    async def set_volume(self, volume: int) -> dict[str, Any]:
        try:
            target = int(volume)
        except (TypeError, ValueError) as exc:
            raise MusicError("O volume deve ser um número inteiro entre 0 e 100.") from exc
        if target < 0 or target > 100:
            raise MusicError("O volume deve ficar entre 0 e 100.")
        try:
            await self.mopidy.set_volume(target)
            actual = await self.mopidy.volume()
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        except MopidyError as exc:
            raise MusicError(str(exc)) from exc
        if actual is None:
            raise MusicError("O Mopidy não informou o volume após a alteração.")
        if abs(int(actual) - target) > 1:
            raise MusicError(
                f"O Mopidy não confirmou o volume: pedido {target}, atual {actual}."
            )
        state = await self._state()
        data = state.as_dict()
        data.update(
            {
                "ok": True,
                "action": "volume",
                "requested_volume": target,
                "message": f"Volume em {int(actual)}%.",
            }
        )
        return data

    async def get_volume(self) -> dict[str, Any]:
        try:
            volume = await self.mopidy.volume()
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        except MopidyError as exc:
            raise MusicError(str(exc)) from exc
        if volume is None:
            raise MusicUnavailable("O Mopidy não expõe controle de volume.")
        return {
            "ok": True,
            "volume_percent": int(volume),
            "volume": round(volume / 100, 2),
        }

    # -- fila ----------------------------------------------------------------

    async def queue_add(self, track_id: str) -> dict[str, Any]:
        try:
            item = await self.queue.add(track_id)
        except (QueueError, YTMusicError, StreamResolutionError) as exc:
            raise MusicError(str(exc)) from exc
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        items = await self.queue.list()
        return {
            "ok": True,
            "added": item.as_dict(),
            "count": len(items),
            "queue": [entry.as_dict() for entry in items],
            "message": f"{item.title} adicionada à fila.",
        }

    async def queue_remove(self, index: int) -> dict[str, Any]:
        try:
            removed = await self.queue.remove(int(index))
        except QueueError as exc:
            raise MusicError(str(exc)) from exc
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        items = await self.queue.list()
        return {
            "ok": True,
            "removed": removed.as_dict(),
            "count": len(items),
            "queue": [entry.as_dict() for entry in items],
            "message": f"{removed.title} removida da fila.",
        }

    async def queue_clear(self) -> dict[str, Any]:
        try:
            count = await self.queue.clear()
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        return {"ok": True, "removed_count": count, "message": "Fila limpa."}

    async def queue_list(self) -> dict[str, Any]:
        try:
            items = await self.queue.list()
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        return {
            "ok": True,
            "count": len(items),
            "queue": [item.as_dict() for item in items],
        }

    # -- playlists e curtidas ------------------------------------------------

    async def playlist_list(self, limit: int | None = None) -> dict[str, Any]:
        try:
            items = await self.ytmusic.library_playlists(limit=limit)
        except YTMusicAuthRequired as exc:
            raise MusicUnavailable(str(exc)) from exc
        except YTMusicError as exc:
            raise MusicUnavailable(str(exc)) from exc
        return {
            "ok": True,
            "count": len(items),
            "playlists": [item.as_dict() for item in items],
        }

    async def _play_tracks(self, tracks: list[Track]) -> PlaybackState:
        if not tracks:
            raise MusicError("Nenhuma faixa foi encontrada para tocar.")
        try:
            await self.mopidy.tracklist_clear()
            items = await self.queue.add_tracks(tracks, limit=self.config.max_playlist_tracks)
            first = items[0]
            try:
                await self.mopidy.play(first.tlid)
            except MopidyTimeout:
                log.warning("Mopidy demorou no play da playlist; conferindo o estado real.")
        except QueueError as exc:
            raise MusicError(str(exc)) from exc
        except MopidyUnavailable as exc:
            raise MusicUnavailable(str(exc)) from exc
        except MopidyError as exc:
            raise MusicError(str(exc)) from exc
        return await self._wait_playing(tracks[0].video_id or tracks[0].id)

    async def playlist_play(self, playlist_id: str) -> dict[str, Any]:
        try:
            playlist = await self.ytmusic.get_playlist(
                playlist_id, limit=self.config.max_playlist_tracks
            )
        except YTMusicError as exc:
            raise MusicUnavailable(str(exc)) from exc
        tracks: list[Track] = []
        for raw in playlist.get("tracks") or []:
            if not isinstance(raw, dict):
                continue
            video_id = str(raw.get("video_id") or raw.get("id") or "")
            title = str(raw.get("title") or "").strip()
            if not video_id or not title:
                continue
            tracks.append(
                Track(
                    id=video_id,
                    video_id=video_id,
                    title=title,
                    artist=str(raw.get("artist") or ""),
                    album=str(raw.get("album") or ""),
                    duration_ms=raw.get("duration_ms"),
                    thumbnail=str(raw.get("thumbnail") or ""),
                )
            )
        state = await self._play_tracks(tracks)
        data = state.as_dict()
        data.update(
            {
                "ok": True,
                "action": "playlist_play",
                "playlist": {
                    "id": playlist.get("id"),
                    "title": playlist.get("title"),
                },
                "queued": len(tracks),
                "message": f"Tocando a playlist {playlist.get('title') or playlist_id}.",
            }
        )
        return data

    async def liked_songs(
        self, limit: int | None = 25, play: bool = False
    ) -> dict[str, Any]:
        try:
            tracks = await self.ytmusic.liked_songs(limit=limit)
        except YTMusicAuthRequired as exc:
            raise MusicUnavailable(str(exc)) from exc
        except YTMusicError as exc:
            raise MusicUnavailable(str(exc)) from exc
        data: dict[str, Any] = {
            "ok": True,
            "count": len(tracks),
            "tracks": [track.as_dict() for track in tracks],
        }
        if play and tracks:
            state = await self._play_tracks(tracks)
            playback = state.as_dict()
            playback.update(
                {
                    "ok": True,
                    "action": "liked_songs",
                    "queued": len(tracks),
                    "message": "Tocando suas músicas curtidas.",
                }
            )
            return playback
        if play and not tracks:
            raise MusicError("Você não tem músicas curtidas disponíveis.")
        return data
