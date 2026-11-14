"""Expressões faciais que o modelo pode solicitar via tool calling.

O conjunto abaixo é exatamente o conjunto de rostos já existente em
``assets/faces`` e no renderer Android. O backend não cria arte nova: apenas
valida a expressão e envia um evento ``face`` para o app aplicar a animação.

Os apelidos em português existem porque modelos locais pequenos às vezes
traduzem o enum do schema. O valor canônico continua sendo validado antes de
qualquer evento chegar ao Android.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Ordem usada no schema/documentação. Todos têm uma pasta correspondente em
# assets/faces (``processing`` reaproveita os frames de ``thinking``).
FACE_EXPRESSIONS: tuple[str, ...] = (
    "neutral",
    "happy",
    "sad",
    "thinking",
    "confused",
    "surprised",
    "excited",
    "sleepy",
    "love",
    "angry",
    "listening",
    "speaking",
    "processing",
    "error",
)

FACE_LABELS: dict[str, str] = {
    "neutral": "Neutro",
    "happy": "Feliz",
    "sad": "Triste",
    "thinking": "Pensando",
    "confused": "Confuso",
    "surprised": "Surpreso",
    "excited": "Animado",
    "sleepy": "Sonolento",
    "love": "Amando",
    "angry": "Bravo",
    "listening": "Ouvindo",
    "speaking": "Falando",
    "processing": "Processando",
    "error": "Erro",
}

_ALIASES: dict[str, str] = {
    "idle": "neutral",
    "neutro": "neutral",
    "neutral": "neutral",
    "feliz": "happy",
    "alegre": "happy",
    "contente": "happy",
    "happy": "happy",
    "triste": "sad",
    "tristeza": "sad",
    "sad": "sad",
    "pensando": "thinking",
    "pensativo": "thinking",
    "thinking": "thinking",
    "confuso": "confused",
    "confusa": "confused",
    "confused": "confused",
    "surpreso": "surprised",
    "surpresa": "surprised",
    "surprised": "surprised",
    "animado": "excited",
    "empolgado": "excited",
    "excited": "excited",
    "sonolento": "sleepy",
    "sono": "sleepy",
    "cansado": "sleepy",
    "sleepy": "sleepy",
    "amor": "love",
    "apaixonado": "love",
    "love": "love",
    "bravo": "angry",
    "brava": "angry",
    "raiva": "angry",
    "irritado": "angry",
    "angry": "angry",
    "ouvindo": "listening",
    "escuta": "listening",
    "listening": "listening",
    "falando": "speaking",
    "speaking": "speaking",
    "processando": "processing",
    "processing": "processing",
    "erro": "error",
    "error": "error",
}


def _plain(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().strip().split())


def normalize_face_expression(value: Any) -> str | None:
    """Devolve a expressão canônica ou ``None`` para um valor inválido."""
    return _ALIASES.get(_plain(str(value or "")))


def face_label(expression: str) -> str:
    return FACE_LABELS.get(expression, expression)


# Substantivos usados quando o pedido fala do rosto em si.
_FACE_NOUNS = frozenset({"cara", "carinha", "rosto", "rostinho", "expressao", "face"})

# Inícios de verbo que indicam mudança (mudar, trocar, colocar, fazer, deixar...).
_FACE_VERB_STEMS = (
    "mud",
    "troc",
    "coloc",
    "poe",
    "ponh",
    "bota",
    "bote",
    "faz",
    "fac",
    "deix",
    "mostr",
    "exib",
    "atualiz",
)

# Formas imperativas que expressam emoção sem citar "cara"/"rosto".
_FACE_IMPERATIVES = frozenset(
    {"fique", "fica", "esteja", "seja", "pareca", "continue", "sorria", "sorri"}
)

_ALIASES_BY_LENGTH = tuple(sorted(_ALIASES, key=len, reverse=True))


def detect_face_intent(text: str) -> str | None:
    """Reconhece pedidos explícitos de mudança de rosto no texto do usuário.

    O modelo pequeno erra o nome da ferramenta com frequência (e o STT troca
    "BMO" por outras palavras), então pedidos diretos como "mude sua cara para
    feliz" são aplicados de forma determinística antes do LLM. A resposta
    falada continua vindo do modelo; aqui só garantimos o rosto.

    Devolve a expressão canônica ou ``None`` quando não é um pedido.
    """
    normalized = _plain(text)
    if not normalized:
        return None
    words = normalized.split()

    expression: str | None = None
    for alias in _ALIASES_BY_LENGTH:
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            expression = _ALIASES[alias]
            break
    if expression is None:
        return None

    has_noun = any(word in _FACE_NOUNS for word in words)
    has_verb = any(word.startswith(_FACE_VERB_STEMS) for word in words)
    has_imperative = any(word in _FACE_IMPERATIVES for word in words)

    if has_noun and (has_verb or "de" in words or "para" in words):
        return expression
    if has_imperative:
        return expression
    return None
