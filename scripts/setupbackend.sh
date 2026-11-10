#!/usr/bin/env bash
# Prepara o backend Python, o token e o Mopidy local do SaturnBMO.
#
# Uso:
#   ./scripts/setupbackend.sh
#
# Variáveis opcionais:
#   BMO_PORT=8765                  porta HTTP do backend
#   BMO_MOPIDY_PORT=6680           porta JSON-RPC do Mopidy (somente localhost)
#   BMO_MOPIDY_AUDIO_OUTPUT=...    saída GStreamer (padrão: autoaudiosink)

set -Eeuo pipefail

C1='\033[38;5;80m'
C2='\033[38;5;117m'
C3='\033[38;5;119m'
C4='\033[38;5;24m'
C5='\033[38;5;203m'
RESET='\033[0m'

info() { printf '%b\n' "${C2}[info]${RESET} $*"; }
ok() { printf '%b\n' "${C3}[ok]${RESET} $*"; }
warn() { printf '%b\n' "${C5}[aviso]${RESET} $*"; }
fail() { printf '%b\n' "${C5}[erro]${RESET} $*" >&2; exit 1; }

printf '%b' "$C1"
echo '  ███████╗ █████╗ ████████╗██╗   ██╗██████╗ ███╗   ██╗'
echo '  ██╔════╝██╔══██╗╚══██╔══╝██║   ██║██╔══██╗████╗  ██║'

printf '%b' "$C2"
echo '  ███████╗███████║   ██║   ██║   ██║██████╔╝██╔██╗ ██║'

printf '%b' "$C1"
echo '  ╚════██║██╔══██║   ██║   ██║   ██║████╗   ██║╚██╗██║'
echo '  ███████║██║  ██║   ██║   ╚██████╔╝██  ██╔╝██║ ╚████║'

printf '%b' "$C4"
echo '  ╚══════╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚══  ═╝ ╚═╝  ╚═══╝'

printf '%b\n' "${RESET}"
echo '=============================================='

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
DATA="$BACKEND/data"
RUN_DIR="$DATA/run"
MOPIDY_DIR="$DATA/mopidy"
MOPIDY_CONFIG="$MOPIDY_DIR/mopidy.conf"
ENV_FILE="$BACKEND/.env"

cd "$BACKEND"

command -v python3 >/dev/null 2>&1 || fail "python3 não encontrado."
command -v mopidy >/dev/null 2>&1 || fail "Mopidy não encontrado. No Nobara/Fedora: sudo dnf install mopidy"
command -v curl >/dev/null 2>&1 || fail "curl não encontrado."

# ---------------------------------------------------------------------------
# Ambiente Python
# ---------------------------------------------------------------------------

if [[ ! -x "$VENV/bin/python" ]]; then
    info "Criando ambiente virtual em backend/.venv"
    python3 -m venv "$VENV" || fail "Não foi possível criar o venv. Instale python3-venv."
fi

if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    info "Instalando pip no ambiente virtual"
    "$VENV/bin/python" -m ensurepip --upgrade \
        || fail "Não foi possível instalar o pip no venv."
fi

REQ_HASH="$(
    {
        sha256sum requirements.txt
        [[ -f requirements-dev.txt ]] && sha256sum requirements-dev.txt
    } | sha256sum | awk '{print $1}'
)"
REQ_MARKER="$VENV/.bmo-requirements.sha256"

if [[ ! -f "$REQ_MARKER" || "$(cat "$REQ_MARKER")" != "$REQ_HASH" ]]; then
    info "Instalando dependências Python"
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install -r requirements.txt
    if [[ -f requirements-dev.txt ]]; then
        "$VENV/bin/python" -m pip install -r requirements-dev.txt
    fi
    printf '%s\n' "$REQ_HASH" > "$REQ_MARKER"
else
    ok "Dependências Python já estão atualizadas"
fi

# ---------------------------------------------------------------------------
# Portas e arquivo .env
# ---------------------------------------------------------------------------

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$BACKEND/.env.example" ]]; then
        cp "$BACKEND/.env.example" "$ENV_FILE"
        info "Criado backend/.env a partir de .env.example"
    else
        : > "$ENV_FILE"
    fi
fi

read_env() {
    local key="$1"
    grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

BACKEND_PORT="${BMO_PORT:-$(read_env BMO_PORT)}"
BACKEND_PORT="${BACKEND_PORT:-8765}"
MOPIDY_PORT="${BMO_MOPIDY_PORT:-$(read_env BMO_MOPIDY_PORT)}"
MOPIDY_PORT="${MOPIDY_PORT:-6680}"
MOPIDY_AUDIO_OUTPUT="${BMO_MOPIDY_AUDIO_OUTPUT:-autoaudiosink}"

"$VENV/bin/python" - "$ENV_FILE" "$BACKEND_PORT" "$MOPIDY_PORT" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
backend_port = sys.argv[2]
mopidy_port = sys.argv[3]

managed = {
    "BMO_PORT": backend_port,
    "BMO_MUSIC_ENABLED": "true",
    "BMO_MOPIDY_RPC_URL": f"http://127.0.0.1:{mopidy_port}/mopidy/rpc",
    "BMO_MOPIDY_PORT": mopidy_port,
    "BMO_YTMUSIC_ENABLED": "true",
    "BMO_YTMUSIC_LANGUAGE": "pt",
    "BMO_YTMUSIC_LOCATION": "BR",
    "BMO_MUSIC_STREAM_BASE_URL": f"http://127.0.0.1:{backend_port}",
}

lines = env_path.read_text(encoding="utf-8").splitlines()
out: list[str] = []
skip_managed = False
for line in lines:
    if line.strip() == "# >>> bmo setupbackend":
        skip_managed = True
        continue
    if line.strip() == "# <<< bmo setupbackend":
        skip_managed = False
        continue
    if skip_managed:
        continue
    key = line.split("=", 1)[0].strip()
    if key in managed:
        continue
    out.append(line)

while out and not out[-1].strip():
    out.pop()

out.extend([
    "",
    "# >>> bmo setupbackend",
    "# Valores gerenciados por scripts/setupbackend.sh",
    *[f"{key}={value}" for key, value in managed.items()],
    "# <<< bmo setupbackend",
    "",
])
env_path.write_text("\n".join(out), encoding="utf-8")
try:
    env_path.chmod(0o600)
except OSError:
    pass
PY
ok "backend/.env configurado (backend :$BACKEND_PORT, Mopidy :$MOPIDY_PORT)"

# Exporta os valores para as etapas seguintes.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

# ---------------------------------------------------------------------------
# Diretórios, token e Mopidy
# ---------------------------------------------------------------------------

mkdir -p "$DATA" "$RUN_DIR" "$MOPIDY_DIR/cache" "$MOPIDY_DIR/data" "$MOPIDY_DIR/config"
chmod 700 "$DATA" 2>/dev/null || true

if [[ -n "${BMO_TOKEN:-}" ]]; then
    ok "Token configurado via BMO_TOKEN em backend/.env"
elif [[ -s "$DATA/token" ]]; then
    ok "Token existente em backend/data/token"
else
    info "Gerando token local"
    TOKEN="$("$VENV/bin/python" -m bmo_backend --print-token)"
    [[ -n "$TOKEN" ]] || fail "Não foi possível gerar o token."
    ok "Token disponível em backend/data/token"
fi

cat > "$MOPIDY_CONFIG.tmp" <<EOF
# Gerado por scripts/setupbackend.sh.
# O Mopidy escuta apenas em localhost; não exponha esta porta na rede.
[core]
cache_dir = $MOPIDY_DIR/cache
data_dir = $MOPIDY_DIR/data
config_dir = $MOPIDY_DIR/config
restore_state = true

[logging]
verbosity = 1

[audio]
mixer = software
output = $MOPIDY_AUDIO_OUTPUT

[http]
enabled = true
hostname = 127.0.0.1
port = $MOPIDY_PORT
csrf_protection = false
zeroconf = false

[file]
enabled = false

[m3u]
enabled = false

[stream]
enabled = true
EOF
mv "$MOPIDY_CONFIG.tmp" "$MOPIDY_CONFIG"
ok "Mopidy configurado em $MOPIDY_CONFIG"

if ! mopidy --config "$MOPIDY_CONFIG" config >/dev/null 2>"$RUN_DIR/mopidy-config-check.log"; then
    cat "$RUN_DIR/mopidy-config-check.log" >&2
    fail "O Mopidy rejeitou a configuração gerada."
fi
ok "Configuração do Mopidy validada"

# ---------------------------------------------------------------------------
# Verificações de dependências e serviços
# ---------------------------------------------------------------------------

echo
info "Verificação de ferramentas"

MOPIDY_VERSION="$(mopidy --version 2>/dev/null | head -n 1 || true)"
ok "Mopidy: ${MOPIDY_VERSION:-instalado}"

if "$VENV/bin/python" -c "import ytmusicapi, yt_dlp" >/dev/null 2>&1; then
    ok "ytmusicapi e yt-dlp instalados"
else
    fail "ytmusicapi/yt-dlp ausentes. Rode: backend/.venv/bin/pip install -r backend/requirements.txt"
fi

if "$VENV/bin/python" -c "import faster_whisper" >/dev/null 2>&1; then
    ok "Faster-Whisper disponível (modelo baixado no primeiro uso)"
else
    warn "Faster-Whisper ausente; o STT pode não funcionar."
fi

if command -v gst-inspect-1.0 >/dev/null 2>&1 && gst-inspect-1.0 autoaudiosink >/dev/null 2>&1; then
    ok "Saída de áudio GStreamer (autoaudiosink) disponível"
else
    warn "Não foi possível confirmar a saída GStreamer autoaudiosink."
fi

if command -v ollama >/dev/null 2>&1; then
    if curl -fsS -m 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
        ok "Ollama respondendo em 127.0.0.1:11434"
    else
        warn "Ollama instalado, mas não está respondendo. Inicie com: ollama serve"
    fi
else
    warn "Ollama não encontrado; o BMO ficará sem respostas do LLM."
fi

AUTH_FILE="${BMO_YTMUSIC_AUTH_FILE:-$DATA/ytmusic_auth.json}"
if [[ "$AUTH_FILE" != /* ]]; then
    AUTH_FILE="$BACKEND/$AUTH_FILE"
fi
if [[ -f "$AUTH_FILE" ]]; then
    ok "Autenticação do YouTube Music encontrada em $AUTH_FILE"
else
    warn "YouTube Music em modo anônimo. Playlists e curtidas exigem backend/data/ytmusic_auth.json"
fi

echo
ok "Backend e Mopidy configurados."
echo
echo "Próximos passos:"
echo "  1. Suba tudo:      ./scripts/start-all.sh"
echo "  2. Veja o status:  ./scripts/status-all.sh"
echo "  3. Pare tudo:      ./scripts/stop-all.sh"
echo "  4. Token do app:   cat backend/data/token"
echo
