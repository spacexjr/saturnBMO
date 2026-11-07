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

Exemplo de texto:

```json
{"type":"text","text":"Ei, BMO, que horas são?"}
```

Exemplo de início de áudio:

```json
{"type":"audio.start","format":"pcm_s16le","sample_rate":16000,"channels":1}
```

Depois de `audio.start`, cada quadro binário deve ter um número par de bytes (amostras PCM16). O app usa 640 bytes por quadro (20 ms a 16 kHz mono).

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
| `wakeword.detected` | `phrase`, `transcript` | Palavra de ativação encontrada. |
| `wakeword.activated` | `manual`, `message` | Ativação manual aceita. |
| `wakeword.not_detected` | `reason?`, `message`, `transcript?` | Fala transcrita sem a palavra de ativação. |
| `request.accepted` | `text` | Pedido aceito para resposta. |
| `assistant.text.delta` | `text`, `id` | Fragmento da resposta do LLM ou ação local. |
| `assistant.text.done` | `text`, `id`, `audio_available` | Resposta completa. |
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

A detecção acontece no backend por **transcrição**, após o Whisper.cpp. O texto é normalizado (minúsculas, sem acentos/pontuação) e comparado com as frases configuradas em `wakeword.phrases`.

- Se a frase for encontrada e houver texto restante, o restante vira o pedido.
- Se a frase for encontrada sozinha, o servidor responde “Pode falar!” e mantém a escuta.
- Se não for encontrada, o servidor envia `wakeword.not_detected` e volta ao estado de escuta.
- A ativação manual (`activate`) ignora a palavra de ativação uma vez.

Isso não é um modelo acústico de “Ei, BMO”. O `wakeword_hey_jarvis.onnx` legado não é usado.

## 6. Ações locais autorizadas

O backend reconhece hora e data antes de chamar o LLM. As únicas ações autorizadas são:

- `get_time` → “Agora são HH:MM.”
- `get_date` → “Hoje é dia da semana, DD de mês de AAAA.”

O LLM pode devolver um JSON de ação, mas o backend só aceita essas duas ações. Qualquer outro comando é ignorado. Não há execução de shell.

## 7. HTTP

Endpoints auxiliares:

| Método | Caminho | Autenticação | Uso |
|---|---|---|---|
| `GET` | `/health` | Não | Verificação simples de vida. |
| `GET` | `/api/v1/info` | Bearer | Protocolo, versão, estado dos serviços, formatos e capacidades. |
| `GET` | `/api/v1/diagnostics` | Bearer | Configuração pública, serviços e últimas 80 linhas de log. |
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
| `stt_unavailable` / `stt_error` | Whisper indisponível ou falhou. |
| `llm_unavailable` / `llm_error` | Ollama indisponível ou falhou. |
| `tts_error` | Piper/espeak-ng falhou. |
| `weather_error` / `weather_unavailable` | Clima falhou ou GPS não foi autorizado/enviado. |
| `empty_answer` | LLM não retornou texto. |
| `internal_error` | Falha inesperada no backend. |

Erros `fatal` encerram a sessão; os demais mantêm o WebSocket aberto e o app pode continuar.
