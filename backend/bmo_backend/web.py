"""Ferramentas de internet para o BMO.

Conteúdo externo é sempre tratado como **dado não confiável**. O texto extraído
de uma página nunca é interpretado como instrução do sistema. O backend também
bloqueia URLs para redes privadas por padrão, evitando SSRF contra serviços
locais (Ollama, roteador, painel do próprio backend).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger("bmo.web")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 SaturnBMO/1.0"
)
MAX_PAGE_BYTES = 2_000_000
MAX_TEXT_CHARS = 12_000


class WebError(RuntimeError):
    pass


def _is_private_host(host: str) -> bool:
    host = host.strip().strip("[]")
    if not host:
        return True
    if host.lower() in {"localhost", "localhost.localdomain"}:
        return True
    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in addresses:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address.split("%")[0])
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


def validate_url(url: str, allow_private: bool = False) -> str:
    raw = (url or "").strip()
    if not raw:
        raise WebError("Informe uma URL.")
    parsed = urlparse(raw)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        raise WebError("Somente URLs http e https são permitidas.")
    if not parsed.scheme:
        raw = "https://" + raw
        parsed = urlparse(raw)
    if not parsed.hostname:
        raise WebError("URL inválida.")
    if not allow_private and _is_private_host(parsed.hostname):
        raise WebError("Por segurança, o BMO não acessa endereços da rede local.")
    return raw


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
    BLOCK = {
        "p", "div", "br", "li", "tr", "section", "article", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "footer", "main", "blockquote", "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self.description = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            values = {key.lower(): value for key, value in attrs}
            name = (values.get("name") or values.get("property") or "").lower()
            if name in {"description", "og:description"} and values.get("content"):
                self.description = values["content"] or ""
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = unescape(data)
        if self._in_title:
            self.title += text
        else:
            self.parts.append(text)

    def text(self) -> str:
        joined = "".join(self.parts)
        joined = re.sub(r"[ \t\f\v]+", " ", joined)
        joined = re.sub(r"\n\s*\n+", "\n", joined)
        return joined.strip()


class _SearchParser(HTMLParser):
    """Extrai resultados do HTML do DuckDuckGo (sem JavaScript)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._in_link = False
        self._in_snippet = False
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = values.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._current = {
                "title": "",
                "url": values.get("href", ""),
                "snippet": "",
            }
            self._in_link = True
        elif self._current is not None and "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
        if self._in_snippet and tag in {"a", "div", "span"}:
            self._in_snippet = False
            if self._current and self._current.get("title"):
                self.results.append(self._current)
                self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._in_link:
            self._current["title"] += data
        elif self._in_snippet:
            self._current["snippet"] += data


def _unwrap_duckduckgo(url: str) -> str:
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        match = re.search(r"[?&]uddg=([^&]+)", url)
        if match:
            from urllib.parse import unquote

            return unquote(match.group(1))
    return url


@dataclass
class WebPage:
    url: str
    title: str
    text: str
    description: str = ""


class WebService:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.allow_private = bool(config.get("allow_private_urls", False))
        self.timeout_s = float(config.get("timeout_s", 15))
        self.max_results = int(config.get("max_results", 5))
        self.search_endpoint = str(
            config.get("search_endpoint", "https://html.duckduckgo.com/html/")
        )

    def status(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "search": "duckduckgo-html"}

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_s, connect=8.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"},
        )

    async def search(self, query: str, max_results: int | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise WebError("A busca na internet está desativada.")
        clean = (query or "").strip()
        if not clean:
            raise WebError("Informe o que pesquisar.")
        limit = max(1, min(int(max_results or self.max_results), 10))
        try:
            async with await self._client() as client:
                response = await client.post(
                    self.search_endpoint,
                    data={"q": clean, "kl": "br-pt"},
                )
                response.raise_for_status()
                html = response.text
        except httpx.HTTPError as exc:
            raise WebError(f"Busca indisponível no momento: {exc}") from exc
        parser = _SearchParser()
        parser.feed(html)
        results = []
        seen: set[str] = set()
        for item in parser.results:
            url = _unwrap_duckduckgo(item.get("url", ""))
            title = re.sub(r"\s+", " ", item.get("title", "")).strip()
            snippet = re.sub(r"\s+", " ", item.get("snippet", "")).strip()
            if not title or not url or url in seen:
                continue
            seen.add(url)
            results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= limit:
                break
        return {"query": clean, "results": results, "source": "DuckDuckGo"}

    async def read_webpage(self, url: str) -> dict[str, Any]:
        target = validate_url(url, self.allow_private)
        try:
            async with await self._client() as client:
                async with client.stream("GET", target) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "html" not in content_type and "text" not in content_type:
                        raise WebError(
                            f"O conteúdo não é texto ({content_type or 'desconhecido'})."
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= MAX_PAGE_BYTES:
                            break
                    raw = b"".join(chunks)
                    charset = response.encoding or "utf-8"
        except httpx.HTTPError as exc:
            raise WebError(f"Não foi possível abrir a página: {exc}") from exc
        html = raw.decode(charset, errors="replace")
        parser = _TextExtractor()
        parser.feed(html)
        text = parser.text()
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + "…"
        return {
            "url": str(response.url) if "response" in locals() else target,
            "title": re.sub(r"\s+", " ", parser.title).strip(),
            "description": re.sub(r"\s+", " ", parser.description).strip(),
            "text": text,
            "truncated": len(text) >= MAX_TEXT_CHARS,
        }

    async def open_in_browser(self, url: str) -> dict[str, Any]:
        target = validate_url(url, self.allow_private)
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdg-open",
                target,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.sleep(0.2)
            if proc.returncode not in (None, 0):
                raise WebError("O navegador padrão não abriu a URL.")
        except FileNotFoundError as exc:
            raise WebError("xdg-open não está disponível neste sistema.") from exc
        return {"ok": True, "url": target, "message": "Página aberta no navegador do PC."}
