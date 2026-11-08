"""Descoberta e controle de aplicativos do desktop Linux.

A descoberta usa os arquivos ``.desktop`` dos diretórios XDG (incluindo Flatpak)
em vez de uma lista fixa. Abertura usa ``gtk-launch``/``flatpak run``; nunca há
shell arbitrário. Controle de janelas usa ``wmctrl`` quando disponível e informa
claramente as limitações do Wayland.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import signal
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("bmo.apps")

CRITICAL_PROCESSES = {
    "systemd", "init", "kwin_wayland", "kwin_x11", "plasmashell", "Xorg", "Xwayland",
    "dbus-daemon", "dbus-broker", "dbus-broker-launch", "pipewire", "wireplumber",
    "pulseaudio", "sshd", "NetworkManager", "avahi-daemon", "tailscaled",
    "flatpak-session-helper", "flatpak-portal", "waydroid", "xdg-desktop-portal",
}

IGNORED_EXEC = {
    "sh", "bash", "env", "python", "python3", "node", "java", "wine",
    # Argumentos genéricos de launchers não identificam um aplicativo.
    "run", "flatpak", "snap", "gtk-launch", "gio", "xdg-open", "command",
    "sudo", "pkexec", "wine64", "wine-preloader", "waydroid",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def desktop_dirs() -> list[Path]:
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    data_dirs = [
        Path(part) for part in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
        if part
    ]
    candidates = [
        data_home / "applications",
        home / ".local/share/applications",
        *[directory / "applications" for directory in data_dirs],
        Path("/var/lib/flatpak/exports/share/applications"),
        data_home / "flatpak/exports/share/applications",
        Path("/var/lib/snapd/desktop/applications"),
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for directory in candidates:
        if directory in seen:
            continue
        seen.add(directory)
        if directory.is_dir():
            unique.append(directory)
    return unique


@dataclass
class DesktopApp:
    desktop_id: str
    name: str
    generic_name: str = ""
    comment: str = ""
    categories: list[str] = field(default_factory=list)
    exec_line: str = ""
    icon: str = ""
    terminal: bool = False
    source: str = "desktop"
    path: str = ""
    no_display: bool = False

    @property
    def launch_command(self) -> list[str]:
        if self.source == "flatpak":
            app_id = self.desktop_id.removesuffix(".desktop")
            return ["flatpak", "run", app_id]
        if shutil.which("gtk-launch"):
            return ["gtk-launch", self.desktop_id.removesuffix(".desktop")]
        return ["gio", "launch", self.path]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.desktop_id,
            "name": self.name,
            "description": self.comment or self.generic_name,
            "categories": self.categories,
            "command": self.exec_line,
            "source": self.source,
            "terminal": self.terminal,
        }


def _parse_desktop(path: Path, source: str) -> DesktopApp | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    in_entry = False
    values: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_entry = stripped == "[Desktop Entry]"
            continue
        if not in_entry or not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    if values.get("Type", "Application") != "Application":
        return None
    if values.get("Hidden", "").lower() == "true":
        return None
    name = values.get("Name[pt_BR]") or values.get("Name[pt]") or values.get("Name") or ""
    if not name:
        return None
    return DesktopApp(
        desktop_id=path.name,
        name=name,
        generic_name=values.get("GenericName[pt_BR]") or values.get("GenericName", ""),
        comment=values.get("Comment[pt_BR]") or values.get("Comment", ""),
        categories=[part for part in values.get("Categories", "").split(";") if part],
        exec_line=values.get("Exec", ""),
        icon=values.get("Icon", ""),
        terminal=values.get("Terminal", "").lower() == "true",
        source=source,
        path=str(path),
        no_display=values.get("NoDisplay", "").lower() == "true",
    )


class AppManager:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.allow_close = bool(config.get("allow_close", True))
        self._apps: list[DesktopApp] | None = None
        self._launched: dict[str, list[int]] = {}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "desktop_dirs": [str(directory) for directory in desktop_dirs()],
            "wmctrl": bool(shutil.which("wmctrl")),
            "session": os.environ.get("XDG_SESSION_TYPE", "desconhecido"),
        }

    # -- descoberta -------------------------------------------------------

    def discover(self, refresh: bool = False) -> list[DesktopApp]:
        if self._apps is not None and not refresh:
            return self._apps
        apps: list[DesktopApp] = []
        seen: set[str] = set()
        for directory in desktop_dirs():
            flatpak = "flatpak" in str(directory)
            for path in sorted(directory.glob("*.desktop")):
                app = _parse_desktop(path, "flatpak" if flatpak else "desktop")
                if app is None:
                    continue
                key = app.desktop_id.lower()
                if key in seen:
                    continue
                seen.add(key)
                apps.append(app)
        apps.sort(key=lambda app: normalize(app.name))
        self._apps = apps
        return apps

    def list_apps(self, query: str = "", limit: int = 40) -> dict[str, Any]:
        if not self.enabled:
            return {"error": "O controle de aplicativos está desativado.", "apps": []}
        apps = self.discover()
        needle = normalize(query)
        if needle:
            scored = []
            for app in apps:
                haystack = normalize(
                    " ".join([app.name, app.generic_name, app.comment, app.desktop_id])
                )
                if needle in haystack:
                    scored.append((0 if normalize(app.name).startswith(needle) else 1, app))
            scored.sort(key=lambda item: (item[0], normalize(item[1].name)))
            selected = [item[1] for item in scored]
        else:
            selected = apps
        return {"apps": [app.as_dict() for app in selected[: max(1, min(limit, 100))]]}

    def find(self, name: str) -> DesktopApp | None:
        needle = normalize(name)
        if not needle:
            return None
        apps = self.discover()
        # 1) nome exato; 2) começa com; 3) contém no nome; 4) id/descrição.
        for app in apps:
            if normalize(app.name) == needle:
                return app
        for app in apps:
            if normalize(app.name).startswith(needle):
                return app
        for app in apps:
            if needle in normalize(app.name):
                return app
        for app in apps:
            haystack = normalize(f"{app.desktop_id} {app.generic_name} {app.comment}")
            if needle in haystack:
                return app
        return None

    # -- processos --------------------------------------------------------

    def _processes(self) -> list[dict[str, Any]]:
        result = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline_raw = (entry / "cmdline").read_bytes()
                comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
            except OSError:
                continue
            parts = [part for part in cmdline_raw.split(b"\x00") if part]
            cmdline = [part.decode("utf-8", "replace") for part in parts]
            if not cmdline:
                continue
            # Alguns programas (Firefox, por exemplo) reescrevem o título do
            # processo com espaços em vez de NUL. O executável é o primeiro
            # token da linha de comando original.
            first = cmdline[0].split()[0] if cmdline[0].split() else cmdline[0]
            result.append(
                {
                    "pid": int(entry.name),
                    "comm": comm,
                    "cmdline": cmdline,
                    "exe": Path(first).name,
                }
            )
        return result

    def _app_tokens(self, app: DesktopApp) -> set[str]:
        tokens = {normalize(app.name), normalize(app.desktop_id.removesuffix(".desktop"))}
        # Apenas o executável (argv[0]) identifica o processo. Argumentos como
        # "run", "launch" ou "app" são genéricos e causariam falsos positivos.
        parts = [part for part in app.exec_line.split() if part and "=" not in part]
        if parts:
            base = Path(parts[0]).name
            if base and base.lower() not in IGNORED_EXEC:
                tokens.add(normalize(base))
        return {token for token in tokens if len(token) >= 3}

    def running_pids(self, app: DesktopApp) -> list[int]:
        """Encontra PIDs do aplicativo sem confundir launchers genéricos.

        A primeira regra compara apenas nomes de processo (comm/exe/argv[0]).
        A segunda aceita trechos longos ou com espaço (ids de Flatpak) na linha
        de comando completa, nunca palavras genéricas como "run" ou "flatpak".
        """
        tokens = self._app_tokens(app)
        if not tokens:
            return []
        pids: list[int] = []
        for process in self._processes():
            names = {normalize(process["comm"]), normalize(process["exe"])}
            matched = any(
                token == name or (len(name) >= 4 and token in name)
                for token in tokens
                for name in names
            )
            if not matched:
                commandline = normalize(" ".join(process["cmdline"]))
                # Somente nomes compostos/ids (com espaço) são específicos o
                # bastante para buscar na linha de comando completa. Palavras
                # soltas como "browser" aparecem em processos não relacionados.
                matched = any(
                    " " in token and len(token) >= 6 and token in commandline
                    for token in tokens
                )
            if matched:
                pids.append(process["pid"])
        return sorted(set(pids))

    def _all_running(self, limit: int = 30) -> list[dict[str, Any]]:
        apps = self.discover()
        running = []
        for app in apps:
            pids = self.running_pids(app)
            if pids:
                running.append({"name": app.name, "id": app.desktop_id, "pids": pids})
            if len(running) >= limit:
                break
        return running

    # -- ações ------------------------------------------------------------

    async def launch(self, name: str) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("O controle de aplicativos está desativado.")
        app = self.find(name)
        if app is None:
            raise RuntimeError(f"Aplicativo não encontrado: {name}")
        if self.running_pids(app):
            return {
                "ok": True,
                "already_running": True,
                "app": app.name,
                "message": f"{app.name} já está aberto.",
            }
        command = app.launch_command
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            await asyncio.sleep(0.6)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Comando de abertura indisponível: {command[0]}") from exc
        if proc.returncode not in (None, 0):
            detail = (await proc.stderr.read()).decode("utf-8", "ignore")[-300:]
            raise RuntimeError(f"Não foi possível abrir {app.name}: {detail.strip()}")
        self._launched.setdefault(app.desktop_id, []).append(proc.pid)
        return {
            "ok": True,
            "app": app.name,
            "id": app.desktop_id,
            "message": f"{app.name} aberto.",
        }

    async def close(self, name: str, force: bool = False) -> dict[str, Any]:
        if not self.allow_close:
            raise RuntimeError("Fechar aplicativos está desativado na configuração.")
        app = self.find(name)
        if app is None:
            raise RuntimeError(f"Aplicativo não encontrado: {name}")
        pids = self.running_pids(app)
        if not pids:
            return {"ok": True, "app": app.name, "message": f"{app.name} não está aberto."}
        for pid in pids:
            if pid == os.getpid() or _comm(pid) in CRITICAL_PROCESSES:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                log.warning("Sem permissão para encerrar PID %s", pid)
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            if not any(_alive(pid) for pid in pids):
                break
            await asyncio.sleep(0.2)
        remaining = [pid for pid in pids if _alive(pid)]
        if remaining and force:
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        return {
            "ok": not remaining,
            "app": app.name,
            "pids": pids,
            "remaining": remaining,
            "message": (
                f"{app.name} fechado."
                if not remaining
                else f"{app.name} recebeu pedido de fechamento, mas ainda há processos ativos."
            ),
        }

    # -- janelas ----------------------------------------------------------

    def list_windows(self) -> dict[str, Any]:
        wmctrl = shutil.which("wmctrl")
        if not wmctrl:
            return {
                "windows": [],
                "available": False,
                "message": "wmctrl não está instalado; listagem de janelas indisponível.",
            }
        try:
            import subprocess

            output = subprocess.run(
                [wmctrl, "-l"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            return {"windows": [], "available": False, "message": f"Falha ao listar janelas: {exc}"}
        windows = []
        for line in output.splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 4:
                windows.append(
                    {"id": parts[0], "desktop": parts[1], "host": parts[2], "title": parts[3]}
                )
        return {"windows": windows, "available": bool(windows), "session": os.environ.get("XDG_SESSION_TYPE", "")}

    def foreground(self) -> dict[str, Any]:
        xdotool = shutil.which("xdotool")
        if xdotool:
            try:
                import subprocess

                title = subprocess.run(
                    [xdotool, "getactivewindow", "getwindowname"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                ).stdout.strip()
                if title:
                    return {"ok": True, "title": title}
            except (OSError, subprocess.SubprocessError):
                pass
        return {
            "ok": False,
            "message": (
                "Não foi possível identificar a janela em primeiro plano. "
                "No Wayland isso depende do compositor; instale xdotool apenas se usar X11."
            ),
        }

    def _window_action(self, name: str, action: str) -> dict[str, Any]:
        wmctrl = shutil.which("wmctrl")
        if not wmctrl:
            return {
                "ok": False,
                "message": "wmctrl não está instalado; controle de janelas indisponível.",
            }
        flags = {
            "minimize": "add,hidden",
            "maximize": "add,maximized_vert,maximized_horz",
            "restore": "remove,hidden",
        }
        flag = flags.get(action)
        if flag is None:
            return {"ok": False, "message": f"Ação de janela desconhecida: {action}"}
        try:
            import subprocess

            result = subprocess.run(
                [wmctrl, "-r", name, "-b", flag],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "message": f"Falha ao controlar janela: {exc}"}
        if result.returncode != 0:
            return {
                "ok": False,
                "message": (
                    f"Não foi possível {action} a janela '{name}'. "
                    f"No Wayland, o controle depende do suporte do compositor. {result.stderr.strip()}"
                ),
            }
        return {"ok": True, "window": name, "action": action}

    def minimize(self, name: str) -> dict[str, Any]:
        return self._window_action(name, "minimize")

    def maximize(self, name: str) -> dict[str, Any]:
        return self._window_action(name, "maximize")

    def restore(self, name: str) -> dict[str, Any]:
        return self._window_action(name, "restore")

    def list_running(self) -> dict[str, Any]:
        return {"apps": self._all_running()}


def _comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
