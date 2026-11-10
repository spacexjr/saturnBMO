"""Cliente assíncrono da API JSON-RPC do Mopidy.

O Mopidy é o único player de áudio usado pelo BMO. Este módulo fala apenas com
o endpoint JSON-RPC local (por padrão ``http://127.0.0.1:6680/mopidy/rpc``) e
não expõe essa porta para a rede. Nenhum comando de shell é executado.
"""

from __future__ import annotations

import itertools
import logging
from typing import Any

import httpx

log = logging.getLogger("bmo.music.mopidy")


class MopidyError(RuntimeError):
    """Falha de comunicação ou erro devolvido pelo Mopidy."""


class MopidyUnavailable(MopidyError):
    """O Mopidy não está acessível no endereço configurado."""


class MopidyTimeout(MopidyError):
    """O Mopidy demorou para responder, mas o comando pode ter sido aceito."""


class MopidyClient:
    def __init__(
        self,
        rpc_url: str,
        *,
        timeout_s: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.rpc_url = rpc_url
        self.timeout_s = float(timeout_s)
        self._ids = itertools.count(1)
        self._client: httpx.AsyncClient | None = client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s, connect=min(5.0, self.timeout_s)),
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def call(self, method: str, **params: Any) -> Any:
        if not method.startswith("core."):
            raise MopidyError(f"Método JSON-RPC não permitido: {method}")
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
            "params": params,
        }
        try:
            response = await self._http().post(self.rpc_url, json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise MopidyUnavailable(
                f"Mopidy não está acessível em {self.rpc_url}. "
                "Inicie o serviço e confira music.mopidy.rpc_url."
            ) from exc
        except httpx.TimeoutException as exc:
            raise MopidyTimeout("O Mopidy demorou demais para responder.") from exc
        except httpx.HTTPError as exc:
            raise MopidyError(f"Erro de rede ao falar com o Mopidy: {exc}") from exc
        if response.status_code >= 400:
            raise MopidyError(
                f"O Mopidy respondeu HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise MopidyError("O Mopidy devolveu uma resposta JSON inválida.") from exc
        if not isinstance(data, dict):
            raise MopidyError("Resposta JSON-RPC inválida do Mopidy.")
        error = data.get("error")
        if error:
            if isinstance(error, dict):
                message = str(error.get("message") or "erro desconhecido")
                code = error.get("code")
                raise MopidyError(f"Mopidy recusou {method}: {message} (código {code}).")
            raise MopidyError(f"Mopidy recusou {method}: {error}")
        return data.get("result")

    # -- descoberta e estado -------------------------------------------------

    async def version(self) -> str:
        return str(await self.call("core.get_version") or "")

    async def uri_schemes(self) -> list[str]:
        result = await self.call("core.get_uri_schemes")
        return [str(item) for item in result or []]

    async def playback_state(self) -> str:
        result = await self.call("core.playback.get_state")
        return str(result or "stopped").lower()

    async def current_track(self) -> dict[str, Any] | None:
        result = await self.call("core.playback.get_current_track")
        return result if isinstance(result, dict) else None

    async def time_position(self) -> int:
        result = await self.call("core.playback.get_time_position")
        try:
            return max(0, int(result or 0))
        except (TypeError, ValueError):
            return 0

    async def _mixer_call(self, method: str, **params: Any) -> Any:
        """Usa ``core.mixer`` (Mopidy 4) com fallback para ``core.playback`` (Mopidy 3)."""
        try:
            return await self.call(method, **params)
        except MopidyError as exc:
            if "not found" not in str(exc).lower():
                raise
            fallback = method.replace("core.mixer.", "core.playback.")
            return await self.call(fallback, **params)

    async def volume(self) -> int | None:
        result = await self._mixer_call("core.mixer.get_volume")
        try:
            return int(result)
        except (TypeError, ValueError):
            return None

    async def set_volume(self, volume: int) -> None:
        await self._mixer_call("core.mixer.set_volume", volume=int(volume))

    # -- transporte ----------------------------------------------------------

    async def play(self, tlid: int | None = None) -> None:
        if tlid is None:
            await self.call("core.playback.play")
        else:
            await self.call("core.playback.play", tlid=int(tlid))

    async def pause(self) -> None:
        await self.call("core.playback.pause")

    async def stop(self) -> None:
        await self.call("core.playback.stop")

    async def next(self) -> None:
        await self.call("core.playback.next")

    async def previous(self) -> None:
        await self.call("core.playback.previous")

    async def seek(self, position_ms: int) -> None:
        await self.call("core.playback.seek", time_position=max(0, int(position_ms)))

    # -- fila ----------------------------------------------------------------

    async def tracklist_tracks(self) -> list[dict[str, Any]]:
        """Lista a fila com ``tlid`` incluído.

        O Mopidy 3 expõe ``get_tracks`` já com ``tlid``; o Mopidy 4 devolve
        apenas objetos ``Track``. ``get_tl_tracks`` é estável nos dois e é
        achatado aqui para manter o mesmo formato usado pela fila do BMO.
        """
        try:
            result = await self.call("core.tracklist.get_tl_tracks")
        except MopidyError as exc:
            if "not found" not in str(exc).lower():
                raise
            result = await self.call("core.tracklist.get_tracks")
        tracks: list[dict[str, Any]] = []
        for item in result or []:
            if not isinstance(item, dict):
                continue
            track = item.get("track")
            if isinstance(track, dict):
                merged = dict(track)
                if item.get("tlid") is not None:
                    merged["tlid"] = item["tlid"]
                tracks.append(merged)
            else:
                tracks.append(item)
        return tracks

    async def tracklist_length(self) -> int:
        try:
            return int(await self.call("core.tracklist.get_length") or 0)
        except (TypeError, ValueError):
            return 0

    async def tracklist_add(
        self, uris: list[str], *, at_position: int | None = None
    ) -> list[dict[str, Any]]:
        if not uris:
            return []
        params: dict[str, Any] = {"uris": uris}
        if at_position is not None:
            params["at_position"] = max(0, int(at_position))
        result = await self.call("core.tracklist.add", **params)
        return [item for item in result or [] if isinstance(item, dict)]

    async def tracklist_remove(self, tlids: list[int]) -> None:
        if not tlids:
            return
        await self.call(
            "core.tracklist.remove", criteria={"tlid": [int(tlid) for tlid in tlids]}
        )

    async def tracklist_clear(self) -> None:
        await self.call("core.tracklist.clear")

    async def tracklist_index(self) -> int | None:
        result = await self.call("core.tracklist.index")
        try:
            return int(result)
        except (TypeError, ValueError):
            return None

    async def tracklist_consume(self) -> bool:
        result = await self.call("core.tracklist.get_consume")
        return bool(result)
