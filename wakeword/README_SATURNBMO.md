# saturnBMO — detector de palavra de ativação

Detector acústico local para **"Ei, BMO", "Hey BMO", "Hey Beemo", "Ei, Beemo",
"BMO", "Beemo", "Bimão", "Bimo", "Bê-mo" e "Bi-mo"**, treinado com o
[livekit-wakeword](https://github.com/livekit/livekit-wakeword) e exportado para
ONNX. Roda **sem LLM, sem STT e sem rede**, no mesmo backend que já recebe o
áudio do aplicativo Android.

> **Modelo em produção:** `saturnbmo.onnx` — 8 h exatas de treino, 14
> pronúncias, fala genérica e negativos duros. Threshold **0,95** com
> `min_consecutive=3`. O modelo antigo de ~4 h fica preservado em
> `saturnbmo_4h.onnx`. Números no [AVALIACAO_8H.md](AVALIACAO_8H.md).

---

## 1. O que foi entregue

```
saturnBMO/
├── wakeword/
│   ├── saturnbmo.onnx            # classificador novo (1,16,96) -> (1,1)
│   ├── saturnbmo_4h.onnx         # modelo antigo, preservado para rollback
│   ├── melspectrogram.onnx       # áudio 16 kHz -> mel
│   ├── embedding_model.onnx      # mel -> embeddings (16,96)
│   ├── AVALIACAO_8H.md           # holdout cego + validação
│   └── AVALIACAO_PER_PHRASE.md   # avaliação do modelo antigo de 4 h
└── backend/
    ├── bmo_backend/acoustic_wakeword.py  # pipeline ONNX completo
    ├── bmo_backend/wakeword_cli.py       # teste com microfone do PC
    ├── bmo_backend/server.py             # integração no WebSocket
    ├── bmo_backend/config.py             # defaults + overrides por ambiente
    ├── config.json                       # configuração em execução
    ├── requirements.txt                  # + numpy, onnxruntime
    └── tests/test_acoustic_wakeword.py
```

O treino fica em `/home/renatto/Documentos/livekit-wakeword` (fora deste
repositório):

```
livekit-wakeword/
├── configs/saturnbmo_8h.yaml            # dataset e aliases de TTS
├── configs/saturnbmo_8h_generic3.yaml   # treino final (gen3)
├── scripts/saturnbmo_holdout.py         # teste cego
├── scripts/evaluate_saturnbmo.py        # avaliação por pronúncia
├── scripts/saturnbmo_build_generic_model.py
├── scripts/saturnbmo_fill_gaps.py
└── output/saturnbmo_8h_generic3/
    ├── saturnbmo_8h_generic3.onnx
    ├── saturnbmo_8h_generic3.pt
    ├── dataset_manifest.json
    └── evaluation/holdout_8h_gen3_per_phrase.{json,md}
```

---

## 2. Como o detector funciona

O áudio **não** pode ser jogado direto no `saturnbmo.onnx`. O pipeline é o
mesmo do livekit-wakeword, congelado:

```
PCM s16le 16 kHz mono
  -> janela deslizante de 2 s (32000 amostras)
  -> melspectrogram.onnx        (76 quadros de mel, stride 8)
  -> embedding_model.onnx       (16 passos x 96)
  -> saturnbmo.onnx             (1,16,96) -> score 0..1
```

`AcousticWakeWord.feed(pcm)` recebe blocos de 20 ms (o mesmo formato que o app
Android envia), mantém a janela de 2 s, infere a cada `hop_ms` (100 ms por
padrão) e aplica limiar + cooldown + `min_consecutive`.

Latência medida nesta máquina (CPU, janela completa): **~18 ms** por inferência,
~0,9 % do tempo real da janela.

---

## 3. Integração no backend

`backend/config.json` (ou `bmo_backend/config.py`):

```json
"wakeword": {
  "enabled": true,
  "mode": "hybrid",
  "phrases": ["ei bmo", "hey bmo", "hey beemo", "ei beemo", "bmo", "beemo",
              "bimao", "ei bimao", "hey bimao", "bimo", "hey bimo", "ei bimo",
              "be mo", "bi mo", "be eme o", "bê ême ó", "ei be eme o",
              "hey be eme o", "ei abmo", "ei mo", "ei mô", "ei bom", "e mo",
              "e bmo", "oi bmo", "oi beemo", "bem o", "bemo", "abmo", "bi emo"],
  "acoustic_model": "../wakeword/saturnbmo.onnx",
  "mel_model": "../wakeword/melspectrogram.onnx",
  "embedding_model": "../wakeword/embedding_model.onnx",
  "threshold": 0.95,
  "cooldown_s": 2.5,
  "hop_ms": 100,
  "min_consecutive": 3
}
```

Modos:

| `mode` | Comportamento |
|---|---|
| `acoustic` | só o classificador ONNX |
| `transcript` | só validação pela transcrição do STT (comportamento antigo) |
| `hybrid` | os dois; o acústico é o principal e a transcrição é fallback |

Se os ONNX não existirem, o backend **não quebra**: registra um aviso e continua
no modo transcrição. Quando o acústico detecta, o evento
`wakeword.detected` sai com `source: "acoustic"` e o score.

Variáveis de ambiente úteis:

```bash
BMO_WAKEWORD="ei bmo,hey bmo,beemo,bmo"
BMO_WAKEWORD_MODEL=../wakeword/saturnbmo.onnx
BMO_WAKEWORD_THRESHOLD=0.95
```

Ajuste de sensibilidade: **aumentar** o threshold reduz falsos positivos e
exige fala mais clara; **diminuir** deixa mais sensível. O `min_consecutive=3`
filtra disparos isolados; para resposta mais rápida (e mais falsos positivos),
use `2` ou `1`.

---

## 4. Uso

### Backend

```bash
cd /home/renatto/Documentos/saturnBMO/backend
.venv/bin/pip install -r requirements.txt   # inclui numpy e onnxruntime
./run.sh
```

### Teste com o microfone do PC (sem Android)

```bash
cd /home/renatto/Documentos/saturnBMO/backend
.venv/bin/python -m bmo_backend.wakeword_cli --device plughw:2,0 --threshold 0.95
```

O CLI usa `arecord` (ALSA/PipeWire), sem PyAudio. Ctrl+C encerra.

### Testes

```bash
cd /home/renatto/Documentos/saturnBMO/backend
.venv/bin/python -m pytest -q          # 143 testes
```

---

## 5. Como o modelo final foi treinado

Executado nesta máquina (Ryzen 5 5600G, 15 GiB RAM, Radeon RX 7600 8 GB, ROCm
7.1, PyTorch 2.10.0+rocm7.1).

### Composição exata das 8 h

| Parte | Clipes de 2 s | Horas |
|---|---:|---:|
| Positivos (14 pronúncias × 40 originais × 12 rodadas) | 6.720 | 3,733 |
| Negativos duros (60 frases; 110 originais × 12 rodadas) | 1.320 | 0,733 |
| Fala genérica (recorte do conjunto de validação) | 5.400 | 3,000 |
| Ruído de fundo | 960 | 0,533 |
| **Total** | **14.400** | **8,000** |

O conjunto de validação original (16,7 h de fala real) foi dividido: as
primeiras **3 h** entram como negativo genérico no treino; as **13,71 h**
restantes continuam só na validação. O holdout de avaliação é gerado à parte,
com outras vozes e outros prompts, e nunca é usado em treino, seleção de
checkpoint ou escolha de threshold.

As 14 pronúncias alvo são:

```
Ei, BMO | Hey BMO | Hey Beemo | Ei, Beemo | BMO | Beemo | Bimão
Ei, Bimão | Hey, Bimão | Bimo | Hey Bimo | Ei Bimo | Bê-mo | Bi-mo
```

`BMO` e `Beemo` isolados são positivos. A síntese de `BMO` usa a grafia
"Bê Ême Ó" para o VoxCPM pronunciar letra por letra; o rótulo e a avaliação
continuam sendo `BMO`. Os negativos duros cobrem "Ei, Bruno", "Hey bro",
"Ei, bom", "Ei, amor", "Hello BMO", etc., e nunca incluem `BMO`/`Beemo`
isolados.

### Pipeline reproduzível

```bash
cd /home/renatto/Documentos/livekit-wakeword

# 1. Dependências, VoxCPM2, RIRs e ruídos MUSAN (sem ACAV100M)
HF_HUB_DISABLE_XET=1 uv run livekit-wakeword setup \
  --config configs/saturnbmo_8h.yaml --skip-acav

# 2. Geração (560 treino + 140 validação por classe)
uv run livekit-wakeword generate configs/saturnbmo_8h.yaml
# Se algum clipe falhar por OOM, preencha só os buracos:
uv run python scripts/saturnbmo_fill_gaps.py configs/saturnbmo_8h.yaml

# 3. Augmentação (12 rodadas independentes) + features
uv run livekit-wakeword augment configs/saturnbmo_8h.yaml

# 4. Monta o dataset gen3 com 3 h de fala genérica e 0,73 h de negativos duros
uv run python scripts/saturnbmo_build_generic_model.py \
  --model-name saturnbmo_8h_generic3 --generic-clips 5400 --hard-originals 110

# 5. Treino (conv-attention medium, 30k + 3k + 3k steps)
uv run livekit-wakeword train configs/saturnbmo_8h_generic3.yaml

# 6. Export ONNX
uv run livekit-wakeword export configs/saturnbmo_8h_generic3.yaml

# 7. Gera o holdout cego e avalia
uv run python scripts/saturnbmo_holdout.py configs/saturnbmo_8h_generic.yaml
uv run python scripts/evaluate_saturnbmo.py configs/saturnbmo_8h_generic3.yaml \
  --model output/saturnbmo_8h_generic3/saturnbmo_8h_generic3.onnx \
  --positive-dir output/saturnbmo_8h_generic/holdout/positive \
  --negative-dir output/saturnbmo_8h_generic/holdout/negative \
  --background-dir output/saturnbmo_8h_generic/holdout/background \
  --threshold 0.95 --label holdout_8h_gen3
```

Depois copie o classificador final:

```bash
cp output/saturnbmo_8h_generic3/saturnbmo_8h_generic3.onnx \
   /home/renatto/Documentos/saturnBMO/wakeword/saturnbmo.onnx
```

Os arquivos `melspectrogram.onnx` e `embedding_model.onnx` são os mesmos do
livekit-wakeword (hash idêntico); não precisam ser regerados.

---

## 6. Resultados

### Holdout cego (10 clipes limpos por pronúncia, threshold 0,95)

- **Recall limpo:** 68,6% (96/140)
- **Precisão:** 99,0%
- **F1:** 81,0%
- **Falsos positivos:** 1 em 180 janelas de negativas/ruído (0,56%)
- **Menor TPR limpo por pronúncia:** 60,0%
- **Spread entre pronúncias:** 20,0%
- **Latência CPU:** 17,8 ms por janela (RTF 0,0089)

Tabela completa em [AVALIACAO_8H.md](AVALIACAO_8H.md). As pronúncias mais
difíceis no holdout foram "Ei, BMO", "Bê-mo" e "Bimo"; as mais fáceis foram
"Hey Beemo", "Ei, Beemo" e "Beemo".

### Validação (13,71 h de fala genérica + negativas aumentadas)

| Threshold | Recall | FPPH (janela isolada) |
|---|---:|---:|
| 0,90 | 66,7% | 1,76 |
| 0,92 | 62,5% | 1,01 |
| 0,94 | 56,1% | 0,47 |
| 0,95 | 51,2% | 0,20 |
| 0,96 | 44,5% | 0,07 |

### Comparação com o modelo de 4 h

No holdout cego, o modelo novo é melhor em todas as faixas de threshold. Em
threshold equivalente de baixo FPPH:

| Modelo | Threshold | Recall limpo | FPPH no holdout |
|---|---:|---:|---:|
| 4 h (`saturnbmo_4h.onnx`) | 0,94 | 19,3% | 0,0 |
| 8 h gen3 (`saturnbmo.onnx`) | 0,95 | 68,6% | 12,9* |

\* O holdout tem apenas 0,1 h de negativas; 1 falso positivo já vale 10 FPPH.
Na validação de 13,71 h de fala genérica, o gen3 fica em **0,20 FPPH** no
threshold 0,95. Com `min_consecutive=3`, o backend filtra disparos isolados.

---

## 7. Limitações e próximos passos

- **Dados 100% sintéticos no holdout.** Não houve gravação de voz humana real
  neste ciclo; a validação mede o sintetizador.
- **Sem ACAV100M.** Para reduzir ainda mais o FPPH, baixe as features (~16 GB)
  e treine com um dataset maior; o limite de 8 h foi respeitado nesta entrega.
- **Poucos clipes por condição no holdout.** 10 por pronúncia dão intervalos de
  confiança largos (±10–15 pontos).
- **Threshold e cooldown** ainda devem ser calibrados com gravações reais do
  dispositivo (celular no bolso, mesa, distância, ar-condicionado).
- **Ruído em 0 dB** derruba o recall para 0–50% nas pronúncias curtas; o modo
  híbrido usa a transcrição como fallback.
- O modelo exportado é ONNX para CPU; não foi feita quantização INT8.

Para repetir a entrega, siga a seção 5. Para rollback do modelo antigo:

```bash
cp wakeword/saturnbmo_4h.onnx wakeword/saturnbmo.onnx
# e ajuste threshold para 0.75 / min_consecutive para 1 em backend/config.json
```

---

## 8. Arquivos e scripts auxiliares

| Arquivo | Função |
|---|---|
| `scripts/saturnbmo_audio_check.py` | valida integridade/duração/volume dos WAVs e distribuição por pronúncia |
| `scripts/evaluate_saturnbmo.py` | TPR/FNR/FPR/latência por pronúncia em 9 condições |
| `scripts/saturnbmo_holdout.py` | gera o teste cego com vozes/prompts fora do treino |
| `scripts/saturnbmo_fill_gaps.py` | recompõe clipes perdidos por OOM sem duplicar índices |
| `scripts/saturnbmo_build_generic_model.py` | monta o dataset de 8 h com fala genérica + negativos duros |

### Teste cego rápido

```bash
cd /home/renatto/Documentos/livekit-wakeword
uv run python scripts/evaluate_saturnbmo.py configs/saturnbmo_8h_generic3.yaml \
  --positive-dir output/saturnbmo_8h_generic/holdout/positive \
  --negative-dir output/saturnbmo_8h_generic/holdout/negative \
  --background-dir output/saturnbmo_8h_generic/holdout/background \
  --threshold 0.95
```

O relatório sai em `output/<model_name>/evaluation/`.
