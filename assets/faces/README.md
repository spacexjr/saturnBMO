# Faces do BMO

Arte das expressões faciais usada pela interface do app. Cada expressão vive na
própria pasta, com frames numerados (`nome_01.png`, `nome_02.png`, ...), para a
animação alternar sem depender de nomes com espaço.

## Especificação

- Canvas: **800 × 480 px**, RGBA, fundo **transparente**.
- O fundo verde (`#BDFFCB`) e os efeitos (lágrimas, Zzz, brilhos, clima) são
  desenhados pelo renderer Compose, não fazem parte do PNG.
- Estilo: contorno petroleum `#01151D`, boca em dois tons
  (`#013F45` + crescente mint `#8AE6BD`), língua/blush rosa `#FD617A`,
  lágrimas ciano `#77DDF5` e lâmpada amarela `#FFD93D`.
- Olhos em pastilha em `x = 218 / 582`, `y = 186`; boca centrada em `x = 400`.
  Essas coordenadas mantêm compatibilidade com o blink e as lágrimas
  procedurais do `BmoFaceRenderer`.

## Estrutura

| Pasta | Frames | Quando aparece |
| --- | --- | --- |
| `idle/` | 1 | repouso / neutro |
| `listening/` | 2 | estado `LISTENING` |
| `speaking/` | 4 | estado `SPEAKING` (01 é a boca fechada entre sílabas) |
| `thinking/` | 6 | estado `THINKING`/`PROCESSING`; a lâmpada acende ao longo do loop |
| `sleeping/` | 2 | sono profundo |
| `sleepy/` | 2 | emoção `SLEEPY` (temas frios, música relaxante) |
| `happy/` | 2 | emoção `HAPPY` |
| `excited/` | 2 | emoção `EXCITED` |
| `love/` | 2 | emoção `LOVE` |
| `sad/` | 2 | emoção `SAD` |
| `confused/` | 2 | emoção `CONFUSED` |
| `angry/` | 2 | emoção `ANGRY` |
| `surprised/` | 1 | emoção `SURPRISED` |
| `error/` | 1 | estado `ERROR` |
| `capturing/` | 1 | captura / surpresa alternativa |
| `warmup/` | 1 | estados `CONNECTING`/`DISCONNECTED` |

`clouds.png` é a arte de nuvens usada pelos temas `CLOUDY` e `STORM`; não é uma
face e não é afetada pela geração.

O mapeamento expressão → arquivos fica em
`android-app/app/src/main/java/com/spacexjr/saturnbmo/ui/BmoFace.kt`
(`FaceController.framesFor`) e o mapeamento estado/emoção → expressão em
`BmoFaceController.kt`.

## Regerar

Requer Python 3 com `pycairo` e `Pillow`:

```bash
python3 tools/generate_bmo_faces.py --sync
```

O script:

1. remove os PNGs antigos de expressão (preserva `clouds.png`);
2. redesenha todos os frames em `assets/faces/`;
3. com `--sync`, espelha o resultado em
   `android-app/app/src/main/assets/faces/` (a pasta que vai para o APK).

Sem `--sync`, apenas `assets/faces/` é atualizado.
