"""Testes da detecção determinística de pedidos de rosto."""

import pytest

from bmo_backend.faces import (
    FACE_EXPRESSIONS,
    detect_face_intent,
    face_label,
    normalize_face_expression,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ei, BMO, mude sua cara para feliz", "happy"),
        ("Ei, Mopidy, mude sua cara para feliz.", "happy"),
        ("muda a cara para triste", "sad"),
        ("troque o rosto para animado", "excited"),
        ("faça uma cara de surpreso", "surprised"),
        ("coloque a expressão de bravo", "angry"),
        ("BMO, fique feliz", "happy"),
        ("fique com sono", "sleepy"),
        ("seja mais alegre", "happy"),
        ("sua cara de confuso agora", "confused"),
        ("mude para a cara de amor", "love"),
    ],
)
def test_detect_face_intent_accepts_direct_requests(text, expected):
    assert detect_face_intent(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "estou muito feliz hoje",
        "fiquei triste com a notícia",
        "você está bravo comigo?",
        "que horas são?",
        "toque uma música alegre",
        "qual é a previsão do tempo?",
        "você parece cansado",
        "",
    ],
)
def test_detect_face_intent_ignores_conversation(text):
    assert detect_face_intent(text) is None


def test_face_helpres_keep_canonical_values():
    assert normalize_face_expression("FELIZ") == "happy"
    assert normalize_face_expression("inexistente") is None
    for expression in FACE_EXPRESSIONS:
        assert face_label(expression)
