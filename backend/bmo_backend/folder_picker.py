"""Seletor nativo de pasta executado no PC.

No KDE Plasma usamos ``kdialog``; se não estiver disponível, ``zenity``. Ambos
abrem o seletor nativo do desktop, inclusive em sessões Wayland quando o
compositor oferece o diálogo. A escolha é validada e persistida pelo
:class:`~bmo_backend.files.Workspace`.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any

from .files import Workspace, WorkspaceError


class FolderPickerError(RuntimeError):
    pass


class FolderPicker:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def status(self) -> dict[str, Any]:
        state = self.workspace.status()
        state["picker"] = self._picker_name()
        state["display_available"] = bool(
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        )
        return state

    def _picker_name(self) -> str:
        override = os.environ.get("BMO_FOLDER_PICKER")
        if override and shutil.which(override):
            return override
        if shutil.which("kdialog"):
            return "kdialog"
        if shutil.which("zenity"):
            return "zenity"
        return ""

    async def select(self, start: str | None = None) -> dict[str, Any]:
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise FolderPickerError(
                "Não há sessão gráfica disponível no PC para abrir o seletor de pastas."
            )
        picker = self._picker_name()
        if not picker:
            raise FolderPickerError(
                "Instale kdialog (KDE) ou zenity para o seletor nativo de pastas."
            )
        current = self.workspace.root
        initial = start or (str(current) if current else str(os.path.expanduser("~")))
        title = "Escolha a pasta de acesso do BMO"
        if picker == "kdialog":
            command = [picker, "--title", title, "--getexistingdirectory", initial]
        else:
            command = [
                picker,
                "--file-selection",
                "--directory",
                f"--title={title}",
                f"--filename={initial.rstrip('/')}/",
            ]
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            if proc.returncode in {1, 255}:
                return {"cancelled": True, **self.status()}
            detail = stderr.decode("utf-8", "ignore").strip()
            raise FolderPickerError(detail or "O seletor de pastas falhou.")
        chosen = stdout.decode("utf-8", "ignore").strip()
        if not chosen:
            return {"cancelled": True, **self.status()}
        try:
            state = self.workspace.authorize(chosen)
        except WorkspaceError as exc:
            raise FolderPickerError(str(exc)) from exc
        return {"cancelled": False, **state.as_dict()}

    def revoke(self) -> dict[str, Any]:
        return self.workspace.revoke().as_dict()
