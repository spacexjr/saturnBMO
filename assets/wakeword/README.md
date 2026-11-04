# saturnBMO — detector de palavra de ativação

Detector acústico local para **"Hey BMO / Hey Beemo / Bê Ême Ó / Ei, Bê Ême Ó"**
(e também "Beemo", "bi-mo", "BMO"), treinado com o
[livekit-wakeword](https://github.com/livekit/livekit-wakeword) e exportado para
ONNX. Ele roda **sem LLM, sem STT e sem rede**, no mesmo backend que já recebe o
áudio do aplicativo Android.

> **Escopo desta entrega:** modelo protótipo treinado em ~4 h, com dados
> sintéticos (VoxCPM2). Ele funciona e está integrado, mas **não** tem a
> qualidade de um modelo treinado com o dataset completo de negativos reais
> (ACAV100M). As limitações e os números medidos estão na seção
> [Resultados reais](#resultados-reais).

---

## 1. O que foi entregue

```
saturnBMO/
├── assets/wakeword/
│   ├── saturnbmo.onnx            # classificador (1,16,96) -> (1,1)
│   ├── melspectrogram.onnx       # áudio 16 kHz -> mel
│   ├── embedding_model.onnx      # mel -> embeddings (16,96)
│   └── AVALIACAO_PER_PHRASE.md   # avaliação por pronúncia
└── backend/
    ├── bmo_backend/acoustic_wakeword.py  # pipeline ONNX completo
    ├── bmo_backend/wakeword_cli.py       # teste com microfone do PC
    ├── bmo_backend/server.py             # integração no WebSocket
    ├── bmo_backend/config.py             # defaults + overrides por ambiente
    ├── config.json                       # configuração em execução
    ├── requirements.txt                  # + numpy, onnxruntime
    └── tests/test_acoustic_wakeword.py
```

O modelo de treino e os dados ficam em
`/home/renatto/Documentos/livekit-wakeword` (fora deste repositório):

```
livekit-wakeword/
├── configs/saturnbmo.yaml       # config completo (7.000/1.400) — não executado
├── configs/saturnbmo_4h.yaml    # config usado nesta entrega (700/140)
├── scripts/saturnbmo_audio_check.py
├── scripts/evaluate_saturnbmo.py
└── output/saturnbmo_4h/
    ├── saturnbmo_4h.onnx
    ├── saturnbmo_4h.pt
    ├── evaluation/per_phrase.json|md
    └── positive_*/ negative_*/ background_* (WAVs + features .npy)
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

Latência medida nesta máquina (CPU, janela completa): **~18–19 ms** por
inferência, ~0,9 % do tempo real da janela.

---

## 3. Integração no backend

`backend/config.json` (ou `bmo_backend/config.py`):

```json
"wakeword": {
  "enabled": true,
  "mode": "hybrid",
  "phrases": ["ei bmo", "ei beemo", "hey bmo", "hey beemo", "be eme o",
              "bê ême ó", "ei be eme o", "beemo", "bi mo", "bmo"],
  "acoustic_model": "../assets/wakeword/saturnbmo.onnx",
  "mel_model": "../assets/wakeword/melspectrogram.onnx",
  "embedding_model": "../assets/wakeword/embedding_model.onnx",
  "threshold": 0.75,
  "cooldown_s": 2.0,
  "hop_ms": 100,
  "min_consecutive": 1
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
BMO_WAKEWORD_MODEL=../assets/wakeword/saturnbmo.onnx
BMO_WAKEWORD_THRESHOLD=0.8
```

Ajuste de sensibilidade: **aumentar** o threshold reduz falsos positivos e
exige fala mais clara; **diminuir** deixa mais sensível.

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
.venv/bin/python -m bmo_backend.wakeword_cli --list-devices
.venv/bin/python -m bmo_backend.wakeword_cli --device "USB HIFI AUDIO"
.venv/bin/python -m bmo_backend.wakeword_cli --device plughw:2,0 --threshold 0.8
```

O CLI usa `arecord` (ALSA/PipeWire), sem PyAudio. Ctrl+C encerra.

### Testes

```bash
cd /home/renatto/Documentos/saturnBMO/backend
.venv/bin/python -m pytest -q          # 47 testes
```

---

## 5. Como o modelo foi treinado

Tudo abaixo foi executado de fato nesta máquina
(Ryzen 5 5600G, 15 GiB RAM, Radeon RX 7600 8 GB, ROCm 7.1, PyTorch 2.10.0+rocm7.1).

```bash
cd /home/renatto/Documentos/livekit-wakeword

# 1. Dependências e modelo TTS (~4,7 GB) + ruídos + RIRs
uv sync --extra train --extra eval --extra export --extra voxcpm
HF_HUB_DISABLE_XET=1 uv run livekit-wakeword setup \
  --config configs/saturnbmo_4h.yaml --skip-acav

# 2. Geração (700 treino + 140 validação por classe)
uv run livekit-wakeword generate configs/saturnbmo_4h.yaml

# 3. Augmentação (3 rodadas) + features
uv run livekit-wakeword augment configs/saturnbmo_4h.yaml

# 4. Treino (conv-attention medium, 30k steps)
uv run livekit-wakeword train configs/saturnbmo_4h.yaml

# 5. Export ONNX
uv run livekit-wakeword export configs/saturnbmo_4h.yaml

# 6. Avaliação por pronúncia
uv run python scripts/evaluate_saturnbmo.py configs/saturnbmo_4h.yaml --threshold 0.75
```

Distribuição exata: 700 = 100 × 7 e 140 = 20 × 7. O VoxCPM cicla
`phrases[i % 7]`, então cada pronúncia recebeu **exatamente** a mesma
quantidade de clipes. As 7 frases são todas positivas, sem hierarquia.

Negativos: 48 frases curadas em pt-BR (incluindo "Hey bro", "Hey Bruno",
"Hello BMO", "Ei, amor") **mais** as frases adversariais geradas
automaticamente pelo repositório, que são filtradas para nunca coincidir com um
alvo exato. "BMO" e "Beemo" isolados **não** entram como negativos.

### Ajuste importante desta execução

O repositório usa as features **ACAV100M** (16 GB, ~2000 h de fala real) como
negativos gerais. Como o alvo era 4 h, elas não foram baixadas
(`--skip-acav`), e o próprio código avisa que o FPR sobe sem elas. Para não
entregar um detector inutilizável, as features do conjunto de validação
(17 h de fala real) foram reaproveitadas como negativos de treino, via:

```bash
ln -sf validation_set_features.npy \
  data/features/openwakeword_features_ACAV100M_2000_hrs_16bit.npy
```

**Consequência:** as métricas oficiais do repositório nesse conjunto deixam de
ser um teste cego e **não são reportadas como generalização**. A avaliação
abaixo usa o `positive_test`/`negative_test` de TTS, que o treino nunca viu.
Para o modelo definitivo, baixe o ACAV100M e use `configs/saturnbmo.yaml`
(7.000/1.400) sem esse reaproveitamento.

---

## 6. Resultados reais

Avaliação no conjunto TTS de teste (20 clipes limpos por pronúncia, nunca
usados no treino), com `--threshold 0.75`:

| Pronúncia | Limpo | Ruído 10 dB | Ruído 5 dB | Ruído 0 dB | Baixa | Rápida | Lenta | Distante | Score médio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Hey BMO | 70% | 65% | 60% | 55% | 70% | 90% | 75% | 80% | 0,712 |
| Hey Beemo | 55% | 60% | 60% | 35% | 55% | 85% | 60% | 60% | 0,677 |
| Bê Ême Ó | 90% | 75% | 65% | 55% | 80% | 65% | 55% | 65% | 0,843 |
| Ei, Bê Ême Ó | 65% | 50% | 45% | 50% | 65% | 60% | 70% | 55% | 0,761 |
| Beemo | 80% | 75% | 70% | 60% | 80% | 85% | 85% | 95% | 0,864 |
| bi-mo | 80% | 55% | 55% | 50% | 75% | 80% | 75% | 70% | 0,782 |
| BMO | 45% | 40% | 45% | 45% | 50% | 65% | 60% | 75% | 0,658 |

- **FPR** em negativas TTS + ruído: **5,1 %** no threshold 0,75
  (9,7 % @ 0,5; 3,3 % @ 0,9).
- **Latência**: 18,8 ms por janela de 2 s (RTF ~0,0094), CPU.
- **Menor TPR limpo entre as 4 oficiais**: 55 % (@ 0,75).
- **Spread entre as 4 oficiais**: 35 % — **desequilibrado**.

Leitura honesta: o modelo **funciona** e reconhece todas as pronúncias, mas:

1. O FPR ainda é alto para uso contínuo (há muitos negativos adversariais
   foneticamente parecidos, tipo "bee mobile", "beeped mo").
2. "Ei, Bê Ême Ó" e "Hey Beemo" ficaram abaixo das demais; a exigência de
   prioridade igual **não foi atingida** com 100 exemplos por pronúncia.
3. 20 clipes por pronúncia dão intervalos de confiança largos (±10 pontos).

### Comparação de thresholds

| Threshold | FPR (TTS) | Menor TPR limpo (4 oficiais) |
|---|---:|---:|
| 0,50 | 9,7 % | 75 % |
| 0,65 | 7,1 % | 55 % |
| 0,75 | 5,1 % | 55 % |
| 0,90 | 3,3 % | 20 % |

O valor 0,75 foi escolhido como padrão por equilibrar falsos positivos e
resposta. Ajuste em `config.json` conforme o ambiente (o microfone do PC e o do
celular têm ruídos diferentes).

---

## 7. Limitações e próximos passos

- **Dados 100 % sintéticos.** Não houve gravação de voz humana real. A validação
  mede o sintetizador, não a sua voz.
- **Sem ACAV100M.** É a maior causa do FPR. Para o modelo de produção, baixe as
  features (~16 GB) e treine com `configs/saturnbmo.yaml`.
- **Poucos exemplos.** 100 positivas por pronúncia é o mínimo para um protótipo.
  O plano completo usa 1.000.
- **Pronúncias desbalanceadas.** "Ei, Bê Ême Ó" precisa de mais dados e/ou
  prompts específicos.
- **Threshold e cooldown** devem ser calibrados com gravações reais do
  dispositivo (celular no bolso, mesa, distância).
- O modelo exportado é ONNX para CPU; não foi feita quantização INT8.

Para repetir a entrega completa (sem o corte de 4 h):

```bash
cd /home/renatto/Documentos/livekit-wakeword
uv run livekit-wakeword setup --config configs/saturnbmo.yaml   # baixa ACAV
uv run livekit-wakeword generate configs/saturnbmo.yaml         # 7.000/1.400
uv run livekit-wakeword augment  configs/saturnbmo.yaml
uv run livekit-wakeword train    configs/saturnbmo.yaml
uv run livekit-wakeword export   configs/saturnbmo.yaml
uv run python scripts/evaluate_saturnbmo.py configs/saturnbmo.yaml
```

Depois copie `output/saturnbmo/saturnbmo.onnx` para
`saturnBMO/assets/wakeword/saturnbmo.onnx`.

---

## 8. Arquivos e scripts auxiliares

| Arquivo | Função |
|---|---|
| `scripts/saturnbmo_audio_check.py` | valida integridade/duração/volume dos WAVs e distribuição por pronúncia |
| `scripts/evaluate_saturnbmo.py` | TPR/FNR/FPR/latência por pronúncia em 9 condições |
| `bmo_backend/acoustic_wakeword.py` | detector incremental independente do LLM |
| `bmo_backend/wakeword_cli.py` | teste de campo com microfone do PC |
| `tests/test_acoustic_wakeword.py` | testes do detector (pulados se os ONNX faltarem) |
