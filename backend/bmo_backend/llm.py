"""Cliente Ollama local com streaming e histórico por sessão."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Any

import httpx

from .toolcalls import looks_like_tool_payload, strip_tool_artifacts

log = logging.getLogger("bmo.llm")


class LlmUnavailable(RuntimeError):
    pass


class LlmError(RuntimeError):
    pass


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class LlmSession:
    messages: list[ChatMessage] = field(default_factory=list)


class OllamaBrain:
    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = str(config.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
        self.model = str(config.get("model", "qwen3.5:2b"))
        self.timeout_s = float(config.get("timeout_s", 180))
        self.temperature = float(config.get("temperature", 0.5))
        self.num_predict = int(config.get("num_predict", 220))
        self.history_messages = int(config.get("history_messages", 12))
        self.think = bool(config.get("think", False))
        self.system_prompt = str(config.get("system_prompt", "")).strip()
        self._history: list[ChatMessage] = []

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
            models = {m.get("name") for m in data.get("models", []) if isinstance(m, dict)}
            return self.model in models or f"{self.model}:latest" in models
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> dict[str, Any]:
        return {"provider": "ollama", "base_url": self.base_url, "model": self.model}

    def reset(self) -> None:
        self._history.clear()

    def _messages(self, user_text: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        for item in self._history[-self.history_messages :]:
            messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": user_text})
        return messages

    async def stream_reply(self, user_text: str) -> AsyncIterator[str]:
        """Produz pedaços de texto. Lança LlmUnavailable/LlmError."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(user_text),
            "stream": True,
            "think": self.think,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
            },
        }
        pieces: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_s, connect=10.0)) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "ignore")[:400]
                        raise LlmError(f"Ollama respondeu {response.status_code}: {body}")
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if "error" in chunk:
                            raise LlmError(str(chunk["error"]))
                        message = chunk.get("message") or {}
                        text = message.get("content") or ""
                        if text:
                            pieces.append(text)
                            yield text
                        if chunk.get("done"):
                            break
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise LlmUnavailable(
                "Não foi possível falar com o Ollama. Verifique se ele está rodando em "
                f"{self.base_url}."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LlmError("O Ollama demorou demais para responder.") from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"Erro de rede ao falar com o Ollama: {exc}") from exc

        final = sanitize_reply("".join(pieces))
        if not final:
            raise LlmError("O modelo não retornou texto.")
        self._history.append(ChatMessage("user", user_text))
        self._history.append(ChatMessage("assistant", final))
        self._history = self._history[-self.history_messages :]

    async def reply(self, user_text: str) -> str:
        pieces: list[str] = []
        async for piece in self.stream_reply(user_text):
            pieces.append(piece)
        return sanitize_reply("".join(pieces))


def sanitize_reply(text: str, known_tools: list[str] | None = None) -> str:
    """Limpa a resposta falada e nunca deixa JSON de ferramenta vazar.

    ``known_tools`` permite remover chamadas completas. Mesmo sem a lista, a
    limpeza reconhece a forma de uma chamada e remove o objeto.
    """
    text = str(text or "").strip()
    # Alguns modelos colocam o nome do personagem no início.
    text = re.sub(r"^\s*(BMO|Bmo|bmo)\s*:\s*", "", text)
    text = strip_tool_artifacts(text, known_tools or [])
    if looks_like_tool_payload(text):
        # Sobrou um objeto de chamada inválido: não fale estruturas internas.
        text = re.sub(r"\{.*\}", " ", text, flags=re.DOTALL)
        text = strip_tool_artifacts(text, known_tools or [])
    # A resposta é falada: remove markdown, listas e ênfase, mantendo o texto.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)(?:^|\s)[-*•]\s+", " ", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Emojis e pictogramas não são falados pelo TTS.
    text = re.sub(
        r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u2B00-\u2BFF]",
        "",
        text,
    )
    text = re.sub(r"\s+", " ", text)
    return text.strip()
