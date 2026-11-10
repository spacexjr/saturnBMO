# Protocolo BMO/1

O app Android e o backend conversam por **WebSocket** em `/ws`, com autenticação por token. O protocolo é versionado como `bmo/1`.

- Transporte: WebSocket (HTTP/1.1 ou HTTP/2 do Uvicorn), `ws://` na rede local.
- Autenticação: cabeçalho `Authorization: Bearer <token>`; o backend também aceita `X-BMO-Token` e, para compatibilidade, `?token=` no WebSocket. Prefira o cabeçalho.
- Texto: JSON UTF-8.
- Áudio: quadros binários PCM 16-bit little-endian, mono, 16 kHz.
- Sequência: eventos do servidor têm `seq` crescente e `ts` em milissegundos Unix. O cliente deve ignorar `seq` menor ou igual ao último recebido.
- Limite de mensagem JSON: 256 KiB (configurável em `server.max_ws_message_bytes`).
- Limite de quadro de áudio: 1 MiB por envio.

Os esquemas formais estão em [`protocol/schemas/client-message.schema.json`](../protocol/schemas/client-message.schema.json) e [`protocol/schemas/server-event.schema.json`](../protocol/schemas/server-event.schema.json).

## 1. Handshake

O servidor aceita a conexão, valida o token e envia imediatamente um evento `hello`:

```json
{
  "type": "hello",
  "seq": 1,
  "ts": 1770000000000,
  "protocol": "bmo/1",
  "server_version": "0.1.0",
  "session_id": "a1b2c3d4e5f6",
  "audio": {
    "format": "pcm_s16le",
    "sample_rate": 16000,
    "channels": 1,
    "frame_ms": 20
  },
  "wakeword": {
    "enabled": true,
    "mode": "transcript",
    "phrases": ["ei bmo", "ei bemo", "hey bmo", "oi bmo", "e bmo", "bmo"]
  },
  "capabilities": ["text", "audio", "tts", "vad", "get_time", "get_date", "get_weather"]
}
```

Em seguida o servidor envia o estado inicial:

```json
{"type":"state","seq":2,"ts":1770000000001,"state":"idle","detail":"Conectado. Toque em Ouvir para começar."}
```

O cliente envia seu `hello`:

```json
{
  "type": "hello",
  "protocol": "bmo/1",
  "client": "saturnBMO Android",
  "client_version": "0.1.0"
}
```

O servidor responde:

```json
{"type":"hello.ok","seq":3,"ts":1770000000002,"protocol":"bmo/1","session_id":"a1b2c3d4e5f6"}
```

Se o token for inválido, o servidor envia um evento `error` com código `unauthorized` e fecha o WebSocket com o código **4401**. Se o protocolo não for suportado, envia `unsupported_protocol` e fecha com **4400**.

## 2. Mensagens do cliente

Todas as mensagens são objetos JSON com `type`. Tipos desconhecidos são rejeitados com `error` (não fatal).

| `type` | Campos | Descrição |
|---|---|---|
| `hello` | `protocol?`, `client?`, `client_version?`, `latitude?`, `longitude?` | Identificação do cliente; pode incluir a localização inicial. |
| `ping` | `ts?` | Keepalive; o servidor responde `pong`. |
| `location` | `latitude`, `longitude`, `accuracy?` | Envia coordenadas do GPS para as consultas de clima. `accuracy` é a precisão em metros. |
| `activate` | — | Ativação manual: ignora a palavra de ativação na próxima fala. |
| `audio.start` | `format?`, `sample_rate?`, `channels?` | Inicia o envio de áudio. Formato aceito: `pcm_s16le`, mono, 8000–48000 Hz. |
| `audio.end` | — | Encerra o envio e finaliza a fala pendente no VAD. |
| `text` | `text` (1–1000 caracteres) | Envia uma mensagem por texto, sem passar pelo microfone. |
| `interrupt` | — | Interrompe resposta, fala e reprodução. |
| `playback.started` | — | Informa que o cliente começou a tocar o áudio recebido. |
| `playback.done` | — | Informa que a reprodução terminou. |
| `reset` | — | Apaga o histórico da sessão no backend. |
| `confirmation` | `id`, `approved` (booleano) | Responde a uma confirmação pendente de ação destrutiva, como exclusão de arquivo. |

Exemplo de texto:

```json
{"type":"text","text":"Ei, BMO, que horas são?"}
```

Exemplo de início de áudio:

```json
{"type":"audio.start","format":"pcm_s16le","sample_rate":16000,"channels":1}
```

Depois de `audio.start`, cada quadro binário deve ter um número par de bytes (amostras PCM16). O app usa 640 bytes por quadro (20 ms a 16 kHz mono).

Exemplo de confirmação:

```json
{"type":"confirmation","id":"abc123","approved":true}
```

Enviar `approved: false` (ou responder “não” por texto/voz) cancela a ação sem executá-la. Uma confirmação com `id` desconhecido gera `confirmation_invalid`.

## 3. Eventos do servidor

Todos têm `type`, `seq` e `ts`, salvo indicação em contrário.

| `type` | Campos principais | Descrição |
|---|---|---|
| `hello` | `protocol`, `server_version`, `session_id`, `audio`, `wakeword`, `capabilities` | Saudação inicial. |
| `hello.ok` | `protocol`, `session_id` | Resposta ao `hello` do cliente. |
| `location.ok` | `latitude`, `longitude` | Coordenadas aceitas e guardadas na sessão. |
| `pong` | `echo?`, `server_ts` | Resposta ao `ping`. |
| `state` | `state`, `detail` | Estado global: `idle`, `listening`, `thinking`, `speaking`, `error`. |
| `audio.ready` | `format`, `sample_rate`, `channels` | Servidor pronto para receber áudio. |
| `vad` | `speaking` | Início/fim de fala detectado. |
| `transcript` | `text`, `final`, `source`, `duration_ms?` | Transcrição do áudio ou texto do usuário. |
| `wakeword.detected` | `phrase`, `transcript?`, `source`, `score?` | Palavra de ativação encontrada (`source`: `acoustic` ou `transcript`). |
| `wakeword.activated` | `manual`, `message` | Ativação manual aceita. |
| `wakeword.not_detected` | `reason?`, `message`, `transcript?` | Fala transcrita sem a palavra de ativação. |
| `request.accepted` | `text` | Pedido aceito para resposta. |
| `assistant.text.delta` | `text`, `id` | Fragmento da resposta do LLM ou ação local. |
| `assistant.text.done` | `text`, `id`, `audio_available` | Resposta completa. |
| `activity` | `activity`, `status`, `label`, `tool?` | Operação real em andamento (`processing`, `searching_web`, `opening_app`, `editing_file`, `success`, `error` etc.). `status`: `start`, `done` ou `error`. |
| `music` | `player`, `is_bitchord`, `status`, `title`, `artist`, `album`, `length_s`, `volume`, `volume_percent`, `position_ms`, `duration_ms`, `queue_length`, `verified`, `art_url` | Metadados reais do Mopidy/YouTube Music (ou MPRIS/BitChord como alternativa). |
| `confirmation.request` | `id`, `tool`, `prompt` | Ação destrutiva aguardando confirmação explícita. |
| `confirmation.result` | `id`, `approved`, `ok`, `message` | Resultado da confirmação e da execução. |
| `audio.start` | `id`, `assistant_id`, `format`, `sample_rate`, `channels`, `duration_ms`, `engine` | Início do áudio TTS; os binários seguem em sequência. |
| `audio.end` | `id` | Fim do áudio. |
| `audio.stop` | `reason` | Parada solicitada (`user`, `new_request` etc.). |
| `audio.unavailable` | `reason`, `message` | Não foi possível gerar/reproduzir áudio. |
| `error` | `code`, `message`, `fatal` | Erro de validação, STT, LLM, TTS ou transporte. |
| `history.reset` | — | Histórico apagado. |

### Binários de áudio

Depois de `audio.start`, o servidor envia bytes PCM16LE crus, sem cabeçalho. O cliente deve:

1. abrir o `AudioTrack` na taxa e canais informados;
2. escrever os bytes recebidos;
3. considerar a reprodução concluída quando o buffer consumir os frames;
4. enviar `playback.started` ao começar e `playback.done` ao terminar.

O backend envia blocos de aproximadamente 100 ms e mantém a fila curta. A reprodução real é medida pelo `AudioTrack` no Android, não apenas pelo fim do envio.

## 4. Fluxo de voz

```text
App                         Backend
 |  audio.start              |
 | ------------------------> |
 |  audio.ready              |
 | <------------------------ |
 |  bytes PCM16 a cada 20ms  |
 | ------------------------> |
 |                           | VAD detecta fala
 |  vad {speaking:true}      |
 | <------------------------ |
 |                           | VAD detecta silêncio
 |  vad {speaking:false}     |
 | <------------------------ |
 |  state: thinking          |
 | <------------------------ |
 |  transcript               |
 | <------------------------ |
 |  wakeword.detected        |
 | <------------------------ |
 |  state: thinking          |
 | <------------------------ |
 |  assistant.text.delta ... |
 | <------------------------ |
 |  assistant.text.done      |
 | <------------------------ |
 |  state: speaking          |
 | <------------------------ |
 |  audio.start              |
 | <------------------------ |
 |  bytes PCM16 do TTS ...   |
 | <------------------------ |
 |  audio.end                |
 | <------------------------ |
 |  playback.started/done    |
 | ------------------------> |
 |  state: listening/idle    |
 | <------------------------ |
```

Fluxo por texto: `text` → `transcript` → `assistant.text.delta` → `assistant.text.done` → `audio.start` → binários → `audio.end`.

## 5. Palavra de ativação

O modo padrão é `hybrid`:

- o classificador acústico ONNX (`wakeword/saturnbmo.onnx`) analisa o áudio de entrada;
- a transcrição do Faster-Whisper também é comparada com as frases de `wakeword.phrases`;
- o texto é normalizado (minúsculas, sem acentos/pontuação).

Quando a ativação vem da transcrição e há texto restante, o restante vira o pedido. Se a frase vier sozinha, o servidor responde “Pode falar!” e mantém a escuta. Sem correspondência, envia `wakeword.not_detected` e volta ao repouso. A ativação manual (`activate`) ignora a palavra de ativação uma vez.

Modos disponíveis em `wakeword.mode`:

- `hybrid`: acústico + transcrição (padrão);
- `acoustic`: apenas o classificador acústico;
- `transcript`: apenas a transcrição.

O modelo acústico ainda não foi validado com voz humana real; veja [LIMITACOES.md](LIMITACOES.md).

## 6. Ferramentas e ações locais

O backend reconhece hora, data e clima antes de chamar o LLM. O LLM pode chamar ferramentas reais por tool calling nativo, mas apenas as registradas no backend:

- arquivos: `list_files`, `search_files`, `read_file`, `create_file`, `write_file`, `edit_file`, `rename_file`, `copy_file`, `move_file`, `create_directory`, `delete_file`, `delete_directory`, `get_file_metadata`;
- internet: `web_search`, `open_url`, `read_webpage`, `extract_page_content`, `summarize_web_content`;
- aplicativos: `list_apps`, `launch_app`, `close_app`, `minimize_app`, `maximize_app`, `restore_app`, `foreground_app`, `list_windows`, `list_running_apps`;
- música: `music_search`, `music_play`, `music_pause`, `music_resume`, `music_stop`, `music_next`, `music_previous`, `music_set_volume`, `music_get_volume`, `music_get_state`, `music_get_now_playing`, `music_queue_add`, `music_queue_remove`, `music_queue_clear`, `music_queue_list`, `music_playlist_list`, `music_playlist_play`, `music_liked_songs` + MPRIS legado (`music_status`, `music_control`, `music_search`);
- sistema: `system_info`.

Cada ferramenta tem validação própria. Não há execução de shell arbitrário nem `sudo` automático. `delete_file` e `delete_directory` retornam `confirmation.request` e só executam após `confirmation` com `approved: true` (ou “sim” por voz/texto).

As ferramentas de arquivo dependem de uma pasta autorizada em `backend/data/access.json`. Sem autorização, retornam erro. As ferramentas novas de música usam o Mopidy local e o YouTube Music (`ytmusicapi` + `yt-dlp`); o BitChord continua acessível por MPRIS nas ferramentas legadas.

## 7. HTTP

Endpoints auxiliares:

| Método | Caminho | Autenticação | Uso |
|---|---|---|---|
| `GET` | `/health` | Não | Verificação simples de vida. |
| `GET` | `/api/v1/info` | Bearer | Protocolo, versão, estado dos serviços, formatos e capacidades. |
| `GET` | `/api/v1/diagnostics` | Bearer | Configuração pública, serviços e últimas 80 linhas de log. |
| `GET` | `/api/v1/folder` | Bearer | Estado da pasta autorizada (`path`, `os`, `selected_at`, `authorized`, `picker`, `display_available`). |
| `POST` | `/api/v1/folder` | Bearer | Autoriza uma pasta por caminho (`{"path": "/..."}`). |
| `POST` | `/api/v1/folder/select` | Bearer | Abre o seletor nativo no PC e autoriza a escolha. |
| `POST` | `/api/v1/folder/revoke` | Bearer | Revoga o acesso à pasta. |
| `GET` | `/api/v1/tools` | Bearer | Lista e estado das ferramentas registradas. |
| `GET` | `/api/v1/media` | Bearer | Metadados MPRIS do player ativo; usa o Mopidy como fallback. |
| `GET` | `/api/music/state` | Bearer | Estado real do Mopidy: status, faixa, posição, duração, volume e fila. |
| `GET` | `/api/music/now-playing` | Bearer | Igual a `state`, com o campo `now_playing`. |
| `GET` | `/api/music/queue` | Bearer | Fila real do Mopidy. |
| `GET` | `/api/music/search?q=&filter=&limit=` | Bearer | Busca no YouTube Music. |
| `GET` | `/api/music/playlists` | Bearer | Playlists da conta autenticada. |
| `POST` | `/api/music/play` | Bearer | `{"track_id":"..."}`, confirma a reprodução no Mopidy. |
| `POST` | `/api/music/{pause,resume,stop,next,previous}` | Bearer | Transporte com confirmação de estado. |
| `POST` | `/api/music/volume` | Bearer | `{"volume":0..100}`. |
| `POST` | `/api/music/queue/{add,remove,clear}` | Bearer | Manipula a fila. |
| `GET/HEAD` | `/api/music/stream/{video_id}?sig=...` | HMAC | Proxy de áudio consumido pelo Mopidy local. |
| `POST` | `/api/v1/text` | Bearer | Resposta por texto; pode gerar WAV em cache. |
| `GET` | `/api/v1/audio/{id}.wav` | Bearer | Baixa áudio TTS em cache (TTL de 300 s). |
| `POST` | `/api/v1/reset?session_id=...` | Bearer | Apaga histórico de uma sessão HTTP. |
| `GET` | `/docs` | Não | OpenAPI interativo (uso local). |

Exemplo de `POST /api/v1/text`:

```json
{
  "text": "Ei, BMO, vai chover hoje?",
  "session_id": "http",
  "speak": true,
  "latitude": -23.5505,
  "longitude": -46.6333
}
```

`latitude` e `longitude` são opcionais, mas devem ser enviadas juntas. Elas permitem consultar o clima por HTTP sem configurar cidade no backend. Se o pedido for de clima e não houver coordenadas nem cidade configurada, a resposta é o erro `weather_unavailable`.

Resposta:

```json
{
  "id": "abc123",
  "text": "Sim, há previsão de chuva para hoje: chance de 63% e garoa leve.",
  "action": "get_weather",
  "audio": {
    "url": "/api/v1/audio/def456.wav",
    "format": "wav",
    "sample_rate": 22050,
    "channels": 1,
    "duration_ms": 1400,
    "engine": "piper"
  },
  "audio_available": true
}
```

## 8. Descoberta UDP

O backend responde na porta **8766/udp** a datagramas com o texto exato:

```text
BMO_DISCOVER_V1
```

Resposta:

```json
{
  "service": "bmo-backend",
  "name": "BMO no PC",
  "protocol": "bmo/1",
  "port": 8765,
  "requires_token": true
}
```

O app usa broadcast para achar o PC, mas o token continua obrigatório.

## 9. Erros e códigos

| Código | Significado |
|---|---|
| `unauthorized` | Token ausente/inválido; fecha 4401. |
| `unsupported_protocol` | Protocolo diferente de `bmo/1`; fecha 4400. |
| `invalid_json` | JSON malformado. |
| `invalid_message` | Estrutura/profundidade inválida. |
| `missing_type` | Falta `type`. |
| `unknown_type` | Tipo não reconhecido. |
| `message_too_large` | JSON acima do limite; erro fatal. |
| `audio_frame_too_large` | Quadro binário acima de 1 MiB; erro fatal. |
| `unsupported_audio_format` | Formato diferente de `pcm_s16le`. |
| `invalid_audio_config` | Taxa/canais inválidos. |
| `invalid_sample_rate` | Taxa fora de 8000–48000. |
| `unsupported_channels` | Canais diferentes de 1. |
| `invalid_text` / `empty_text` / `text_too_long` | Texto inválido. |
| `invalid_location` | Latitude/longitude ausentes, fora do intervalo ou `accuracy` inválida. |
| `invalid_confirmation` | Confirmação sem `id` ou sem `approved` booleano. |
| `confirmation_invalid` | Nenhuma confirmação pendente com o `id` informado. |
| `invalid_folder` / `empty_path` | Caminho de pasta inválido ou vazio. |
| `picker_error` | Seletor nativo indisponível, sem sessão gráfica ou falhou. |
| `stt_unavailable` / `stt_error` | Faster-Whisper (ou fallback whisper.cpp) indisponível ou falhou. |
| `llm_unavailable` / `llm_error` | Ollama indisponível ou falhou. |
| `tts_error` | Piper/espeak-ng falhou. |
| `weather_error` / `weather_unavailable` | Clima falhou ou GPS não foi autorizado/enviado. |
| `empty_answer` | LLM não retornou texto. |
| `internal_error` | Falha inesperada no backend. |

Erros `fatal` encerram a sessão; os demais mantêm o WebSocket aberto e o app pode continuar.
