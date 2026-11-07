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
        "engine": "whisper_cpp",
        "binary": "../tools/whisper.cpp/build/bin/whisper-cli",
        "model": "../tools/whisper-models/ggml-base.bin",
        "language": "pt",
        "threads": 4,
        "timeout_s": 90,
        "prompt": "Ei, BMO. Ei, BMO. Conversa em português do Brasil com o assistente BMO.",
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
        "mode": "transcript",
        "phrases": [
            "ei bmo",
            "ei bemo",
            "hey bmo",
            "oi bmo",
            "e bmo",
            "bmo",
        ],
        "acoustic_model": None,
        "note": (
            "A palavra de ativação é validada pela transcrição (STT). "
            "O wakeword.onnx original do projeto be-more-agent é 'Hey Jarvis' "
            "e não reconhece 'Ei, BMO'; ele não é usado como detector principal."
        ),
    },
    "security": {
        "allowed_commands": ["get_time", "get_date"],
        "max_text_chars": 1000,
        "audio_cache_ttl_s": 300,
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
        ("stt", "binary"): "BMO_STT_BINARY",
        ("stt", "model"): "BMO_STT_MODEL",
        ("tts", "piper_binary"): "BMO_PIPER_BINARY",
        ("tts", "voice_model"): "BMO_TTS_VOICE",
        ("weather", "location"): "BMO_WEATHER_LOCATION",
        ("weather", "latitude"): "BMO_WEATHER_LATITUDE",
        ("weather", "longitude"): "BMO_WEATHER_LONGITUDE",
        ("wakeword", "phrases"): "BMO_WAKEWORD",
    }
    for (section, key), env_name in env_map.items():
        value = os.environ.get(env_name)
        if value:
            if key == "port":
                try:
                    value = int(value)  # type: ignore[assignment]
                except ValueError as exc:
                    raise SystemExit(f"{env_name} deve ser um número") from exc
            if key == "phrases":
                value = [phrase.strip() for phrase in value.split(",") if phrase.strip()]
            config[section][key] = value

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
    for section, key in (
        ("stt", "binary"),
        ("stt", "model"),
        ("tts", "piper_binary"),
        ("tts", "voice_model"),
    ):
        config[section][key] = str(project_path(config[section].get(key)) or "")
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
