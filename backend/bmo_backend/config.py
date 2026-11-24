"""Carregamento e validação da configuração do backend do BMO."""

from __future__ import annotations

import copy
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {
        "host": "0.0.0.0",
        "port": 8765,
        # Nunca deixe um token fixo no repositório. O token é gerado em data/token.
        "token_env": "BMO_TOKEN",
        "max_ws_message_bytes": 262144,
        "log_level": "INFO",
        "discovery_enabled": True,
        "discovery_port": 8766,
    },
    "llm": {
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen3.5:2b",
        "timeout_s": 180,
        "temperature": 0.5,
        "num_predict": 220,
        "history_messages": 12,
        "think": False,
        "system_prompt": (
            "Você é o BMO, um pequeno robô assistente simpático que mora em um celular. "
            "Fale sempre em português do Brasil, com frases curtas, claras e amigáveis. "
            "Não use emojis nem símbolos; sua resposta será falada em voz alta. "
            "Não invente que executou ações. Você não tem câmera e não tira fotos. "
            "Quando não souber algo, diga que não sabe. "
            "Se o usuário pedir a hora ou a data, o sistema responde antes de você; "
            "não tente adivinhar horários."
        ),
    },
    "stt": {
        # Qwen3-ASR local via Ollama é o mecanismo principal (roda no PC,
        # nunca no Android). Requer: ollama pull frozenlab/qwen3-asr:0.6b
        "engine": "qwen3_asr",
        "model": "frozenlab/qwen3-asr:0.6b",
        "base_url": "http://127.0.0.1:11434",
        "language": "pt-BR",
        "timeout_s": 60,
        "max_audio_s": 55,
        "keep_alive": "10m",
        "num_predict": 256,
        # Fallback opcional e desligado por padrão: se o Qwen falhar, o erro é
        # mostrado ao usuário em vez de ser escondido por outro mecanismo.
        "fallback": {
            "enabled": False,
            "engine": "faster_whisper",
            "model": "small",
            "device": "cpu",
            "compute_type": "int8",
            "language": "pt",
            "beam_size": 5,
            "num_workers": 1,
            "vad_filter": True,
            "condition_on_previous_text": False,
            "cpu_threads": 4,
            "timeout_s": 180,
        },
    },
    "tts": {
        "engine": "auto",
        "piper_binary": "../tools/piper/piper",
        "voice_model": "../tools/voices/pt_BR-faber-medium.onnx",
        "espeak_binary": "espeak-ng",
        "espeak_voice": "pt-br",
        "espeak_speed": 150,
        "timeout_s": 90,
        "max_chars": 1200,
    },
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "frame_ms": 20,
        "vad_min_rms": 0.012,
        "vad_start_ms": 180,
        "vad_end_silence_ms": 700,
        "vad_pre_roll_ms": 300,
        "min_utterance_ms": 350,
        "max_utterance_s": 15,
        # Escuta contínua: o microfone do app permanece ativo e o backend volta
        # sozinho a aguardar a wake word depois de cada resposta.
        "continuous_listening": True,
        # Áudio ignorado logo após o playback para não transcrever o próprio TTS.
        "playback_guard_ms": 600,
        # Fila curta de falas curtas; evita perder uma pergunta se o VAD fechar
        # duas falas quase juntas, sem criar capturas concorrentes.
        "utterance_queue": 4,
    },
    "weather": {
        "enabled": True,
        # Vazio = usa o GPS enviado pelo app. Pode ser preenchido como alternativa manual.
        "location": "",
        # Se informados, servem de alternativa quando o app não enviar coordenadas.
        "latitude": None,
        "longitude": None,
        "timezone": "auto",
        "timeout_s": 10,
        "cache_ttl_s": 600,
    },
    "wakeword": {
        "enabled": True,
        # hybrid = acústico como principal + transcrição como fallback.
        "mode": "hybrid",
        "phrases": [
            "ei bmo",
            "hey bmo",
            "hey beemo",
            "ei beemo",
            "bmo",
            "beemo",
            "bimao",
            "ei bimao",
            "hey bimao",
            "bimo",
            "hey bimo",
            "ei bimo",
            "be mo",
            "bi mo",
            "be eme o",
            "bê ême ó",
            "ei be eme o",
            "hey be eme o",
            "ei abmo",
            "ei mo",
            "ei mô",
            "ei bom",
            "e mo",
            "e bmo",
            "oi bmo",
            "oi beemo",
            "bem o",
            "bemo",
            "abmo",
            "bi emo",
        ],
        "acoustic_model": "../wakeword/saturnbmo.onnx",
        "mel_model": "../wakeword/melspectrogram.onnx",
        "embedding_model": "../wakeword/embedding_model.onnx",
        "threshold": 0.95,
        "cooldown_s": 2.5,
        "hop_ms": 100,
        "min_consecutive": 2,
        "note": (
            "Modelo acústico saturnbmo.onnx (8 h, gen3) treinado com livekit-wakeword. "
            "Threshold 0.95 + 2 janelas consecutivas equilibram recall e falsos positivos. "
            "Em modo hybrid, a transcrição continua como fallback."
        ),
    },
    "music": {
        # YouTube Music (busca/biblioteca) + Mopidy (player/fila) + proxy local.
        "enabled": True,
        "max_queue_items": 200,
        "max_playlist_tracks": 100,
        "mopidy": {
            # Mantenha o Mopidy escutando apenas em 127.0.0.1.
            "rpc_url": "http://127.0.0.1:6680/mopidy/rpc",
            "timeout_s": 20,
            "confirm_timeout_s": 10,
            "service_unit": "mopidy",
            "start_timeout_s": 20,
        },
        "ytmusic": {
            "enabled": True,
            # Arquivo browser.json gerado por `ytmusicapi browser` (fora do Git).
            "auth_file": "data/ytmusic_auth.json",
            # Opcional: cookies do yt-dlp para faixas restritas (fora do Git).
            "cookies_file": "",
            "language": "pt",
            "location": "BR",
            "max_results": 10,
            "timeout_s": 25,
        },
        "stream": {
            "enabled": True,
            # Vazio = http://127.0.0.1:<server.port>. Use o IP do PC se o Mopidy
            # estiver em outra máquina (não recomendado).
            "public_base_url": "",
            "secret_file": "data/music_stream.secret",
            "cache_ttl_s": 1800,
            "timeout_s": 30,
        },
    },
    "security": {
        "allowed_commands": ["get_time", "get_date"],
        "max_text_chars": 1000,
        "audio_cache_ttl_s": 300,
    },
    "tools": {
        "enabled": True,
        "max_tool_steps": 5,
        "allow_private_urls": False,
        "web": {
            "enabled": True,
            "timeout_s": 15,
            "max_results": 5,
            "search_endpoint": "https://html.duckduckgo.com/html/",
        },
        "apps": {
            "enabled": True,
            "allow_close": True,
        },
        "media": {
            "enabled": True,
            "preferred_players": ["bitchord"],
            "timeout_s": 8,
        },
        "system": {
            "enabled": True,
            "allowed_services": ["pipewire", "wireplumber", "ollama"],
        },
        "access_file": "data/access.json",
    },
    "paths": {
        "log_file": "data/bmo-backend.log",
    },
}


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def project_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    return path


def load_config(config_file: str | Path | None = None) -> dict[str, Any]:
    """Carrega config.json e aplica variáveis de ambiente.

    A configuração do repositório não contém segredos. O token é lido de
    BMO_TOKEN ou de data/token.
    """

    env_file = os.environ.get("BMO_CONFIG")
    path = Path(config_file or env_file or (BACKEND_DIR / "config.json"))
    config = copy.deepcopy(DEFAULT_CONFIG)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                user_config = json.load(fh)
            if not isinstance(user_config, dict):
                raise ValueError("o arquivo deve conter um objeto JSON")
            config = _deep_merge(config, user_config)
        except Exception as exc:  # noqa: BLE001 - erro de configuração é reportado ao usuário
            raise SystemExit(f"Erro ao ler {path}: {exc}") from exc

    # Variáveis de ambiente têm precedência e evitam segredos no arquivo.
    env_map = {
        ("server", "host"): "BMO_HOST",
        ("server", "port"): "BMO_PORT",
        ("llm", "base_url"): "BMO_OLLAMA_URL",
        ("llm", "model"): "BMO_LLM_MODEL",
        ("llm", "system_prompt"): "BMO_SYSTEM_PROMPT",
        ("stt", "engine"): "BMO_ASR_ENGINE",
        ("stt", "model"): "BMO_ASR_MODEL",
        ("stt", "base_url"): "BMO_ASR_BASE_URL",
        ("stt", "language"): "BMO_ASR_LANGUAGE",
        ("stt", "timeout_s"): "BMO_ASR_TIMEOUT",
        ("stt", "max_audio_s"): "BMO_ASR_MAX_AUDIO_S",
        ("stt", "keep_alive"): "BMO_ASR_KEEP_ALIVE",
        ("stt", "num_predict"): "BMO_ASR_NUM_PREDICT",
        ("stt", "fallback", "enabled"): "BMO_ASR_FALLBACK",
        ("stt", "fallback", "engine"): "BMO_ASR_FALLBACK_ENGINE",
        ("stt", "fallback", "model"): "BMO_ASR_FALLBACK_MODEL",
        ("tts", "piper_binary"): "BMO_PIPER_BINARY",
        ("tts", "voice_model"): "BMO_TTS_VOICE",
        ("weather", "location"): "BMO_WEATHER_LOCATION",
        ("weather", "latitude"): "BMO_WEATHER_LATITUDE",
        ("weather", "longitude"): "BMO_WEATHER_LONGITUDE",
        ("wakeword", "phrases"): "BMO_WAKEWORD",
        ("wakeword", "mode"): "BMO_WAKEWORD_MODE",
        ("wakeword", "acoustic_model"): "BMO_WAKEWORD_MODEL",
        ("wakeword", "threshold"): "BMO_WAKEWORD_THRESHOLD",
        ("tools", "enabled"): "BMO_TOOLS_ENABLED",
        ("music", "enabled"): "BMO_MUSIC_ENABLED",
        ("music", "mopidy", "rpc_url"): "BMO_MOPIDY_RPC_URL",
        ("music", "ytmusic", "enabled"): "BMO_YTMUSIC_ENABLED",
        ("music", "ytmusic", "auth_file"): "BMO_YTMUSIC_AUTH_FILE",
        ("music", "ytmusic", "cookies_file"): "BMO_YTMUSIC_COOKIES_FILE",
        ("music", "ytmusic", "language"): "BMO_YTMUSIC_LANGUAGE",
        ("music", "ytmusic", "location"): "BMO_YTMUSIC_LOCATION",
        ("music", "stream", "public_base_url"): "BMO_MUSIC_STREAM_BASE_URL",
    }
    # Nomes antigos continuam aceitos; os novos (BMO_ASR_*) têm precedência.
    aliases = {
        "BMO_ASR_ENGINE": "BMO_STT_ENGINE",
        "BMO_ASR_MODEL": "BMO_STT_MODEL",
        "BMO_ASR_LANGUAGE": "BMO_STT_LANGUAGE",
        "BMO_ASR_FALLBACK_MODEL": "BMO_STT_FALLBACK_MODEL",
    }
    for path, env_name in env_map.items():
        value = os.environ.get(env_name) or os.environ.get(aliases.get(env_name, ""), "")
        if not value:
            continue
        *parents, key = path
        if key in {"port", "beam_size", "max_audio_s", "num_predict"}:
            try:
                value = int(float(value))  # type: ignore[assignment]
            except ValueError as exc:
                raise SystemExit(f"{env_name} deve ser um número") from exc
        elif key in {"threshold", "timeout_s"}:
            try:
                value = float(value)  # type: ignore[assignment]
            except ValueError as exc:
                raise SystemExit(f"{env_name} deve ser um número") from exc
        if key in {"enabled", "fallback"}:
            value = value.strip().lower() in {"1", "true", "sim", "yes", "on"}  # type: ignore[assignment]
        if key == "phrases":
            value = [phrase.strip() for phrase in value.split(",") if phrase.strip()]
        target = config
        for part in parents:
            target = target.setdefault(part, {})
        target[key] = value

    config["_config_file"] = str(path)
    config["_token"] = load_or_create_token(config)
    resolve_runtime_paths(config)
    return config


def load_or_create_token(config: dict[str, Any]) -> str:
    env_name = config.get("server", {}).get("token_env", "BMO_TOKEN")
    token = os.environ.get(env_name, "").strip()
    if token:
        return token
    token_file = DATA_DIR / "token"
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token + "\n", encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    print(
        f"[BMO] Token local criado em {token_file}. "
        "Informe esse token nas configurações do aplicativo.",
        file=sys.stderr,
    )
    return token


def resolve_runtime_paths(config: dict[str, Any]) -> None:
    for path in (
        ("stt", "fallback", "binary"),
        ("stt", "fallback", "model"),
        ("tts", "piper_binary"),
        ("tts", "voice_model"),
        ("wakeword", "acoustic_model"),
        ("wakeword", "mel_model"),
        ("wakeword", "embedding_model"),
        ("tools", "access_file"),
        ("music", "ytmusic", "auth_file"),
        ("music", "ytmusic", "cookies_file"),
        ("music", "stream", "secret_file"),
    ):
        *section, key = path
        target = config
        ok = True
        for part in section:
            target = target.get(part, {}) if isinstance(target, dict) else {}
            if not isinstance(target, dict):
                ok = False
                break
        if not ok:
            continue
        current = target.get(key)
        if current:
            target[key] = str(project_path(str(current)) or "")
    for key in ("log_file",):
        config["paths"][key] = str(project_path(config["paths"].get(key)) or "")


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    """Remove segredos e caminhos internos antes de expor via API."""
    clean = copy.deepcopy(config)
    clean.pop("_token", None)
    clean.pop("_config_file", None)
    clean["server"].pop("token_env", None)
    clean["paths"] = {}
    return clean
