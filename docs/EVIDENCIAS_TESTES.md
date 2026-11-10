# Evidências de teste

Registro do que foi realmente executado. As seções históricas abaixo são de **2026-10-28**; a atualização de **2026-11-08** cobre Faster-Whisper e ferramentas; a de **2026-11-10** cobre a integração musical.

## Atualização 2026-11-10 — música real

### Testes automatizados

```text
backend: 98 passed (22 em tests/test_music.py)
android: BUILD SUCCESSFUL + testes unitários existentes passando
```

Os 22 testes de música cobrem configuração, cliente JSON-RPC (incluindo
`core.mixer` do Mopidy 4 e `get_tl_tracks`), busca, normalização, play/pause/
resume/stop, volume, fila, playlists, ferramentas do LLM, aliases de argumentos
gerados por modelos pequenos, API autenticada, proxy assinado e falhas de
confirmação.

### Mopidy real

Ambiente: Mopidy **4.0.0a15** em `127.0.0.1:6681`, saída `fakesink sync=true`,
áudio WAV local servido em `127.0.0.1:8099`.

```text
PASS mopidy reachable (4.0.0a15)
PASS play verified + faixa correta
PASS state com position_ms
PASS pause / resume
PASS volume set/get 37%
PASS queue add/list (2 faixas)
PASS next mudou para a faixa 2
PASS previous voltou para a faixa 1
PASS stop
PASS queue remove/clear
RESULTADO: todos os comandos foram confirmados pelo Mopidy real.
```

Esse teste expôs e corrigiu dois problemas reais de Mopidy 4:

- volume mudou de `core.playback.*` para `core.mixer.*`; o cliente agora usa
  `core.mixer` com fallback para Mopidy 3;
- `core.tracklist.get_tracks` devolve `Track` sem `tlid`; a fila agora usa
  `core.tracklist.get_tl_tracks` e achata `tlid` + `track`.

### YouTube Music real e API completa

Fluxo executado com o backend real em `127.0.0.1:8765`, Mopidy real e
`ytmusicapi`/`yt-dlp` reais:

```text
GET  /api/music/search?q=daft+punk+one+more+time  -> 200, 3 resultados
POST /api/music/play  {"track_id":"n6RTF4OPzf8"}  -> 200, playing, verified=true
GET  /api/music/state                              -> 200, title real
POST /api/music/queue/add                          -> 200, fila=2
POST /api/music/next                               -> 200, faixa mudou, verified=true
POST /api/music/previous                           -> 200, faixa voltou, verified=true
POST /api/music/volume {"volume":33}               -> 200, volume=33
POST /api/music/stop                               -> 200, stopped, verified=true
POST /api/music/queue/clear                        -> 200
```

O Mopidy consumiu a URL assinada local, o proxy resolveu o áudio com `yt-dlp`
e a reprodução foi confirmada por `status=playing` + `videoId` correspondente.
Também foi validado que o primeiro `play` pode ultrapassar 8 s enquanto o
`yt-dlp` resolve; o timeout do Mopidy foi elevado para 20 s e um timeout no RPC
de `play` não é tratado como sucesso: o backend continua conferindo o estado
real.

### Correções encontradas durante os testes reais

- `StreamResolver` lia `cookies_file` de `StreamConfig`, mas o valor vinha de
  `YtMusicConfig`; o campo foi adicionado e a herança corrigida.
- O arquivo de autenticação ausente impedia até a busca anônima. Agora ele é
  opcional e a busca cai para o modo anônimo; biblioteca pessoal continua
  exigindo login.
- `POST /api/music/stop` e as rotas de fila usadas pelo Android não existiam;
  foram adicionadas.
- `next`/`previous` só retornam sucesso depois de confirmar que o `videoId`
  mudou. No fim da fila, `next` retorna “Fim da fila” apenas quando o Mopidy
  está realmente `stopped`; não há troca de faixa inventada.

### Agente real (WebSocket + Ollama/Qwen3)

Pedido enviado por texto no WebSocket real, com o backend real, Mopidy real,
YouTube Music real e Ollama real:

```text
usuário: "toque Bohemian Rhapsody"
activity: music_play start -> Tocando música
music: status=playing, verified=true
activity: music_play done -> Música iniciada
resposta final em português, sem afirmar nada antes da confirmação
```

A faixa escolhida pelo YouTube Music foi
`Queen - Bohemian Rhapsody (Live HD) Legendado em PT-BR`. O `music_play` agora
aceita `query` diretamente, então o modelo não precisa encadear duas chamadas
nem escolher `music_queue_add` por engano. Os testes também aceitam os aliases
de argumentos mais comuns (`id`, `type`, `level`). Antes desse ajuste, numa
execução real o modelo chamou `music_queue_add` em vez de `music_play`; o
comportamento foi corrigido e revalidado com a execução acima.

### Android

O app passou a consultar `/api/music/state` a cada 4 s (com fallback para
`/api/v1/media`), exibe título/artista/progresso/volume/fila e envia comandos
`play`, `pause`, `resume`, `stop`, `next`, `previous`, `volume`, busca e fila
com o token. O build foi executado com JDK 21 (o ambiente só tinha JRE 25):

```text
JAVA_HOME=/tmp/opencode/jdk/jdk-21.0.13+9 ./gradlew testDebugUnitTest
BUILD SUCCESSFUL
```

### Pendente

- Validação do APK em um celular físico.
- Teste de faixas restritas por idade/região com cookies reais.
- Teste de playlists/curtidas com uma conta autenticada real.

## Atualização 2026-11-08

### Testes automatizados

```text
backend: 76 passed
android: 17 testes unitários (3 AppSettings + 9 FaceClassifier + 5 ActivityFace)
```

O backend agora cobre também `files`, `web`, `tools_services` e `acoustic_wakeword`, além do fluxo de confirmação no WebSocket.

### Testes reais executados

- Backend real + Ollama: resposta HTTP por texto.
- WebSocket real: evento `music_status` via BitChord (`player=bitchord`, `is_bitchord=true`, `status=paused`, título `EXPANSÃO DE DOMÍNIO`, artista `M4rkim`, volume `0.53`, `search=false`).
- WebSocket real: `web_search` e `create_file` na pasta autorizada.
- WebSocket real: `delete_file` com `confirmation.request`, confirmação e remoção efetiva do arquivo, emitindo `confirmation.result`.
- Piper real com `pt_BR-faber-medium` (22.050 Hz) e Faster-Whisper real (`medium`, `int8`, `pt`) com áudio sintético.
  - Modelo `medium` baixado no primeiro uso (~146 s incluindo download).
  - Carregamento do modelo em processo novo: ~9,8 s; inferência quente de 1,7 s de áudio: **~3,4 s** em CPU.
  - Transcrição obtida: `"Olá Bumol, que horas são agora?"` (o “BMO” sintético ainda sai distorcido; a ativação usa o detector acústico, não essa transcrição).
- Detector acústico carregado de `wakeword/`; áudio sintético “Ei BMO” ficou abaixo do limiar. **Ainda não há teste com voz humana real.**
- Backend reiniciado com `stt.model=medium` confirmado em `/api/v1/info` (`active_engine=faster-whisper`), após corrigir `BMO_STT_MODEL` antigo em `backend/.env`.
- WebSocket real (texto): “retome a música” executou `music_control`, emitiu evento `music` com `status=playing` e o BitChord saiu de `paused` para `playing`.
- WebSocket real (áudio sintético): o Faster-Whisper `medium` carregou e transcreveu, mas a voz do Piper distorceu “Ei BMO”/“retome a música”; a wake word não foi detectada nesse áudio sintético (limitação já registrada).
- App Android: polling de `/api/v1/media` a cada 4 s e mensagens amigáveis para fechamento 4401/4400 implementados; build e 17 testes passando.
- Faces CLOUDY e STORM validadas no emulador Android (Medium_Phone): arte `clouds.png` carregada dos assets, nuvens claras e lentas no tema nublado e nuvens escuras no tema de tempestade (com chuva/raio), sempre com o rosto visível; “tempo” e “tempestade” ativaram os temas via classificador real.

### O que continua pendente

- Validação de “Ei, BMO” com voz humana ao vivo.
- Teste de controle de janelas em KDE/Wayland real.
- Teste do seletor de pastas no PC com `kdialog` e `zenity`.
- Teste do APK atual no Galaxy A22.

As seções a seguir preservam o registro histórico original.

## Ambiente

### PC

```text
Linux fedora 7.1.8-200.fc44.x86_64
Python 3.14.6
OpenJDK 25.0.4.1
Gradle 9.3.0
Android compileSdk 36 / minSdk 26 / targetSdk 36
```

Serviços locais:

- Ollama em `127.0.0.1:11434` com `qwen3.5:2b` (também instalados `gemma3:1b` e `moondream`).
- whisper.cpp com `ggml-base.bin`.
- Piper com `pt_BR-faber-medium.onnx`.
- espeak-ng como fallback.
- Backend em `0.0.0.0:8765`, descoberta UDP em `8766`.

### Celular real

```text
adb devices -l
75GUQG6TIVOFIRGI  device usb:1-1 product:rodin_in model:2412DPC0AI device:rodin

Fabricante: Xiaomi
Modelo:     2412DPC0AI
Codinome:   rodin
Android:    17 (API 37)
Hardware:   mt6899
Tela nativa: 1220 x 2712, densidade 490 dpi
```

O app foi instalado e executado nesse aparelho real, via USB para instalação e via Wi-Fi para a conexão com o backend. Em um momento anterior, a resolução foi reduzida com `wm size 720x1600` e `wm density 320` para capturas de tela; depois foi restaurada para a resolução nativa.

Rede do teste:

```text
PC:      192.168.3.24
Celular: 192.168.3.9
Máscara: 192.168.3.0/24
```

## 1. Testes automatizados do backend

Comando:

```bash
cd backend
.venv/bin/python -m pytest -q
```

Resultado:

```text
........................................                                 [100%]
40 passed, 1 warning in 1.70s
```

O único aviso é uma depreciação externa do Starlette/httpx (`StarletteDeprecationWarning`), não uma falha do projeto.

Cobrem:

- validação do protocolo, incluindo coordenadas de GPS;
- autenticação;
- VAD e conversão de áudio;
- detecção de palavra de ativação;
- ações locais de hora/data;
- endpoints HTTP;
- comportamento de sessão WebSocket;
- clima por coordenadas enviadas no HTTP e no WebSocket;
- limpeza de transcrição.

## 2. Testes unitários do Android

Comando:

```bash
cd android-app
./gradlew testDebugUnitTest
```

Resultado:

```text
TEST-com.spacexjr.saturnbmo.AppSettingsTest.xml
tests="3" skipped="0" failures="0" errors="0"
```

Cobrem a montagem de `ws://`/`http://` a partir do host configurado, a remoção de esquema/barra final e a validação de host/porta.

## 3. Teste E2E com serviços reais

Comando:

```bash
cd backend
.venv/bin/python ../scripts/e2e_ws.py \
  --text "Ei, BMO, que horas são?" \
  --output /tmp/bmo-resposta-e2e.wav
```

Saída:

```text
[teste] Fala sintetizada (1.6s, 22050 Hz)
[teste] PCM: 50612 bytes
[teste] Protocolo: bmo/1 sessão ee1b63eea105
[teste] Estado inicial: idle
[teste] Áudio pronto: audio.ready
[teste] Evento: state listening Microfone ativo. Diga 'Ei, BMO'.
[teste] Evento: state idle Microfone pausado.
[teste] Evento: state thinking Transcrevendo a fala...
[teste] Transcrição: 'E BMO, que horas são?'
[teste] Evento: wakeword.detected
[teste] Evento: state thinking Pensando...
[teste] Resposta: 'Agora são 21:55.'
[teste] Evento: state speaking Falando...
[teste] Evento: audio.start 22050 Hz
[teste] Evento: audio.end
[teste] Áudio da resposta salvo em /tmp/bmo-resposta-e2e.wav (89716 bytes)
[teste] RESULTADO: OK
```

O teste usa **fala sintetizada**, não voz humana ao vivo. Ele valida a cadeia completa:

```text
WAV -> PCM 16 kHz -> WebSocket -> VAD -> whisper.cpp -> wake word
    -> intenção local (hora) -> texto -> Piper -> PCM -> WAV de resposta
```

A transcrição não foi perfeita (“E BMO” em vez de “Ei, BMO”), mas a normalização do detector aceitou a frase `e bmo`. Isso é uma evidência real da limitação descrita em [LIMITACOES.md](LIMITACOES.md).

## 4. Teste de conexão Wi-Fi no celular real

O APK debug foi instalado e iniciado com:

```bash
adb shell am start -n com.spacexjr.saturnbmo.debug/com.spacexjr.saturnbmo.MainActivity \
  --es bmo_host 192.168.3.24 \
  --ei bmo_port 8765 \
  --es bmo_token "$(cat backend/data/token)"
```

Depois de alguns segundos, a interface mostrou:

```text
PC conectado
Conectado. Toque em Ouvir para começar.
```

A conexão foi feita **pelo Wi-Fi real** (`192.168.3.24`), sem `adb reverse`. O servidor registrou a descoberta UDP respondida para `192.168.3.9`:

```text
INFO bmo.discovery: Descoberta respondida para 192.168.3.9:...
```

Capturas:

- `docs/evidence/real-wifi-rosto-2712x1220.png` — rosto somente, tela nativa.
- `docs/evidence/real-wifi-controles-2712x1220.png` — controles revelados por toque.
- `docs/evidence/real-wifi-transcricao-2712x1220.png` — sessão com microfone ativo e transcrição.

A captura de microfone real chegou a produzir a transcrição espontânea `Eu vou em um meu suor.` durante a sessão. Isso demonstra que o caminho de captura/STT estava ativo, mas **não** é um teste acústico controlado de “Ei, BMO”.

## 5. Interface e modo somente rosto

Capturas:

- `docs/evidence/rosto-somente-1600x720.png` — rosto somente, versão com resolução de teste 1600×720.
- `docs/evidence/release-rosto-somente-1600x720.png` — APK release abrindo no modo somente rosto.
- `docs/evidence/real-wifi-rosto-2712x1220.png` — rosto somente na resolução nativa do celular real, conectado por Wi-Fi.
- `docs/evidence/ajustes-paisagem-1600x720.png` — tela de ajustes em paisagem, com rolagem.

Nota: a captura `release-rosto-somente-1600x720.png` foi feita antes do ajuste final de cor de fundo/ícone. O APK release final foi recompilado, assinado e reinstalado; a mudança posterior foi apenas de recursos visuais de inicialização, sem alterar o comportamento do app.

Comportamento verificado:

- abre em paisagem;
- rosto ocupa a tela, com o fundo verde contínuo;
- controles ficam ocultos;
- toque no rosto mostra os controles;
- toque e segure abre os ajustes;
- botões de microfone, texto, falar agora e parar fala aparecem no overlay;
- ajustes continuam acessíveis e roláveis em paisagem;
- barras do sistema ficam ocultas em modo imersivo.

## 6. APK release

Build:

```bash
cd android-app
STORE_PASS=$(sed -n 's/^storePassword=//p' keystore/keystore.properties)
BMO_KEYSTORE="$PWD/keystore/bmo-release.jks" \
BMO_KEY_ALIAS=bmo \
BMO_STORE_PASSWORD="$STORE_PASS" \
BMO_KEY_PASSWORD="$STORE_PASS" \
./gradlew assembleRelease
```

Resultado: `BUILD SUCCESSFUL`.

Verificação da assinatura:

```text
Signer #1 certificate DN: CN=BMO App, OU=Desenvolvimento Local, O=BMO, L=Local, ST=Local, C=BR
Signer #1 certificate SHA-256 digest: ecedc95295803337ace411eefe1fea08b890a5d51f32860bac406fe44cc19088
Signer #1 certificate SHA-1 digest: 73068a87e8ca595f94222e5c9c05436cfc7ce5d7
```

APKs gerados:

```text
android-app/app/build/outputs/apk/debug/app-debug.apk
android-app/app/build/outputs/apk/release/app-release.apk
```

Tamanhos e hashes no momento do teste:

```text
Debug   ~12 MB   SHA-256 259307b945c1d579e7c57ae48e8c7329a9435fd7b9ccacd6e5d3f50a30c21f13
Release ~7,9 MB  SHA-256 ea9432a41f4b9705b3302dbb30a5c892077a7a6c5bcfaaed12ac8dc0c18d0d05
```

O APK release foi instalado no celular real e abriu no modo somente rosto. O debug foi usado para os testes com extras de conexão e para as capturas na resolução nativa.

## 7. Serviço em primeiro plano

A notificação persistente do serviço foi observada no Android:

```text
BMO — Microfone ativo
```

O serviço usa o tipo `microphone` e uma notificação de baixa importância, com ação **Parar escuta**. Quando o microfone é pausado, o serviço se encerra após alguns segundos.

Ressalva: o teste prolongado com a tela apagada e voz humana ao vivo ainda não foi concluído de forma objetiva. O comportamento depende das políticas de bateria do fabricante.

## 8. O que não foi validado

- “Ei, BMO” com voz humana ao vivo, em várias distâncias/ruídos.
- Permissão e leitura de GPS no celular real.
- Latência ponta a ponta com voz humana.
- Qualidade acústica do alto-falante e do microfone dentro da carcaça.
- Cancelamento de eco com o BMO falando e ouvindo ao mesmo tempo.
- Teste de 24h contínuas.
- Outros modelos de celular.
- Instalação via Play Store (o APK é assinado localmente).
- TLS/reverse proxy.

Essas pendências estão detalhadas em [LIMITACOES.md](LIMITACOES.md).
