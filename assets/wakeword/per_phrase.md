# Avaliação por pronúncia — saturnbmo_4h

- Modelo: `output/saturnbmo_4h/saturnbmo_4h.onnx`
- Threshold: 0.75
- Latência média (CPU, janela de 2 s): 19.11 ms (RTF 0.0096)
- FPR em negativas/ruído: 0.0514 (~92.50 FPPH por janela)
- Menor TPR limpo entre as 4 oficiais: 55.0%
- Spread entre as 4 oficiais: 35.0% (DESEQUILIBRADO)

| Pronúncia | N | Limpo | Ruído 10 dB | Ruído 5 dB | Ruído 0 dB | Baixa | Rápida | Lenta | Distante | Score médio limpo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Hey BMO | 20 | 70.0% | 65.0% | 60.0% | 55.0% | 70.0% | 90.0% | 75.0% | 80.0% | 0.712 |
| Hey Beemo | 20 | 55.0% | 60.0% | 60.0% | 35.0% | 55.0% | 85.0% | 60.0% | 60.0% | 0.677 |
| Bê Ême Ó | 20 | 90.0% | 75.0% | 65.0% | 55.0% | 80.0% | 65.0% | 55.0% | 65.0% | 0.843 |
| Ei, Bê Ême Ó | 20 | 65.0% | 50.0% | 45.0% | 50.0% | 65.0% | 60.0% | 70.0% | 55.0% | 0.761 |
| Beemo | 20 | 80.0% | 75.0% | 70.0% | 60.0% | 80.0% | 85.0% | 85.0% | 95.0% | 0.864 |
| bi-mo | 20 | 80.0% | 55.0% | 55.0% | 50.0% | 75.0% | 80.0% | 75.0% | 70.0% | 0.782 |
| BMO | 20 | 45.0% | 40.0% | 45.0% | 45.0% | 50.0% | 65.0% | 60.0% | 75.0% | 0.658 |

As quatro pronúncias oficiais estão em **negrito** no objetivo do projeto; as três curtas usam a mesma cabeça de classificação e a mesma prioridade.
