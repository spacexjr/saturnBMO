# saturnBMO

BMO de mesa com rosto animado no Android e processamento de voz/IA no PC.

O celular Android é a interface: mostra apenas o rosto do BMO em paisagem, captura o microfone e reproduz a voz. O PC executa o backend local com detecção de fala, transcrição, LLM e síntese de voz. O áudio não é enviado para nuvem.

> Estado atual: funcional em rede local, com APK de depuração e APK release assinado localmente. A validação manual foi feita em um **Xiaomi 2412DPC0AI real** (Android 17) via Wi-Fi e USB. Veja [docs/EVIDENCIAS_TESTES.md](docs/EVIDENCIAS_TESTES.md).

## Funcionalidades

- Rosto do BMO ocupando a tela inteira, em paisagem, sem barras do sistema.
- Controles escondidos: toque no rosto mostra/oculta; toque longo abre os ajustes.
- Estados visuais: desconectado, conectando, aguardando, ouvindo, pensando, falando e erro.
- Microfone PCM 16 kHz mono, em blocos de 20 ms.
- Reprodução de voz em streaming no alto-falante.
- Detecção de fala por energia (VAD) no PC.
- Transcrição local com whisper.cpp.
- Respostas locais de hora/data sem passar pelo LLM.
- Clima e previsão de chuva pela internet, usando o GPS do celular para localizar você.
- Conversa com Ollama em português do Brasil.
- Voz local com Piper (pt-BR) e fallback para espeak-ng.
- WebSocket autenticado por token e protocolo versionado `bmo/1`.
- Descoberta do PC na rede local por UDP broadcast.
- Reconexão automática com espera progressiva.
- Serviço em primeiro plano para escutar com a tela desligada.
- Configuração de IP, porta, token, volume, tela ligada, reconexão e escuta em segundo plano.
- Testes de alto-falante e de nível do microfone.
- Logs de diagnóstico no app e no backend.
- Sem câmera, sem gravação de áudio em arquivo e sem comandos de shell.

## Arquitetura

```text
┌─────────────────────────────┐        Wi-Fi local         ┌──────────────────────────────┐
│ Celular Android             │                            │ PC Linux                     │
│                             │  WebSocket bmo/1 + token   │                              │
│  Rosto / Compose            │ <────────────────────────> │  FastAPI + Uvicorn           │
│  AudioRecord 16 kHz PCM16   │      áudio binário         │  VAD por energia             │
│  AudioTrack streaming       │                            │  whisper.cpp (STT)           │
│  Android Keystore (token)   │                            │  Ollama (LLM)                │
│  Serviço em 1º plano        │                            │  Piper / espeak-ng (TTS)     │
│                             │       UDP 8766             │  cache de áudio em memória   │
└─────────────────────────────┘                            └──────────────────────────────┘
```

O celular não executa LLM nem STT. O backend também não executa comandos arbitrários: as únicas ações locais autorizadas são `get_time` e `get_date`.

## Requisitos

### PC

- Linux (testado no Fedora 44), Python 3.11+.
- `ffmpeg` (usado pelo teste E2E), `espeak-ng` (fallback de voz).
- [Ollama](https://ollama.com/) com um modelo local, por padrão `qwen3.5:2b`.
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp) com modelo `ggml-base.bin`.
- [Piper](https://github.com/rhasspy/piper) com voz `pt_BR-faber-medium.onnx` (opcional se espeak-ng estiver disponível).
- Portas `8765/tcp` e `8766/udp` liberadas na rede local.

### Android

- Android 8.0+ (API 26+). Testado em Android 17 (API 37).
- Permissão de microfone.
- Mesma rede Wi-Fi do PC, ou USB com `adb reverse` para testes.
- APK de depuração para desenvolvimento; release para uso normal.

## Início rápido

### 1. Preparar o backend

```bash
cd /caminho/para/saturnBMO
./scripts/setup_backend.sh
```

O script cria `backend/.venv`, instala as dependências Python, gera o token em `backend/data/token` e confere as ferramentas. Ele não baixa modelos grandes automaticamente; siga [docs/INSTALACAO.md](docs/INSTALACAO.md) para instalar Whisper, Piper e o modelo do Ollama.

Inicie o Ollama e baixe o modelo, se ainda não existir:

```bash
ollama serve
ollama pull qwen3.5:2b
```

Inicie o backend:

```bash
./backend/run.sh
```

Saída esperada: API em `http://0.0.0.0:8765` e descoberta UDP na porta 8766. O token está em:

```bash
cat backend/data/token
```

### 2. Gerar e instalar o APK

```bash
./scripts/build_android.sh debug
adb install -r android-app/app/build/outputs/apk/debug/app-debug.apk
```

Para release assinado, veja [Build](#build). O APK release fica em `android-app/app/build/outputs/apk/release/app-release.apk`.

### 3. Configurar no celular

1. Abra o app. A tela deve mostrar somente o rosto do BMO.
2. Toque no rosto para mostrar os controles.
3. Toque em **⚙ Ajustes** (ou toque e segure o rosto).
4. Informe o IP do PC, a porta `8765` e o token de `backend/data/token`.
5. Toque em **Testar**. Devem aparecer LLM, STT e TTS como `ok`.
6. Toque em **Salvar e conectar**.
7. Autorize a localização quando o app pedir (ou use **Ajustes → Localização (clima)**). Ela é usada apenas para o clima.
8. Toque no botão do microfone e diga **“Ei, BMO”** seguido do pedido.

Atalho de desenvolvimento: o APK debug aceita extras de conexão:

```bash
adb install -r android-app/app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.spacexjr.saturnbmo.debug/com.spacexjr.saturnbmo.MainActivity \
  --es bmo_host 192.168.3.24 \
  --ei bmo_port 8765 \
  --es bmo_token "$(cat backend/data/token)"
```

Troque `192.168.3.24` pelo IP do seu PC. Em caso de bloqueio de Wi-Fi, para teste via USB:

```bash
adb reverse tcp:8765 tcp:8765
adb shell am start -n com.spacexjr.saturnbmo.debug/com.spacexjr.saturnbmo.MainActivity \
  --es bmo_host 127.0.0.1 --ei bmo_port 8765 \
  --es bmo_token "$(cat backend/data/token)"
```

O `adb reverse` é só para desenvolvimento; não substitui a conexão Wi-Fi real.

## Uso

- **Rosto somente:** o app abre sem botões. Toque no rosto para revelar os controles.
- **Ajustes:** toque no rosto e depois em **⚙ Ajustes**, ou toque e segure o rosto.
- **Falar agora:** ativa o microfone e ignora a palavra de ativação uma vez.
- **Digitar:** abre uma conversa por texto, útil se o microfone ou o TTS falharem.
- **Microfone:** o botão redondo inicia/para a captura. Com a escuta em segundo plano ativa, o serviço mantém o microfone com a tela apagada.
- **Parar fala:** interrompe a reprodução e a resposta em andamento.
- **Testar alto-falante:** emite um tom de 440 Hz.
- **Testar microfone:** mostra o nível local; não envia áudio ao PC.

### Palavra de ativação

A palavra de ativação é **baseada na transcrição**. O áudio é transcrito pelo Whisper.cpp e o texto normalizado é comparado com `ei bmo`, `ei bemo`, `hey bmo`, `oi bmo`, `e bmo` e `bmo`.

Isso **não** é um detector acústico treinado para “Ei, BMO”. O arquivo `wakeword_hey_jarvis.onnx` do projeto original é o modelo “Hey Jarvis” e é preservado apenas como referência; ele não é usado como detector principal. Vamos adicionar wakeword e voz do BMO futuramente. Veja [docs/LIMITACOES.md](docs/LIMITACOES.md).

Vamos melhorar a deteccao de voz futuramente


## Build

### Debug

```bash
./scripts/build_android.sh debug
```

Saída: `android-app/app/build/outputs/apk/debug/app-debug.apk`

### Release assinado

O projeto não guarda a chave de assinatura no repositório. Gere uma chave local uma vez:

```bash
./scripts/generate_release_keystore.sh
```

Depois:

```bash
./scripts/build_android.sh release
```

O script lê `android-app/keystore/keystore.properties` e exporta `BMO_KEYSTORE`, `BMO_KEY_ALIAS`, `BMO_STORE_PASSWORD` e `BMO_KEY_PASSWORD` para o Gradle. O APK fica em:

```text
android-app/app/build/outputs/apk/release/app-release.apk
```

Verificação da assinatura:

```bash
"$ANDROID_HOME/build-tools/36.0.0/apksigner" verify --print-certs \
  android-app/app/build/outputs/apk/release/app-release.apk
```

Os APKs e a pasta `android-app/keystore/` estão no `.gitignore`.

## Testes

Backend:

```bash
cd backend  android-app/app/build/outputs/apk/release/app-release.apk
.venv/bin/python -m pytest -q
```

Testes unitários do Android:

```bash
cd android-app
./gradlew testDebugUnitTest
```

Teste E2E com serviços reais (Whisper, Piper, Ollama e backend):

```bash
cd backend
.venv/bin/python ../scripts/e2e_ws.py \
  --text "Ei, BMO, que horas são?" \
  --output /tmp/bmo-resposta-e2e.wav
```

Resultado registrado: **36 testes de backend** e **3 testes unitários Android** passaram, e o E2E real retornou transcrição, resposta e áudio. Detalhes e limitações em [docs/EVIDENCIAS_TESTES.md](docs/EVIDENCIAS_TESTES.md).

## Segurança e privacidade

- O backend escuta na rede local e exige token Bearer em HTTP e WebSocket.
- O app guarda o token cifrado com AES/GCM e chave do Android Keystore.
- Não há câmera, permissão de câmera, upload para nuvem ou comando de shell.
- A consulta de clima envia apenas as coordenadas do GPS do celular (ou cidade/coordenadas configuradas manualmente) ao Open-Meteo; o nome da cidade pode ser consultado no BigDataCloud. Áudio e texto da conversa não saem do PC.
- Áudio de microfone é transmitido em tempo real, sem gravação em arquivo.
- O backend mantém histórico de conversa apenas em memória por sessão.
- A API usa **HTTP sem TLS** para funcionar offline em LAN. Não exponha a porta 8765 à internet.
- Leia [docs/SEGURANCA_E_PRIVACIDADE.md](docs/SEGURANCA_E_PRIVACIDADE.md).

## Estrutura do projeto

```text
backend/                 FastAPI, VAD, STT, LLM, TTS, protocolo e testes
  bmo_backend/
  tests/
  config.json
  run.sh
android-app/             App Android (Kotlin + Compose)
  app/src/main/java/com/spacexjr/saturnbmo/
  app/src/main/assets/faces/
  app/build.gradle.kts
assets/                  Rosto original, licença e wakeword legado
docs/                    Instalação, protocolo, segurança, limitações e evidências
protocol/schemas/        Esquemas JSON do protocolo bmo/1
scripts/                 Setup, build, E2E e utilitários
tools/                   Binári  android-app/app/build/outputs/apk/release/app-release.apkos/modelos locais (não versionados)
```

## Documentação

- [Instalação](docs/INSTALACAO.md)
- [Protocolo bmo/1](docs/PROTOCOLO.md)
- [Segurança e privacidade](docs/SEGURANCA_E_PRIVACIDADE.md)
- [Solução de problemas](docs/SOLUCAO_DE_PROBLEMAS.md)
- [Limitações conhecidas](docs/LIMITACOES.md)
- [Evidências de teste](docs/EVIDENCIAS_TESTES.md)

## 3D 
Tem que imprimir em escala 113% 

## Licença e créditos

<<<<<<< HEAD
Os rostos e o arquivo legado `wakeword_hey_jarvis.onnx` vêm do projeto original `be-more-agent`. Consulte [assets/ORIGINAL_LICENSE](assets/ORIGINAL_LICENSE).

O detector `saturnbmo.onnx` [nao testado] foi treinado com [livekit-wakeword](https://github.com/livekit/livekit-wakeword) e dados sintéticos; os modelos de mel e embedding acompanham o pipeline do livekit. O código deste projeto é de uso local/educacional; revise as licenças das ferramentas e modelos de terceiros (Whisper.cpp, Piper, Ollama, livekit-wakeword e modelos baixados) antes de redistribuir.
=======
Os rostos e o arquivo `wakeword_hey_jarvis.onnx` vêm do projeto original `be-more-agent`. Consulte [assets/ORIGINAL_LICENSE](assets/ORIGINAL_LICENSE). O código deste projeto é de uso local/educacional; revise as licenças das ferramentas e modelos de terceiros (Whisper.cpp, Piper, Ollama e modelos baixados) antes de redistribuir.
>>>>>>> 59f8aca (REVERSAO DE IMPLEMENTACAO DE WAKEWORD)
