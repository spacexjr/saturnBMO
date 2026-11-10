#!/usr/bin/env bash
# Sobe Mopidy e o backend do SaturnBMO, espera os dois ficarem prontos e
# mostra o endereço/token para configurar o aplicativo Android.

set -Eeuo pipefail

C1='\033[38;5;80m'
C3='\033[38;5;119m'
C5='\033[38;5;203m'
RESET='\033[0m'

info() { printf '%b\n' "${C1}[bmo]${RESET} $*"; }
ok() { printf '%b\n' "${C3}[ok]${RESET} $*"; }
fail() { printf '%b\n' "${C5}[erro]${RESET} $*" >&2; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
DATA="$BACKEND/data"
RUN_DIR="$DATA/run"
MOPIDY_CONFIG="$DATA/mopidy/mopidy.conf"
ENV_FILE="$BACKEND/.env"
MOPIDY_PID="$RUN_DIR/mopidy.pid"
BACKEND_PID="$RUN_DIR/bmo.pid"
MOPIDY_LOG="$RUN_DIR/mopidy.log"
BACKEND_LOG="$RUN_DIR/bmo.log"

if [[ ! -x "$VENV/bin/python" || ! -f "$MOPIDY_CONFIG" || ! -f "$ENV_FILE" ]]; then
    info "Configuração incompleta; executando setupbackend.sh"
    "$ROOT/scripts/setupbackend.sh"
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

BACKEND_PORT="${BMO_PORT:-8765}"
MOPIDY_PORT="${BMO_MOPIDY_PORT:-6680}"
BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
MOPIDY_URL="http://127.0.0.1:$MOPIDY_PORT/mopidy/rpc"
TOKEN="${BMO_TOKEN:-}"
if [[ -z "$TOKEN" && -f "$DATA/token" ]]; then
    TOKEN="$(cat "$DATA/token")"
fi

mkdir -p "$RUN_DIR"

rpc_ok() {
    curl -fsS -m 2 -X POST -H 'Content-Type: application/json' \
        -d '{"jsonrpc":"2.0","id":1,"method":"core.get_version","params":{}}' \
        "$MOPIDY_URL" 2>/dev/null | grep -q '"result"'
}

backend_ok() {
    curl -fsS -m 2 "$BACKEND_URL/health" >/dev/null 2>&1
}

port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# Mopidy
# ---------------------------------------------------------------------------

if rpc_ok; then
    ok "Mopidy já está rodando em 127.0.0.1:$MOPIDY_PORT"
else
    port_open "$MOPIDY_PORT" && fail "A porta $MOPIDY_PORT está ocupada, mas o Mopidy não responde ao JSON-RPC."
    printf '\n===== %s =====\n' "$(date -Is)" >> "$MOPIDY_LOG"
    info "Iniciando Mopidy em 127.0.0.1:$MOPIDY_PORT"
    nohup mopidy --config "$MOPIDY_CONFIG" >> "$MOPIDY_LOG" 2>&1 &
    MOPIDY_PROCESS=$!
    printf '%s\n' "$MOPIDY_PROCESS" > "$MOPIDY_PID"

    ready=0
    for _ in $(seq 1 60); do
        if rpc_ok; then
            ready=1
            break
        fi
        if ! kill -0 "$MOPIDY_PROCESS" 2>/dev/null; then
            tail -n 30 "$MOPIDY_LOG" >&2 || true
            fail "O Mopidy encerrou durante a inicialização. Veja $MOPIDY_LOG"
        fi
        sleep 0.5
    done
    [[ "$ready" == "1" ]] || {
        tail -n 30 "$MOPIDY_LOG" >&2 || true
        fail "O Mopidy não respondeu em 30 s. Veja $MOPIDY_LOG"
    }
    ok "Mopidy pronto (PID $MOPIDY_PROCESS)"
fi

# ---------------------------------------------------------------------------
# Backend BMO
# ---------------------------------------------------------------------------

if backend_ok; then
    ok "Backend já está rodando em $BACKEND_URL"
else
    port_open "$BACKEND_PORT" && fail "A porta $BACKEND_PORT está ocupada, mas o backend não responde em /health."
    printf '\n===== %s =====\n' "$(date -Is)" >> "$BACKEND_LOG"
    info "Iniciando backend BMO em $BACKEND_URL"
    nohup "$BACKEND/run.sh" >> "$BACKEND_LOG" 2>&1 &
    BACKEND_PROCESS=$!
    printf '%s\n' "$BACKEND_PROCESS" > "$BACKEND_PID"

    ready=0
    for _ in $(seq 1 90); do
        if backend_ok; then
            ready=1
            break
        fi
        if ! kill -0 "$BACKEND_PROCESS" 2>/dev/null; then
            tail -n 40 "$BACKEND_LOG" >&2 || true
            fail "O backend encerrou durante a inicialização. Veja $BACKEND_LOG"
        fi
        sleep 0.5
    done
    [[ "$ready" == "1" ]] || {
        tail -n 40 "$BACKEND_LOG" >&2 || true
        fail "O backend não respondeu em 45 s. Veja $BACKEND_LOG"
    }
    ok "Backend pronto (PID $BACKEND_PROCESS)"
fi

# ---------------------------------------------------------------------------
# Validação autenticada da música
# ---------------------------------------------------------------------------

[[ -n "$TOKEN" ]] || fail "Token não encontrado em backend/data/token nem em BMO_TOKEN."

STATE="$(
    curl -fsS -m 10 -H "Authorization: Bearer $TOKEN" \
        "$BACKEND_URL/api/music/state"
)" || fail "A API de música não respondeu. Veja $BACKEND_LOG"

"$VENV/bin/python" - "$STATE" <<'PY' || fail "O estado da música não pôde ser lido."
import json
import sys

state = json.loads(sys.argv[1])
if not state.get("available"):
    detail = state.get("message") or "Mopidy indisponível"
    print(f"[erro] Integração musical indisponível: {detail}", file=sys.stderr)
    raise SystemExit(1)
print(
    "[ok] Música pronta: "
    f"status={state.get('status')} volume={state.get('volume_percent')}%"
)
PY

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
HOST_IP="${HOST_IP:-127.0.0.1}"

echo
ok "Tudo pronto para testar."
echo
echo "  Android/API: http://$HOST_IP:$BACKEND_PORT"
echo "  Local:        $BACKEND_URL"
echo "  Mopidy:       http://127.0.0.1:$MOPIDY_PORT/mopidy/rpc"
echo "  Token:        $TOKEN"
echo
echo "  Logs:         $RUN_DIR"
echo "  Parar tudo:   ./scripts/stop-all.sh"
echo
