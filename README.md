<div align="center">

# saturnBMO

<img src="assets/faces/happy/happy_02.png" alt="Rosto do saturnBMO" width="360">

### Seu BMO de mesa: Android na interface, Linux no cérebro.

Assistente de voz local com reconhecimento de fala, IA, ferramentas, música e síntese de voz.

**Privacidade local · Android + PC · Português do Brasil**

</div>

---

## Sobre o projeto

O **saturnBMO** transforma um celular Android em um BMO de mesa interativo. O telefone funciona como rosto, microfone e alto-falante; um computador Linux executa o processamento de voz, o modelo de linguagem e as ferramentas.

A comunicação acontece pela rede local usando WebSocket autenticado. O áudio e o texto da conversa são processados localmente e não são enviados para serviços de IA na nuvem.

> **Estado do projeto:** o sistema funciona em rede local e os testes automatizados do backend e do Android passam. A validação da palavra de ativação com voz humana real ainda está pendente. Consulte [Limitações conhecidas](docs/LIMITACOES.md).

## Índice

- [Funcionalidades](#funcionalidades)
- [Arquitetura](#arquitetura)
- [Tecnologias](#tecnologias)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Configuração do Android](#configuração-do-android)
- [Como usar](#como-usar)
- [Palavra de ativação](#palavra-de-ativação)
- [Configuração avançada](#configuração-avançada)
- [Build](#build)
- [Testes](#testes)
- [Segurança e privacidade](#segurança-e-privacidade)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Documentação](#documentação)
- [Modelo 3D](#modelo-3d)
- [Licença e créditos](#licença-e-créditos)

## Funcionalidades

### Interface e animações

- Rosto do BMO em tela cheia, orientação paisagem e sem barras do sistema.
- Estados visuais para idle, listening, thinking, speaking, sleeping, capturing, error e warmup.
- **Expressões humanas durante a conversa**: piscadas em quase todos os rostos, emoção extraída do texto da resposta (alegria, tristeza, surpresa) e camadas 8-bit por cima da fala; a boca só anima quando há som saindo do alto-falante.
- **Dorme sozinho após 10 s** sem atividade, com `assets/faces/sleeping` (olhos fechados) e Zzz animado. Ruído do microfone (VAD, transcrição vazia) não conta como atividade; wake word real, fala, pergunta ou operação acorda na hora.
- **Microfone automático**: ao conectar, o app pede a permissão uma vez e já começa ouvindo a wake word, sem precisar tocar em **Ouvir**.
- **Rosto de música** (`EQUALIZER`) enquanto uma faixa estiver tocando, com título, artista e barras reagindo ao áudio; a música impede o BMO de dormir.
- Cenas procedurais em estilo 8-bit sobre os PNGs originais: clima, astronomia, matemática, ciência e música.
- Indicadores visuais de operações reais: pesquisa, leitura, abertura de aplicativos, arquivos, sistema, confirmação, sucesso e erro.
- Toque no rosto para mostrar ou ocultar controles; toque longo para abrir os ajustes.

### Voz e inteligência artificial

- Captura de áudio PCM 16 kHz, mono, em blocos de 20 ms.
- VAD por energia no PC.
- **Faster-Whisper** como mecanismo principal de transcrição, com modelo, idioma, `compute_type`, `beam_size`, VAD e vocabulário contextual configuráveis.
- Whisper.cpp disponível como alternativa.
- Wake word híbrida: classificador acústico ONNX `saturnbmo.onnx` com verificação por transcrição.
- Conversa com Ollama em português do Brasil, com tool calling, validação de argumentos, timeout por ferramenta e proteção contra chamadas duplicadas.
- Ferramenta real `change_face(expression)`: o modelo escolhe uma das expressões existentes em `assets/faces` e o app aplica a animação em tempo real, com restauração automática ao estado normal.
- Recuperação de chamadas que o modelo eventualmente imprime como JSON: somente ferramentas registradas e argumentos válidos podem ser executados.
- Síntese de voz local com Piper em português do Brasil e fallback para espeak-ng.
- Limpeza de Markdown, blocos de código e conteúdo interno das ferramentas antes da resposta falada.

### Música

Integração principal com **Mopidy 4 + YouTube Music**:

- Busca e reprodução de músicas.
- Pausa, retomada, próxima, anterior e parada.
- Controle de volume e posição.
- Fila de reprodução.
- Playlists e músicas curtidas.
- Informações reais de título, artista, posição e duração.
- Controles pelo aplicativo Android ou por voz.

O **BitChord 1.8** continua disponível como alternativa via MPRIS/D-Bus.

### Ferramentas e controle do PC

- Pesquisa e leitura de páginas na internet.
- Abertura de URLs.
- Controle de aplicativos no KDE: listar, abrir, fechar, minimizar, maximizar, restaurar e trazer para frente.
- Gerenciamento de arquivos dentro de uma pasta autorizada: listar, buscar, ler, criar, editar, renomear, copiar, mover, excluir e consultar metadados.
- Informações do sistema: CPU, memória, armazenamento e uptime.
- Confirmação explícita antes de excluir arquivos.
- Descoberta automática do computador na rede local.
- Reconexão automática e logs de diagnóstico.

## Arquitetura

O Android é a interface física do BMO. O computador concentra o processamento pesado e as integrações locais.

<div align="center">

| Android | PC Linux |
|:---:|:---:|
| Rosto animado em Jetpack Compose | FastAPI + Uvicorn |
| Captura com AudioRecord | VAD + Faster-Whisper |
| Reprodução com AudioTrack | Wake word ONNX |
| Token protegido pelo Android Keystore | Ollama + ferramentas |
| Serviço em primeiro plano | Piper / espeak-ng |
| Controles de música | Mopidy + YouTube Music |
| Conexão WebSocket | MPRIS, XDG, arquivos e internet |

</div>

```text
┌──────────────────────────┐       Wi-Fi / USB       ┌──────────────────────────┐
│       ANDROID            │   WebSocket bmo/1       │        PC LINUX          │
│                          │   + token autenticado   │                          │
│  Rosto / Jetpack Compose │ <─────────────────────> │  FastAPI / Uvicorn       │
│  AudioRecord (PCM 16 kHz)│                         │  VAD / Faster-Whisper    │
│  AudioTrack              │       Áudio             │  Wake word ONNX          │
│  Android Keystore        │                         │  Ollama + Tool Calling   │
│  Serviço em 1º plano     │                         │  Piper / espeak-ng      │
│  Controles de música     │                         │  Mopidy / YouTube Music │
│                          │       UDP 8766          │  Ferramentas locais     │
└──────────────────────────┘                         └──────────────────────────┘
```

O Android não executa o LLM nem a transcrição. O backend não permite execução arbitrária de comandos de shell. As operações com arquivos são limitadas à pasta autorizada pelo usuário.

## Tecnologias

| Componente | Tecnologia |
|---|---|
| Aplicativo | Kotlin + Jetpack Compose |
| Backend | Python + FastAPI |
| Comunicação | WebSocket + protocolo `bmo/1` |
| Descoberta local | UDP broadcast |
| Transcrição | Faster-Whisper |
| Wake word | ONNX + verificação por transcrição |
| Modelo de linguagem | Ollama |
| Síntese de voz | Piper / espeak-ng |
| Música | Mopidy 4 + YouTube Music |
| Player alternativo | BitChord 1.8 via MPRIS |

## Requisitos

### Computador

- Linux (testado no Fedora/Nobara com KDE).
- Python 3.11 ou superior.
- `ffmpeg`.
- [Ollama](https://ollama.com/) com um modelo local. O padrão do repositório é `qwen3:8b`.
- Faster-Whisper, instalado pelas dependências do backend.
- [Piper](https://github.com/rhasspy/piper), com a voz `pt_BR-faber-medium.onnx`; espeak-ng é o fallback.
- [Mopidy 4](https://mopidy.com/), para reprodução de música.
- `ytmusicapi` e `yt-dlp`.
- `playerctl` e/ou `busctl`, para MPRIS.
- `kdialog` ou `zenity`, para selecionar a pasta autorizada.
- Portas `8765/tcp` e `8766/udp` disponíveis na rede local.

### Celular

- Android 8.0 ou superior (API 26+).
- Permissão de microfone.
- Localização opcional, utilizada para recursos de clima.
- Conexão à mesma rede do PC ou USB com `adb reverse`.

## Instalação

### 1. Clonar o repositório

```bash
git clone https://github.com/spacexjr/saturnBMO.git
cd saturnBMO
```

### 2. Preparar o backend

```bash
./scripts/setupbackend.sh
```

O script prepara o ambiente virtual, instala as dependências, gera o token de autenticação em `backend/data/token`, configura o arquivo `.env` e cria a configuração local do Mopidy.

### 3. Preparar o Ollama

Inicie o serviço:

```bash
ollama serve
```

Baixe o modelo padrão:

```bash
ollama pull qwen3:8b
```

Se o computador tiver pouca memória, escolha outro modelo compatível e altere `llm.model` em `backend/config.json`.

### 4. Iniciar o sistema

Para iniciar o Mopidy e o backend juntos:

```bash
./scripts/start-all.sh
```

O script aguarda os serviços ficarem prontos, verifica a API de música e informa o IP e o token necessários para conectar o Android.

Para consultar o estado:

```bash
./scripts/status-all.sh
```

Para parar:

```bash
./scripts/stop-all.sh
```

Também é possível iniciar somente o backend:

```bash
./backend/run.sh
```

O backend disponibiliza a API na porta `8765/tcp` e a descoberta local na porta `8766/udp`.

### 5. Configurar o Mopidy

Instale os pacotes necessários no Fedora/Nobara:

```bash
sudo dnf install mopidy gstreamer1-plugins-good gstreamer1-plugins-bad-free ffmpeg
```

Prepare a configuração:

```bash
mkdir -p ~/.config/mopidy
cp docs/mopidy.conf.example ~/.config/mopidy/mopidy.conf
systemctl --user enable --now mopidy
```

Mantenha o Mopidy restrito a `127.0.0.1:6680`. O backend se comunica com ele por JSON-RPC.

A busca e a reprodução do YouTube Music funcionam sem login. Playlists e músicas curtidas exigem autenticação do `ytmusicapi`:

```bash
./scripts/ytmusic_login.py
```

Consulte o [guia de música](docs/MUSICA.md) para os detalhes.

## Configuração do Android

### 1. Gerar o APK

```bash
./scripts/build_android.sh debug
```

### 2. Instalar no dispositivo

```bash
./scripts/install_android.sh
```

O script compila, instala o APK de depuração (`com.spacexjr.saturnbmo.debug`) e
mostra a versão e a data de instalação registradas no aparelho. Se preferir
instalar um APK já compilado:

```bash
adb install -r android-app/app/build/outputs/apk/debug/app-debug.apk
```

Para conferir sem o PC se a versão instalada é a nova, abra
**Ajustes → Sobre o aplicativo**: a data mostrada é a da instalação do APK.

### 3. Conectar ao computador

1. Abra o saturnBMO no Android.
2. Toque no rosto ou mantenha pressionado para abrir os ajustes.
3. Informe o IP do PC, a porta `8765` e o token salvo em `backend/data/token`.
4. Utilize **Testar** para verificar LLM, STT e TTS.
5. Se estiver tudo certo, selecione **Salvar e conectar**.
6. Autorize o microfone (o pedido aparece sozinho na primeira conexão) e, opcionalmente, a localização. Depois disso o app já começa ouvindo ao conectar, sem precisar tocar em **Ouvir**.

Para desenvolvimento via USB:

```bash
adb reverse tcp:8765 tcp:8765
adb shell am start -n com.spacexjr.saturnbmo.debug/com.spacexjr.saturnbmo.MainActivity \
  --es bmo_host 127.0.0.1 --ei bmo_port 8765 \
  --es bmo_token "$(cat backend/data/token)"
```

## Como usar

- **Falar:** diga “Ei, BMO” e faça seu pedido.
- **Falar agora:** ativa o microfone sem precisar da palavra de ativação naquela interação.
- **Digitar:** permite conversar por texto.
- **Música:** abre os controles para pesquisar, tocar e gerenciar a fila.
- **Parar fala:** interrompe a reprodução da resposta atual.
- **Testar áudio:** reproduz um tom de 440 Hz e exibe o nível do microfone.
- **Confirmações:** operações destrutivas exigem confirmação explícita.

Exemplos de comandos:

```text
Ei, BMO, que horas são?
Ei, BMO, toque Legião Urbana.
Ei, BMO, pause a música.
Ei, BMO, aumente o volume para 40.
Ei, BMO, qual música está tocando?
Ei, BMO, abra o navegador.
```

## Palavra de ativação

O modo padrão é **híbrido**:

1. O classificador acústico ONNX (`wakeword/saturnbmo.onnx`) analisa o áudio.
2. A transcrição do Faster-Whisper funciona como verificação e fallback.
3. Há cooldown para evitar ativações repetidas.
4. O BMO ignora o próprio áudio enquanto está falando.

Frases reconhecidas pelo fluxo incluem:

- Ei BMO
- Hey BMO
- Hey Beemo
- Be eme ó

O detector acústico foi validado com áudio sintético. A validação com gravações de voz humana real ainda está pendente. Consulte [Limitações](docs/LIMITACOES.md).

## Configuração avançada

O arquivo principal é:

```text
backend/config.json
```

As variáveis de ambiente podem sobrescrever configurações, incluindo `BMO_HOST`, `BMO_PORT`, `BMO_LLM_MODEL`, `BMO_STT_MODEL`, `BMO_STT_COMPUTE_TYPE`, `BMO_WAKEWORD_MODE`, `BMO_TOOLS_ENABLED` e `BMO_TOKEN`.

Exemplo de configuração do Faster-Whisper:

```json
{
  "engine": "faster_whisper",
  "model": "medium",
  "device": "cpu",
  "compute_type": "int8",
  "language": "pt",
  "beam_size": 5,
  "cpu_threads": 4,
  "num_workers": 1,
  "vad_filter": true
}
```

`cpu_threads` limita o CTranslate2 a 4 núcleos. Sem esse limite, o modelo
`medium` podia ocupar todos os núcleos em uma única transcrição e travar o
servidor. Áudios novos são descartados enquanto uma inferência está em
andamento, em vez de enfileirar threads.

O perfil `medium`/`int8` é o padrão documentado atualmente. Em uma medição registrada no projeto, a inferência levou aproximadamente 3,4 segundos para processar 1,7 segundo de áudio em CPU. Se a latência for alta, experimente o modelo `small`.

## Build

### APK de depuração

```bash
./scripts/build_android.sh debug
```

Saída:

```text
android-app/app/build/outputs/apk/debug/app-debug.apk
```

### APK de release

Gere uma chave de assinatura local:

```bash
./scripts/generate_release_keystore.sh
```

Depois execute:

```bash
./scripts/build_android.sh release
```

Saída:

```text
android-app/app/build/outputs/apk/release/app-release.apk
```

A chave de assinatura não deve ser enviada ao repositório.

## Testes

### Backend

```bash
cd backend
.venv/bin/python -m pytest -q
```

### Android

```bash
cd android-app
JAVA_HOME=/caminho/para/jdk-17-ou-21 ./gradlew testDebugUnitTest
```

### Teste de ponta a ponta

Com Faster-Whisper, Piper, Ollama e backend disponíveis:

```bash
cd backend
.venv/bin/python ../scripts/e2e_ws.py \
  --text "Ei, BMO, que horas são?" \
  --output /tmp/bmo-resposta-e2e.wav
```

Último resultado documentado no README:

- **114 testes** de backend.
- **17 testes** unitários Android.
- JDK 21.

Os testes automatizados não substituem a validação manual em um aparelho real. Consulte [Evidências de teste](docs/EVIDENCIAS_TESTES.md).

## Segurança e privacidade

- Comunicação autenticada por token Bearer em HTTP e WebSocket.
- Token Android protegido com AES/GCM e Android Keystore.
- Processamento de voz e IA no computador local.
- Sem câmera, permissão de câmera ou gravação de áudio em arquivo.
- Sem execução arbitrária de shell.
- Ferramentas de arquivo limitadas à pasta autorizada.
- Proteção contra caminhos `..` e links simbólicos.
- Exclusões exigem confirmação.
- Conteúdo externo da internet é tratado como não confiável.
- URLs privadas e loopback são bloqueadas por padrão nas ferramentas web.

**Atenção:** a API utiliza HTTP sem TLS para funcionar na rede local. Não exponha a porta `8765` diretamente à internet.

Leia também [Segurança e privacidade](docs/SEGURANCA_E_PRIVACIDADE.md).

## Estrutura do projeto

```text
saturnBMO/
├── android-app/       Aplicativo Android em Kotlin + Compose
├── assets/            Rostos originais e arquivos de licença
├── backend/           API, STT, VAD, LLM, TTS e ferramentas
├── docs/              Guias, limitações e evidências
├── protocol/          Esquemas JSON do protocolo bmo/1
├── scripts/           Instalação, build e testes E2E
├── tools/             Ferramentas e modelos locais
└── wakeword/          Modelo acústico e modelos auxiliares
```

## Documentação

| Documento | Conteúdo |
|---|---|
| [Instalação](docs/INSTALACAO.md) | Dependências e preparação do ambiente |
| [Música](docs/MUSICA.md) | Mopidy e YouTube Music |
| [Protocolo](docs/PROTOCOLO.md) | Comunicação entre Android e PC |
| [Segurança](docs/SEGURANCA_E_PRIVACIDADE.md) | Proteções e privacidade |
| [Solução de problemas](docs/SOLUCAO_DE_PROBLEMAS.md) | Diagnóstico de erros |
| [Limitações](docs/LIMITACOES.md) | O que ainda precisa ser validado |
| [Evidências de teste](docs/EVIDENCIAS_TESTES.md) | Resultados dos testes |

## Modelo 3D

O projeto também prevê um gabinete físico inspirado no BMO para acomodar o celular.

**Escala de impressão documentada: 113%.**

## Licença e créditos

Os rostos e o arquivo legado `wakeword_hey_jarvis.onnx` são provenientes do projeto original [be-more-agent](https://github.com/brenpoly/be-more-agent). Consulte [assets/ORIGINAL_LICENSE](assets/ORIGINAL_LICENSE).

O detector `wakeword/saturnbmo.onnx` foi treinado com [livekit-wakeword](https://github.com/livekit/livekit-wakeword). Os modelos auxiliares de mel e embedding acompanham o pipeline do projeto.

O saturnBMO integra ferramentas e modelos de terceiros, incluindo Faster-Whisper, Whisper.cpp, Piper, Ollama, Mopidy, BitChord e livekit-wakeword. Verifique as respectivas licenças antes de redistribuir binários, modelos ou versões modificadas.

---

<div align="center">

**Feito com dedicação para trazer o BMO para a vida real.**

[Repositório](https://github.com/spacexjr/saturnBMO) · [Issues](https://github.com/spacexjr/saturnBMO/issues)

</div>
