#!/usr/bin/env bash
# Compila o APK de depuração ou o release assinado.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-debug}"

# O Gradle pode escolher um JRE sem javac (por exemplo, java-25-openjdk).
# Preferimos um JAVA_HOME válido ou um JDK local com compilador.
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
  echo "Instale um JDK 17+ ou defina JAVA_HOME para um JDK válido." >&2
  exit 1
}

choose_java_home
echo "[build] JAVA_HOME=$JAVA_HOME"

if [ -z "${ANDROID_HOME:-}" ] && [ -d "$HOME/Android/Sdk" ]; then
  export ANDROID_HOME="$HOME/Android/Sdk"
fi
if [ -n "${ANDROID_HOME:-}" ]; then
  export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
  echo "[build] ANDROID_HOME=$ANDROID_HOME"
fi

cd "$ROOT/android-app"

case "$MODE" in
  debug)
    echo "[build] Compilando APK debug"
    ./gradlew assembleDebug
    APK="$ROOT/android-app/app/build/outputs/apk/debug/app-debug.apk"
    ;;
  release)
    PROP="$ROOT/android-app/keystore/keystore.properties"
    if [ ! -f "$PROP" ]; then
      echo "ERRO: keystore não encontrado." >&2
      echo "Execute: ./scripts/generate_release_keystore.sh" >&2
      exit 1
    fi
    STORE_FILE="$(sed -n 's/^storeFile=//p' "$PROP")"
    STORE_PASS="$(sed -n 's/^storePassword=//p' "$PROP")"
    KEY_ALIAS="$(sed -n 's/^keyAlias=//p' "$PROP")"
    KEY_PASS="$(sed -n 's/^keyPassword=//p' "$PROP")"
    if [ -z "$STORE_FILE" ] || [ -z "$STORE_PASS" ] || [ -z "$KEY_ALIAS" ]; then
      echo "ERRO: keystore.properties incompleto." >&2
      exit 1
    fi
    case "$STORE_FILE" in
      /*) KEYSTORE="$STORE_FILE" ;;
      *) KEYSTORE="$ROOT/android-app/$STORE_FILE" ;;
    esac
    if [ ! -f "$KEYSTORE" ]; then
      echo "ERRO: keystore não encontrado em $KEYSTORE" >&2
      exit 1
    fi
    echo "[build] Compilando APK release assinado"
    BMO_KEYSTORE="$KEYSTORE" \
    BMO_KEY_ALIAS="$KEY_ALIAS" \
    BMO_STORE_PASSWORD="$STORE_PASS" \
    BMO_KEY_PASSWORD="$KEY_PASS" \
      ./gradlew assembleRelease
    APK="$ROOT/android-app/app/build/outputs/apk/release/app-release.apk"
    ;;
  *)
    echo "Uso: $0 [debug|release]" >&2
    exit 2
    ;;
esac

if [ ! -f "$APK" ]; then
  echo "ERRO: APK não encontrado em $APK" >&2
  exit 1
fi

echo
echo "[build] APK: $APK"
echo "[build] Tamanho: $(du -h "$APK" | cut -f1)"
echo "[build] SHA-256: $(sha256sum "$APK" | cut -d' ' -f1)"
