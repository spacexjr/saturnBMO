# Solução de problemas

## O app não mostra nada além da cara

É o comportamento esperado. O modo principal é **somente a cara do BMO**, em paisagem.

- **Toque no rosto** para mostrar os controles.
- **Toque e segure** no rosto para abrir os ajustes.
- Se a tela estiver com controles abertos, toque em **Ocultar**.

## Não conecta ao PC

### 1. Confirme o IP e a porta

No PC:

```bash
ip -4 -o addr show | grep -v ' lo '
```

No app, use o IP da interface da LAN (no teste: `192.168.3.24`), não `127.0.0.1`, a menos que esteja usando `adb reverse`.

Teste o backend no PC:

```bash
curl http://127.0.0.1:8765/health
```

Teste de outro ponto da rede, se possível:

```bash
curl http://IP_DO_PC:8765/health
```

### 2. Confirme o firewall

Fedora/firewalld:

```bash
sudo firewall-cmd --list-all
sudo firewall-cmd --add-port=8765/tcp --add-port=8766/udp
sudo firewall-cmd --runtime-to-permanent
```

Ubuntu/ufw:

```bash
sudo ufw status
sudo ufw allow 8765/tcp
sudo ufw allow 8766/udp
```

O backend precisa escutar em `0.0.0.0:8765`, não apenas em `127.0.0.1`.

```bash
ss -ltnup | grep -E '8765|8766'
```

### 3. Confirme a mesma rede

O celular e o PC precisam estar na mesma sub-rede. No teste:

- PC: `192.168.3.24`
- celular: `192.168.3.9`

Se o celular estiver no 5 GHz e o PC no 2.4 GHz, normalmente ainda é a mesma rede; o problema costuma ser **AP isolation** (isolamento de clientes) no roteador. Desative esse recurso ou use uma rede convidada sem isolamento.

### 4. Confirme o token

```bash
cat backend/data/token
```

No app, o token deve ser colado sem espaços. O botão **Testar** mostra “Token inválido” quando o token está errado.

### 5. Use `adb reverse` para isolar o problema

Se via USB funcionar, o problema é rede/firewall, não o backend:

```bash
adb reverse tcp:8765 tcp:8765
adb shell am start -n com.spacexjr.saturnbmo.debug/com.spacexjr.saturnbmo.MainActivity \
  --es bmo_host 127.0.0.1 --ei bmo_port 8765 \
  --es bmo_token "$(cat backend/data/token)"
```

### 6. Veja os logs

No app: **Ajustes → Logs do aplicativo**.

No PC:

```bash
tail -f backend/data/bmo-backend.log
```

No Android:

```bash
adb logcat -s BmoEngine BmoClient BmoAudio BmoPlayer
```

## “Desconectado” ou reconectando sem parar

- Confirme que o backend continua rodando.
- Veja se o PC mudou de IP (DHCP). Fixe o IP no roteador ou atualize o app.
- Verifique se o celular entrou em economia de energia e cortou o Wi-Fi.
- Em **Ajustes**, deixe **Conectar automaticamente** ativo.
- A reconexão usa espera progressiva de até 15 s.

## O microfone não ativa

- Verifique a permissão de microfone do app no Android.
- Feche outros apps que estejam usando o microfone (chamadas, gravadores).
- Em **Ajustes → Áudio → Testar microfone**, confira se o nível se move.
- O serviço em primeiro plano precisa da permissão de notificações no Android 13+.
- Em Xiaomi, ative **Autostart** e remova a restrição de bateria do app.

## O BMO não ouve “Ei, BMO”

O modo padrão é híbrido: classificador acústico + transcrição. Se um dos dois falhar, o outro ainda pode ativar.

- Fale perto do microfone e sem ruído.
- Diga “Ei, BMO” de forma clara.
- Confira o log de STT no app.
- Use **Falar agora** para ativar sem a palavra de ativação.
- Ajuste `vad_min_rms` em `backend/config.json` se o ambiente for barulhento.
- Verifique se os modelos existem: `wakeword/saturnbmo.onnx`, `wakeword/melspectrogram.onnx` e `wakeword/embedding_model.onnx`.
- Para testar só a transcrição, use `BMO_WAKEWORD_MODE=transcript`.
- Para testar só o acústico, use `BMO_WAKEWORD_MODE=acoustic`.
- O limiar fica em `wakeword.threshold` (padrão `0.75`). O modelo acústico ainda não foi validado com voz humana real; consulte [LIMITACOES.md](LIMITACOES.md).

## O BMO responde em texto, mas não fala

- Em **Ajustes → Estado do servidor**, veja se o TTS está `ok`.
- Teste o Piper no PC:

  ```bash
  echo "Teste de voz." | tools/piper/piper \
    -m tools/voices/pt_BR-faber-medium.onnx \
    -f /tmp/teste.wav
  ffplay /tmp/teste.wav
  ```

- Teste o espeak-ng:

  ```bash
  espeak-ng -v pt-br "Teste de voz."
  ```

- Veja `backend/data/bmo-backend.log`.
- No app, o botão **Testar alto-falante** isola o alto-falante do TTS.

## O LLM não responde

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

- Confirme que o modelo configurado existe.
- Se o modelo for pesado, tente `gemma3:1b`.
- O backend tem timeout de 180 s por padrão.
- Erros aparecem no log e no app como `llm_unavailable`/`llm_error`.

## O STT não funciona

O motor principal é o **Faster-Whisper**, instalado no `backend/.venv`.

```bash
cd backend
.venv/bin/python -c "import faster_whisper; print(faster_whisper.__version__)"
```

- Confira no app se STT aparece `ok` em **Ajustes → Estado do servidor**.
- O modelo (`medium` por padrão) é baixado no primeiro uso; aguarde a conclusão.
- Se o download falhar, veja a conexão do PC ou ajuste `stt.model` para um modelo já baixado.
- Em CPU, use `compute_type: int8`. `float16` pode falhar sem GPU compatível.
- Verifique o log em `backend/data/bmo-backend.log`.
- Se o log mostrar `Carregando Faster-Whisper ../tools/whisper-models/ggml-base.bin`, há um `BMO_STT_MODEL` antigo em `backend/.env` sobrescrevendo o `config.json` (o `run.sh` carrega esse arquivo). Deixe `BMO_STT_MODEL=` em branco ou use `medium`/`small`.
- Para testar o fallback whisper.cpp, confira `tools/whisper.cpp/build/bin/whisper-cli` e `tools/whisper-models/ggml-base.bin`. Ele é opcional; sem esses arquivos, o Faster-Whisper continua funcionando.

## A música não atualiza ou não despausa

- O app consulta `/api/v1/media` a cada **4 s** enquanto está conectado; não é preciso pedir “qual música está tocando”.
- Ações em português como `despausar`, `retomar`, `tocar`, `pausar`, `próxima` e `anterior` são aceitas. Se o player só implementar `PlayPause`, o backend usa esse método como fallback seguro.
- **Pesquisar e tocar uma faixa por nome não é possível** no BitChord 1.8 via MPRIS: a capacidade `search` é `false`. O BMO informa essa limitação; abra o BitChord e escolha a faixa manualmente.

## As ferramentas não abrem aplicativos / janelas

- Confirme que `tools.enabled` é `true` em `backend/config.json`.
- Verifique se o backend está rodando na mesma sessão gráfica do usuário (KDE).
- Em **Wayland**, alguns compositores não permitem fechar/minimizar janelas de outros apps. Abrir e listar costuma funcionar; foco e fechamento podem ser limitados.
- Teste manualmente:

  ```bash
  which kdotool ydotool wmctrl xdotool 2>/dev/null
  ls /usr/share/applications ~/.local/share/applications | head
  ```

- O BMO não usa shell arbitrário; ele só usa os mecanismos suportados pelo ambiente.
- Consulte `GET /api/v1/tools` com o token para ver o que está registrado.

## O BitChord não responde

- Abra o BitChord antes de pedir música.
- Teste o MPRIS:

  ```bash
  playerctl -l
  playerctl -p bitchord status
  playerctl -p bitchord metadata
  busctl --user list | grep mpris
  ```

- O serviço esperado é `org.mpris.MediaPlayer2.bitchord`.
- O backend não instala nem modifica o BitChord.
- Play, pause, próxima, anterior, parar e volume funcionam por MPRIS.
- **Pesquisar faixas por voz não é suportado** pelo BitChord 1.8; o BMO deve informar essa limitação em vez de fingir que tocou.
- Se `playerctl` não existir, instale-o.

## A pasta de acesso não abre

- O seletor roda no **PC**, não no celular.
- Confirme uma sessão gráfica:

  ```bash
  echo "$DISPLAY / $WAYLAND_DISPLAY"
  ```

- Instale `kdialog` (KDE) ou `zenity`.
- Teste:

  ```bash
  kdialog --title "Teste" --getexistingdirectory "$HOME"
  # ou
  zenity --file-selection --directory
  ```

- O app mostra o caminho, o sistema e a data da autorização. Use **Revogar** para remover o acesso.
- Sem pasta autorizada, qualquer ferramenta de arquivo retorna erro de permissão.

## A exclusão de arquivo não acontece

- É intencional: exclusões exigem confirmação.
- No app, responda **Confirmar** no diálogo; por voz/texto, diga “sim” ou “não”.
- Se você mudou de assunto, a confirmação é abandonada e nada é excluído.
- Confira `confirmation.request`/`confirmation.result` nos logs.
- O arquivo precisa estar dentro da pasta autorizada.

## O serviço em segundo plano para sozinho

Comportamento esperado: quando o microfone é pausado, o serviço encerra após alguns segundos. Se ele parar enquanto deveria estar ouvindo:

- confira a notificação “BMO — Microfone ativo”;
- permita notificações;
- desative a otimização de bateria para o app;
- em MIUI/HyperOS, permita autostart e “sem restrições”;
- mantenha a tela de bloqueio sem modo ultraeconomia.

## O app abre em paisagem e não gira

É intencional: `android:screenOrientation="sensorLandscape"`. O BMO foi feito para uma carcaça horizontal. Os ajustes também abrem em paisagem.

Se você quiser testar em retrato, altere o manifesto e recompile, mas o layout foi desenhado para paisagem.

## A resolução do celular ficou estranha

Durante os testes, a resolução pode ter sido alterada com `wm size`/`wm density`. Para restaurar:

```bash
adb shell wm size reset
adb shell wm density reset
adb shell settings put system accelerometer_rotation 1
```

## Instalação do APK release falha

- O release usa applicationId `com.spacexjr.saturnbmo`; o debug usa `com.spacexjr.saturnbmo.debug`.
- Se já houver uma versão com assinatura diferente, desinstale antes:

  ```bash
  adb uninstall com.spacexjr.saturnbmo
  adb install -r android-app/app/build/outputs/apk/release/app-release.apk
  ```

- Verifique a assinatura:

  ```bash
  "$ANDROID_HOME/build-tools/36.0.0/apksigner" verify --print-certs \
    android-app/app/build/outputs/apk/release/app-release.apk
  ```

## Limpar o histórico e logs

- Histórico da conversa: **Ajustes → Apagar histórico**.
- Logs do app: **Ajustes → Limpar logs**.
- Logs do backend:

  ```bash
  rm -f backend/data/bmo-backend.log
  ```

## Ainda não funciona

Reúna:

```bash
uname -a
python3 --version
java -version
adb devices -l
adb shell getprop ro.product.model
adb shell getprop ro.build.version.release
tail -80 backend/data/bmo-backend.log
```

E descreva o passo em que falhou. **Não cole o token** em issue, print ou mensagem.
