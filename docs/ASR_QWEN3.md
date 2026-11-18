# Qwen3-ASR local no Ollama

O saturnBMO usa o **Qwen3-ASR 0.6B** (`frozenlab/qwen3-asr:0.6b`) como motor
principal de transcrição. Ele roda no PC, dentro do Ollama, e é acessado pelo
backend por HTTP local. O Android continua apenas capturando PCM 16 kHz mono e
enviando os blocos pelo WebSocket `bmo/1`.

## Por que este modelo

- Executa offline depois do download, sem APIs pagas.
- Boa qualidade em português do Brasil.
- Modelo pequeno (cerca de 1 GB) e rápido em CPU/GPU modesta.
- Não exige Faster-Whisper nem binários nativos no Android.

Faster-Whisper e Whisper.cpp continuam no repositório como **fallback opcional**.
Eles nunca são usados silenciosamente quando o Qwen falha: o erro é mostrado ao
usuário, a menos que o fallback seja ativado explicitamente.

## Instalação

```bash
ollama serve
ollama pull frozenlab/qwen3-asr:0.6b
```

Confirme que o modelo aparece:

```bash
ollama list
ollama show frozenlab/qwen3-asr:0.6b
```

O Ollama não possui um endpoint dedicado de transcrição. O modelo é multimodal e
a API usada é `/api/chat` com o WAV PCM 16 kHz mono em base64 no campo `images`
de uma mensagem com `content` vazio:

```json
{
  "model": "frozenlab/qwen3-asr:0.6b",
  "stream": false,
  "messages": [
    { "role": "user", "content": "", "images": ["<base64 do WAV>"] }
  ],
  "options": { "temperature": 0, "num_predict": 256 }
}
```

A resposta real tem o formato:

```text
language Portuguese<asr_text>E bem, que horas são agora
```

O backend descarta o prefixo de idioma, usa apenas o texto depois de
`<asr_text>` e nunca inventa uma transcrição quando o campo vem vazio.

## Configuração

`backend/config.json`:

```json
"stt": {
  "engine": "qwen3_asr",
  "model": "frozenlab/qwen3-asr:0.6b",
  "base_url": "http://127.0.0.1:11434",
  "language": "pt-BR",
  "timeout_s": 60,
  "max_audio_s": 55,
  "keep_alive": "10m",
  "num_predict": 256,
  "fallback": {
    "enabled": false,
    "engine": "faster_whisper",
    "model": "small"
  }
}
```

| Campo | Efeito |
|---|---|
| `engine` | `qwen3_asr` (aceita também `qwen3-asr`, `qwen_asr`). |
| `model` | Nome exato do modelo no Ollama. |
| `base_url` | Endereço local do Ollama. |
| `language` | Idioma preferido; o modelo ainda informa o idioma detectado. |
| `timeout_s` | Tempo máximo da requisição de transcrição. |
| `max_audio_s` | Trecho máximo enviado; o excedente é cortado com aviso no log. |
| `keep_alive` | Mantém o modelo carregado entre falas. |
| `fallback.enabled` | Liga o mecanismo alternativo em caso de falha. |

### Variáveis de ambiente

```text
BMO_ASR_ENGINE=qwen3_asr
BMO_ASR_MODEL=frozenlab/qwen3-asr:0.6b
BMO_ASR_BASE_URL=http://127.0.0.1:11434
BMO_ASR_LANGUAGE=pt-BR
BMO_ASR_TIMEOUT=60
BMO_ASR_MAX_AUDIO_S=55
BMO_ASR_KEEP_ALIVE=10m
BMO_ASR_FALLBACK=false
```

Os nomes antigos `BMO_STT_ENGINE`, `BMO_STT_MODEL` e `BMO_STT_LANGUAGE` continuam
sendo aceitos como alias.

## Arquitetura de áudio

```text
Android AudioRecord (PCM 16 kHz, 20 ms)
        │  WebSocket bmo/1
        ▼
VAD por energia ──► fila curta de falas ──► worker único
        │                                      │
        ▼                                      ▼
Wake word ONNX / transcrição          Qwen3-ASR (Ollama /api/chat)
                                               │
                                               ▼
                                   LLM + ferramentas (Ollama)
                                               │
                                               ▼
                                   Piper / espeak-ng ──► Android AudioTrack
```

Módulos separados no backend:

| Módulo | Responsabilidade |
|---|---|
| `wakeword.py` | Variantes textuais e correspondência aproximada. |
| `acoustic_wakeword.py` | Classificador ONNX independente do ASR. |
| `audio.py` | PCM, WAV e VAD por energia. |
| `qwen_asr.py` | Cliente Qwen3-ASR/Ollama, preparação do WAV e métricas. |
| `stt.py` | Fachada de STT, resultado padronizado e fallback opcional. |
| `agent.py` / `toolcalls.py` / `toolkit.py` | Conversa, chamadas de ferramenta e execução validada. |
| `tts.py` | Síntese local. |

## Escuta contínua

Com `audio.continuous_listening: true` (padrão):

1. O microfone permanece ativo enquanto o usuário não pausar.
2. O VAD fecha cada fala e a coloca em uma fila curta (`audio.utterance_queue`).
3. Um único worker transcreve e responde, sem abrir duas capturas concorrentes.
4. Durante `transcribing`, `thinking` e `speaking` o áudio é ignorado para não
   transcrever o próprio TTS nem iniciar outra pergunta.
5. Depois do playback, o backend aplica `audio.playback_guard_ms` e volta ao
   estado `listening` automaticamente.

Estados enviados ao app: `listening`, `wakeword_detected`, `transcribing`,
`thinking`, `speaking`, `error` e `idle`.

## Teste real

```bash
backend/.venv/bin/python scripts/check_asr.py --text "Ei BMO, que horas são?"
```

O script usa o Piper (ou espeak-ng) local para gerar a fala, envia ao Ollama e
mostra idioma, duração, latência e transcrição. Ele falha com código 1 quando o
modelo não devolve texto.

Para testar um WAV já existente:

```bash
backend/.venv/bin/python scripts/check_asr.py --wav /tmp/pergunta.wav
```

Resultado real registrado neste ambiente (Ollama 0.33.3, CPU):

```text
Idioma: pt
Áudio: 1755 ms
Latência: 90 ms
Motor: qwen3-asr
Transcrição: 'E bem, que horas são agora'
```

A primeira chamada após iniciar o Ollama levou cerca de 1,9 s porque incluiu o
carregamento do modelo.

## Diagnóstico

| Sintoma | Verificação |
|---|---|
| `Ollama indisponível` | `curl http://127.0.0.1:11434/api/tags` e `systemctl status ollama`. |
| `Modelo ASR não encontrado` | `ollama pull frozenlab/qwen3-asr:0.6b`. |
| Transcrição vazia | Verifique volume do microfone, ruído e `stt.max_audio_s`. |
| Muito lento | Confirme `keep_alive` e se o modelo já está carregado (`ollama ps`). |
| Eco do TTS virou pergunta | Aumente `audio.playback_guard_ms` ou reduza o volume. |
| Wake word não acorda | Ajuste `wakeword.threshold` e confira `wakeword.mode`. |

Logs úteis:

```bash
tail -f backend/data/bmo-backend.log
```

O evento `transcript` inclui `engine`, `duration_ms` e `latency_ms`. O endpoint
`GET /api/v1/info` expõe `stt.engine`, `stt.model`, `stt.available`,
`stt.last_latency_ms` e `stt.last_error`.
