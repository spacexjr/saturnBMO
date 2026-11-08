"""Integração com o BitChord 1.8 (e outros players) via MPRIS.

A descoberta é dinâmica pelo barramento D-Bus do usuário. Não presumimos que o
serviço se chama ``bitchord``: procuramos qualquer ``org.mpris.MediaPlayer2.*``
e priorizamos aquele cujo nome contém ``bitchord``. O controle usa ``playerctl``,
que fala MPRIS diretamente e funciona tanto em X11 quanto em Wayland.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("bmo.media")


class MediaError(RuntimeError):
    pass


@dataclass
class PlayerInfo:
    name: str
    identity: str = ""


class MediaService:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.preferred = [item.lower() for item in config.get("preferred_players", ["bitchord"])]
        self.timeout_s = float(config.get("timeout_s", 8))
        self.playerctl = shutil.which("playerctl")
        self.busctl = shutil.which("busctl")

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "playerctl": bool(self.playerctl),
            "mpris": bool(self.busctl or self.playerctl),
        }

    async def _run(self, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise MediaError("O player demorou demais para responder.") from exc
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", "replace").strip(),
            stderr.decode("utf-8", "replace").strip(),
        )

    async def players(self) -> list[PlayerInfo]:
        if not self.enabled:
            return []
        names: list[str] = []
        if self.busctl:
            code, out, _ = await self._run(self.busctl, "--user", "list", "--no-legend")
            if code == 0:
                for line in out.splitlines():
                    parts = line.split()
                    if not parts:
                        continue
                    bus_name = parts[0]
                    prefix = "org.mpris.MediaPlayer2."
                    if bus_name.startswith(prefix):
                        name = bus_name[len(prefix):]
                        if name and name not in names:
                            names.append(name)
        if not names and self.playerctl:
            code, out, _ = await self._run(self.playerctl, "-l")
            if code == 0:
                names = [line.strip() for line in out.splitlines() if line.strip()]
        players = []
        for name in names:
            identity = name
            if self.playerctl:
                code, out, _ = await self._run(
                    self.playerctl, "-p", name, "metadata", "--format", "{{playerName}}"
                )
                if code == 0 and out:
                    identity = name
            players.append(PlayerInfo(name=name, identity=identity))
        return players

    def _choose(self, players: list[PlayerInfo]) -> PlayerInfo | None:
        if not players:
            return None
        for preferred in self.preferred:
            for player in players:
                if preferred in player.name.lower():
                    return player
        for player in players:
            if player.name.lower() not in {"playerctld"}:
                return player
        return players[0]

    async def _target(self) -> PlayerInfo:
        if not self.playerctl:
            raise MediaError("playerctl não está instalado; controle de mídia indisponível.")
        player = self._choose(await self.players())
        if player is None:
            raise MediaError("Nenhum player MPRIS ativo. Abra o BitChord primeiro.")
        return player

    async def current(self) -> dict[str, Any]:
        player = await self._target()
        code, status, error = await self._run(self.playerctl, "-p", player.name, "status")
        if code != 0:
            raise MediaError(error or "Não foi possível consultar o estado do player.")
        code, data, _ = await self._run(
            self.playerctl,
            "-p",
            player.name,
            "metadata",
            "--format",
            "{{artist}}\u001f{{title}}\u001f{{album}}\u001f{{mpris:length}}\u001f{{mpris:artUrl}}",
        )
        parts = (data.split("\u001f") + ["", "", "", "", ""])[:5]
        artist, title, album, length, art = parts
        length_s = None
        try:
            length_s = round(int(length) / 1_000_000, 1) if length else None
        except ValueError:
            pass
        volume = None
        if self.playerctl:
            code, out, _ = await self._run(self.playerctl, "-p", player.name, "volume")
            if code == 0:
                try:
                    volume = round(float(out), 2)
                except ValueError:
                    pass
        capabilities = {
            "play": True,
            "pause": True,
            "next": True,
            "previous": True,
            "volume": volume is not None,
            "search": False,
        }
        return {
            "player": player.name,
            "is_bitchord": "bitchord" in player.name.lower(),
            "status": status.lower(),
            "title": title,
            "artist": artist,
            "album": album,
            "length_s": length_s,
            "art_url": art,
            "volume": volume,
            "capabilities": capabilities,
        }

    async def control(self, action: str, value: float | None = None) -> dict[str, Any]:
        player = await self._target()
        normalized = (action or "").strip().lower()
        mapping = {
            "play": "play",
            "tocar": "play",
            "iniciar": "play",
            "continuar": "play",
            "retomar": "play",
            "despausar": "play",
            "resume": "play",
            "pause": "pause",
            "pausar": "pause",
            "pausa": "pause",
            "parar": "pause",
            "pare": "pause",
            "playpause": "play-pause",
            "play_pause": "play-pause",
            "toggle": "play-pause",
            "alternar": "play-pause",
            "next": "next",
            "proximo": "next",
            "próximo": "next",
            "avancar": "next",
            "avançar": "next",
            "pular": "next",
            "previous": "previous",
            "anterior": "previous",
            "voltar": "previous",
            "stop": "stop",
            "encerrar": "stop",
        }
        volume_actions = {
            "volume",
            "volume_set",
            "definir_volume",
            "volume_up",
            "aumentar_volume",
            "aumentar",
            "mais_volume",
            "volume_down",
            "diminuir_volume",
            "diminuir",
            "menos_volume",
        }
        args: list[str] = [self.playerctl or "playerctl", "-p", player.name]
        command: str | None = None
        if normalized in volume_actions:
            current = await self.current()
            current_volume = float(current.get("volume") or 0.5)
            if normalized in {"volume", "volume_set", "definir_volume"}:
                target = max(0.0, min(1.0, float(value if value is not None else current_volume)))
            elif normalized in {"volume_up", "aumentar_volume", "aumentar", "mais_volume"}:
                target = min(1.0, current_volume + (value or 0.1))
            else:
                target = max(0.0, current_volume - (value or 0.1))
            args.extend(["volume", f"{target:.2f}"])
        else:
            command = mapping.get(normalized)
            if command is None:
                raise MediaError(f"Ação de mídia não suportada: {action}")
            args.append(command)
        code, out, error = await self._run(*args)
        if code != 0 and command in {"play", "pause"}:
            # Alguns players (incluindo versões do BitChord) só implementam
            # PlayPause. Usa o estado atual para não inverter a reprodução.
            try:
                status = str((await self.current()).get("status", "")).lower()
            except MediaError:
                status = ""
            should_toggle = (
                (command == "play" and status in {"paused", "stopped"})
                or (command == "pause" and status == "playing")
            )
            if should_toggle:
                code, out, error = await self._run(
                    self.playerctl or "playerctl", "-p", player.name, "play-pause"
                )
        if code != 0:
            raise MediaError(error or f"O player recusou a ação {action}.")
        state = await self.current()
        state.update(
            {
                "ok": True,
                "action": normalized,
                "message": f"Ação {normalized} enviada ao player.",
            }
        )
        return state

    async def search_and_play(self, query: str) -> dict[str, Any]:
        raise MediaError(
            "O BitChord 1.8 não expõe pesquisa de músicas pelo MPRIS. "
            "Posso abrir, pausar, retomar, avançar, voltar e controlar o volume, "
            "mas não consigo pesquisar faixas por voz por uma interface pública."
        )
