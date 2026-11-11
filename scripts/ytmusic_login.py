#!/usr/bin/env python3
"""Autentica o YouTube Music usando os headers do navegador.

O fluxo é o mesmo do ``ytmusicapi browser``, mas com instruções em português,
detecção do arquivo configurado no backend e validação da conta antes de
substituir a autenticação existente.

Uso:
    ./scripts/ytmusic_login.py
    ./scripts/ytmusic_login.py --check
    ./scripts/ytmusic_login.py --headers /tmp/headers.txt
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DEFAULT_AUTH_FILE = BACKEND / "data" / "ytmusic_auth.json"
MUSIC_URL = "https://music.youtube.com/"

C_INFO = "\033[38;5;117m"
C_OK = "\033[38;5;119m"
C_WARN = "\033[38;5;203m"
C_DIM = "\033[38;5;244m"
C_RESET = "\033[0m"


def info(message: str) -> None:
    print(f"{C_INFO}[info]{C_RESET} {message}")


def ok(message: str) -> None:
    print(f"{C_OK}[ok]{C_RESET} {message}")


def warn(message: str) -> None:
    print(f"{C_WARN}[aviso]{C_RESET} {message}", file=sys.stderr)


def fail(message: str) -> None:
    print(f"{C_WARN}[erro]{C_RESET} {message}", file=sys.stderr)
    raise SystemExit(1)


def load_dotenv(path: Path) -> None:
    """Carrega ``backend/.env`` sem executar shell e sem sobrescrever o ambiente."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_auth_file(explicit: str | None, config_file: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    load_dotenv(BACKEND / ".env")
    try:
        from bmo_backend.config import load_config
    except Exception as exc:  # noqa: BLE001
        warn(f"Não foi possível ler a configuração do backend: {exc}")
        return DEFAULT_AUTH_FILE

    try:
        config = load_config(config_file)
    except SystemExit as exc:
        fail(str(exc))
    value = (config.get("music", {}).get("ytmusic", {}) or {}).get("auth_file") or ""
    if not value:
        return DEFAULT_AUTH_FILE
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = BACKEND / path
    return path.resolve()


def parse_pasted(raw: str) -> str:
    """Aceita headers crus ou um comando ``curl`` copiado do navegador."""
    text = raw.strip()
    if not text:
        return ""
    first = text.split(None, 1)[0].lower()
    if first not in {"curl", "curl.exe"}:
        return text

    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        fail(f"Não foi possível interpretar o cURL colado: {exc}")

    headers: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        value: str | None = None
        if token in {"-H", "--header"} and index + 1 < len(tokens):
            value = tokens[index + 1]
            index += 2
        elif token.startswith("--header="):
            value = token.split("=", 1)[1]
            index += 1
        else:
            index += 1
            continue
        if value:
            headers.append(value)
    if not headers:
        fail("O cURL colado não contém headers (-H). Copie a requisição 'browse' novamente.")
    return "\n".join(headers)


def read_paste() -> str:
    print()
    print("Como copiar os headers no navegador:")
    print("  1. Faça login em https://music.youtube.com")
    print("  2. Abra o DevTools (F12) e vá em Network/Rede")
    print("  3. Recarregue a página (F5) e filtre por 'browse'")
    print("  4. Clique numa requisição 'browse?...' do tipo xhr/fetch")
    print("  5. Clique com o botão direito -> Copy/Copiar -> Copy as cURL")
    print("     (ou abra Headers -> Request Headers e copie tudo)")
    print()
    print(f"{C_DIM}Cole abaixo e pressione Enter duas vezes (linha vazia) para terminar.{C_RESET}")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines)


def validate_headers(raw: str) -> None:
    names = set()
    for line in raw.splitlines():
        if ":" in line:
            names.add(line.split(":", 1)[0].strip().lower())
    missing = {"cookie", "x-goog-authuser"} - names
    if missing:
        fail(
            "Faltam headers obrigatórios: "
            + ", ".join(sorted(missing))
            + ". Copie a requisição 'browse' de uma sessão já logada."
        )


def validate_auth(path: Path) -> str:
    try:
        from ytmusicapi import YTMusic
    except Exception as exc:  # noqa: BLE001
        fail(f"ytmusicapi não está instalado no ambiente do backend: {exc}")

    try:
        client = YTMusic(auth=str(path), language="pt", location="BR")
        account = client.get_account_info()
    except Exception as exc:  # noqa: BLE001
        fail(f"O arquivo foi criado, mas o YouTube Music recusou a sessão: {exc}")

    name = str(
        account.get("accountName")
        or account.get("name")
        or account.get("channelHandle")
        or ""
    ).strip()
    return name


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Autentica o YouTube Music com os headers copiados do navegador."
    )
    parser.add_argument(
        "--auth-file",
        help="Arquivo de saída (padrão: music.ytmusic.auth_file do backend).",
    )
    parser.add_argument(
        "--config",
        help="config.json alternativo do backend.",
    )
    parser.add_argument(
        "--headers",
        help="Lê os headers de um arquivo em vez de pedir no terminal.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Não abre o navegador automaticamente.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Somente valida a autenticação existente.",
    )
    args = parser.parse_args()

    auth_path = resolve_auth_file(args.auth_file, args.config)

    if args.check:
        if not auth_path.is_file():
            fail(f"Autenticação não encontrada em {auth_path}")
        name = validate_auth(auth_path)
        ok(f"Sessão válida em {auth_path}" + (f" (conta: {name})" if name else ""))
        return 0

    info(f"Arquivo de autenticação: {auth_path}")
    if not args.no_browser and not args.headers:
        if webbrowser.open(MUSIC_URL):
            info("Navegador aberto em https://music.youtube.com")
        else:
            warn("Não consegui abrir o navegador; abra a URL manualmente.")

    if args.headers:
        headers_file = Path(args.headers).expanduser()
        if not headers_file.is_file():
            fail(f"Arquivo de headers não encontrado: {headers_file}")
        raw = headers_file.read_text(encoding="utf-8")
    else:
        raw = read_paste()

    headers_raw = parse_pasted(raw)
    if not headers_raw.strip():
        fail("Nenhum header recebido.")
    validate_headers(headers_raw)

    try:
        import ytmusicapi
    except Exception as exc:  # noqa: BLE001
        fail(
            "ytmusicapi não está instalado. Rode: "
            f"{BACKEND}/.venv/bin/pip install -r {BACKEND}/requirements.txt "
            f"({exc})"
        )

    auth_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = auth_path.with_name(auth_path.name + ".tmp")
    try:
        ytmusicapi.setup(filepath=str(temp_path), headers_raw=headers_raw)
        name = validate_auth(temp_path)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, auth_path)
    except SystemExit:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        temp_path.unlink(missing_ok=True)
        fail(f"Não foi possível salvar a autenticação: {exc}")

    ok("Login do YouTube Music concluído." + (f" Conta: {name}." if name else ""))
    ok(f"Credenciais salvas em {auth_path} (permissão 600).")
    print()
    print("Reinicie o backend para ele carregar a nova sessão, se estiver rodando.")
    print(f"{C_DIM}Não compartilhe esse arquivo: ele contém cookies da sua conta.{C_RESET}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        raise SystemExit(130)
