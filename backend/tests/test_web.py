"""Testes de segurança e extração das ferramentas de internet."""

from __future__ import annotations

import pytest

from bmo_backend.web import (
    WebError,
    _SearchParser,
    _TextExtractor,
    _unwrap_duckduckgo,
    validate_url,
)


def test_blocks_private_and_loopback_urls():
    for url in (
        "http://127.0.0.1:11434/api/tags",
        "http://localhost:8765",
        "http://192.168.0.10/",
        "http://10.0.0.1/",
        "http://[::1]/",
    ):
        with pytest.raises(WebError):
            validate_url(url)


def test_allows_public_ip():
    assert validate_url("https://1.1.1.1/") == "https://1.1.1.1/"


def test_rejects_non_http_schemes():
    with pytest.raises(WebError):
        validate_url("file:///etc/passwd")
    with pytest.raises(WebError):
        validate_url("javascript:alert(1)")


def test_adds_https_when_scheme_is_missing():
    assert validate_url("example.com") == "https://example.com"


def test_only_private_allowed_when_explicit():
    assert validate_url("http://127.0.0.1:8765", allow_private=True) == "http://127.0.0.1:8765"


def test_text_extractor_ignores_scripts_and_reads_meta():
    parser = _TextExtractor()
    parser.feed(
        """
        <html><head>
          <title>Notícia</title>
          <meta name="description" content="Resumo da página">
        </head>
        <body>
          <script>alert('ignore')</script>
          <style>.x { color: red }</style>
          <h1>Título</h1>
          <p>Primeiro parágrafo.</p>
          <p>Segundo parágrafo.</p>
        </body></html>
        """
    )
    text = parser.text()
    assert parser.title == "Notícia"
    assert parser.description == "Resumo da página"
    assert "Primeiro parágrafo." in text
    assert "Segundo parágrafo." in text
    assert "alert" not in text
    assert "color: red" not in text


def test_search_parser_extracts_results():
    parser = _SearchParser()
    parser.feed(
        """
        <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F">Exemplo</a>
        <a class="result__snippet">Um trecho de exemplo.</a>
        """
    )
    assert parser.results
    assert parser.results[0]["title"] == "Exemplo"
    assert _unwrap_duckduckgo(parser.results[0]["url"]) == "https://example.com/"
