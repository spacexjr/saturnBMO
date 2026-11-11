"""Detecção e recuperação de chamadas de ferramenta impressas como texto.

Alguns modelos locais não usam o campo estruturado ``tool_calls`` da API do
Ollama e escrevem um objeto JSON na mensagem de conteúdo. Este módulo:

* encontra apenas objetos que tenham *forma* de chamada de ferramenta;
* aceita a chamada somente quando o nome existe no registro do BMO;
* devolve o texto restante para que o usuário nunca veja JSON interno;
* remove artefatos de chamadas da resposta final.

Nada aqui executa código. A validação de argumentos e a execução continuam no
:class:`~bmo_backend.toolkit.ToolRegistry`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*(.*?)```", re.DOTALL)
# Campos que indicam que um objeto JSON pretende ser uma chamada de ferramenta.
_NAME_KEYS = ("tool_name", "name", "tool", "function_name")
_ARGS_KEYS = ("arguments", "parameters", "args", "input", "params")


@dataclass
class TextToolCall:
    name: str
    arguments: dict[str, Any]
    start: int
    end: int


def _object_spans(text: str) -> list[tuple[int, int]]:
    """Localiza objetos JSON balanceados dentro de um texto."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append((start, index + 1))
                    start = -1
    return spans


def _parse_object(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _arguments(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return {}
        parsed = _parse_object(value)
        if isinstance(parsed, dict):
            return parsed
        return None
    if isinstance(value, dict):
        return value
    return None


def _call_from_mapping(
    data: dict[str, Any], known: set[str]
) -> tuple[str, dict[str, Any]] | None:
    """Reconhece um objeto de chamada e devolve (nome, argumentos)."""
    # Formato OpenAI/Ollama: {"function": {"name": ..., "arguments": {...}}}
    function = data.get("function")
    if isinstance(function, dict):
        name = str(function.get("name") or "").strip()
        if name in known:
            args = _arguments(
                function.get("arguments", function.get("parameters", {}))
            )
            if args is not None:
                return name, args
    if isinstance(function, str) and function.strip() in known and not data.get("name"):
        args = _arguments(data.get("arguments", {}))
        if args is not None:
            return function.strip(), args

    for key in _NAME_KEYS:
        candidate = data.get(key)
        if isinstance(candidate, dict):
            # {"name": {"name": ...}} não é formato válido.
            continue
        if not isinstance(candidate, str):
            continue
        name = candidate.strip()
        if name not in known:
            continue
        args_value = None
        for args_key in _ARGS_KEYS:
            if args_key in data:
                args_value = data.get(args_key)
                break
        if args_value is None:
            # Sem argumentos explícitos: aceita somente se o objeto tiver
            # exclusivamente chaves de chamada.
            extra = set(data) - {key} - set(_ARGS_KEYS)
            if extra:
                continue
            args_value = {}
        args = _arguments(args_value)
        if args is not None:
            return name, args
    return None


def find_text_tool_calls(
    text: str, known_names: Iterable[str]
) -> list[TextToolCall]:
    """Extrai chamadas em texto que usam nomes registrados.

    Objetos JSON com nome desconhecido são ignorados (não são chamadas válidas)
    e permanecem no texto para que a camada de limpeza os remova sem executar.
    """
    known = {name for name in known_names if name}
    calls: list[TextToolCall] = []
    if not text or not known:
        return calls
    for start, end in _object_spans(text):
        data = _parse_object(text[start:end])
        if not isinstance(data, dict):
            continue
        # Aceita também {"tool_calls": [...]} escrito como texto.
        nested = data.get("tool_calls") or data.get("tool_call")
        if isinstance(nested, list):
            for item in nested:
                if not isinstance(item, dict):
                    continue
                found = _call_from_mapping(item, known)
                if found is not None:
                    calls.append(TextToolCall(found[0], found[1], start, end))
            continue
        if isinstance(nested, dict):
            found = _call_from_mapping(nested, known)
            if found is not None:
                calls.append(TextToolCall(found[0], found[1], start, end))
            continue
        found = _call_from_mapping(data, known)
        if found is not None:
            calls.append(TextToolCall(found[0], found[1], start, end))
    return calls


def looks_like_tool_payload(text: str) -> bool:
    """Heurística conservadora: há um objeto JSON de chamada (mesmo inválido)?"""
    if not text or "{" not in text:
        return False
    lowered = text.lower()
    markers = (
        '"tool_calls"',
        '"tool_call"',
        '"function"',
        '"arguments"',
        '"parameters"',
    )
    if not any(marker in lowered for marker in markers):
        return False
    return len(_object_spans(text)) > 0


def strip_tool_artifacts(text: str, known_names: Iterable[str] = ()) -> str:
    """Remove chamadas de ferramenta e blocos de código internos do texto."""
    if not text:
        return ""
    known = {name for name in known_names if name}
    calls = find_text_tool_calls(text, known)
    spans = sorted({(call.start, call.end) for call in calls}, reverse=True)
    cleaned = text
    for start, end in spans:
        cleaned = cleaned[:start] + " " + cleaned[end:]

    # Objetos com forma de chamada mas nome desconhecido também são internos:
    # remova-os para nunca aparecerem ao usuário, sem executar nada.
    for start, end in sorted(_object_spans(cleaned), reverse=True):
        data = _parse_object(cleaned[start:end])
        if not isinstance(data, dict):
            continue
        if _looks_like_call_shape(data):
            cleaned = cleaned[:start] + " " + cleaned[end:]

    # Remove cercas de código mantendo o conteúdo (quando não é JSON).
    def _fence(match: re.Match[str]) -> str:
        body = match.group(1).strip()
        if body.startswith(("{", "[")):
            return " "
        return body

    cleaned = _FENCE_RE.sub(_fence, cleaned)
    cleaned = re.sub(r"</?tool_call>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\btool_calls?\b\s*[:=]", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _looks_like_call_shape(data: dict[str, Any]) -> bool:
    if isinstance(data.get("tool_calls"), (list, dict)):
        return True
    if isinstance(data.get("tool_call"), (list, dict)):
        return True
    function = data.get("function")
    if isinstance(function, dict) and ("name" in function or "arguments" in function):
        return True
    if isinstance(function, str) and any(key in data for key in _ARGS_KEYS):
        return True
    has_name = any(isinstance(data.get(key), str) for key in _NAME_KEYS)
    has_args = any(key in data for key in _ARGS_KEYS)
    return has_name and has_args


def remove_spans(text: str, calls: Iterable[TextToolCall]) -> str:
    """Remove exatamente os trechos das chamadas detectadas."""
    cleaned = text
    for start, end in sorted({(c.start, c.end) for c in calls}, reverse=True):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    return re.sub(r"\s+", " ", cleaned).strip()
