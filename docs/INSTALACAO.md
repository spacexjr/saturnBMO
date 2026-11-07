# Instalação

Este guia monta o backend local no PC e o app Android. O projeto foi testado em **Fedora 44**, **Python 3.14**, **JDK 25**, **Gradle 9.3**, **Android SDK 36** e em um **Xiaomi 2412DPC0AI real com Android 17**. Outras distribuições e versões compatíveis devem funcionar, mas os comandos de instalação de pacotes variam.

## 1. Visão geral

Você precisa de:

1. PC e celular na mesma rede local (Wi-Fi ou Ethernet).
2. Backend Python rodando no PC.
3. Ollama com um modelo local.
4. Whisper.cpp com modelo de reconhecimento de fala.
5. Piper com voz pt-BR **ou** espeak-ng como fallback.
6. APK instalado no celular.
7. Internet no PC apenas para a consulta de clima (opcional).

O celular não precisa de internet, apenas de acesso ao PC.

## 2. Pacotes do sistema

### Fedora

```bash
sudo dnf install python3 python3-pip python3-virtualenv ffmpeg espeak-ng \
  cmake gcc-c++ make git java-17-openjdk-devel android-tools
```

Se for usar a versão do JDK já instalada (testado com JDK 25), mantenha-a. O projeto exige Java 17+.

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip ffmpeg espeak-ng \
  cmake build-essential git openjdk-17-jdk adb
```

### Android SDK

Instale o Android Studio ou o command-line tools. O build usa:

- `compileSdk = 36`
- `minSdk = 26`
- `targetSdk = 36`
- Build Tools 36.0.0 (ou compatível)

Defina `ANDROID_HOME` ou crie `android-app/local.properties`:

```properties
sdk.dir=/home/SEU_USUARIO/Android/Sdk
```

O arquivo `local.properties` é local e está no `.gitignore`.

## 3. Backend Python

Na raiz do projeto:

```bash
./scripts/setup_backend.sh
```

O script:

- cria `backend/.venv`;
- instala `backend/requirements.txt` e `backend/requirements-dev.txt`;
- cria `backend/data/token` se ainda não existir;
- verifica os caminhos de Whisper, Piper, espeak-ng e Ollama;
- lista o que estiver faltando.

Para executar manualmente:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m bmo_backend --print-token
```

## 4. Ollama e modelo de linguagem

Instale o Ollama pelo site oficial e baixe um modelo. O padrão do projeto é:

```bash
ollama pull qwen3.5:2b
ollama list
```

O Ollama deve escutar em `127.0.0.1:11434` (padrão). O backend acessa essa URL.

Para usar outro modelo, edite `backend/config.json`:

```json
"llm": {
  "model": "gemma3:1b"
}
```

Ou use a variável de ambiente:

```bash
export BMO_LLM_MODEL=gemma3:1b
```

Modelos menores respondem mais rápido, mas erram mais. O teste registrado usou `qwen3.5:2b`.

## 5. Whisper.cpp

O backend chama o binário `whisper-cli` e um modelo `.bin`.

Caminhos esperados por padrão:

```text
tools/whisper.cpp/build/bin/whisper-cli
tools/whisper-models/ggml-base.bin
```

Compilação resumida:

```bash
git clone https://github.com/ggml-org/whisper.cpp tools/whisper.cpp
cmake -S tools/whisper.cpp -B tools/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build tools/whisper.cpp/build -j"$(nproc)"
mkdir -p tools/whisper-models
curl -L -o tools/whisper-models/ggml-base.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
```

Se os caminhos forem diferentes, ajuste `backend/config.json` em `stt.binary` e `stt.model`, ou use:

```bash
export BMO_STT_BINARY=/caminho/para/whisper-cli
export BMO_STT_MODEL=/caminho/para/ggml-base.bin
```

O modelo `base` foi usado nos testes. Modelos maiores tendem a transcrever melhor, mas consomem mais CPU/RAM.

## 6. Piper e voz pt-BR

Caminhos esperados:

```text
tools/piper/piper
tools/voices/pt_BR-faber-medium.onnx
```

Baixe o binário do Piper em <https://github.com/rhasspy/piper/releases> e a voz `pt_BR-faber-medium` em <https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR/faber/medium>. O binário precisa ser executável:

```bash
chmod +x tools/piper/piper
```

Teste rápido:

```bash
echo "Olá, eu sou o BMO." | tools/piper/piper \
  -m tools/voices/pt_BR-faber-medium.onnx \
  -f /tmp/bmo-teste.wav
ffplay /tmp/bmo-teste.wav
```

Se o Piper não estiver disponível, o backend tenta o **espeak-ng** com voz `pt-br`:

```bash
espeak-ng -v pt-br -w /tmp/bmo-teste-espeak.wav "Olá, eu sou o BMO."
```

O Piper é preferido por ter voz mais natural. O fallback por espeak-ng mantém o app funcional.

Para trocar o motor:

```json
"tts": {
  "engine": "piper"
}
```

Valores: `auto`, `piper`, `espeak`.

## 7. Token de acesso

O token é gerado automaticamente no primeiro uso e fica em:

```text
backend/data/token
```

Para imprimir:

```bash
cd backend
.venv/bin/python -m bmo_backend --print-token
```

O arquivo tem permissão `600` quando possível. Também é possível definir o token por ambiente:

```bash
export BMO_TOKEN="um-token-longo-e-aleatorio"
```

O app guarda o token cifrado com Android Keystore. O token não deve ser colocado em prints, issues ou repositórios.

## 8. Clima e previsão do tempo

O BMO consulta temperatura e previsão de chuva pela internet usando o **Open-Meteo**, sem chave de API. A localização vem do **GPS do celular** (ou da rede Wi-Fi/celular), enviada pelo app ao backend como latitude e longitude. O áudio e o texto da conversa não são enviados: apenas as coordenadas.

Na primeira conexão, o app pede a permissão de localização. Também é possível autorizar depois em **Ajustes → Localização (clima)**. Se a permissão for negada, o backend responde pedindo para ativar o GPS; não há cidade padrão nem estimativa por IP.

A cidade no `config.json` é apenas uma alternativa manual. Para usar o GPS, deixe os campos vazios:

```json
"weather": {
  "enabled": true,
  "location": "",
  "latitude": null,
  "longitude": null,
  "timezone": "auto",
  "timeout_s": 10,
  "cache_ttl_s": 600
}
```

- `location`: vazio = usa o GPS do app. Preencha apenas para fixar uma cidade manualmente.
- `latitude`/`longitude`: alternativa manual quando o app não envia coordenadas; use os dois juntos.
- `cache_ttl_s`: tempo em segundos para reaproveitar a previsão (padrão 600 = 10 min).

Também é possível configurar uma cidade manual por ambiente:

```bash
export BMO_WEATHER_LOCATION="São Paulo"
```

O PC precisa de saída HTTPS para `api.open-meteo.com`. O nome da cidade é obtido com `api.bigdatacloud.net`; se esse serviço falhar, a resposta usa “sua localização” e a previsão continua funcionando. Perguntas como “vai chover hoje?”, “qual a temperatura?” e “como está o tempo amanhã?” são respondidas localmente, sem passar pelo LLM, e faladas pelo TTS.

## 9. Iniciar o backend

```bash
./backend/run.sh
```

Saída esperada (resumida):

```text
INFO bmo.server: API em http://0.0.0.0:8765
INFO bmo.discovery: Descoberta UDP ativa na porta 8766
```

Teste no próprio PC:

```bash
curl http://127.0.0.1:8765/health
curl -H "Authorization: Bearer $(cat backend/data/token)" \
  http://127.0.0.1:8765/api/v1/info
```

### Firewall

Libere as portas na rede local:

```bash
# Fedora / firewalld
sudo firewall-cmd --add-port=8765/tcp --add-port=8766/udp
sudo firewall-cmd --runtime-to-permanent
```

```bash
# Ubuntu / ufw
sudo ufw allow 8765/tcp
sudo ufw allow 8766/udp
```

Não faça port forwarding no roteador. O serviço é para LAN, sem TLS.

## 10. Build do app Android

### Debug

```bash
./scripts/build_android.sh debug
adb install -r android-app/app/build/outputs/apk/debug/app-debug.apk
```

### Release assinado

```bash
./scripts/generate_release_keystore.sh   # uma vez
./scripts/build_android.sh release
adb install -r android-app/app/build/outputs/apk/release/app-release.apk
```

O APK release usa o applicationId `com.spacexjr.saturnbmo`; o debug usa `com.spacexjr.saturnbmo.debug`. Os dois podem ficar instalados ao mesmo tempo.

## 11. Conectar o app

### Pela rede Wi-Fi (uso normal)

1. Descubra o IP do PC:

   ```bash
   ip -4 -o addr show | grep -v ' lo '
   ```

2. No celular, abra o app e toque no rosto.
3. Toque em **⚙ Ajustes**.
4. Informe o IP, a porta `8765` e o token.
5. Toque em **Testar** e confira LLM/STT/TTS.
6. Toque em **Salvar e conectar**.
7. Autorize a localização quando o app pedir (ou em **Ajustes → Localização (clima)**). O clima não usa cidade padrão.

Se a rede tiver isolamento de clientes (AP isolation) ou firewall bloqueando, o celular não verá o PC. Veja [SOLUCAO_DE_PROBLEMAS.md](SOLUCAO_DE_PROBLEMAS.md).

### Por USB, só para desenvolvimento

```bash
adb reverse tcp:8765 tcp:8765
adb shell am start -n com.spacexjr.saturnbmo.debug/com.spacexjr.saturnbmo.MainActivity \
  --es bmo_host 127.0.0.1 --ei bmo_port 8765 \
  --es bmo_token "$(cat backend/data/token)"
```

O `adb reverse` encaminha a porta do celular para o PC via USB. Não é o modo de uso final.

## 12. Testes de áudio

No app, em **Ajustes → Áudio**:

- **Testar alto-falante:** deve emitir um tom de 440 Hz.
- **Testar microfone:** deve mostrar o nível variando quando você fala.

O teste de microfone é local: o áudio não é enviado ao PC nem gravado.

## 13. Serviço em segundo plano

Ative **Escuta com tela desligada** em Ajustes. O Android mostra uma notificação persistente “BMO — Microfone ativo”. Com a tela apagada, o serviço mantém o microfone e a conexão.

Observações:

- O Android pode exigir permissão de notificações (Android 13+).
- Fabricantes como Xiaomi podem encerrar serviços em segundo plano; permita o app na lista de exceções de bateria.
- Se o microfone for pausado, o serviço encerra depois de alguns segundos.

## 14. Verificação final

```bash
# Backend
cd backend && .venv/bin/python -m pytest -q

# E2E com serviços reais
.venv/bin/python ../scripts/e2e_ws.py --text "Ei, BMO, que horas são?"

# Android debug
cd ../android-app && ./gradlew assembleDebug

# APK release
cd .. && ./scripts/build_android.sh release
```
