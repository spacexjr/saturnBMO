
> **Conjunto cego (holdout):** 10 clipes por pronúncia, vozes/prompts e
> combinações de cfg/timesteps que não aparecem no treino. Nunca usado para
> selecionar checkpoint ou threshold. Threshold de implantação: **0,95**,
> com `min_consecutive=2` e `hop_ms=100` no backend.

## Validação (features aumentadas, 13,71 h de fala genérica + negativas do split)

| Threshold | Recall | FPPH (janela isolada) |
|---|---:|---:|
| 0,90 | 66,7% | 1,76 |
| 0,92 | 62,5% | 1,01 |
| 0,94 | 56,1% | 0,47 |
| 0,95 | 51,2% | 0,20 |
| 0,96 | 44,5% | 0,07 |
| 0,97 | 33,2% | 0,07 |

O threshold 0,95 foi escolhido por ficar próximo da meta de 0,1 FPPH na
validação e manter o menor TPR limpo em 60% no holdout. No backend, a avaliação
deslizante do holdout com `min_consecutive=2` deu **68,6% de recall (96/140) e
0 falso positivo em 140 negativas**; com 3 janelas, o recall cai para 54,3%.

# Avaliação por pronúncia — holdout_8h_gen3

- Modelo: `output/saturnbmo_8h_generic3/saturnbmo_8h_generic3.onnx`
- Positivas: `output/saturnbmo_8h_generic/holdout/positive`
- Negativas: `output/saturnbmo_8h_generic/holdout/negative`
- Threshold: 0.95
- Latência média (CPU, janela de 2 s): 17.76 ms (RTF 0.0089)
- Precisão / recall / F1 (limpo): 99.0% / 68.6% / 81.0%
- Falsos negativos (limpo): 44 de 140
- FPR em negativas/ruído: 0.0056 (~10.00 FPPH por janela)
- Menor TPR limpo entre as pronúncias: 60.0%
- Spread entre as pronúncias: 20.0% (DESEQUILIBRADO)

| Pronúncia | N | Limpo | Ruído 10 dB | Ruído 5 dB | Ruído 0 dB | Baixa | Rápida | Lenta | Distante | Score médio limpo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ei, BMO | 10 | 60.0% | 40.0% | 30.0% | 20.0% | 60.0% | 10.0% | 30.0% | 30.0% | 0.901 |
| Hey BMO | 10 | 60.0% | 40.0% | 30.0% | 20.0% | 60.0% | 20.0% | 40.0% | 10.0% | 0.805 |
| Hey Beemo | 10 | 80.0% | 50.0% | 40.0% | 40.0% | 80.0% | 70.0% | 30.0% | 90.0% | 0.973 |
| Ei, Beemo | 10 | 70.0% | 40.0% | 30.0% | 30.0% | 80.0% | 30.0% | 10.0% | 70.0% | 0.961 |
| BMO | 10 | 80.0% | 60.0% | 50.0% | 30.0% | 80.0% | 50.0% | 60.0% | 50.0% | 0.912 |
| Beemo | 10 | 80.0% | 50.0% | 50.0% | 50.0% | 80.0% | 70.0% | 80.0% | 80.0% | 0.950 |
| Bimão | 10 | 70.0% | 10.0% | 10.0% | 10.0% | 50.0% | 80.0% | 50.0% | 60.0% | 0.952 |
| Ei, Bimão | 10 | 60.0% | 20.0% | 10.0% | 10.0% | 60.0% | 50.0% | 20.0% | 50.0% | 0.880 |
| Hey, Bimão | 10 | 70.0% | 20.0% | 20.0% | 20.0% | 80.0% | 50.0% | 40.0% | 80.0% | 0.925 |
| Bimo | 10 | 60.0% | 10.0% | 0.0% | 0.0% | 50.0% | 60.0% | 40.0% | 40.0% | 0.860 |
| Hey Bimo | 10 | 60.0% | 20.0% | 20.0% | 20.0% | 60.0% | 60.0% | 50.0% | 60.0% | 0.965 |
| Ei Bimo | 10 | 80.0% | 20.0% | 10.0% | 10.0% | 70.0% | 60.0% | 30.0% | 60.0% | 0.969 |
| Bê-mo | 10 | 60.0% | 10.0% | 0.0% | 0.0% | 50.0% | 50.0% | 40.0% | 60.0% | 0.622 |
| Bi-mo | 10 | 70.0% | 40.0% | 20.0% | 10.0% | 70.0% | 60.0% | 50.0% | 70.0% | 0.863 |

Todas as pronúncias-alvo usam a mesma cabeça de classificação e a mesma prioridade; o teste cego (holdout) é avaliado separadamente.
