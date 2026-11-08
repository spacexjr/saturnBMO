"""Informações seguras do sistema para o BMO.

Não há execução arbitrária de comandos. Os dados vêm de ``/proc``,
``shutil``, ``platform`` e de uma lista explicitamente permitida de serviços
``systemd --user``.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import socket
import time
from pathlib import Path
from typing import Any


class SystemInfoError(RuntimeError):
    pass


class SystemInfo:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.allowed_services = list(config.get("allowed_services", []))
        self._last_cpu: tuple[int, int] | None = None

    def status(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "allowed_services": self.allowed_services}

    async def get(self, section: str = "resumo") -> dict[str, Any]:
        if not self.enabled:
            raise SystemInfoError("As ferramentas de sistema estão desativadas.")
        key = (section or "resumo").strip().lower()
        if key in {"resumo", "tudo", "all", "status"}:
            return {
                "system": self._system(),
                "cpu": await self._cpu(),
                "memory": self._memory(),
                "disk": self._disk(),
                "network": self._network(),
            }
        if key in {"cpu", "processador"}:
            return await self._cpu()
        if key in {"memoria", "memória", "ram", "memory"}:
            return self._memory()
        if key in {"disco", "disk", "armazenamento"}:
            return self._disk()
        if key in {"sistema", "system", "os"}:
            return self._system()
        if key in {"rede", "network", "ip"}:
            return self._network()
        if key in {"processos", "processes", "top"}:
            return self._top_processes()
        if key in {"servicos", "serviços", "services"}:
            return await self._services()
        raise SystemInfoError(
            "Seção desconhecida. Use resumo, cpu, memoria, disco, sistema, rede, "
            "processos ou servicos."
        )

    def _system(self) -> dict[str, Any]:
        return {
            "os": platform.platform(),
            "distribution": _read_text("/etc/os-release").replace("\n", " ")[:300],
            "kernel": platform.release(),
            "machine": platform.machine(),
            "hostname": socket.gethostname(),
            "uptime_s": int(float(_read_text("/proc/uptime").split()[0] or 0)),
            "session": os.environ.get("XDG_SESSION_TYPE", "desconhecido"),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "desconhecido"),
        }

    async def _cpu(self) -> dict[str, Any]:
        first = _cpu_times()
        await asyncio.sleep(0.25)
        second = _cpu_times()
        usage = None
        if first and second:
            total = second[0] - first[0]
            idle = second[1] - first[1]
            if total > 0:
                usage = round((1.0 - idle / total) * 100.0, 1)
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        return {
            "cores": os.cpu_count(),
            "usage_percent": usage,
            "load_1m": round(load[0], 2),
            "load_5m": round(load[1], 2),
            "load_15m": round(load[2], 2),
            "model": _cpu_model(),
        }

    def _memory(self) -> dict[str, Any]:
        data: dict[str, int] = {}
        for line in _read_text("/proc/meminfo").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    data[parts[0].rstrip(":")] = int(parts[1]) * 1024
                except ValueError:
                    pass
        total = data.get("MemTotal", 0)
        available = data.get("MemAvailable", data.get("MemFree", 0))
        used = max(0, total - available)
        swap_total = data.get("SwapTotal", 0)
        swap_free = data.get("SwapFree", 0)
        return {
            "total_gb": round(total / 1024**3, 2),
            "used_gb": round(used / 1024**3, 2),
            "available_gb": round(available / 1024**3, 2),
            "usage_percent": round(used / total * 100.0, 1) if total else None,
            "swap_total_gb": round(swap_total / 1024**3, 2),
            "swap_used_gb": round((swap_total - swap_free) / 1024**3, 2),
        }

    def _disk(self) -> dict[str, Any]:
        home = Path.home()
        usage = shutil.disk_usage(home)
        return {
            "path": str(home),
            "total_gb": round(usage.total / 1024**3, 2),
            "used_gb": round(usage.used / 1024**3, 2),
            "free_gb": round(usage.free / 1024**3, 2),
            "usage_percent": round(usage.used / usage.total * 100.0, 1) if usage.total else None,
        }

    def _network(self) -> dict[str, Any]:
        addresses = []
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                address = info[4][0]
                if address not in addresses:
                    addresses.append(address)
        except socket.gaierror:
            pass
        return {
            "hostname": socket.gethostname(),
            "addresses": addresses[:8],
            "interfaces": sorted(
                name for name in os.listdir("/sys/class/net")
                if name != "lo"
            ) if Path("/sys/class/net").is_dir() else [],
        }

    def _top_processes(self, limit: int = 10) -> dict[str, Any]:
        processes = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
                status = (entry / "status").read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rss = 0
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    try:
                        rss = int(line.split()[1]) * 1024
                    except (IndexError, ValueError):
                        pass
                    break
            if comm:
                processes.append({"pid": int(entry.name), "name": comm, "rss_mb": round(rss / 1024**2, 1)})
        processes.sort(key=lambda item: item["rss_mb"], reverse=True)
        return {"processes": processes[: max(1, min(limit, 30))]}

    async def _services(self) -> dict[str, Any]:
        if not self.allowed_services:
            return {
                "services": [],
                "message": "Nenhum serviço foi autorizado na configuração.",
            }
        if not shutil.which("systemctl"):
            raise SystemInfoError("systemctl não está disponível.")
        results = []
        for unit in self.allowed_services:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "is-active", unit,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            results.append(
                {
                    "unit": unit,
                    "active": stdout.decode("utf-8", "ignore").strip() == "active",
                    "state": stdout.decode("utf-8", "ignore").strip(),
                }
            )
        return {"services": results}


def _read_text(path: str, limit: int = 200_000) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def _cpu_times() -> tuple[int, int] | None:
    line = _read_text("/proc/stat").splitlines()
    if not line:
        return None
    parts = line[0].split()
    if not parts or parts[0] != "cpu":
        return None
    values = [int(value) for value in parts[1:] if value.isdigit()]
    if len(values) < 4:
        return None
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


def _cpu_model() -> str:
    for line in _read_text("/proc/cpuinfo").splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or "desconhecido"
