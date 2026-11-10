#!/usr/bin/env bash
# Mostra o estado dos serviços iniciados por scripts/start-all.sh.

set -Eeuo pipefail

C1='\033[38;5;80m'
C3='\033[38;5;119m'
C5='\033[38;5;203m'
RESET='\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
DATA="$BACKEND/data"
RUN_DIR="$DATA/run"
ENV_FILE="$BACKEND/.env"

[[ -f "$ENV_FILE" ]] || { printf '%b\n' "${C5}[erro]${RESET} Rode ./scripts/setupbackend.sh primeiro." >&2; exit 1; }

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

BACKEND_PORT="${BMO_PORT:-8765}"
MOPIDY_PORT="${BMO_MOPIDY_PORT:-6680}"
TOKEN="${BMO_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
    TOKEN="$(cat "$DATA/token" 2>/dev/null || true)"
fi

print_pid() {
    local name="$1"
    local file="$2"
    if [[ -f "$file" ]] && kill -0 "$(cat "$file")" 2>/dev/null; then
        printf '%b\n' "${C3}[rodando]${RESET} $name (PID $(cat "$file"))"
    else
        printf '%b\n' "${C5}[parado]${RESET} $name"
    fi
}

echo
print_pid "Mopidy" "$RUN_DIR/mopidy.pid"
print_pid "Backend BMO" "$RUN_DIR/bmo.pid"

echo
if curl -fsS -m 3 "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1; then
    printf '%b\n' "${C3}[ok]${RESET} API em http://127.0.0.1:$BACKEND_PORT"
else
    printf '%b\n' "${C5}[falha]${RESET} API não responde"
fi

if [[ -n "$TOKEN" ]]; then
    STATE="$(curl -fsS -m 5 -H "Authorization: Bearer $TOKEN" \
        "http://127.0.0.1:$BACKEND_PORT/api/music/state" 2>/dev/null || true)"
    if [[ -n "$STATE" ]]; then
        "$ROOT/backend/.venv/bin/python" - "$STATE" <<'PY'
import json
import sys

state = json.loads(sys.argv[1])
print(
    f"[música] status={state.get('status')} "
    f"volume={state.get('volume_percent')}% "
    f"fila={state.get('queue_length')} "
    f"título={state.get('title') or '-'}"
)
PY
    else
        printf '%b\n' "${C5}[falha]${RESET} Estado da música indisponível"
    fi
fi

echo
