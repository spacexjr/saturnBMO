"""Testes do detector acústico de wake word.

Os ONNX ficam em ``assets/wakeword``. Se não existirem (ex.: clone sem os
artefatos treinados), os testes são pulados em vez de falhar.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from bmo_backend.acoustic_wakeword import AcousticWakeWord

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "wakeword"
MODEL = ASSETS / "saturnbmo.onnx"
MEL = ASSETS / "melspectrogram.onnx"
EMBEDDING = ASSETS / "embedding_model.onnx"

pytestmark = pytest.mark.skipif(
    not (MODEL.is_file() and MEL.is_file() and EMBEDDING.is_file()),
    reason="modelos ONNX de wake word ausentes em assets/wakeword",
)


def make_detector(**kwargs) -> AcousticWakeWord:
    return AcousticWakeWord(MODEL, MEL, EMBEDDING, **kwargs)


def test_predict_silence_is_low() -> None:
    detector = make_detector()
    silence = np.zeros(32000, dtype=np.float32)
    assert detector.predict(silence) < 0.5


def test_predict_window_shape_and_range() -> None:
    detector = make_detector()
    rng = np.random.default_rng(0)
    noise = (rng.normal(0, 0.01, 32000)).astype(np.float32)
    score = detector.predict(noise)
    assert 0.0 <= score <= 1.0


def test_feed_accumulates_and_requires_full_window() -> None:
    detector = make_detector(threshold=0.0, cooldown_s=0.0, hop_s=0.0)
    pcm = np.zeros(16000, dtype="<i2").tobytes()  # 1 s
    assert detector.feed(pcm) == []  # janela de 2 s ainda incompleta
    detections = detector.feed(pcm)  # completa 2 s
    assert len(detections) == 1
    assert detections[0].score >= 0.0


def test_stop_disables_feed() -> None:
    detector = make_detector(threshold=0.0)
    pcm = np.zeros(32000, dtype="<i2").tobytes()
    detector.stop()
    assert detector.feed(pcm) == []
    detector.start()
    assert detector.running
