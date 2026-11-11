"""Testes da integração musical (Mopidy + YouTube Music + ferramentas/API)."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from bmo_backend.apps import AppManager
from bmo_backend.config import DEFAULT_CONFIG
from bmo_backend.files import Workspace
from bmo_backend.media import MediaService
from bmo_backend.music.config import MusicConfig, StreamConfig
from bmo_backend.music.manager import MusicManager, MusicPlaybackError, MusicUnavailable
from bmo_backend.music.models import MediaItem, Track
from bmo_backend.music.mopidy_client import MopidyClient, MopidyError, MopidyUnavailable
from bmo_backend.music.stream_proxy import StreamSigner
from bmo_backend.music.stream_resolver import ResolvedStream, StreamResolver
from bmo_backend.music.tools import build_music_tools
from bmo_backend.music.ytmusic_client import _normalize_item
from bmo_backend.server import Services, create_app
from bmo_backend.sysinfo import SystemInfo
from bmo_backend.toolkit import ToolRegistry
from bmo_backend.web import WebService

TOKEN = "token-musica-teste"
VIDEO_A = "vidAAAAAAA1"
VIDEO_B = "vidBBBBBBB2"
VIDEO_C = "vidCCCCCCC3"


class FakeMopidy:
    def __init__(self) -> None:
        self.tracks: list[dict[str, Any]] = []
        self.current: int | None = None
        self.state = "stopped"
        self.volume_value = 40
        self.next_tlid = 1
        self.fail_play = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def version(self) -> str:
        return "4.0.0-test"

    async def playback_state(self) -> str:
        return self.state

    async def current_track(self) -> dict[str, Any] | None:
        if self.current is None or self.current >= len(self.tracks):
            return None
        return dict(self.tracks[self.current])

    async def time_position(self) -> int:
        return 12000

    async def volume(self) -> int:
        return self.volume_value

    async def set_volume(self, volume: int) -> None:
        self.volume_value = int(volume)

    async def play(self, tlid: int | None = None) -> None:
        if not self.tracks:
            self.state = "stopped"
            return
        if tlid is not None:
            for index, item in enumerate(self.tracks):
                if int(item["tlid"]) == int(tlid):
                    self.current = index
                    break
        elif self.current is None:
            self.current = 0
        self.state = "stopped" if self.fail_play else "playing"

    async def pause(self) -> None:
        self.state = "paused"

    async def stop(self) -> None:
        self.state = "stopped"

    async def next(self) -> None:
        if self.current is not None and self.current + 1 < len(self.tracks):
            self.current += 1
            self.state = "playing"
        else:
            self.state = "stopped"

    async def previous(self) -> None:
        if self.current is not None and self.current > 0:
            self.current -= 1
            self.state = "playing"
        else:
            self.state = "stopped"

    async def seek(self, position_ms: int) -> None:
        self.calls.append(("seek", {"position_ms": int(position_ms)}))

    async def tracklist_tracks(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.tracks]

    async def tracklist_length(self) -> int:
        return len(self.tracks)

    async def tracklist_add(
        self, uris: list[str], *, at_position: int | None = None
    ) -> list[dict[str, Any]]:
        added = []
        position = len(self.tracks) if at_position is None else max(0, int(at_position))
        for offset, uri in enumerate(uris):
            item = {"tlid": self.next_tlid, "uri": uri, "name": uri}
            self.next_tlid += 1
            self.tracks.insert(position + offset, item)
            added.append(dict(item))
        return added

    async def tracklist_remove(self, tlids: list[int]) -> None:
        wanted = {int(tlid) for tlid in tlids}
        self.tracks = [item for item in self.tracks if int(item["tlid"]) not in wanted]
        if self.current is not None and self.current >= len(self.tracks):
            self.current = len(self.tracks) - 1 if self.tracks else None

    async def tracklist_clear(self) -> None:
        self.tracks = []
        self.current = None
        self.state = "stopped"

    async def tracklist_index(self) -> int | None:
        return self.current


class FakeYTMusic:
    enabled = True

    def auth_status(self) -> dict[str, Any]:
        return {"enabled": True, "authenticated": True, "mode": "browser"}

    async def search(
        self, query: str, filter: str = "songs", limit: int | None = None
    ) -> list[MediaItem]:
        items = [
            MediaItem(
                id=VIDEO_A,
                type="song",
                title="One More Time",
                artist="Daft Punk",
                album="Discovery",
                duration_ms=320000,
                video_id=VIDEO_A,
            ),
            MediaItem(
                id=VIDEO_B,
                type="song",
                title="Around the World",
                artist="Daft Punk",
                album="Homework",
                duration_ms=420000,
                video_id=VIDEO_B,
            ),
        ]
        if filter == "artists":
            return [MediaItem(id="artist1", type="artist", title="Daft Punk")]
        return items[: int(limit or 10)]

    async def get_track(self, video_id: str) -> Track:
        if video_id == VIDEO_A:
            return Track(
                id=VIDEO_A,
                video_id=VIDEO_A,
                title="One More Time",
                artist="Daft Punk",
                album="Discovery",
                duration_ms=320000,
            )
        if video_id == VIDEO_B:
            return Track(
                id=VIDEO_B,
                video_id=VIDEO_B,
                title="Around the World",
                artist="Daft Punk",
                duration_ms=420000,
            )
        if video_id == VIDEO_C:
            return Track(id=VIDEO_C, video_id=VIDEO_C, title="Get Lucky", artist="Daft Punk")
        raise RuntimeError("faixa inexistente")

    async def get_playlist(self, playlist_id: str, limit: int | None = None) -> dict[str, Any]:
        return {
            "id": playlist_id,
            "title": "Minha playlist",
            "tracks": [
                Track(id=VIDEO_A, video_id=VIDEO_A, title="One More Time", artist="Daft Punk").as_dict(),
                Track(id=VIDEO_B, video_id=VIDEO_B, title="Around the World", artist="Daft Punk").as_dict(),
            ],
        }

    async def library_playlists(self, limit: int | None = None) -> list[MediaItem]:
        return [MediaItem(id="PL1", type="playlist", title="Favoritas")]

    async def liked_songs(self, limit: int | None = None) -> list[Track]:
        return [Track(id=VIDEO_C, video_id=VIDEO_C, title="Get Lucky", artist="Daft Punk")]


class FakeResolver:
    config = StreamConfig(enabled=True)

    def available(self) -> bool:
        return True

    async def resolve(self, video_id: str) -> ResolvedStream:
        return ResolvedStream(url="http://audio.invalid/test", headers={}, expires_at=9e12)

    def status(self) -> dict[str, object]:
        return {"enabled": True, "resolver": "fake", "installed": True}


def make_manager(tmp_path, *, fail_play: bool = False) -> tuple[MusicManager, FakeMopidy, FakeYTMusic]:
    mopidy = FakeMopidy()
    mopidy.fail_play = fail_play
    config = MusicConfig.from_dict(
        {
            "enabled": True,
            "max_queue_items": 10,
            "mopidy": {"confirm_timeout_s": 0.15},
        }
    )
    signer = StreamSigner(tmp_path / "stream.secret", base_url="http://127.0.0.1:8765")
    manager = MusicManager(config, mopidy, FakeYTMusic(), FakeResolver(), signer)
    return manager, mopidy, manager.ytmusic


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Mopidy JSON-RPC
# ---------------------------------------------------------------------------


def test_mopidy_json_rpc_request_and_error():
    async def scenario() -> None:
        seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            seen.append(payload)
            if payload["method"] == "core.get_version":
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": payload["id"], "result": "4.0.0"}
                )
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "error": {"code": -32601, "message": "Method not found"},
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = MopidyClient("http://mopidy.test/mopidy/rpc", client=http)
        assert await client.version() == "4.0.0"
        with pytest.raises(MopidyError, match="Method not found"):
            await client.call("core.playback.bogus")
        assert seen[0]["jsonrpc"] == "2.0"
        assert seen[0]["params"] == {}
        await client.close()

    run(scenario())


def test_mopidy4_mixer_volume_falls_back_and_works():
    """Mopidy 4 expõe volume em core.mixer; Mopidy 3 usava core.playback."""

    async def scenario() -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload["method"]
            calls.append(method)
            if method == "core.mixer.get_volume":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "error": {"code": -32601, "message": "Method not found"},
                    },
                )
            if method == "core.playback.get_volume":
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": payload["id"], "result": 45}
                )
            if method == "core.playback.set_volume":
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": payload["id"], "result": None}
                )
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "error": {"code": -32601, "message": "Method not found"},
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = MopidyClient("http://mopidy.test/mopidy/rpc", client=http)
        assert await client.volume() == 45
        await client.set_volume(45)
        assert calls == [
            "core.mixer.get_volume",
            "core.playback.get_volume",
            "core.mixer.set_volume",
            "core.playback.set_volume",
        ]
        await client.close()

    run(scenario())


def test_mopidy4_tracklist_flattens_tl_tracks():
    """get_tl_tracks devolve {'tlid', 'track'}; a fila precisa do uri + tlid."""

    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": [
                        {
                            "tlid": 7,
                            "track": {
                                "uri": "http://127.0.0.1:8765/api/music/stream/vidAAAAAAA1",
                                "name": "One More Time",
                            },
                        }
                    ],
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = MopidyClient("http://mopidy.test/mopidy/rpc", client=http)
        tracks = await client.tracklist_tracks()
        assert tracks[0]["tlid"] == 7
        assert tracks[0]["uri"].endswith("vidAAAAAAA1")
        await client.close()

    run(scenario())


def test_missing_ytmusic_auth_falls_back_to_anonymous(monkeypatch, tmp_path):
    import sys
    import types

    created: list[str | None] = []

    class FakeYTMusic:
        def __init__(self, auth: str | None = None, **_: Any) -> None:
            created.append(auth)

    monkeypatch.setitem(sys.modules, "ytmusicapi", types.SimpleNamespace(YTMusic=FakeYTMusic))
    from bmo_backend.music.config import YtMusicConfig
    from bmo_backend.music.ytmusic_client import YTMusicClient

    client = YTMusicClient(YtMusicConfig(auth_file=str(tmp_path / "nao-existe.json")))
    instance = client._build()
    assert isinstance(instance, FakeYTMusic)
    assert created == [None]


def test_mopidy_connection_failure_is_reported():
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusado", request=request)

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = MopidyClient("http://mopidy.test/mopidy/rpc", client=http)
        with pytest.raises(MopidyError, match="não está acessível"):
            await client.version()
        await client.close()

    run(scenario())


# ---------------------------------------------------------------------------
# Manager: pesquisa, transporte, volume e fila
# ---------------------------------------------------------------------------


def test_search_returns_structured_results(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    result = run(manager.search("Daft Punk", filter="songs"))
    assert result["ok"] is True
    assert result["count"] == 2
    assert result["results"][0]["id"] == VIDEO_A
    assert result["results"][0]["artist"] == "Daft Punk"


def test_next_reports_end_of_queue_only_when_mopidy_stops(tmp_path):
    manager, mopidy, _ = make_manager(tmp_path)
    run(manager.play(VIDEO_A))
    result = run(manager.next())
    assert result["ok"] is True
    assert result["status"] == "stopped"
    assert result["message"] == "Fim da fila."
    assert mopidy.state == "stopped"


def test_previous_without_a_previous_track_is_not_faked(tmp_path):
    manager, mopidy, _ = make_manager(tmp_path)
    manager.config.mopidy.confirm_timeout_s = 0.3
    run(manager.play(VIDEO_A))
    with pytest.raises(MusicPlaybackError, match="música anterior"):
        run(manager.previous())
    assert mopidy.state == "stopped"


def test_play_pause_resume_stop_and_volume_are_verified(tmp_path):
    manager, mopidy, _ = make_manager(tmp_path)

    played = run(manager.play(VIDEO_A))
    assert played["ok"] is True
    assert played["verified"] is True
    assert played["status"] == "playing"
    assert played["title"] == "One More Time"
    assert mopidy.tracks[0]["uri"].startswith("http://127.0.0.1:8765/api/music/stream/")

    paused = run(manager.pause())
    assert paused["status"] == "paused" and paused["verified"] is True

    resumed = run(manager.resume())
    assert resumed["status"] == "playing"

    volume = run(manager.set_volume(55))
    assert volume["volume_percent"] == 55
    assert volume["volume"] == 0.55
    assert mopidy.volume_value == 55

    stopped = run(manager.stop())
    assert stopped["status"] == "stopped"

    with pytest.raises(Exception):
        run(manager.set_volume(101))


def test_play_does_not_claim_success_when_mopidy_does_not_play(tmp_path):
    manager, _, _ = make_manager(tmp_path, fail_play=True)
    with pytest.raises(MusicPlaybackError) as exc:
        run(manager.play(VIDEO_A))
    assert "não confirmou" in str(exc.value)
    assert exc.value.state is not None
    assert exc.value.state.status == "stopped"


def test_queue_add_remove_list_and_clear(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    added = run(manager.queue_add(VIDEO_A))
    assert added["count"] == 1
    assert added["queue"][0]["track_id"] == VIDEO_A

    run(manager.queue_add(VIDEO_B))
    listing = run(manager.queue_list())
    assert listing["count"] == 2
    assert [item["title"] for item in listing["queue"]] == [
        "One More Time",
        "Around the World",
    ]

    removed = run(manager.queue_remove(0))
    assert removed["removed"]["track_id"] == VIDEO_A
    assert removed["count"] == 1

    cleared = run(manager.queue_clear())
    assert cleared["removed_count"] == 1
    assert run(manager.queue_list())["count"] == 0


def test_queue_limit_is_enforced(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    manager.config.max_queue_items = 1
    manager.queue.max_items = 1
    run(manager.queue_add(VIDEO_A))
    with pytest.raises(Exception, match="limite"):
        run(manager.queue_add(VIDEO_B))


def test_playlist_play_and_liked_songs(tmp_path):
    manager, mopidy, _ = make_manager(tmp_path)
    played = run(manager.playlist_play("PL1"))
    assert played["verified"] is True
    assert played["queued"] == 2
    assert manager.signer.video_id_from_uri(mopidy.tracks[0]["uri"]) == VIDEO_A
    assert run(manager.get_state())["track"]["video_id"] == VIDEO_A

    listed = run(manager.playlist_list())
    assert listed["playlists"][0]["title"] == "Favoritas"

    liked = run(manager.liked_songs(limit=5))
    assert liked["tracks"][0]["title"] == "Get Lucky"

    liked_play = run(manager.liked_songs(limit=5, play=True))
    assert liked_play["verified"] is True
    assert liked_play["title"] == "Get Lucky"


def test_manager_reports_mopidy_unavailable(tmp_path):
    manager, mopidy, _ = make_manager(tmp_path)

    async def unavailable() -> str:
        raise MopidyUnavailable("Mopidy fora do ar")

    mopidy.version = unavailable
    mopidy.playback_state = unavailable
    with pytest.raises(MusicUnavailable):
        run(manager.get_state())


# ---------------------------------------------------------------------------
# Ferramentas do LLM
# ---------------------------------------------------------------------------


def test_music_tools_are_registered_and_execute(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    registry = ToolRegistry(
        workspace=Workspace(None),
        apps=AppManager({"enabled": False}),
        media=MediaService({"enabled": False}),
        web=WebService({"enabled": False}),
        system=SystemInfo({"enabled": False}),
        music=manager,
        config={},
    )
    names = set(registry.names())
    required = {
        "music_search",
        "music_play",
        "music_pause",
        "music_resume",
        "music_stop",
        "music_next",
        "music_previous",
        "music_set_volume",
        "music_get_volume",
        "music_get_state",
        "music_get_now_playing",
        "music_queue_add",
        "music_queue_remove",
        "music_queue_clear",
        "music_queue_list",
        "music_playlist_list",
        "music_playlist_play",
        "music_liked_songs",
    }
    assert required <= names
    schemas = {schema["function"]["name"]: schema for schema in registry.schemas()}
    assert schemas["music_search"]["function"]["parameters"]["required"] == ["query"]
    assert schemas["music_set_volume"]["function"]["parameters"]["properties"]["volume"][
        "maximum"
    ] == 100

    async def scenario() -> None:
        search = await registry.execute("music_search", {"query": "Daft Punk"})
        assert search.ok and search.data["count"] == 2
        play = await registry.execute("music_play", {"track_id": VIDEO_A})
        assert play.ok and play.data["verified"] is True
        bad = await registry.execute("music_play", {"track_id": "inexistente"})
        assert bad.ok is False and "error" in bad.data

    run(scenario())


def test_music_tools_accept_common_model_argument_aliases(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    registry = ToolRegistry(
        workspace=Workspace(None),
        apps=AppManager({"enabled": False}),
        media=MediaService({"enabled": False}),
        web=WebService({"enabled": False}),
        system=SystemInfo({"enabled": False}),
        music=manager,
        config={},
    )

    async def scenario() -> None:
        search = await registry.execute(
            "music_search", {"q": "Daft Punk", "type": "songs", "max_results": 1}
        )
        assert search.ok and search.data["filter"] == "songs"
        assert search.data["count"] == 1
        play = await registry.execute("music_play", {"query": "Daft Punk"})
        assert play.ok and play.data["verified"] is True
        assert play.data["matched_query"] == "One More Time"
        play_id = await registry.execute("music_play", {"id": VIDEO_B})
        assert play_id.ok and play_id.data["verified"] is True
        volume = await registry.execute("music_set_volume", {"level": 33})
        assert volume.ok and volume.data["volume_percent"] == 33
        missing = await registry.execute("music_play", {})
        assert missing.ok is False and "track_id" in missing.data["error"]

    run(scenario())


def test_music_tool_specs_have_clear_descriptions(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    specs = build_music_tools(manager)
    assert all(spec["description"] for spec in specs)
    handlers = {spec["name"]: spec["handler"] for spec in specs}
    assert callable(handlers["music_get_state"])


def test_mopidy_aliases_are_registered_and_work(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    registry = ToolRegistry(
        workspace=Workspace(None),
        apps=AppManager({"enabled": False}),
        media=MediaService({"enabled": False}),
        web=WebService({"enabled": False}),
        system=SystemInfo({"enabled": False}),
        music=manager,
        config={},
    )
    names = set(registry.names())
    expected = {
        "mopidy_start",
        "mopidy_status",
        "mopidy_now_playing",
        "mopidy_play",
        "mopidy_pause",
        "mopidy_stop",
        "mopidy_next",
        "mopidy_previous",
        "mopidy_seek",
        "mopidy_set_volume",
        "mopidy_get_volume",
        "mopidy_search",
        "mopidy_add_to_queue",
        "mopidy_get_queue",
        "mopidy_clear_queue",
    }
    assert expected <= names

    async def scenario() -> None:
        played = await registry.execute("mopidy_play", {"query": "Daft Punk"})
        assert played.ok and played.data["verified"] is True
        status = await registry.execute("mopidy_status", {})
        assert status.ok and status.data["playback"]["status"] == "playing"
        added = await registry.execute(
            "mopidy_add_to_queue", {"id": VIDEO_B}
        )
        assert added.ok
        seeked = await registry.execute("mopidy_seek", {"position_ms": 5000})
        assert seeked.ok and seeked.data["position_ms"] == 12000

    run(scenario())


# ---------------------------------------------------------------------------
# Assinatura e proxy de áudio
# ---------------------------------------------------------------------------


def test_stream_signer_rejects_tampering_and_extracts_video_id(tmp_path):
    signer = StreamSigner(tmp_path / "secret", base_url="http://127.0.0.1:8765")
    sig = signer.sign(VIDEO_A)
    assert signer.verify(VIDEO_A, sig) is True
    assert signer.verify(VIDEO_A, "0" * 40) is False
    assert signer.verify(VIDEO_B, sig) is False
    uri = signer.stream_uri(VIDEO_A)
    assert f"/api/music/stream/{VIDEO_A}" in uri
    assert signer.video_id_from_uri(uri) == VIDEO_A
    assert signer.video_id_from_uri("http://outro/uri") is None


def test_stream_resolver_caches_results(tmp_path, monkeypatch):
    resolver = StreamResolver(StreamConfig(enabled=True, cache_ttl_s=60, timeout_s=2))
    calls = 0

    def fake_extract(video_id: str) -> ResolvedStream:
        nonlocal calls
        calls += 1
        return ResolvedStream(url="http://audio", headers={}, expires_at=9e12)

    monkeypatch.setattr(resolver, "_extract_sync", fake_extract)

    async def scenario() -> None:
        first = await resolver.resolve(VIDEO_A)
        second = await resolver.resolve(VIDEO_A)
        assert first.url == second.url == "http://audio"
        assert calls == 1

    run(scenario())


# ---------------------------------------------------------------------------
# Normalização do ytmusicapi
# ---------------------------------------------------------------------------


def test_normalize_ytmusic_search_items():
    song = _normalize_item(
        {
            "resultType": "song",
            "videoId": VIDEO_A,
            "title": "One More Time",
            "artists": [{"name": "Daft Punk"}],
            "album": {"name": "Discovery"},
            "duration_seconds": 320,
            "thumbnails": [{"url": "thumb", "width": 60, "height": 60}],
        }
    )
    assert song is not None and song.type == "song" and song.duration_ms == 320000
    artist = _normalize_item(
        {"resultType": "artist", "artist": "Daft Punk", "browseId": "UC1"}
    )
    assert artist is not None and artist.type == "artist"
    playlist = _normalize_item(
        {"resultType": "playlist", "title": "Favoritas", "browseId": "VLPL1", "itemCount": 12}
    )
    assert playlist is not None and playlist.item_count == 12
    assert _normalize_item({"resultType": "desconhecido"}) is None


# ---------------------------------------------------------------------------
# API HTTP
# ---------------------------------------------------------------------------


class FakeBrain:
    async def available(self) -> bool:
        return True

    def status(self) -> dict[str, Any]:
        return {"provider": "fake"}


class FakeStt:
    def available(self) -> bool:
        return True

    def status(self) -> dict[str, Any]:
        return {"engine": "fake", "available": True}


class FakeTts:
    def available(self) -> bool:
        return False

    def status(self) -> dict[str, Any]:
        return {"engine": "fake", "available": False}


class FakeWeather:
    pass


def make_api(tmp_path, manager: MusicManager | None):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["_token"] = TOKEN
    cfg["paths"]["log_file"] = str(tmp_path / "bmo.log")
    cfg["tools"]["enabled"] = False
    cfg["tools"]["access_file"] = str(tmp_path / "access.json")
    cfg["wakeword"]["mode"] = "transcript"
    cfg["wakeword"]["enabled"] = False
    cfg["music"]["enabled"] = manager is not None
    cfg["music"]["stream"]["secret_file"] = str(tmp_path / "stream.secret")
    services = Services(
        cfg,
        stt=FakeStt(),
        tts=FakeTts(),
        weather=FakeWeather(),
        brain_factory=lambda: FakeBrain(),
        music=manager,
    )
    return create_app(cfg, services=services)


def test_music_api_requires_token_and_works(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    app = make_api(tmp_path, manager)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as client:
        assert client.get("/api/music/state").status_code == 401
        state = client.get("/api/music/state", headers=headers)
        assert state.status_code == 200
        assert state.json()["status"] == "stopped"

        search = client.get(
            "/api/music/search", headers=headers, params={"q": "Daft Punk"}
        )
        assert search.status_code == 200
        assert search.json()["results"][0]["id"] == VIDEO_A

        play = client.post(
            "/api/music/play", headers=headers, json={"track_id": VIDEO_A}
        )
        assert play.status_code == 200
        assert play.json()["verified"] is True
        assert play.json()["title"] == "One More Time"

        pause = client.post("/api/music/pause", headers=headers)
        assert pause.status_code == 200
        assert pause.json()["status"] == "paused"

        resume = client.post("/api/music/resume", headers=headers)
        assert resume.json()["status"] == "playing"

        volume = client.post("/api/music/volume", headers=headers, json={"volume": 30})
        assert volume.status_code == 200
        assert volume.json()["volume_percent"] == 30

        invalid = client.post("/api/music/volume", headers=headers, json={"volume": 130})
        assert invalid.status_code == 422

        queue = client.get("/api/music/queue", headers=headers)
        assert queue.status_code == 200
        assert queue.json()["count"] == 1

        queue_add = client.post(
            "/api/music/queue/add", headers=headers, json={"track_id": VIDEO_B}
        )
        assert queue_add.status_code == 200
        assert queue_add.json()["count"] == 2

        queue_remove = client.post(
            "/api/music/queue/remove", headers=headers, json={"index": 1}
        )
        assert queue_remove.status_code == 200
        assert queue_remove.json()["count"] == 1

        queue_clear = client.post("/api/music/queue/clear", headers=headers)
        assert queue_clear.status_code == 200
        assert queue_clear.json()["removed_count"] == 1

        stop = client.post("/api/music/stop", headers=headers)
        assert stop.status_code == 200
        assert stop.json()["status"] == "stopped"

        playlists = client.get("/api/music/playlists", headers=headers)
        assert playlists.status_code == 200
        assert playlists.json()["playlists"][0]["title"] == "Favoritas"

        bad_stream = client.get(f"/api/music/stream/{VIDEO_A}?sig=invalida")
        assert bad_stream.status_code == 403


def test_music_api_reports_disabled(tmp_path):
    app = make_api(tmp_path, None)
    with TestClient(app) as client:
        response = client.get(
            "/api/music/state", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "music_disabled"
