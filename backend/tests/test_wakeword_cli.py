from __future__ import annotations

import wave
from types import SimpleNamespace

import pytest

from bmo_backend import wakeword_cli


def test_resolve_device_passthrough() -> None:
    assert wakeword_cli.resolve_device("plughw:2,0") == "plughw:2,0"
    assert wakeword_cli.resolve_device("hw:1,0") == "hw:1,0"
    assert wakeword_cli.resolve_device("3") == "3"
    assert wakeword_cli.resolve_device(None) is None


def test_resolve_device_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    output = "card 3: AUDIO [USB HIFI AUDIO], device 0: USB Audio [USB Audio]\n"
    monkeypatch.setattr(
        wakeword_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=output),
    )
    assert wakeword_cli.resolve_device("USB HIFI") == "plughw:3,0"


def test_resolve_device_not_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        wakeword_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=""),
    )
    assert wakeword_cli.resolve_device("inexistente") is None
    assert "não encontrado" in capsys.readouterr().err


def test_list_devices_without_arecord(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(wakeword_cli.shutil, "which", lambda name: None)
    assert wakeword_cli.list_devices() == 1
    assert "alsa-utils" in capsys.readouterr().err


class DummyDetector:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def feed(self, chunk: bytes) -> list[object]:
        self.chunks.append(chunk)
        return []


def test_run_wav_pads_short_clip(tmp_path) -> None:
    path = tmp_path / "curto.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000)
    detector = DummyDetector()
    assert wakeword_cli.run_wav(path, detector) == 1
    assert len(b"".join(detector.chunks)) >= 32000 * 2


def test_run_wav_rejects_wrong_format(tmp_path) -> None:
    path = tmp_path / "estereo.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 32000)
    with pytest.raises(SystemExit, match="PCM 16-bit mono"):
        wakeword_cli.run_wav(path, DummyDetector())
