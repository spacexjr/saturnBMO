#!/usr/bin/env bash
# Para o backend BMO e o Mopidy iniciados por scripts/start-all.sh.
# Não encerra processos desconhecidos nem serviços systemd.

set -Eeuo pipefail

C1='\033[38;5;80m'
C3='\033[38;5;119m'
C5='\033[38;5;203m'
RESET='\033[0m'

info() { printf '%b\n' "${C1}[bmo]${RESET} $*"; }
ok() { printf '%b\n' "${C3}[ok]${RESET} $*"; }
warn() { printf '%b\n' "${C5}[aviso]${RESET} $*"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/backend/data/run"

stop_pid() {
    local name="$1"
    local pid_file="$2"
    local pattern="$3"

    if [[ ! -f "$pid_file" ]]; then
        info "$name já está parado (sem PID registrado)"
        return
    fi

    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -z "$pid" ]] || ! [[ "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$pid_file"
        info "$name já está parado"
        return
    fi

    local cmd
    cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    if [[ "$cmd" != *"$pattern"* ]]; then
        warn "PID $pid não parece ser $name; não vou encerrar. Comando: $cmd"
        rm -f "$pid_file"
        return
    fi

    info "Parando $name (PID $pid)"
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.25
    done
    if kill -0 "$pid" 2>/dev/null; then
        warn "$name não respondeu ao SIGTERM; enviando SIGKILL"
        kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
    ok "$name parado"
}

stop_pid "Backend BMO" "$RUN_DIR/bmo.pid" "bmo_backend"
stop_pid "Mopidy" "$RUN_DIR/mopidy.pid" "mopidy"

echo
