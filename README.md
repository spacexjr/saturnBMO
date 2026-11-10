# saturnBMO

BMO de mesa com rosto animado no Android e processamento de voz/IA no PC.

O celular Android é a interface: mostra o rosto do BMO em paisagem, captura o microfone e reproduz a voz. O PC executa o backend local com detecção de fala, transcrição, LLM, ferramentas e síntese de voz. Áudio e texto da conversa não são enviados para nuvem.

> Estado atual: funcional em rede local. O backend e os testes automatizados rodam de ponta a ponta no PC. A validação com voz humana real da palavra de ativação acústica ainda está pendente; veja [Limitações](docs/LIMITACOES.md).

## Funcionalidades

- Rosto do BMO ocupando a tela inteira, em paisagem, sem barras do sistema.
- Cenas procedurais 8-bit desenhadas sobre os PNGs originais: clima, astronomia, matemática, ciência e música.
- **Música real com Mopidy + YouTube Music**: busca, reprodução, pausa, próxima/anterior, parar, volume, fila, playlists e músicas curtidas. Título, artista, posição, duração e fila vêm do player real; o BitChord 1.8 continua disponível via MPRIS como alternativa.
- Controles de música no app Android e por voz, com confirmação do Mopidy antes de o BMO afirmar que a música começou.
- Indicadores procedurais das operações reais: pesquisando, lendo, abrindo/fechando app, arquivos, sistema, confirmação, sucesso e erro.
- Controles escondidos: toque no rosto mostra/oculta; toque longo abre os ajustes.
- Microfone PCM 16 kHz mono, em blocos de 20 ms, com VAD por energia no PC.
- STT local com **Faster-Whisper** (principal), modelo, `compute_type`, `beam_size`, VAD e idioma configuráveis.
- Whisper.cpp preservado como fallback opcional.
- Palavra de ativação em modo **híbrido**: classificador acústico `saturnbmo.onnx` + verificação por transcrição.
- Conversa com Ollama em português do Brasil, com tool calling nativo.
- Voz local com Piper (pt-BR) e fallback para espeak-ng.
- Internet: `web_search`, `open_url`, `read_webpage`, `extract_page_content` e `summarize_web_content`.
- Controle de aplicativos no KDE/Nobara: listar, abrir, fechar, minimizar, maximizar, restaurar e trazer para frente.
- Ferramentas de música para o LLM: `music_search`, `music_play`, `music_pause`, `music_resume`, `music_stop`, `music_next`, `music_previous`, `music_set_volume`, `music_get_volume`, `music_get_state`, `music_get_now_playing`, `music_queue_*`, `music_playlist_*` e `music_liked_songs`.
- BitChord 1.8 via MPRIS/D-Bus preservado como player alternativo: play, pause, próxima, anterior, parar e volume.
- Arquivos confinados a uma pasta autorizada, escolhida por seletor nativo (`kdialog`/`zenity`): listar, buscar, ler, criar, editar, renomear, copiar, mover, excluir e metadados.
- Exclusões exigem confirmação explícita no app ou por voz/texto.
- Informações do sistema (CPU, memória, disco, uptime etc.) sem shell arbitrário.
- WebSocket autenticado por token e protocolo versionado `bmo/1`.
- Descoberta do PC na rede local por UDP broadcast.
- Reconexão automática, serviço em primeiro plano e logs de diagnóstico.
- Sem câmera, sem gravação de áudio em arquivo e sem comandos de shell arbitrários.

## Arquitetura

```text
┌─────────────────────────────┐        Wi-Fi local         ┌──────────────────────────────────┐
│ Celular Android             │                            │ PC Linux (Nobara/KDE)            │
│                             │  WebSocket bmo/1 + token   │                                  │
│  Rosto / Compose            │ <────────────────────────> │  FastAPI + Uvicorn               │
│  AudioRecord 16 kHz PCM16   │      áudio binário         │  VAD + Faster-Whisper (STT)      │
│  AudioTrack streaming       │                            │  Wakeword ONNX + transcrição     │
│  Android Keystore (token)   │                            │  Ollama (LLM + ferramentas)      │
│  Serviço em 1º plano        │                            │  Piper / espeak-ng (TTS)         │
│  Mopidy + YouTube Music          │
│                             │       UDP 8766             │  MPRIS, XDG, arquivos, internet  │
└─────────────────────────────┘                            └──────────────────────────────────┘
```

O celular não executa LLM nem STT. As ferramentas locais são expostas ao modelo por um registro validado; não há execução de shell arbitrário. Operações destrutivas de arquivo passam por confirmação.

## Requisitos

### PC

- Linux (testado no Fedora/Nobara, Python 3.12).
- Python 3.11+ e `ffmpeg`.
- [Ollama](https://ollama.com/) com um modelo local; o padrão do repositório é `qwen3:8b`.
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) (instalado via `requirements.txt`; o modelo é baixado no primeiro uso).
- [Piper](https://github.com/rhasspy/piper) com voz `pt_BR-faber-medium.onnx`; `espeak-ng` como fallback.
- [Mopidy 4](https://mopidy.com/) rodando em `127.0.0.1:6680` para música do YouTube Music; veja [docs/MUSICA.md](docs/MUSICA.md).
- `ytmusicapi` e `yt-dlp` (já em `backend/requirements.txt`). Busca e reprodução funcionam sem login; playlists/curtidas exigem `ytmusicapi browser`.
- `playerctl` e/ou `busctl` para MPRIS/BitChord (alternativa).
- `kdialog` (KDE) ou `zenity` para o seletor nativo de pastas.
- Portas `8765/tcp` e `8766/udp` liberadas na rede local.
- Internet no PC apenas para as ferramentas web. Clima usa Open-Meteo.

### Android

- Android 8.0+ (API 26+).
- Permissão de microfone; localização opcional para clima.
- Mesma rede Wi-Fi do PC, ou USB com `adb reverse` para testes.
- APK de depuração para desenvolvimento; release para uso normal.

## Início rápido

### 1. Preparar o backend

```bash
cd /caminho/para/saturnBMO
./scripts/setup_backend.sh
```

O script cria `backend/.venv`, instala as dependências, gera o token em `backend/data/token` e confere as ferramentas. Ele não baixa modelos grandes automaticamente; siga [docs/INSTALACAO.md](docs/INSTALACAO.md) para Piper, Faster-Whisper e Ollama.

Inicie o Ollama e baixe o modelo, se ainda não existir:

```bash
ollama serve
ollama pull qwen3:8b
```

Se o PC tiver pouca memória, troque `llm.model` em `backend/config.json` por um modelo menor disponível em `ollama list`.

Inicie o backend:

```bash
./backend/run.sh
```

Saída esperada: API em `http://0.0.0.0:8765` e descoberta UDP na porta 8766. O token está em:

```bash
cat backend/data/token
```

### 2. Ativar a música (Mopidy + YouTube Music)

Instale e configure o Mopidy uma única vez:

```bash
sudo dnf install mopidy gstreamer1-plugins-good gstreamer1-plugins-bad-free ffmpeg
mkdir -p ~/.config/mopidy
cp docs/mopidy.conf.example ~/.config/mopidy/mopidy.conf
systemctl --user enable --now mopidy
```

Mantenha o Mopidy em `127.0.0.1:6680`. O backend fala com ele por JSON-RPC e
o app usa somente a API autenticada do BMO. Busca e reprodução do YouTube Music
funcionam sem login; para playlists e músicas curtidas, gere
`backend/data/ytmusic_auth.json` com `cd backend && .venv/bin/ytmusicapi browser`.
Passo a passo completo, segurança e limitações em **[docs/MUSICA.md](docs/MUSICA.md)**.

### 3. Autorizar uma pasta no PC

No app: **Ajustes → Pasta de acesso do BMO → Escolher pasta no PC**. O seletor nativo abre na tela do PC. A escolha fica em `backend/data/access.json` e pode ser revogada a qualquer momento. Sem pasta autorizada, as ferramentas de arquivo recusam todas as operações.

### 4. Gerar e instalar o APK

```bash
./scripts/build_android.sh debug
adb install -r android-app/app/build/outputs/apk/debug/app-debug.apk
```

Para release assinado, veja [Build](#build).

### 5. Configurar no celular

1. Abra o app. A tela deve mostrar somente o rosto do BMO.
2. Toque no rosto e em **⚙ Ajustes** (ou toque e segure).
3. Informe o IP do PC, a porta `8765` e o token de `backend/data/token`.
4. Toque em **Testar**. LLM, STT e TTS devem aparecer como `ok`.
5. Toque em **Salvar e conectar**.
6. Autorize a localização quando pedido (opcional, usada apenas para clima).
7. Toque no botão do microfone e diga **“Ei, BMO”** seguido do pedido.

Atalho de desenvolvimento: o APK debug aceita extras de conexão:

```bash
adb shell am start -n com.spacexjr.saturnbmo.debug/com.spacexjr.saturnbmo.MainActivity \
  --es bmo_host 192.168.0.10 --ei bmo_port 8765 \
  --es bmo_token "$(cat backend/data/token)"
```

Para teste via USB:

```bash
adb reverse tcp:8765 tcp:8765
adb shell am start -n com.spacexjr.saturnbmo.debug/com.spacexjr.saturnbmo.MainActivity \
  --es bmo_host 127.0.0.1 --ei bmo_port 8765 \
  --es bmo_token "$(cat backend/data/token)"
```

## Uso

- **Rosto somente:** o app abre sem botões. Toque no rosto para revelar os controles.
- **Falar agora:** ativa o microfone e ignora a palavra de ativação uma vez.
- **Digitar:** conversa por texto, útil se o microfone ou o TTS falharem.
- **Música:** toque em **Música** para buscar no YouTube Music, tocar ou adicionar à fila. Quando algo está tocando, aparece uma barra com título, progresso, volume e botões de anterior, play/pause, próxima e parar.
- **Música por voz:** peça, por exemplo, “toque Legião Urbana”, “pause a música”, “aumente o volume para 40” ou “qual está tocando?”. O BMO só confirma depois de consultar o Mopidy.
- **Confirmação:** exclusões mostram um diálogo com **Confirmar** e **Cancelar**; também é possível responder “sim” ou “não” por voz/texto.
- **Parar fala:** interrompe a reprodução e a resposta em andamento.
- **Testar alto-falante/microfone:** tom de 440 Hz e medidor local de nível.

### Palavra de ativação

O modo padrão é **hybrid**:

- o classificador acústico ONNX (`wakeword/saturnbmo.onnx`) roda no áudio de entrada;
- a transcrição do Faster-Whisper continua como fallback;
- frases aceitas incluem “Ei BMO”, “Hey BMO”, “Hey Beemo”, “Be eme ó” e variantes normalizadas;
- há cooldown e o BMO ignora o próprio áudio durante a fala.

O modelo acústico e os modelos de mel/embedding estão em `wakeword/`. A detecção foi validada apenas com áudio sintético; **áudio de voz humana real ainda precisa ser testado**. Veja [Limitações](docs/LIMITACOES.md).

## Configuração

O arquivo principal é `backend/config.json`. Variáveis de ambiente sobrescrevem valores (`BMO_HOST`, `BMO_PORT`, `BMO_LLM_MODEL`, `BMO_STT_MODEL`, `BMO_STT_COMPUTE_TYPE`, `BMO_WAKEWORD_MODE`, `BMO_TOOLS_ENABLED`, etc.). O token pode vir de `BMO_TOKEN`.

Principais opções de STT:

```json
"stt": {
  "engine": "faster_whisper",
  "model": "medium",
  "device": "cpu",
  "compute_type": "int8",
  "language": "pt",
  "beam_size": 5,
  "num_workers": 1,
  "vad_filter": true
}
```

`medium`/`int8` é o padrão atual: melhor precisão que o `small`, com ~3,4 s de inferência para ~1,7 s de áudio em CPU (medido nesta máquina). Se a latência incomodar, volte para `small`; modelos maiores aumentam memória e tempo.

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

O APK fica em `android-app/app/build/outputs/apk/release/app-release.apk`.

## Testes

Backend:

```bash
cd backend
.venv/bin/python -m pytest -q
```

Android:

```bash
cd android-app
JAVA_HOME=/caminho/para/jdk-17-ou-21 ./gradlew testDebugUnitTest
```

Teste E2E com serviços reais (Faster-Whisper, Piper, Ollama e backend):

```bash
cd backend
.venv/bin/python ../scripts/e2e_ws.py \
  --text "Ei, BMO, que horas são?" \
  --output /tmp/bmo-resposta-e2e.wav
```

Estado atual: **76 testes de backend** e **17 testes unitários Android** passam. A validação manual em aparelho real e com voz humana ainda deve ser refeita para o conjunto atual; veja [docs/EVIDENCIAS_TESTES.md](docs/EVIDENCIAS_TESTES.md).

## Segurança e privacidade

- O backend escuta na rede local e exige token Bearer em HTTP e WebSocket.
- O app guarda o token cifrado com AES/GCM e chave do Android Keystore.
- Não há câmera, permissão de câmera, upload de áudio para nuvem ou shell arbitrário.
- Conteúdo web é tratado como não confiável; URLs privadas/loopback são bloqueadas por padrão.
- Ferramentas de arquivo são confinadas à pasta autorizada, com proteção contra `..` e links simbólicos.
- Exclusões exigem confirmação explícita.
- A API usa HTTP sem TLS para funcionar offline em LAN. Não exponha a porta 8765 à internet.
- Leia [docs/SEGURANCA_E_PRIVACIDADE.md](docs/SEGURANCA_E_PRIVACIDADE.md).

## Estrutura do projeto

```text
backend/                 FastAPI, VAD, STT, LLM, TTS, ferramentas e testes
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
tools/                   Binários/modelos locais (não versionados)
wakeword/                Modelo acústico e modelos de mel/embedding
```

## Documentação

- [Instalação](docs/INSTALACAO.md)
- [Protocolo bmo/1](docs/PROTOCOLO.md)
- [Segurança e privacidade](docs/SEGURANCA_E_PRIVACIDADE.md)
- [Solução de problemas](docs/SOLUCAO_DE_PROBLEMAS.md)
- [Limitações conhecidas](docs/LIMITACOES.md)
- [Evidências de teste](docs/EVIDENCIAS_TESTES.md)

## 3D

Tem que imprimir em escala 113%.

## Licença e créditos

Os rostos e o arquivo legado `wakeword_hey_jarvis.onnx` vêm do projeto original `be-more-agent`. Consulte [assets/ORIGINAL_LICENSE](assets/ORIGINAL_LICENSE).

O detector `wakeword/saturnbmo.onnx` foi treinado com [livekit-wakeword](https://github.com/livekit/livekit-wakeword); os modelos de mel e embedding acompanham o pipeline do livekit. O código deste projeto é de uso local/educacional; revise as licenças das ferramentas e modelos de terceiros (Faster-Whisper, Whisper.cpp, Piper, Ollama, BitChord, livekit-wakeword e modelos baixados) antes de redistribuir.
