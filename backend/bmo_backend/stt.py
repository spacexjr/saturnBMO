"""Reconhecimento de fala local.

O mecanismo principal é o **Faster-Whisper** executado no PC. O
``whisper.cpp`` permanece disponível como alternativa compatível, mas não é
usado no Android em nenhuma hipótese.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import tempfile
import unicodedata
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio import pcm16_to_wav

log = logging.getLogger("bmo.stt")

WHISPER_SIZES = {"tiny", "base", "small", "medium", "large-v3"}


class SttUnavailable(RuntimeError):
    pass


class SttError(RuntimeError):
    pass


@dataclass
class SttResult:
    text: str
    language: str
    duration_ms: int


class FasterWhisperStt:
    """Faster-Whisper local (CPU int8 por padrão).

    O modelo é carregado sob demanda, uma única vez, em uma thread separada.
    A inferência nunca roda na thread principal do servidor nem no Android.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.model_name = str(config.get("model", "small"))
        if self.model_name not in WHISPER_SIZES:
            # Também aceita um caminho local ou nome de modelo do Hugging Face.
            self.model_name = str(config.get("model", "small"))
        self.device = str(config.get("device", "cpu"))
        self.compute_type = str(config.get("compute_type", "int8"))
        self.language = str(config.get("language", "pt") or "pt")
        self.auto_language = self.language.lower() in {"auto", ""}
        self.beam_size = int(config.get("beam_size", 5))
        self.num_workers = int(config.get("num_workers", 1))
        self.vad_filter = bool(config.get("vad_filter", True))
        self.condition_on_previous_text = bool(
            config.get("condition_on_previous_text", False)
        )
        vocabulary = config.get("vocabulary")
        if isinstance(vocabulary, (list, tuple)):
            words = [str(item).strip() for item in vocabulary if str(item).strip()]
            vocabulary_prompt = ", ".join(words)
        else:
            vocabulary_prompt = str(vocabulary or "").strip()
        self.initial_prompt = str(config.get("initial_prompt") or vocabulary_prompt).strip()
        self.hotwords = (
            str(config.get("hotwords") or "").strip()
            or str(config.get("vocabulary_hotwords") or "").strip()
        )
        if not self.hotwords and isinstance(vocabulary, (list, tuple)):
            self.hotwords = " ".join(
                str(item).strip() for item in vocabulary if str(item).strip()
            )
        if not self.hotwords:
            self.hotwords = self.initial_prompt
        self.timeout_s = float(config.get("timeout_s", 180))
        # Limita o número de threads do CTranslate2. Sem isto o modelo
        # "medium" ocupava todos os núcleos e travava o servidor em uma
        # transcrição, derrubando também o WebSocket e o /health.
        self.cpu_threads = int(config.get("cpu_threads", 4) or 4)
        self._model: Any = None
        self._load_error: str | None = None
        self._lock = asyncio.Lock()
        # Uma única thread de inferência: impede que timeouts empilhem
        # transcrições concorrentes (era o que gerava 8 threads a 99% CPU).
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="bmo-stt",
        )
        self._pending: Future[Any] | None = None

    def _import_available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def available(self) -> bool:
        return self._import_available()

    def status(self) -> dict[str, Any]:
        return {
            "engine": "faster-whisper",
            "available": self.available(),
            "model": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "language": "auto" if self.auto_language else self.language,
            "beam_size": self.beam_size,
            "cpu_threads": self.cpu_threads,
            "vad_filter": self.vad_filter,
            "condition_on_previous_text": self.condition_on_previous_text,
            "initial_prompt": self.initial_prompt,
            "hotwords": self.hotwords,
            "load_error": self._load_error,
        }

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"faster-whisper não instalado: {exc}"
            raise SttUnavailable(
                "Faster-Whisper não está instalado. Execute "
                "'pip install faster-whisper' no ambiente do backend."
            ) from exc
        try:
            log.info(
                "Carregando Faster-Whisper %s (%s, %s)...",
                self.model_name,
                self.device,
                self.compute_type,
            )
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                num_workers=self.num_workers,
                cpu_threads=self.cpu_threads,
            )
            log.info("Faster-Whisper carregado.")
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            raise SttUnavailable(
                f"Não foi possível carregar o modelo Faster-Whisper '{self.model_name}': {exc}"
            ) from exc
        return self._model

    async def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> SttResult:
        if not pcm:
            raise SttError("Áudio vazio.")
        if not self.available():
            return await _transcribe_or_fail(self, pcm, sample_rate)
        duration_ms = int(len(pcm) / 2 / sample_rate * 1000)
        async with self._lock:
            if self._pending is not None and not self._pending.done():
                raise SttError(
                    "O reconhecimento anterior ainda está em andamento; "
                    "áudio descartado para não sobrecarregar a CPU."
                )
            loop = asyncio.get_running_loop()
            self._pending = self._executor.submit(
                self._transcribe_sync, pcm, sample_rate
            )
            try:
                text, language = await asyncio.wait_for(
                    asyncio.wrap_future(self._pending, loop=loop),
                    timeout=self.timeout_s,
                )
            except asyncio.TimeoutError as exc:
                log.warning(
                    "Faster-Whisper excedeu %.0fs; a inferência continuará em "
                    "segundo plano e novos áudios serão recusados até terminar.",
                    self.timeout_s,
                )
                raise SttError("Tempo limite do Faster-Whisper excedido.") from exc
            except (SttUnavailable, SttError):
                raise
            except Exception as exc:  # noqa: BLE001
                raise SttError(f"Faster-Whisper falhou: {exc}") from exc
        return SttResult(text=text, language=language, duration_ms=duration_ms)

    def _transcribe_sync(self, pcm: bytes, sample_rate: int) -> tuple[str, str]:
        import numpy as np

        model = self._load()
        audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
        if sample_rate != 16000:
            audio = _resample_linear(audio, sample_rate, 16000)
        segments, info = model.transcribe(
            audio,
            language=None if self.auto_language else self.language,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=self.condition_on_previous_text,
            initial_prompt=self.initial_prompt or None,
            hotwords=self.hotwords or None,
            without_timestamps=True,
        )
        pieces = [segment.text.strip() for segment in segments if segment.text.strip()]
        text = clean_transcript(" ".join(pieces))
        language = getattr(info, "language", None) or (
            "auto" if self.auto_language else self.language
        )
        return drop_hallucination(text), language

    async def close(self) -> None:
        self._model = None
        with contextlib.suppress(Exception):
            self._executor.shutdown(wait=False, cancel_futures=True)


class WhisperCppStt:
    """Alternativa legada via binário whisper.cpp."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.binary = Path(config.get("binary", ""))
        self.model = Path(config.get("model", ""))
        self.language = config.get("language", "pt")
        self.threads = int(config.get("threads", 4))
        self.timeout_s = float(config.get("timeout_s", 90))
        self.prompt = config.get("prompt", "")
        self._lock = asyncio.Lock()

    def available(self) -> bool:
        return self.binary.is_file() and os.access(self.binary, os.X_OK) and self.model.is_file()

    def status(self) -> dict[str, Any]:
        return {
            "engine": "whisper.cpp",
            "available": self.available(),
            "binary": str(self.binary),
            "model": str(self.model),
            "language": self.language,
        }

    async def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> SttResult:
        if not self.available():
            raise SttUnavailable(
                "Whisper.cpp não encontrado. Execute scripts/setup_backend.sh ou ajuste stt.binary e stt.model."
            )
        if not pcm:
            raise SttError("Áudio vazio.")
        wav_bytes = pcm16_to_wav(pcm, sample_rate=sample_rate)
        duration_ms = int(len(pcm) / 2 / sample_rate * 1000)

        async with self._lock:
            with tempfile.TemporaryDirectory(prefix="bmo-stt-") as tmp:
                wav_path = Path(tmp) / "entrada.wav"
                out_prefix = Path(tmp) / "transcricao"
                wav_path.write_bytes(wav_bytes)
                cmd = [
                    str(self.binary),
                    "-m",
                    str(self.model),
                    "-f",
                    str(wav_path),
                    "-l",
                    self.language,
                    "-t",
                    str(self.threads),
                    "-otxt",
                    "-of",
                    str(out_prefix),
                    "-np",
                ]
                if self.prompt:
                    cmd.extend(["--prompt", self.prompt])
                log.debug("Executando STT: %s", " ".join(cmd[:6]))
                env = os.environ.copy()
                lib_dir = str(self.binary.resolve().parent)
                current = env.get("LD_LIBRARY_PATH", "")
                env["LD_LIBRARY_PATH"] = f"{lib_dir}:{current}" if current else lib_dir
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                try:
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
                except asyncio.TimeoutError as exc:
                    proc.kill()
                    await proc.wait()
                    raise SttError("Tempo limite do reconhecimento de fala excedido.") from exc
                if proc.returncode != 0:
                    detail = stderr.decode("utf-8", "ignore")[-400:]
                    raise SttError(f"Whisper.cpp falhou (código {proc.returncode}). {detail}")
                text_file = out_prefix.with_suffix(".txt")
                text = text_file.read_text(encoding="utf-8", errors="ignore") if text_file.exists() else ""
                text = drop_hallucination(clean_transcript(text))
                return SttResult(text=text, language=self.language, duration_ms=duration_ms)

    async def close(self) -> None:
        return None


class FallbackStt:
    """Fachada que tenta o Faster-Whisper e cai para o whisper.cpp."""

    def __init__(self, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback
        self.last_engine = ""

    def available(self) -> bool:
        return bool(
            (self.primary is not None and self.primary.available())
            or (self.fallback is not None and self.fallback.available())
        )

    def status(self) -> dict[str, Any]:
        data = (
            self.primary.status()
            if self.primary is not None
            else {"engine": "faster-whisper", "available": False}
        )
        data["fallback"] = (
            self.fallback.status() if self.fallback is not None else None
        )
        data["available"] = self.available()
        data["active_engine"] = self.last_engine or data.get("engine")
        return data

    async def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> SttResult:
        errors: list[str] = []
        if self.primary is not None and self.primary.available():
            try:
                result = await self.primary.transcribe(pcm, sample_rate)
                self.last_engine = "faster-whisper"
                return result
            except SttUnavailable as exc:
                errors.append(str(exc))
            except SttError as exc:
                log.warning("Faster-Whisper falhou; tentando fallback: %s", exc)
                errors.append(str(exc))
        if self.fallback is not None and self.fallback.available():
            result = await self.fallback.transcribe(pcm, sample_rate)
            self.last_engine = "whisper.cpp"
            return result
        raise SttUnavailable(" ".join(errors) or "Nenhum mecanismo de STT disponível.")

    async def close(self) -> None:
        for item in (self.primary, self.fallback):
            if item is not None:
                await item.close()


def build_stt(config: dict[str, Any]) -> Any:
    """Cria o STT conforme a configuração, mantendo fallback seguro."""
    engine = str(config.get("engine", "faster_whisper")).lower()
    fallback_cfg = config.get("fallback") or {}
    if engine == "whisper_cpp":
        return WhisperCppStt(config)
    if engine == "faster_whisper":
        primary = FasterWhisperStt(config)
        fallback = WhisperCppStt(fallback_cfg) if fallback_cfg.get("binary") else None
        return FallbackStt(primary, fallback)
    raise ValueError(f"Mecanismo de STT desconhecido: {engine}")


async def _transcribe_or_fail(stt: FasterWhisperStt, pcm: bytes, sample_rate: int) -> SttResult:
    raise SttUnavailable(
        "Faster-Whisper não está disponível. Instale com 'pip install faster-whisper' "
        "e reinicie o backend."
    )


def _resample_linear(samples: Any, source_rate: int, target_rate: int) -> Any:
    import numpy as np

    if source_rate == target_rate or samples.size == 0:
        return samples
    duration = samples.size / float(source_rate)
    target_size = int(duration * target_rate)
    source_times = np.arange(samples.size, dtype=np.float64) / source_rate
    target_times = np.arange(target_size, dtype=np.float64) / target_rate
    return np.interp(target_times, source_times, samples).astype(np.float32)


# Frases que o Whisper costuma inventar em trechos de silêncio/ruído.
_HALLUCINATION_PATTERNS = (
    "legendas pela comunidade amara.org",
    "legendas pela comunidade",
    "subtitles by the amara.org community",
    "obrigado por assistir",
    "obrigado por assistir ao video",
    "thanks for watching",
    "thank you for watching",
    "inscreva-se no canal",
    "ate a proxima",
    "blank audio",
    "blank audio silence",
)


def drop_hallucination(text: str) -> str:
    normalized = _plain(text)
    if not normalized:
        return ""
    for phrase in _HALLUCINATION_PATTERNS:
        if normalized == phrase or (len(normalized) <= len(phrase) + 8 and phrase in normalized):
            return ""
    return text


def clean_transcript(text: str) -> str:
    text = text.strip()
    # Remove marcações de som do Whisper, como [Risos], (música) e [BLANK_AUDIO].
    text = re.sub(r"\[[^\]]{1,60}\]", " ", text)
    text = re.sub(r"\((?:risos|música|silêncio|inaudível)[^)]*\)", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
