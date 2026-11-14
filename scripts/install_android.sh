#!/usr/bin/env bash
# Compila (opcional) e instala o APK de depuração no aparelho conectado.
#
# Uso:
#   scripts/install_android.sh             # compila e instala
#   scripts/install_android.sh --no-build  # instala o APK já compilado
#
# Ao final, mostra a versão e a data de instalação registradas no Android,
# para confirmar que o aparelho está rodando o APK novo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK="$ROOT/android-app/app/build/outputs/apk/debug/app-debug.apk"
PACKAGE="com.spacexjr.saturnbmo.debug"

BUILD=1
for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD=0 ;;
    -h|--help)
      sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "ERRO: argumento desconhecido: $arg" >&2
      exit 1
      ;;
  esac
done

choose_java_home() {
  if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/javac" ]; then
    return 0
  fi
  local candidate
  for candidate in \
    "$HOME/.local/jdks"/jdk-21* \
    "$HOME/.local/jdks"/jdk-17* \
    "$HOME/.local"/jdk-21* \
    "$HOME/.local"/jdk-17* \
    /usr/lib/jvm/java-21-openjdk* \
    /usr/lib/jvm/java-17-openjdk*; do
    if [ -x "$candidate/bin/javac" ]; then
      export JAVA_HOME="$candidate"
      return 0
    fi
  done
  echo "ERRO: nenhum JDK com javac encontrado." >&2
  exit 1
}

devices_online() {
  adb devices 2>/dev/null | awk 'NR>1 && $2=="device"' | wc -l
}

if ! command -v adb >/dev/null 2>&1; then
  echo "ERRO: adb não encontrado. Instale platform-tools ou adicione ao PATH." >&2
  exit 1
fi

online="$(devices_online)"
if [ "$online" -eq 0 ]; then
  echo "ERRO: nenhum aparelho autorizado conectado." >&2
  echo "Conecte o celular por USB (ou 'adb connect IP:5555') e autorize a depuração USB." >&2
  adb devices >&2 || true
  exit 2
fi

if [ "$BUILD" -eq 1 ]; then
  choose_java_home
  echo "[install] compilando APK de depuração..."
  "$ROOT/scripts/build_android.sh" debug >/dev/null
fi

if [ ! -f "$APK" ]; then
  echo "ERRO: APK não encontrado em $APK. Rode sem --no-build." >&2
  exit 1
fi

echo "[install] APK: $(stat -c '%y (%s bytes)' "$APK")"
echo "[install] instalando em $PACKAGE ..."
adb install -r "$APK"

echo "[install] conferindo o que ficou no aparelho:"
adb shell dumpsys package "$PACKAGE" 2>/dev/null \
  | grep -E "versionCode=|versionName=|lastUpdateTime=|firstInstallTime=" \
  | sed 's/^ */  /' || true

echo "[install] Ajustes > Sobre o aplicativo mostra a mesma data de instalação."
