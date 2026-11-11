"""Detecção da palavra de ativação 'Ei, BMO'.

A detecção padrão é textual: o áudio é transcrito pelo Whisper.cpp e o texto
normalizado é comparado com frases configuráveis. Isso permite testar o
reconhecimento sem depender de um modelo acústico treinado para "Ei, BMO".

O arquivo wakeword.onnx do projeto original é o modelo "Hey Jarvis" do
OpenWakeWord. Ele NÃO é usado silenciosamente como se fosse "Ei, BMO".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

DEFAULT_PHRASES = [
    "ei bmo",
    "ei bemo",
    "hey bmo",
    "oi bmo",
    "e bmo",
    "bmo",
]


def normalize_text(text: str) -> str:
    """Minúsculas, sem acentos e sem pontuação, com espaços simples."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class WakeWordResult:
    detected: bool
    remaining_text: str
    matched_phrase: str | None
    normalized_text: str


class WakeWordDetector:
    def __init__(
        self,
        phrases: list[str] | None = None,
        enabled: bool = True,
        *,
        fuzzy: bool = True,
    ) -> None:
        raw = phrases if phrases is not None else DEFAULT_PHRASES
        # Frases maiores primeiro evita que "bmo" consuma só o final de "ei bmo".
        self.phrases = sorted(
            {normalize_text(p) for p in raw if normalize_text(p)},
            key=len,
            reverse=True,
        )
        self.enabled = enabled
        self.fuzzy = fuzzy
        self._patterns = [
            (phrase, re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"))
            for phrase in self.phrases
        ]

    def detect(self, text: str) -> WakeWordResult:
        normalized = normalize_text(text)
        if not self.enabled:
            return WakeWordResult(True, text.strip(), None, normalized)
        for phrase, pattern in self._patterns:
            match = pattern.search(normalized)
            if not match:
                continue
            # Remove a ocorrência da frase do texto original normalizado e
            # devolve o restante em minúsculas (sem acentos). O texto original
            # é usado apenas para transcrição; a resposta do LLM não depende de
            # acentuação do comando.
            remaining = (normalized[: match.start()] + " " + normalized[match.end() :]).strip()
            remaining = re.sub(r"\s+", " ", remaining).strip(" ,.!?;:-")
            return WakeWordResult(True, remaining, phrase, normalized)

        if self.fuzzy:
            fuzzy = self._detect_fuzzy(normalized)
            if fuzzy is not None:
                return fuzzy
        return WakeWordResult(False, text.strip(), None, normalized)

    def _detect_fuzzy(self, normalized: str) -> WakeWordResult | None:
        """Aceita variantes fonéticas curtas que o Whisper costuma escrever.

        Só considera o começo da fala, exige um prefixo de chamada ("ei", "hey",
        "oi") ou a palavra isolada, e usa uma lista conservadora de formas do
        som "bemo". Evita ativar com "ei, bem" ou conversa comum.
        """
        tokens = normalized.split()
        if not tokens:
            return None
        start = 0
        matched = ""
        if _is_bmo_token(tokens[0]):
            matched = tokens[0]
            start = 1
        elif (
            len(tokens) >= 2
            and tokens[0] in {"ei", "hey", "oi"}
            and _is_bmo_token(tokens[1], after_prefix=True)
        ):
            matched = f"{tokens[0]} {tokens[1]}"
            start = 2
        if not matched:
            return None
        remaining = " ".join(tokens[start:]).strip(" ,.!?;:-")
        return WakeWordResult(True, remaining, matched, normalized)


_BMO_FUZZY = re.compile(r"^(?:(?:e|i|u)?m(?:o|ol|l|m)|bo|bom)$")


def _is_bmo_token(token: str, *, after_prefix: bool = False) -> bool:
    """Formas curtas de 'BMO' produzidas por STT em português."""
    token = token.strip(".,!?;:-")
    if token in {"bo", "bom"}:
        # "bom dia" não deve ativar; "ei, bom" pode ser a wake word.
        return after_prefix
    if token in {"mo", "bmo", "abmo"}:
        return True
    if token.startswith("ab"):
        core = token[2:]
    elif token.startswith("b"):
        core = token[1:]
    else:
        return False
    return bool(_BMO_FUZZY.match(core))
