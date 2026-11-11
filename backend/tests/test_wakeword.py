from bmo_backend.wakeword import WakeWordDetector, normalize_text


def test_normalize_removes_accent_and_punctuation():
    assert normalize_text("Ei, BMO! Que horas são?") == "ei bmo que horas sao"


def test_detects_ei_bmo_and_keeps_command():
    detector = WakeWordDetector(["ei bmo", "bmo"])
    result = detector.detect("Ei, BMO, que horas são?")
    assert result.detected is True
    assert result.matched_phrase == "ei bmo"
    assert "que horas" in result.remaining_text
    assert "bmo" not in result.remaining_text


def test_detects_common_whisper_variant():
    detector = WakeWordDetector(["ei bmo", "ei bemo", "bmo"])
    result = detector.detect("Ei, bemo, conte uma piada")
    assert result.detected
    assert result.matched_phrase == "ei bemo"


def test_detects_mo_variant_from_real_transcription():
    detector = WakeWordDetector(["ei bmo", "ei mo", "bmo"])
    result = detector.detect("Ei, Mo, quais aplicativos estão instalados no PC?")
    assert result.detected
    assert result.matched_phrase == "ei mo"
    assert "aplicativos" in result.remaining_text


def test_fuzzy_accepts_bumol_but_not_bom_dia():
    detector = WakeWordDetector(["ei bmo", "bmo"])
    result = detector.detect("Ei, Bumol, quais aplicativos estão instalados?")
    assert result.detected
    assert "aplicativos" in result.remaining_text
    assert detector.detect("Bom dia, tudo bem?").detected is False
    assert detector.detect("Ei, bem, tudo bem?").detected is False


def test_does_not_detect_unrelated_speech():
    detector = WakeWordDetector(["ei bmo", "bmo"])
    result = detector.detect("Boa tarde, tudo bem?")
    assert result.detected is False


def test_phrase_without_command():
    detector = WakeWordDetector(["ei bmo", "bmo"])
    result = detector.detect("Ei BMO")
    assert result.detected
    assert result.remaining_text == ""


def test_disabled_detector_accepts_everything():
    detector = WakeWordDetector(["ei bmo"], enabled=False)
    result = detector.detect("qualquer coisa")
    assert result.detected
    assert result.remaining_text == "qualquer coisa"
