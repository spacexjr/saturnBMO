# Instalação

Este guia monta o backend local no PC e o app Android. O projeto foi desenvolvido e testado em **Fedora/Nobara**, **Python 3.12**, **JDK 21**, **Gradle 9.3** e **Android SDK 36**. Outras distribuições e versões compatíveis devem funcionar; os comandos de instalação de pacotes variam.

## 1. Visão geral

Você precisa de:

1. PC e celular na mesma rede local (Wi-Fi ou Ethernet).
2. Backend Python rodando no PC.
3. Ollama com um modelo local.
4. Faster-Whisper (instalado pelo `requirements.txt`; modelo baixado no primeiro uso).
5. Piper com voz pt-BR **ou** espeak-ng como fallback.
6. Mopidy 4 para tocar YouTube Music; `playerctl`/`busctl` para MPRIS/BitChord (alternativa) e `kdialog`/`zenity` para o seletor de pastas.
7. APK instalado no celular.
8. Internet no PC para as ferramentas web e clima (opcional para conversa local).

O celular não precisa de internet, apenas de acesso ao PC. O celular também não executa STT nem LLM.

## 2. Pacotes do sistema

### Fedora / Nobara

```bash
sudo dnf install python3 python3-pip python3-virtualenv ffmpeg espeak-ng \
  cmake gcc-c++ make git java-21-openjdk-devel android-tools \
  playerctl kdialog zenity mopidy gstreamer1-plugins-good \
  gstreamer1-plugins-bad-free gstreamer1-plugins-ugly-free \
  gstreamer1-plugin-libav
```

Ubuntu/Debian usam `playerctl`, `kdialog` (ou `zenity`), `openjdk-17-jdk`/`openjdk-21-jdk` e `adb`.

O build do Android exige um **JDK com `javac`**, não apenas um JRE. Se o `java` padrão do sistema não tiver compilador, aponte `JAVA_HOME` para um JDK 17 ou 21.

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
- verifica Piper, Faster-Whisper, espeak-ng, playerctl, kdialog/zenity e Ollama;
- lista o que estiver faltando.

Para executar manualmente:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m bmo_backend --print-token
```

As dependências principais incluem `faster-whisper`, `onnxruntime`, `numpy`, `httpx`, `fastapi` e `uvicorn`.

## 4. Ollama e modelo de linguagem

Instale o Ollama pelo site oficial e baixe um modelo. O padrão do repositório é:

```bash
ollama pull qwen3:8b
ollama list
```

O Ollama deve escutar em `127.0.0.1:11434` (padrão). Para usar outro modelo, edite `backend/config.json`:

```json
"llm": {
  "model": "qwen3:8b"
}
```

Ou use a variável de ambiente:

```bash
export BMO_LLM_MODEL=outro-modelo
```

Se o modelo padrão não existir no seu PC, escolha um de `ollama list`; caso contrário o backend responde que o LLM está indisponível. Modelos menores respondem mais rápido, mas erram mais.

## 5. Faster-Whisper (STT principal)

O Faster-Whisper é instalado por `backend/requirements.txt`. O modelo é baixado/carregado na primeira transcrição. Configuração padrão:

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

- `model`: `tiny`, `base`, `small`, `medium`, `large-v3` etc.
- `compute_type`: `int8` é o mais leve em CPU; `float16` exige GPU compatível.
- `beam_size`: maior tende a melhorar a precisão e aumentar a latência.
- `language`: `pt` para português.

Se o modelo não baixar, verifique a conexão do PC ou baixe manualmente um modelo do projeto Faster-Whisper/Systran e ajuste o caminho em `stt.model`.

### Fallback whisper.cpp (opcional)

O projeto mantém suporte a `whisper.cpp` como fallback. Ele **não** é obrigatório e o binário pode estar ausente. Para ativá-lo, compile e coloque:

```text
tools/whisper.cpp/build/bin/whisper-cli
tools/whisper-models/ggml-base.bin
```

E ajuste `stt.fallback` em `backend/config.json`. Sem esses arquivos, o backend continua usando Faster-Whisper.

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

Para forçar o motor:

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

O app guarda o token cifrado com Android Keystore. Não coloque o token em prints, issues ou repositórios.

## 8. Ferramentas do PC

### Dependências

```bash
command -v playerctl
command -v busctl
command -v kdialog || command -v zenity
```

- `playerctl` e `busctl` são usados para MPRIS (BitChord e outros players).
- `kdialog` (KDE) ou `zenity` abre o seletor nativo de pastas.
- O seletor precisa de uma sessão gráfica (`DISPLAY` ou `WAYLAND_DISPLAY`).

### Música: Mopidy + YouTube Music

O player principal é o Mopidy 4. Instale e configure uma vez:

```bash
mopidy --version
mkdir -p ~/.config/mopidy
cp docs/mopidy.conf.example ~/.config/mopidy/mopidy.conf
systemctl --user enable --now mopidy
```

O exemplo escuta somente em `127.0.0.1:6680` e habilita a extensão `stream`.
Confirme o JSON-RPC:

```bash
curl -sS -X POST http://127.0.0.1:6680/mopidy/rpc \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"core.get_version","params":{}}'
```

As dependências `ytmusicapi` e `yt-dlp` já são instaladas pelo
`requirements.txt`. Busca e reprodução funcionam sem login; para playlists e
músicas curtidas:

```bash
cd backend
.venv/bin/ytmusicapi browser   # salve em data/ytmusic_auth.json
chmod 600 data/ytmusic_auth.json
```

O arquivo de autenticação e cookies do yt-dlp nunca devem ir para o Git. O guia
completo, API, ferramentas do LLM e limitações está em
**[MUSICA.md](MUSICA.md)**.

> Não instale `mopidy-ytmusic`: o último release exige Mopidy 3,
> `pytube<13` e `ytmusicapi<0.30`, incompatível com o Mopidy 4. O BMO usa
> `ytmusicapi` + `yt-dlp` mantendo o Mopidy como player.

### BitChord 1.8 (alternativo)

Abra o BitChord normalmente. O backend descobre o serviço `org.mpris.MediaPlayer2.bitchord` no barramento do usuário. Não é necessário instalar outro BitChord nem modificar o programa.

Funcionalidades disponíveis por MPRIS: play, pause, alternar, próxima, anterior, parar e volume. **Pesquisar faixas por voz não é exposto pelo BitChord 1.8**; o BMO informa essa limitação.

Teste manual:

```bash
playerctl -p bitchord status
playerctl -p bitchord metadata
```

### Pasta autorizada

A autorização é feita pelo app: **Ajustes → Pasta de acesso do BMO → Escolher pasta no PC**. O seletor abre no PC e a escolha é salva em `backend/data/access.json`. Também é possível autorizar por HTTP:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/folder \
  -H "Authorization: Bearer $(cat backend/data/token)" \
  -H "Content-Type: application/json" \
  -d '{"path":"/home/SEU_USUARIO/Documentos/BMO"}'
```

Revogar:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/folder/revoke \
  -H "Authorization: Bearer $(cat backend/data/token)"
```

Todas as ferramentas de arquivo ficam confinadas a essa pasta. Exclusões exigem confirmação.

## 9. Clima e previsão do tempo

O BMO consulta temperatura e previsão de chuva pela internet usando o **Open-Meteo**, sem chave de API. A localização vem do **GPS do celular** (ou da rede Wi-Fi/celular), enviada pelo app ao backend como latitude e longitude. Apenas as coordenadas são enviadas; áudio e texto não saem do PC.

Na primeira conexão, o app pede a permissão de localização. Também é possível autorizar depois em **Ajustes → Localização (clima)**. Se a permissão for negada, o backend responde pedindo para ativar o GPS; não há cidade padrão nem estimativa por IP.

A cidade no `config.json` é uma alternativa manual:

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

O PC precisa de saída HTTPS para `api.open-meteo.com`. O nome da cidade é obtido com `api.bigdatacloud.net`; se esse serviço falhar, a resposta usa “sua localização”. Perguntas como “vai chover hoje?”, “qual a temperatura?” e “como está o tempo amanhã?” são respondidas localmente, sem passar pelo LLM, e faladas pelo TTS.

## 10. Iniciar o backend

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

## 11. Build do app Android

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

## 12. Conectar o app

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
7. Autorize a localização quando o app pedir (opcional).
8. Em **Ajustes → Pasta de acesso do BMO**, escolha a pasta no PC.

Se a rede tiver isolamento de clientes (AP isolation) ou firewall bloqueando, o celular não verá o PC. Veja [SOLUCAO_DE_PROBLEMAS.md](SOLUCAO_DE_PROBLEMAS.md).

### Por USB, só para desenvolvimento

```bash
adb reverse tcp:8765 tcp:8765
adb shell am start -n com.spacexjr.saturnbmo.debug/com.spacexjr.saturnbmo.MainActivity \
  --es bmo_host 127.0.0.1 --ei bmo_port 8765 \
  --es bmo_token "$(cat backend/data/token)"
```

O `adb reverse` encaminha a porta do celular para o PC via USB. Não é o modo de uso final.

## 13. Testes de áudio

No app, em **Ajustes → Áudio**:

- **Testar alto-falante:** deve emitir um tom de 440 Hz.
- **Testar microfone:** deve mostrar o nível variando quando você fala.

O teste de microfone é local: o áudio não é enviado ao PC nem gravado.

## 14. Serviço em segundo plano

Ative **Escuta com tela desligada** em Ajustes. O Android mostra uma notificação persistente “BMO — Microfone ativo”. Com a tela apagada, o serviço mantém o microfone e a conexão.

Observações:

- O Android pode exigir permissão de notificações (Android 13+).
- Fabricantes como Xiaomi e Samsung podem encerrar serviços em segundo plano; permita o app na lista de exceções de bateria.
- Se o microfone for pausado, o serviço encerra depois de alguns segundos.

## 15. Verificação final

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

Consulte também [LIMITACOES.md](LIMITACOES.md) antes de considerar a instalação validada com voz humana real.
