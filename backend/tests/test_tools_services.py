"""Testes dos serviços de aplicativos, mídia, sistema e fábrica de STT."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from bmo_backend.apps import AppManager, DesktopApp, normalize
from bmo_backend.config import DEFAULT_CONFIG, resolve_runtime_paths
from bmo_backend.media import MediaError, MediaService, PlayerInfo
from bmo_backend.stt import (
    FallbackStt,
    WhisperCppStt,
    build_stt,
    drop_hallucination,
)
from bmo_backend.sysinfo import SystemInfo, SystemInfoError


def test_app_manager_matches_by_name_and_ignores_accents():
    manager = AppManager()
    manager._apps = [
        DesktopApp(desktop_id="firefox.desktop", name="Firefox"),
        DesktopApp(desktop_id="code.desktop", name="Visual Studio Code"),
        DesktopApp(desktop_id="musica.desktop", name="Música"),
    ]
    assert manager.find("firefox").name == "Firefox"
    assert manager.find("visual studio").name == "Visual Studio Code"
    assert manager.find("musica").name == "Música"
    assert manager.find("inexistente") is None
    assert normalize("Música Legal!") == "musica legal"


def test_app_manager_list_apps_filters():
    manager = AppManager()
    manager._apps = [
        DesktopApp(desktop_id="a.desktop", name="Alpha"),
        DesktopApp(desktop_id="b.desktop", name="Beta"),
    ]
    result = manager.list_apps("alp")
    assert [app["name"] for app in result["apps"]] == ["Alpha"]


def test_media_chooses_preferred_bitchord_player():
    service = MediaService({"preferred_players": ["bitchord"]})
    players = [PlayerInfo("spotify"), PlayerInfo("bitchord"), PlayerInfo("playerctld")]
    assert service._choose(players).name == "bitchord"


def test_media_falls_back_to_first_real_player():
    service = MediaService({"preferred_players": ["bitchord"]})
    players = [PlayerInfo("playerctld"), PlayerInfo("vlc")]
    assert service._choose(players).name == "vlc"
    assert service._choose([]) is None


def test_media_search_reports_bit_chord_limitation():
    service = MediaService()
    import asyncio

    with pytest.raises(MediaError) as exc:
        asyncio.run(service.search_and_play("qualquer música"))
    assert "não expõe pesquisa" in str(exc.value)


def test_system_info_disabled_and_unknown_section():
    import asyncio

    disabled = SystemInfo({"enabled": False})
    with pytest.raises(SystemInfoError):
        asyncio.run(disabled.get("cpu"))

    enabled = SystemInfo({"enabled": True})
    with pytest.raises(SystemInfoError):
        asyncio.run(enabled.get("senha_do_root"))


def test_system_info_memory_and_disk():
    import asyncio

    service = SystemInfo({"enabled": True})
    memory = asyncio.run(service.get("memoria"))
    assert memory["total_gb"] > 0
    assert 0 <= (memory["usage_percent"] or 0) <= 100
    disk = asyncio.run(service.get("disco"))
    assert disk["total_gb"] > 0


def test_build_stt_faster_whisper_with_fallback():
    cfg = copy.deepcopy(DEFAULT_CONFIG["stt"])
    resolve_runtime_paths({"stt": cfg, "tts": {}, "wakeword": {}, "paths": {}, "tools": {}})
    stt = build_stt(cfg)
    assert isinstance(stt, FallbackStt)
    assert stt.primary.__class__.__name__ == "FasterWhisperStt"
    assert stt.fallback is not None and isinstance(stt.fallback, WhisperCppStt)


def test_build_stt_whisper_cpp_only():
    stt = build_stt({"engine": "whisper_cpp", "binary": "/bin/echo", "model": "/tmp/m"})
    assert isinstance(stt, WhisperCppStt)


def test_drop_hallucination_filters_silence_phrases():
    assert drop_hallucination("Obrigado por assistir!") == ""
    assert drop_hallucination("[BLANK_AUDIO]") == ""
    assert drop_hallucination("Ei BMO, tudo bem") == "Ei BMO, tudo bem"


def test_resolve_runtime_paths_keeps_stt_model_name():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["paths"]["log_file"] = "data/x.log"
    resolve_runtime_paths(cfg)
    # Nome do modelo do Faster-Whisper não deve virar caminho absoluto.
    assert cfg["stt"]["model"] == "small"
    assert Path(cfg["wakeword"]["acoustic_model"]).name == "saturnbmo.onnx"
    assert Path(cfg["tools"]["access_file"]).name == "access.json"
