#!/usr/bin/env bash
# Prepara o backend Python e verifica as ferramentas locais.

set -Eeuo pipefail

# Cores do BMO
C1='\033[38;5;80m'
C2='\033[38;5;117m'
C3='\033[38;5;119m'
C4='\033[38;5;24m'
C5='\033[38;5;203m'
RESET='\033[0m'

# Exibe o banner
printf '%b' "$C1"
echo '  ███████╗ █████╗ ████████╗██╗   ██╗██████╗ ███╗   ██╗'
echo '  ██╔════╝██╔══██╗╚══██╔══╝██║   ██║██╔══██╗████╗  ██║'

printf '%b' "$C2"
echo '  ███████╗███████║   ██║   ██║   ██║██████╔╝██╔██╗ ██║'

printf '%b' "$C1"
echo '  ╚════██║██╔══██║   ██║   ██║   ██║████╗   ██║╚██╗██║'
echo '  ███████║██║  ██║   ╚██████╔╝██║  ██║╚██████╔╝██║ ╚████║'

printf '%b' "$C4"
echo '  ╚══════╝╚═╝  ╚═╝    ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝'

printf '%b\n' "${RESET}"
echo '=============================================='

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
cd "$BACKEND"

# Verifica o Python
if ! command -v python3 >/dev/null 2>&1; then
    printf '%b\n' "${C5}ERRO: python3 não encontrado.${RESET}" >&2
    exit 1
fi

# Cria o ambiente virtual
if [[ ! -d .venv ]]; then
    echo "[setup] Criando ambiente virtual em backend/.venv"
    python3 -m venv .venv
fi

# Instala as dependências
echo "[setup] Instalando dependências Python"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ -f requirements-dev.txt ]]; then
    .venv/bin/python -m pip install -r requirements-dev.txt
fi

# Prepara os dados locais
mkdir -p data

echo "[setup] Gerando/verificando token local"
TOKEN="$(.venv/bin/python -m bmo_backend --print-token)"

if [[ -z "$TOKEN" ]]; then
    printf '%b\n' "${C5}ERRO: não foi possível obter o token.${RESET}" >&2
    exit 1
fi

echo "[ok] Token disponível em backend/data/token"

# Verifica arquivos
check_file() {
    local label="$1"
    local path="$2"

    if [[ -f "$path" ]]; then
        printf '%b\n' "${C3}[ok]${RESET} $label: $path"
    else
        printf '%b\n' "${C5}[falta]${RESET} $label: $path"
    fi
}

# Verifica executáveis
check_cmd() {
    local label="$1"
    local cmd="$2"

    if command -v "$cmd" >/dev/null 2>&1; then
        printf '%b\n' "${C3}[ok]${RESET} $label: $(command -v "$cmd")"
    else
        printf '%b\n' "${C5}[falta]${RESET} $label: $cmd"
    fi
}

echo
echo "[setup] Verificação de ferramentas"

check_file "Whisper.cpp" "$ROOT/tools/whisper.cpp/build/bin/whisper-cli"
check_file "Modelo Whisper" "$ROOT/tools/whisper-models/ggml-base.bin"
check_file "Piper" "$ROOT/tools/piper/piper"
check_file "Voz Piper pt-BR" "$ROOT/tools/voices/pt_BR-faber-medium.onnx"

check_cmd "espeak-ng" "espeak-ng"
check_cmd "ffmpeg" "ffmpeg"
check_cmd "Ollama" "ollama"

# Verifica os modelos locais sem obrigar o uso de um modelo específico
echo
echo "[setup] Modelos Ollama"

if command -v ollama >/dev/null 2>&1; then
    if ollama list; then
        echo
        echo "[info] Você pode selecionar um dos modelos instalados na configuração do BMO."
    else
        echo "[aviso] Não foi possível consultar os modelos do Ollama."
        echo "[info] Verifique se o serviço está iniciado com: ollama serve"
    fi
else
    echo "[aviso] Ollama não está instalado ou não está no PATH."
    echo "[info] Instale o Ollama para utilizar modelos locais."
fi

echo
echo "[setup] Próximos passos:"
echo "  1. Inicie o Ollama, se necessário: ollama serve"
echo "  2. Baixe um modelo de sua preferência: ollama pull NOME_DO_MODELO"
echo "  3. Inicie o backend: ./backend/run.sh"
echo "  4. Consulte o token: cat backend/data/token"
echo "  5. Configure IP, porta e token no aplicativo Android."
echo
echo "Para instruções adicionais, consulte docs/INSTALACAO.md."
