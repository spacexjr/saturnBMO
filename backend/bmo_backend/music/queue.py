"""Fila de reprodução do Mopidy com metadados do YouTube Music.

O Mopidy só conhece URIs. Este módulo mantém um cache em memória dos metadados
das faixas para que a API, o rosto do BMO e o LLM recebam título, artista e
álbum reais, sem inventar informações.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any, Iterable

from .mopidy_client import MopidyClient
from .models import QueueItem, Track
from .stream_proxy import StreamSigner
from .ytmusic_client import YTMusicClient


class QueueError(RuntimeError):
    pass


class TrackRegistry:
    def __init__(self, max_items: int = 1000) -> None:
        self.max_items = max(10, int(max_items))
        self._items: OrderedDict[str, Track] = OrderedDict()
        self._lock = asyncio.Lock()

    async def remember(self, track: Track) -> None:
        key = track.video_id or track.id
        if not key:
            return
        async with self._lock:
            self._items[key] = track
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    async def get(self, track_id: str) -> Track | None:
        async with self._lock:
            return self._items.get(track_id)

    async def all(self) -> list[Track]:
        async with self._lock:
            return list(self._items.values())


class QueueService:
    def __init__(
        self,
        mopidy: MopidyClient,
        ytmusic: YTMusicClient,
        signer: StreamSigner,
        registry: TrackRegistry,
        *,
        max_items: int = 200,
    ) -> None:
        self.mopidy = mopidy
        self.ytmusic = ytmusic
        self.signer = signer
        self.registry = registry
        self.max_items = max(1, int(max_items))

    async def track_for(self, track_id: str) -> Track:
        clean = (track_id or "").strip()
        if not clean:
            raise QueueError("Informe o identificador da faixa.")
        cached = await self.registry.get(clean)
        if cached is not None:
            return cached
        track = await self.ytmusic.get_track(clean)
        await self.registry.remember(track)
        return track

    async def add(self, track_id: str, *, at_position: int | None = None) -> QueueItem:
        length = await self.mopidy.tracklist_length()
        if length >= self.max_items:
            raise QueueError(
                f"A fila já tem {length} itens; o limite configurado é {self.max_items}."
            )
        track = await self.track_for(track_id)
        uri = self.signer.stream_uri(track.video_id or track.id)
        added = await self.mopidy.tracklist_add([uri], at_position=at_position)
        await self.registry.remember(track)
        tlid = None
        if added and isinstance(added[0], dict):
            tlid = added[0].get("tlid")
        index = at_position if at_position is not None else length
        return QueueItem(
            index=int(index),
            tlid=int(tlid) if tlid is not None else None,
            track_id=track.id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_ms=track.duration_ms,
            uri=uri,
        )

    async def add_tracks(self, tracks: Iterable[Track], *, limit: int) -> list[QueueItem]:
        selected = list(tracks)[: max(1, int(limit))]
        if not selected:
            raise QueueError("Nenhuma faixa foi encontrada para adicionar à fila.")
        length = await self.mopidy.tracklist_length()
        room = self.max_items - length
        if room <= 0:
            raise QueueError(
                f"A fila já tem {length} itens; o limite configurado é {self.max_items}."
            )
        selected = selected[:room]
        uris: list[str] = []
        for track in selected:
            uri = self.signer.stream_uri(track.video_id or track.id)
            uris.append(uri)
            await self.registry.remember(track)
        added = await self.mopidy.tracklist_add(uris, at_position=length)
        items: list[QueueItem] = []
        for offset, track in enumerate(selected):
            tlid = None
            if offset < len(added) and isinstance(added[offset], dict):
                tlid = added[offset].get("tlid")
            items.append(
                QueueItem(
                    index=length + offset,
                    tlid=int(tlid) if tlid is not None else None,
                    track_id=track.id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    duration_ms=track.duration_ms,
                    uri=uris[offset],
                )
            )
        return items

    async def list(self) -> list[QueueItem]:
        tracks = await self.mopidy.tracklist_tracks()
        items: list[QueueItem] = []
        for index, raw in enumerate(tracks):
            uri = str(raw.get("uri") or "")
            track_id = self.signer.video_id_from_uri(uri) or ""
            track: Track | None = await self.registry.get(track_id) if track_id else None
            duration = raw.get("length")
            try:
                duration_ms = int(duration) if duration is not None else None
            except (TypeError, ValueError):
                duration_ms = None
            items.append(
                QueueItem(
                    index=index,
                    tlid=int(raw["tlid"]) if raw.get("tlid") is not None else None,
                    track_id=track_id or uri,
                    title=(track.title if track else "") or str(raw.get("name") or ""),
                    artist=(track.artist if track else ""),
                    album=(track.album if track else ""),
                    duration_ms=(track.duration_ms if track else None) or duration_ms,
                    uri=uri,
                )
            )
        return items

    async def remove(self, index: int) -> QueueItem:
        items = await self.list()
        if index < 0 or index >= len(items):
            raise QueueError(
                f"Índice {index} fora da fila (a fila tem {len(items)} itens)."
            )
        item = items[index]
        if item.tlid is None:
            raise QueueError("O Mopidy não informou o identificador interno deste item.")
        await self.mopidy.tracklist_remove([item.tlid])
        return item

    async def clear(self) -> int:
        count = await self.mopidy.tracklist_length()
        await self.mopidy.tracklist_clear()
        return count
