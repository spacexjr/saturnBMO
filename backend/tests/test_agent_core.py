"""Testes do núcleo de tool calling: JSON em texto, validação e limites."""

from __future__ import annotations

import asyncio
import json

import pytest

from bmo_backend.agent import ToolAgent
from bmo_backend.toolcalls import (
    find_text_tool_calls,
    looks_like_tool_payload,
    strip_tool_artifacts,
)
from bmo_backend.toolkit import (
    PendingConfirmation,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    normalize_aliases,
    validate_arguments,
)


class FakeRegistry:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []

    def names(self) -> list[str]:
        return ["launch_app", "web_search", "delete_file"]

    def schemas(self) -> list[dict]:
        return []

    def canonical_arguments(self, name: str, arguments: dict) -> dict:
        return dict(arguments or {})

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        self.executed.append((name, arguments))
        return ToolResult(True, {"ok": True, "name": name})


def make_agent(monkeypatch, responses, registry=None):
    registry = registry or FakeRegistry()
    agent = ToolAgent(
        {"model": "fake", "max_tool_steps": 4},
        registry,  # type: ignore[arg-type]
        system_prompt="Você é BMO.",
    )
    queue = list(responses)

    async def fake_chat(messages, *, with_tools, **kwargs):
        if not queue:
            return {"message": {"content": "Fim."}}
        return queue.pop(0)

    monkeypatch.setattr(agent, "_chat", fake_chat)
    return agent, registry


class Emitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, event_type: str, **fields):
        self.events.append((event_type, fields))


def run(coro):
    return asyncio.run(coro)


def test_json_printed_as_text_is_recovered_and_executed(monkeypatch):
    agent, registry = make_agent(
        monkeypatch,
        [
            {"message": {"content": '{"name": "launch_app", "arguments": {"name": "Firefox"}}'}},
            {"message": {"content": "Pronto, abri o Firefox."}},
        ],
    )
    emit = Emitter()
    result = run(agent.run("Abre o Firefox", emit))
    assert registry.executed == [("launch_app", {"name": "Firefox"})]
    assert result.text == "Pronto, abri o Firefox."
    assert "{" not in result.text and "launch_app" not in result.text


def test_unknown_tool_json_is_never_executed_nor_shown(monkeypatch):
    agent, registry = make_agent(
        monkeypatch,
        [
            {"message": {"content": '{"name": "rm_rf", "arguments": {"path": "/"}}'}},
            {"message": {"content": "Não consegui fazer isso."}},
        ],
    )
    result = run(agent.run("Apague tudo", Emitter()))
    assert registry.executed == []
    assert result.text == "Não consegui fazer isso."


def test_structured_tool_call_still_works(monkeypatch):
    agent, registry = make_agent(
        monkeypatch,
        [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": {"query": "clima hoje"},
                            }
                        }
                    ],
                },
                "done_reason": "tool_calls",
            },
            {"message": {"content": "Hoje faz sol."}},
        ],
    )
    result = run(agent.run("Pesquisa o clima", Emitter()))
    assert registry.executed == [("web_search", {"query": "clima hoje"})]
    assert result.text == "Hoje faz sol."


def test_duplicate_tool_call_is_not_executed_twice(monkeypatch):
    call = {
        "message": {
            "content": "",
            "tool_calls": [
                {"function": {"name": "launch_app", "arguments": {"name": "Firefox"}}}
            ],
        }
    }
    agent, registry = make_agent(
        monkeypatch,
        [call, call, {"message": {"content": "O Firefox já está aberto."}}],
    )
    result = run(agent.run("Abre o Firefox", Emitter()))
    assert registry.executed == [("launch_app", {"name": "Firefox"})]
    assert result.text == "O Firefox já está aberto."


def test_tool_arguments_validation():
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
            "mode": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["query"],
    }
    assert validate_arguments(schema, {})[1] is not None
    assert validate_arguments(schema, {"query": "x", "limit": "oito"})[1] is not None
    assert validate_arguments(schema, {"query": "x", "limit": 99})[1] is not None
    assert validate_arguments(schema, {"query": "x", "mode": "c"})[1] is not None
    args, error = validate_arguments(schema, {"query": "x", "limit": "3"})
    assert error is None and args["limit"] == 3


def test_alias_normalization_only_for_schema_fields():
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    assert normalize_aliases(schema, {"q": "Daft Punk"}) == {"query": "Daft Punk"}
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    assert normalize_aliases(schema, {"q": "Firefox"}) == {"q": "Firefox"}


class DummyService:
    def __getattr__(self, name):
        async def handler(*args, **kwargs):
            return {"result": "dummy"}

        return handler


def build_registry(**config) -> ToolRegistry:
    dummy = DummyService()
    return ToolRegistry(
        workspace=dummy,  # type: ignore[arg-type]
        apps=dummy,  # type: ignore[arg-type]
        media=dummy,  # type: ignore[arg-type]
        web=dummy,  # type: ignore[arg-type]
        system=dummy,  # type: ignore[arg-type]
        config=config,
    )


def test_registry_timeout_returns_friendly_error():
    registry = build_registry()

    async def slow() -> dict:
        await asyncio.sleep(1.2)
        return {"ok": True}

    registry._add(ToolSpec("slow", "lento", {"type": "object", "properties": {}}, slow, timeout_s=0.01))
    result = run(registry.execute("slow", {}))
    assert result.ok is False
    assert "demorou demais" in result.data["error"]


def test_registry_confirmation_runs_only_after_approval():
    registry = build_registry()
    calls: list[str] = []

    async def delete(path: str) -> dict:
        calls.append(path)
        return {"path": path}

    registry._add(
        ToolSpec(
            "delete_file",
            "apaga",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            delete,
            destructive=True,
        )
    )
    pending_result = run(registry.execute("delete_file", {"path": "x.txt"}))
    assert pending_result.pending is not None
    assert calls == []
    confirmed = run(registry.execute_confirmed(pending_result.pending))
    assert confirmed.ok is True
    assert calls == ["x.txt"]


def test_tool_json_extraction_and_artifact_strip():
    text = (
        "Vou abrir.\n```json\n"
        '{"name": "launch_app", "arguments": {"name": "Firefox"}}\n```'
    )
    calls = find_text_tool_calls(text, ["launch_app"])
    assert len(calls) == 1 and calls[0].name == "launch_app"
    assert looks_like_tool_payload(text)
    cleaned = strip_tool_artifacts(text, ["launch_app"])
    assert "launch_app" not in cleaned
    assert "{" not in cleaned
    assert cleaned.startswith("Vou abrir.")


def test_sanitize_reply_removes_invalid_tool_payload():
    from bmo_backend.llm import sanitize_reply

    raw = '{"name":"ferramenta_inexistente","arguments":{"x":1}}'
    assert sanitize_reply(raw, ["launch_app"]) == ""


def test_sanitize_reply_removes_markdown_and_emoji():
    from bmo_backend.llm import sanitize_reply

    raw = "**Pronto!** 😊\n- Firefox aberto\n- Música pausada"
    cleaned = sanitize_reply(raw)
    assert cleaned == "Pronto! Firefox aberto Música pausada"


def test_schemas_for_routes_by_intent():
    registry = build_registry()
    registry._add(ToolSpec("list_apps", "apps", {"type": "object", "properties": {}}, lambda: {}))
    registry._add(ToolSpec("web_search", "web", {"type": "object", "properties": {}}, lambda: {}))
    registry._add(ToolSpec("music_play", "music", {"type": "object", "properties": {}}, lambda: {}))
    registry._add(ToolSpec("read_file", "files", {"type": "object", "properties": {}}, lambda: {}))

    app_names = {item["function"]["name"] for item in registry.schemas_for("Quais aplicativos de música estão instalados?")}
    assert "list_apps" in app_names
    assert "music_play" not in app_names

    music_names = {item["function"]["name"] for item in registry.schemas_for("Toca uma música do Daft Punk")}
    assert "music_play" in music_names

    file_names = {item["function"]["name"] for item in registry.schemas_for("Leia o arquivo README")}
    assert "read_file" in file_names

    web_names = {item["function"]["name"] for item in registry.schemas_for("Pesquise na internet notícias de hoje")}
    assert "web_search" in web_names


def test_pending_confirmation_is_explicit_state(monkeypatch):
    pending = PendingConfirmation("abc", "delete_file", {"path": "x"}, "Confirma?", "editing_file")

    class Registry(FakeRegistry):
        async def execute(self, name, arguments):
            return ToolResult(False, {"pending": pending.as_dict()}, pending=pending)

    agent, registry = make_agent(
        monkeypatch,
        [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "delete_file", "arguments": {"path": "x"}}}
                    ],
                }
            }
        ],
        Registry(),
    )
    result = run(agent.run("Apague x", Emitter()))
    assert result.pending is not None and result.pending.id == "abc"
    assert result.text == "Confirma?"
