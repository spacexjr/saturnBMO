"""Ferramentas de música expostas ao LLM via function calling do Ollama.

As ferramentas não executam comandos de shell. Cada uma chama métodos
validados do :class:`~bmo_backend.music.manager.MusicManager`, que por sua vez
fala com o Mopidy via JSON-RPC e com o YouTube Music via ytmusicapi.
"""

from __future__ import annotations

from typing import Any

from .manager import MusicManager


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _string(description: str, enum: list[str] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"type": "string", "description": description}
    if enum:
        data["enum"] = enum
    return data


def _pick(args: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        value = args.get(name)
        if value not in (None, ""):
            return value
    return default


def build_music_tools(music: MusicManager) -> list[dict[str, Any]]:
    """Devolve especificações no formato aceito por ``ToolRegistry._add``.

    Os adaptadores abaixo aceitam sinônimos comuns que modelos pequenos
    inventam (``type``/``kind`` no lugar de ``filter``, ``id`` no lugar de
    ``track_id``). Eles apenas normalizam a chamada; a validação real continua
    no :class:`MusicManager`.
    """

    async def search_tool(
        query: str = "",
        filter: str = "songs",
        limit: int | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        query = _pick({"query": query, **extra}, "query", "q", "term", "text", default="")
        filter = _pick(
            {"filter": filter, **extra}, "filter", "type", "kind", "category", default="songs"
        )
        allowed = {"songs", "artists", "albums", "playlists", "all"}
        filter = str(filter).lower()
        if filter not in allowed:
            filter = "songs"
        raw_limit = _pick({"limit": limit, **extra}, "limit", "max_results", default=None)
        try:
            limit_value = int(raw_limit) if raw_limit is not None else None
        except (TypeError, ValueError):
            limit_value = None
        return await music.search(str(query), filter=filter, limit=limit_value)

    async def _resolve_track(value: str, query: str) -> tuple[str, str]:
        """Resolve um id direto ou pesquisa a melhor faixa para o texto livre."""
        value = value.strip()
        if value:
            return value, ""
        query = query.strip()
        if not query:
            raise ValueError(
                "Informe track_id (id de music_search) ou query (nome da música)."
            )
        found = await music.search(query, filter="songs", limit=5)
        results = found.get("results") or []
        if not results:
            raise ValueError(f"Nenhuma música encontrada para '{query}'.")
        best = results[0]
        track_id = str(best.get("id") or best.get("video_id") or "").strip()
        if not track_id:
            raise ValueError("A busca não retornou um id de faixa utilizável.")
        return track_id, str(best.get("title") or query)

    async def play_tool(
        track_id: str = "", query: str = "", **extra: Any
    ) -> dict[str, Any]:
        value = _pick(
            {"track_id": track_id, **extra},
            "track_id",
            "id",
            "video_id",
            "videoId",
            "uri",
            default="",
        )
        text = _pick(
            {"query": query, **extra}, "query", "q", "name", "title", default=""
        )
        resolved, matched_title = await _resolve_track(str(value), str(text))
        data = await music.play(resolved)
        if matched_title:
            data["matched_query"] = matched_title
        return data

    async def queue_add_tool(
        track_id: str = "", query: str = "", **extra: Any
    ) -> dict[str, Any]:
        value = _pick(
            {"track_id": track_id, **extra},
            "track_id",
            "id",
            "video_id",
            "videoId",
            "uri",
            default="",
        )
        text = _pick(
            {"query": query, **extra}, "query", "q", "name", "title", default=""
        )
        resolved, matched_title = await _resolve_track(str(value), str(text))
        data = await music.queue_add(resolved)
        if matched_title:
            data["matched_query"] = matched_title
        return data

    async def set_volume_tool(volume: Any = None, **extra: Any) -> dict[str, Any]:
        value = _pick(
            {"volume": volume, **extra},
            "volume",
            "level",
            "percent",
            "value",
            default=None,
        )
        if value is None:
            raise ValueError("O campo volume é obrigatório (0 a 100).")
        number = float(value)
        if 0 < number <= 1 and not isinstance(value, int):
            number *= 100
        return await music.set_volume(int(round(number)))

    async def queue_remove_tool(index: Any = None, **extra: Any) -> dict[str, Any]:
        value = _pick(
            {"index": index, **extra}, "index", "position", "item", default=None
        )
        if value is None:
            raise ValueError("O campo index é obrigatório.")
        return await music.queue_remove(int(value))

    async def playlist_play_tool(playlist_id: str = "", **extra: Any) -> dict[str, Any]:
        value = _pick(
            {"playlist_id": playlist_id, **extra},
            "playlist_id",
            "id",
            "browse_id",
            "browseId",
            default="",
        )
        if not str(value).strip():
            raise ValueError("O campo playlist_id é obrigatório.")
        return await music.playlist_play(str(value).strip())

    def spec(
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Any,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "description": description,
            "parameters": parameters,
            "handler": handler,
            "activity": "playing_music",
        }

    return [
        spec(
            "music_search",
            "Pesquisa no YouTube Music e devolve faixas, artistas, álbuns ou playlists "
            "com identificador, título, artista e duração. Não toca nada. Use o campo id "
            "de uma música em music_play ou music_queue_add. Se o usuário pediu para "
            "tocar, chame music_play logo depois desta busca com o resultado mais "
            "relevante; não encerre a resposta apenas listando resultados.",
            _object(
                {
                    "query": _string("Nome da música, artista, álbum ou playlist."),
                    "filter": _string(
                        "Tipo de resultado desejado.",
                        ["songs", "artists", "albums", "playlists", "all"],
                    ),
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "Número máximo de resultados.",
                    },
                },
                ["query"],
            ),
            search_tool,
        ),
        spec(
            "music_play",
            "Toca uma música agora e substitui a fila atual. Para pedidos como "
            "'toque Bohemian Rhapsody', passe query com o nome pedido; não use "
            "music_search antes nem music_queue_add no lugar desta ferramenta. "
            "Também aceita track_id de music_search. Só afirme que a música começou "
            "depois que o resultado tiver verified=true.",
            _object(
                {
                    "track_id": _string("Id/videoId da faixa (opcional se usar query)."),
                    "query": _string("Nome da música ou artista para tocar diretamente."),
                }
            ),
            play_tool,
        ),
        spec(
            "music_pause",
            "Pausa a reprodução atual no Mopidy.",
            _object({}),
            music.pause,
        ),
        spec(
            "music_resume",
            "Retoma a reprodução que estava pausada.",
            _object({}),
            music.resume,
        ),
        spec(
            "music_stop",
            "Para a reprodução atual.",
            _object({}),
            music.stop,
        ),
        spec(
            "music_next",
            "Avança para a próxima faixa da fila.",
            _object({}),
            music.next,
        ),
        spec(
            "music_previous",
            "Volta para a faixa anterior da fila.",
            _object({}),
            music.previous,
        ),
        spec(
            "music_set_volume",
            "Define o volume do player em porcentagem, de 0 a 100.",
            _object(
                {
                    "volume": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                        "description": "Volume em porcentagem.",
                    }
                },
                ["volume"],
            ),
            set_volume_tool,
        ),
        spec(
            "music_get_volume",
            "Consulta o volume atual em porcentagem.",
            _object({}),
            music.get_volume,
        ),
        spec(
            "music_get_state",
            "Consulta o estado real do Mopidy: tocando, pausado, parado, volume, "
            "posição, fila e faixa atual.",
            _object({}),
            music.get_state,
        ),
        spec(
            "music_get_now_playing",
            "Informa a música que está tocando agora, com título, artista, álbum, "
            "capa, posição e duração.",
            _object({}),
            music.now_playing,
        ),
        spec(
            "music_queue_add",
            "Adiciona uma faixa à fila sem interromper a música atual. Use somente "
            "quando o usuário pedir para adicionar à fila, não para tocar agora.",
            _object(
                {
                    "track_id": _string("Id/videoId da faixa (opcional se usar query)."),
                    "query": _string("Nome da música para pesquisar e adicionar."),
                }
            ),
            queue_add_tool,
        ),
        spec(
            "music_queue_remove",
            "Remove um item da fila pelo índice (começando em 0) informado por music_queue_list.",
            _object(
                {
                    "index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Índice do item na fila.",
                    }
                },
                ["index"],
            ),
            queue_remove_tool,
        ),
        spec(
            "music_queue_clear",
            "Esvazia a fila de reprodução.",
            _object({}),
            music.queue_clear,
        ),
        spec(
            "music_queue_list",
            "Lista a fila atual com índice, título, artista e duração.",
            _object({}),
            music.queue_list,
        ),
        spec(
            "music_playlist_list",
            "Lista as playlists pessoais do YouTube Music. Exige autenticação configurada.",
            _object(
                {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Número máximo de playlists.",
                    }
                }
            ),
            music.playlist_list,
        ),
        spec(
            "music_playlist_play",
            "Toca uma playlist do YouTube Music pelo id retornado por music_playlist_list "
            "ou music_search.",
            _object(
                {"playlist_id": _string("Id/browseId da playlist.")},
                ["playlist_id"],
            ),
            playlist_play_tool,
        ),
        spec(
            "music_liked_songs",
            "Lista as músicas curtidas do usuário. Use play=true para tocar todas. "
            "Exige autenticação configurada.",
            _object(
                {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500,
                        "description": "Número máximo de músicas.",
                    },
                    "play": {
                        "type": "boolean",
                        "description": "Se verdadeiro, toca as músicas curtidas.",
                    },
                }
            ),
            music.liked_songs,
        ),
    ] + _mopidy_aliases(music, play_tool, queue_add_tool, search_tool)


def _mopidy_aliases(
    music: MusicManager, play_tool: Any, queue_add_tool: Any, search_tool: Any
) -> list[dict[str, Any]]:
    """Nomes explícitos do Mopidy, equivalentes às ferramentas music_*.

    Existem para que o modelo atenda pedidos como "estado do Mopidy",
    "pesquise no Mopidy" e "limpe a fila do Mopidy" sem confundir o player
    com o BitChord legado.
    """

    async def status_tool() -> dict[str, Any]:
        info = await music.status()
        try:
            info["playback"] = await music.get_state()
        except Exception as exc:  # noqa: BLE001 - status não deve falhar inteiro
            info["playback_error"] = str(exc)
        return info

    def spec(
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Any,
        *,
        timeout_s: float = 45.0,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "description": description,
            "parameters": parameters,
            "handler": handler,
            "activity": "playing_music",
            "timeout_s": timeout_s,
        }

    return [
        spec(
            "mopidy_start",
            "Inicia o serviço Mopidy no PC (systemctl --user), sem sudo, e confirma "
            "que ele responde. Use só quando o usuário pedir para iniciar ou quando "
            "o player estiver comprovadamente indisponível.",
            _object({}),
            music.start,
            timeout_s=40.0,
        ),
        spec(
            "mopidy_status",
            "Consulta o estado do serviço Mopidy e da reprodução: tocando, pausado, "
            "parado, faixa atual, volume, posição e fila.",
            _object({}),
            status_tool,
        ),
        spec(
            "mopidy_now_playing",
            "Informa a música atual do Mopidy com título, artista, álbum, posição e duração.",
            _object({}),
            music.now_playing,
        ),
        spec(
            "mopidy_play",
            "Toca uma música no Mopidy. Passe query com o nome pedido ou track_id de "
            "mopidy_search. Só confirme depois de verified=true.",
            _object(
                {
                    "track_id": _string("Id da faixa (opcional se usar query)."),
                    "query": _string("Nome da música ou artista."),
                }
            ),
            play_tool,
        ),
        spec("mopidy_pause", "Pausa a reprodução do Mopidy.", _object({}), music.pause),
        spec(
            "mopidy_resume",
            "Retoma a reprodução pausada do Mopidy.",
            _object({}),
            music.resume,
        ),
        spec("mopidy_stop", "Para a reprodução do Mopidy.", _object({}), music.stop),
        spec("mopidy_next", "Avança para a próxima faixa do Mopidy.", _object({}), music.next),
        spec(
            "mopidy_previous",
            "Volta para a faixa anterior do Mopidy.",
            _object({}),
            music.previous,
        ),
        spec(
            "mopidy_seek",
            "Move a reprodução do Mopidy para uma posição em milissegundos.",
            _object(
                {
                    "position_ms": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Posição desejada em milissegundos.",
                    }
                },
                ["position_ms"],
            ),
            music.seek,
        ),
        spec(
            "mopidy_set_volume",
            "Define o volume do Mopidy em porcentagem de 0 a 100.",
            _object(
                {
                    "volume": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                        "description": "Volume em porcentagem.",
                    }
                },
                ["volume"],
            ),
            music.set_volume,
        ),
        spec(
            "mopidy_get_volume",
            "Consulta o volume atual do Mopidy.",
            _object({}),
            music.get_volume,
        ),
        spec(
            "mopidy_search",
            "Pesquisa faixas, artistas, álbuns ou playlists para o Mopidy. Não toca nada.",
            _object(
                {
                    "query": _string("Nome da música, artista, álbum ou playlist."),
                    "filter": _string(
                        "Tipo de resultado.",
                        ["songs", "artists", "albums", "playlists", "all"],
                    ),
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                ["query"],
            ),
            search_tool,
        ),
        spec(
            "mopidy_add_to_queue",
            "Adiciona uma faixa à fila do Mopidy sem interromper a música atual.",
            _object(
                {
                    "track_id": _string("Id da faixa."),
                    "query": _string("Nome para pesquisar e adicionar."),
                }
            ),
            queue_add_tool,
        ),
        spec(
            "mopidy_get_queue",
            "Lista a fila atual do Mopidy com índice, título, artista e duração.",
            _object({}),
            music.queue_list,
        ),
        spec(
            "mopidy_clear_queue",
            "Esvazia a fila do Mopidy.",
            _object({}),
            music.queue_clear,
        ),
    ]
