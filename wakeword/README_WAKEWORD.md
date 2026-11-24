# README movido

A documentação do detector de wake word do saturnBMO agora fica em
[README_SATURNBMO.md](README_SATURNBMO.md).

Resumo do estado atual:

- Modelo em produção: `saturnbmo.onnx` (8 h, 14 pronúncias, gen3).
- Modelo antigo preservado: `saturnbmo_4h.onnx`.
- Threshold padrão: `0.95`, `min_consecutive=3`, `hop_ms=100`, `cooldown_s=2.5`.
- Os ONNX ficam em `wakeword/` (não em `assets/wakeword/`).
- Avaliação: [AVALIACAO_8H.md](AVALIACAO_8H.md).
