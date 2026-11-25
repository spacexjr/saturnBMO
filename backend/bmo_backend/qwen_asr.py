"""Reconhecimento de fala com Qwen3-ASR executado localmente no Ollama.

O Ollama não expõe um endpoint dedicado de transcrição. O modelo
``frozenlab/qwen3-asr`` é empacotado com o projetor de áudio (``qwen3a``) e a
API efetivamente suportada é a de chat multimodal: o WAV PCM 16 kHz mono vai
em base64 no campo ``images`` de uma mensagem com ``content`` vazio.

Formato real da resposta (verificado contra o modelo)::

    language Portuguese<asr_text>E bem, que horas são agora

Tudo até ``<asr_text>`` é metadado de idioma e não deve ser falado nem enviado
ao LLM. Este módulo não depende de Faster-Whisper, de APIs externas ou de
serviços pagos.

Referência do modelo: https://ollama.com/frozenlab/qwen3-asr
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from typing import Any

import httpx

from .audio import pcm16_to_wav
from .stt import SttError, SttResult, SttUnavailable, clean_transcript, drop_hallucination

log = logging.getLogger("bmo.asr.qwen")

SAMPLE_RATE = 16000
DEFAULT_MODEL = "frozenlab/qwen3-asr:0.6b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"

_ASR_TAG = re.compile(r"<asr_text>\s*(.*)$", re.IGNORECASE | re.DOTALL)
_LANGUAGE_PREFIX = re.compile(
    r"^\s*language\s+([^<\n]+?)\s*(?=<asr_text>|$)", re.IGNORECASE
)
_SPECIAL_TOKENS = re.compile(r"<\|[^>]*\|>")

_LANGUAGE_CODES = {
    "portuguese": "pt",
    "portugues": "pt",
    "português": "pt",
    "english": "en",
    "spanish": "es",
    "espanhol": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "japanese": "ja",
    "chinese": "zh",
    "korean": "ko",
}

# Nomes canônicos aceitos pelo Qwen3-ASR para forçar o idioma. O modelo é
# treinado a responder ``language <NOME><asr_text>``; preencher esse prefixo no
# turno do assistente evita que áudio curto/ruidoso seja detectado como francês,
# japonês etc.
_LANGUAGE_NAMES = {
    "pt": "Portuguese",
    "pt-br": "Portuguese",
    "pt_br": "Portuguese",
    "portuguese": "Portuguese",
    "portugues": "Portuguese",
    "português": "Portuguese",
    "en": "English",
    "english": "English",
    "es": "Spanish",
    "spanish": "Spanish",
    "espanhol": "Spanish",
    "fr": "French",
    "french": "French",
    "de": "German",
    "german": "German",
    "it": "Italian",
    "italian": "Italian",
    "ja": "Japanese",
    "japanese": "Japanese",
    "zh": "Chinese",
    "chinese": "Chinese",
    "ko": "Korean",
    "korean": "Korean",
}


def _language_name(value: str) -> str:
    """Converte ``pt-BR``/``Portuguese`` no nome canônico do Qwen3-ASR."""
    key = str(value or "").strip().lower().replace("_", "-")
    if not key or key in {"auto", "automatic", "detect"}:
        return ""
    if key in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[key]
    return _LANGUAGE_NAMES.get(key.split("-")[0], "")


class QwenAsrStt:
    """Transcrição local pelo Qwen3-ASR no Ollama.

    Args:
        config: seção ``stt`` do config.json. Campos usados:
            ``model``, ``base_url``, ``language``, ``timeout_s``,
            ``max_audio_s``, ``keep_alive`` e ``num_predict``.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.model = str(config.get("model") or DEFAULT_MODEL)
        self.base_url = str(config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self.language = str(config.get("language") or "pt-BR")
        self.timeout_s = float(config.get("timeout_s", 60) or 60)
        self.max_audio_s = float(config.get("max_audio_s", 55) or 55)
        self.keep_alive = str(config.get("keep_alive") or "10m")
        self.num_predict = int(config.get("num_predict", 256) or 256)
        # Forçar o idioma evita a detecção automática errar em clipes curtos
        # (o modelo já transcreveu áudio de "BMO" como japonês/francês).
        self.force_language = bool(config.get("force_language", True))
        self._forced_language = (
            _language_name(self.language) if self.force_language else ""
        )
        self._lock = asyncio.Lock()

        # Otimista até a primeira sondagem: evita marcar o STT como
        # indisponível no boot antes de o Ollama responder ao /api/tags.
        self._available = True
        self._checked_at = 0.0
        self._last_latency_ms = 0
        self._last_audio_ms = 0
        self._transcriptions = 0
        self._failures = 0
        self._last_error: str | None = None

    # -- estado -----------------------------------------------------------

    def available(self) -> bool:
        return self._available

    def status(self) -> dict[str, Any]:
        return {
            "engine": "qwen3-asr",
            "available": self._available,
            "model": self.model,
            "base_url": self.base_url,
            "language": self.language,
            "timeout_s": self.timeout_s,
            "max_audio_s": self.max_audio_s,
            "last_latency_ms": self._last_latency_ms,
            "last_audio_ms": self._last_audio_ms,
            "transcriptions": self._transcriptions,
            "failures": self._failures,
            "last_error": self._last_error,
        }

    async def refresh_availability(self, force: bool = False) -> bool:
        """Confirma no Ollama que o modelo existe e está carregável."""
        if not force and time.monotonic() - self._checked_at < 10.0:
            return self._available
        self._checked_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=2.0)) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001 - indisponibilidade é estado normal
            self._available = False
            self._last_error = f"Ollama indisponível em {self.base_url}: {exc}"
            return False
        names = {
            str(item.get("name") or "")
            for item in data.get("models", [])
            if isinstance(item, dict)
        }
        found = bool(
            self.model in names
            or f"{self.model}:latest" in names
            or (":" not in self.model and f"{self.model}:latest" in names)
        )
        self._available = found
        if found:
            self._last_error = None
        else:
            self._last_error = (
                f"Modelo ASR '{self.model}' não encontrado no Ollama. "
                "Execute: ollama pull frozenlab/qwen3-asr:0.6b"
            )
        return found

    # -- áudio ------------------------------------------------------------

    def _prepare_pcm(self, pcm: bytes, sample_rate: int) -> tuple[bytes, int, int]:
        """Devolve (pcm 16 kHz, duração original em ms, duração usada em ms)."""
        if len(pcm) % 2:
            pcm = pcm[:-1]
        duration_ms = int(len(pcm) / 2 / max(1, sample_rate) * 1000)
        limit_bytes = int(self.max_audio_s * sample_rate) * 2
        if len(pcm) > limit_bytes > 0:
            log.warning(
                "Áudio de %.1fs excede stt.max_audio_s=%.0fs; usando o início.",
                duration_ms / 1000,
                self.max_audio_s,
            )
            pcm = pcm[:limit_bytes]
        if sample_rate != SAMPLE_RATE:
            pcm = _resample_pcm16(pcm, sample_rate, SAMPLE_RATE)
        used_ms = int(len(pcm) / 2 / SAMPLE_RATE * 1000)
        return pcm, duration_ms, used_ms

    def _payload(self, model: str, wav: bytes, *, keep_alive: str, num_predict: int) -> dict[str, Any]:
        encoded = base64.b64encode(wav).decode("ascii")
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "", "images": [encoded]}
        ]
        if self._forced_language:
            # Prefill do turno do assistente: o modelo continua a partir de
            # "language Portuguese<asr_text>" e não tenta detectar o idioma.
            messages.append(
                {
                    "role": "assistant",
                    "content": f"language {self._forced_language}<asr_text>",
                }
            )
        return {
            "model": model,
            "stream": False,
            "keep_alive": keep_alive,
            "messages": messages,
            "options": {
                # O modelo é de ASR: temperatura 0 evita "criatividade".
                "temperature": 0,
                "num_predict": max(16, int(num_predict)),
            },
        }

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        timeout = httpx.Timeout(self.timeout_s, connect=min(10.0, self.timeout_s))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code >= 400:
                body = response.text[:500]
                if response.status_code == 404:
                    raise SttUnavailable(
                        f"O Ollama não encontrou o modelo '{self.model}'. "
                        "Execute: ollama pull frozenlab/qwen3-asr:0.6b"
                    )
                raise SttError(
                    f"O Ollama respondeu {response.status_code} na transcrição: {body}"
                )
            data = response.json()
        if not isinstance(data, dict):
            raise SttError("Resposta inválida do Ollama na transcrição.")
        if "error" in data:
            raise SttError(str(data["error"]))
        return data

    async def transcribe(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> SttResult:
        if not pcm:
            raise SttError("Áudio vazio.")
        pcm16, duration_ms, used_ms = self._prepare_pcm(pcm, sample_rate)
        if not pcm16:
            raise SttError("Áudio vazio após a preparação.")
        if used_ms < 100:
            raise SttError("Áudio curto demais para transcrever.")

        wav = pcm16_to_wav(pcm16, sample_rate=SAMPLE_RATE)
        payload = self._payload(
            self.model,
            wav,
            keep_alive=self.keep_alive,
            num_predict=self.num_predict,
        )
        started = time.monotonic()
        async with self._lock:
            try:
                data = await self._post_chat(payload)
            except SttUnavailable:
                self._available = False
                self._failures += 1
                raise
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                self._available = False
                self._failures += 1
                self._last_error = str(exc)
                raise SttUnavailable(
                    "Não foi possível falar com o Ollama em "
                    f"{self.base_url}. Verifique se ele está rodando "
                    "(ollama serve) e se o modelo foi baixado."
                ) from exc
            except httpx.TimeoutException as exc:
                self._failures += 1
                self._last_error = str(exc)
                raise SttError(
                    f"Qwen3-ASR excedeu o tempo limite de {self.timeout_s:.0f}s."
                ) from exc
            except httpx.HTTPError as exc:
                self._failures += 1
                self._last_error = str(exc)
                raise SttError(f"Erro de rede ao falar com o Ollama: {exc}") from exc
            except SttError as exc:
                self._failures += 1
                self._last_error = str(exc)
                raise

        latency_ms = int((time.monotonic() - started) * 1000)
        message = data.get("message") or {}
        content = str(message.get("content") or "")
        text, language = self.parse_response(content)
        text = clean_transcript(text)
        text = drop_hallucination(text).strip()

        self._last_latency_ms = latency_ms
        self._last_audio_ms = used_ms
        self._available = True
        self._last_error = None
        if text:
            self._transcriptions += 1
        log.info(
            "Qwen3-ASR: %.1fs de áudio transcritos em %d ms (%s).",
            used_ms / 1000,
            latency_ms,
            language or "idioma não informado",
        )
        return SttResult(
            text=text,
            language=language or self.language,
            duration_ms=duration_ms,
            latency_ms=latency_ms,
            engine="qwen3-asr",
        )

    # -- resposta ---------------------------------------------------------

    @staticmethod
    def parse_response(content: str) -> tuple[str, str]:
        """Separa ``language X<asr_text>texto`` em (texto, código do idioma).

        A resposta do modelo não é JSON: é uma linha de idioma seguida da
        transcrição depois de ``<asr_text>``. Quando o marcador não aparece,
        devolvemos o texto restante (sem inventar transcrição).
        """
        raw = str(content or "").strip()
        if not raw:
            return "", ""
        raw = _SPECIAL_TOKENS.sub("", raw)
        language_name = ""
        match = _LANGUAGE_PREFIX.search(raw)
        if match:
            language_name = match.group(1).strip()
        tag = _ASR_TAG.search(raw)
        text = tag.group(1) if tag else raw
        if not tag and language_name:
            # Alguns builds omitem o marcador; remove só o prefixo de idioma.
            text = raw[match.end() :] if match else raw
        text = text.strip().strip('"').strip()
        language = _LANGUAGE_CODES.get(language_name.lower(), "")
        if not language and language_name:
            language = language_name.lower()[:8]
        return text, language

    async def close(self) -> None:
        # Nenhum processo ou sessão persistente é mantido aqui.
        return None


def _resample_pcm16(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    """Reamostragem linear simples para o WAV de entrada do modelo."""
    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    if samples.size == 0 or source_rate == target_rate:
        return pcm
    duration = samples.size / float(source_rate)
    target_size = max(1, int(duration * target_rate))
    source_times = np.arange(samples.size, dtype=np.float64) / source_rate
    target_times = np.arange(target_size, dtype=np.float64) / target_rate
    resampled = np.interp(target_times, source_times, samples)
    return np.clip(resampled, -32768, 32767).astype("<i2").tobytes()
