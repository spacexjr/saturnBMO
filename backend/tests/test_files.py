"""Testes do sandbox de arquivos e das confirmações de exclusão."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bmo_backend.apps import AppManager
from bmo_backend.files import Workspace, WorkspaceError
from bmo_backend.media import MediaService
from bmo_backend.sysinfo import SystemInfo
from bmo_backend.toolkit import ToolRegistry
from bmo_backend.web import WebService


def make_workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "bmo"
    root.mkdir()
    workspace = Workspace(tmp_path / "access.json")
    workspace.authorize(str(root))
    return workspace


def test_requires_authorized_folder(tmp_path):
    workspace = Workspace(tmp_path / "access.json")
    with pytest.raises(WorkspaceError):
        workspace.list_files()


def test_authorize_persists_and_can_be_revoked(tmp_path):
    workspace = make_workspace(tmp_path)
    status = workspace.status()
    assert status["authorized"] is True
    assert Path(status["path"]).is_dir()

    reloaded = Workspace(tmp_path / "access.json")
    assert reloaded.status()["authorized"] is True

    reloaded.revoke()
    assert Workspace(tmp_path / "access.json").status()["authorized"] is False


def test_crud_inside_sandbox(tmp_path):
    workspace = make_workspace(tmp_path)
    created = workspace.create_file("nota.txt", "linha um\nlinha dois\n")
    assert created["ok"] is True

    listing = workspace.list_files()
    assert [entry["name"] for entry in listing["entries"]] == ["nota.txt"]

    read = workspace.read_file("nota.txt")
    assert "linha dois" in read["content"]

    workspace.write_file("nota.txt", "novo conteúdo")
    assert workspace.read_file("nota.txt")["content"] == "novo conteúdo"

    workspace.edit_file("nota.txt", "novo", "outro")
    assert workspace.read_file("nota.txt")["content"] == "outro conteúdo"

    workspace.create_directory("docs")
    workspace.copy_file("nota.txt", "docs/copia.txt")
    assert workspace.read_file("docs/copia.txt")["content"] == "outro conteúdo"

    workspace.rename_file("docs/copia.txt", "renomeado.txt")
    assert workspace.read_file("docs/renomeado.txt")["content"] == "outro conteúdo"

    workspace.move_file("docs/renomeado.txt", "movido.txt")
    assert workspace.get_file_metadata("movido.txt")["type"] == "file"

    workspace.delete_file("movido.txt")
    assert not (Path(workspace.root) / "movido.txt").exists()


def test_blocks_traversal_and_absolute_paths(tmp_path):
    workspace = make_workspace(tmp_path)
    outside = tmp_path / "fora.txt"
    outside.write_text("segredo", encoding="utf-8")

    with pytest.raises(WorkspaceError):
        workspace.read_file("../fora.txt")
    with pytest.raises(WorkspaceError):
        workspace.read_file(str(outside))


def test_blocks_symlink_escape(tmp_path):
    workspace = make_workspace(tmp_path)
    outside = tmp_path / "fora.txt"
    outside.write_text("segredo", encoding="utf-8")
    link = Path(workspace.root) / "atalho.txt"
    os.symlink(outside, link)

    with pytest.raises(WorkspaceError):
        workspace.read_file("atalho.txt")


def test_cannot_delete_authorized_root(tmp_path):
    workspace = make_workspace(tmp_path)
    with pytest.raises(WorkspaceError):
        workspace.delete_directory("", recursive=True)


def test_search_files_by_name_and_content(tmp_path):
    workspace = make_workspace(tmp_path)
    workspace.create_file("receita.txt", "bolo de cenoura")
    workspace.create_file("outro.txt", "nada aqui")

    by_content = workspace.search_files("cenoura", content=True)
    assert [entry["name"] for entry in by_content["entries"]] == ["receita.txt"]

    by_name = workspace.search_files("recei")
    assert [entry["name"] for entry in by_name["entries"]] == ["receita.txt"]


def test_registry_requires_confirmation_before_deleting(tmp_path):
    workspace = make_workspace(tmp_path)
    workspace.create_file("apagar.txt", "x")
    registry = ToolRegistry(
        workspace=workspace,
        apps=AppManager(),
        media=MediaService(),
        web=WebService(),
        system=SystemInfo(),
    )

    import asyncio

    pending_result = asyncio.run(registry.execute("delete_file", {"path": "apagar.txt"}))
    assert pending_result.pending is not None
    assert pending_result.ok is False
    # Nada foi excluído ainda.
    assert (Path(workspace.root) / "apagar.txt").exists()

    confirmed = asyncio.run(registry.execute_confirmed(pending_result.pending))
    assert confirmed.ok is True
    assert not (Path(workspace.root) / "apagar.txt").exists()


def test_registry_rejects_unknown_tool(tmp_path):
    import asyncio

    workspace = make_workspace(tmp_path)
    registry = ToolRegistry(
        workspace=workspace,
        apps=AppManager(),
        media=MediaService(),
        web=WebService(),
        system=SystemInfo(),
    )
    result = asyncio.run(registry.execute("rm_rf", {"path": "/"}))
    assert result.ok is False
    assert "desconhecida" in result.data["error"]
