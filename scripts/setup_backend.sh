#!/usr/bin/env bash
# Compatibilidade: nome antigo do setup. Use ./scripts/setupbackend.sh.
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/setupbackend.sh" "$@"
