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
  "force_language": true,
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
| `language` | Idioma preferido; com `force_language` o modelo é obrigado a transcrever nele. |
| `force_language` | `true` (padrão) preenche `language <Nome><asr_text>` no turno do assistente. Sem isso, clipes curtos/ruidosos podem ser detectados como francês, japonês etc. |
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
BMO_ASR_FORCE_LANGUAGE=true
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

Resultado real registrado neste ambiente (Ollama 0.33.3):

```text
Idioma: pt
Áudio: 1755 ms
Latência: 90 ms
Motor: qwen3-asr
Transcrição: 'E bem, que horas são agora'
```

A primeira chamada após iniciar o Ollama levou 1966 ms porque incluiu o
carregamento do modelo:

```text
Idioma: pt
Áudio: 1901 ms
Latência: 1966 ms
Motor: qwen3-asr
Transcrição: 'E bom, que horas são agora'
```

Quando o LLM (`qwen3:8b`) e o ASR disputam a mesma GPU, o primeiro turno após
uma resposta pode levar dezenas de segundos para recarregar o ASR; medições
reais ficaram entre 1,9 s e 27 s nesse cenário. O segundo turno com o modelo
residente voltou a ~100 ms.

Por isso a ativação manual é gravada **junto com a fala capturada**, não apenas
como uma janela de tempo: mesmo que o ASR demore mais que a janela, a pergunta
já capturada continua válida e não é descartada.

### Execução somente em CPU

O ASR não exige GPU. Sem GPU disponível, o Ollama usa CPU automaticamente;
para forçar e confirmar, envie `options: {"num_gpu": 0}` na requisição
`/api/chat`. Teste real com um WAV de 1755 ms e o modelo forçado em CPU:

```text
chamada 1 (carregando): 1452 ms
chamada 2 (aquecida):    238 ms
ollama ps: 100% CPU, 1.9 GB, contexto 4096
Transcrição: 'Ebimol, que hora sao agora'
```

Em CPU pura a latência é maior que na GPU (238 ms contra ~90 ms aquecidos),
mas continua utilizável para frases curtas. O modelo ocupa cerca de 2 GB de
RAM. Se a latência em CPU for alta, aumente `stt.timeout_s` ou avalie o
fallback Faster-Whisper `small`/`int8`.

No PC de teste, a GPU disponível é uma **Radeon RX 7600 8 GB** (discreta).
Forçando `options: {"num_gpu": 999}`, o Ollama reportou `100% GPU` e o mesmo
áudio levou 2259 ms no carregamento e 89 ms aquecido. A iGPU Vega do Ryzen 5
5600G não é exposta ao sistema; para usá-la seria preciso habilitá-la na BIOS
e confirmar que o backend de GPU do Ollama a reconhece.

## Diagnóstico

| Sintoma | Verificação |
|---|---|
| `Ollama indisponível` | `curl http://127.0.0.1:11434/api/tags` e `systemctl status ollama`. |
| `Modelo ASR não encontrado` | `ollama pull frozenlab/qwen3-asr:0.6b`. |
| Transcrição vazia | Verifique volume do microfone, ruído e `stt.max_audio_s`. |
| Muito lento | Confirme `keep_alive` e se o modelo já está carregado (`ollama ps`). |
| Primeiro turno após uma resposta demora dezenas de segundos | LLM e ASR podem estar se revezando na GPU; veja `ollama ps` e considere manter o ASR residente ou usar fallback/CPU. |
| iGPU não aparece em `ollama ps`/`lspci` | Habilite a GPU integrada na BIOS e confirme que o Ollama a reconhece; caso contrário, use a GPU discreta ou CPU. |
| Eco do TTS virou pergunta | Aumente `audio.playback_guard_ms` ou reduza o volume. |
| Wake word não acorda | Ajuste `wakeword.threshold` e confira `wakeword.mode`. |

Logs úteis:

```bash
tail -f backend/data/bmo-backend.log
```

O evento `transcript` inclui `engine`, `duration_ms` e `latency_ms`. O endpoint
`GET /api/v1/info` expõe `stt.engine`, `stt.model`, `stt.available`,
`stt.last_latency_ms` e `stt.last_error`.
