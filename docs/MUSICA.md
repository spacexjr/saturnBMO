# Música: Mopidy + YouTube Music

O BMO toca música de verdade usando três peças locais:

| Peça | Responsabilidade |
| --- | --- |
| **Mopidy 4** | Player, fila, volume e transporte via JSON-RPC em `127.0.0.1`. |
| **ytmusicapi** | Busca, metadados, playlists e músicas curtidas do YouTube Music. |
| **yt-dlp** | Resolve a URL de áudio temporária que o Mopidy consome. |

O backend expõe uma API autenticada para o Android e ferramentas de function
calling para o Ollama. Nenhum comando de shell é executado pelo LLM.

## Por que não usar `mopidy-ytmusic`?

O último release do `mopidy-ytmusic` (0.3.8, de 2022) declara:

```text
Mopidy>=3,<4
pytube>=12.1,<13
ytmusicapi>=0.22,<0.30
```

Ele é incompatível com o Mopidy 4.0.0a15 instalado no PC e depende do `pytube`
antigo, que quebra com frequência. Rebaixar o Mopidy global quebraria o restante
da instalação. Por isso o BMO mantém o **Mopidy como player** e faz a ponte com
o YouTube Music usando `ytmusicapi` + `yt-dlp`:

1. `ytmusicapi` pesquisa a faixa e devolve `videoId`, título, artista e duração.
2. O BMO assina uma URL local `GET /api/music/stream/<videoId>?sig=...`.
3. O Mopidy enfileira essa URL local, nunca uma URL `googlevideo.com` que expira.
4. Quando o Mopidy pede o áudio, o proxy resolve a URL atual com `yt-dlp` e
   repassa o fluxo, aceitando `Range` para busca/seek.

## Instalação no Nobara / Fedora

### 1. Mopidy

```bash
mopidy --version
```

O código foi testado com **Mopidy 4.0.0a15**. Se o comando não existir:

```bash
sudo dnf install mopidy
```

Instale também os plugins do GStreamer necessários para MP3/AAC/Opus e o
`ffmpeg`:

```bash
sudo dnf install gstreamer1-plugins-good gstreamer1-plugins-bad-free \
  gstreamer1-plugins-ugly-free gstreamer1-plugin-libav ffmpeg
```

> Em algumas versões do Fedora/Nobara o pacote se chama
> `gstreamer1-plugins-ugly` ou `gstreamer1-plugin-libav`. Verifique com
> `dnf search gstreamer1-plugin`.

### 2. Configuração automática recomendada

Na raiz do projeto, execute uma vez:

```bash
./scripts/setupbackend.sh
```

Ele cria toda a configuração local do Mopidy em
`backend/data/mopidy/mopidy.conf`, configura `backend/.env`, gera/verifica o
token e valida a configuração. Depois, suba os dois serviços juntos:

```bash
./scripts/start-all.sh
./scripts/status-all.sh
```

O config gerado habilita:

- HTTP em `127.0.0.1:6680` (nunca `0.0.0.0`);
- extensão `stream`, que permite ao Mopidy consumir a URL assinada do backend;
- saída de áudio pelo PipeWire/PulseAudio da sessão do usuário.

Teste em primeiro plano:

```bash
mopidy --config backend/data/mopidy/mopidy.conf
curl -sS -X POST http://127.0.0.1:6680/mopidy/rpc \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"core.get_version","params":{}}'
```

Resposta esperada: `{"jsonrpc":"2.0","id":1,"result":"4.0.0..."}`.

`./scripts/start-all.sh` inicia os dois serviços em segundo plano e registra os
PIDs em `backend/data/run/`. Para iniciar junto com a sessão gráfica, adapte
`scripts/mopidy-user.service.example` para apontar para
`backend/data/mopidy/mopidy.conf`.

Se preferir configurar o Mopidy manualmente em `~/.config/mopidy/`, use
`docs/mopidy.conf.example` como referência.

### 3. Dependências do backend

As dependências já estão em `backend/requirements.txt`:

```text
ytmusicapi>=1.10,<2
yt-dlp>=2025.1
```

Atualize o ambiente:

```bash
./scripts/setupbackend.sh
# ou
cd backend && .venv/bin/pip install -r requirements.txt
```

Mantenha o `yt-dlp` atualizado. O YouTube muda com frequência:

```bash
cd backend && .venv/bin/pip install -U yt-dlp
```

### 4. Configuração do BMO

A seção `music` de `backend/config.json` já vem preenchida. O essencial:

```json
{
  "music": {
    "enabled": true,
    "mopidy": {
      "rpc_url": "http://127.0.0.1:6680/mopidy/rpc",
      "timeout_s": 20,
      "confirm_timeout_s": 10
    },
    "ytmusic": {
      "enabled": true,
      "auth_file": "data/ytmusic_auth.json",
      "cookies_file": "",
      "language": "pt",
      "location": "BR",
      "max_results": 10
    },
    "stream": {
      "enabled": true,
      "public_base_url": "",
      "secret_file": "data/music_stream.secret",
      "cache_ttl_s": 1800,
      "timeout_s": 30
    }
  }
}
```

`public_base_url` vazio usa `http://127.0.0.1:<porta do backend>`. Só altere se
o Mopidy estiver em outra máquina — e, nesse caso, proteja a rede.

Variáveis equivalentes:

```bash
BMO_MUSIC_ENABLED=true
BMO_MOPIDY_RPC_URL=http://127.0.0.1:6680/mopidy/rpc
BMO_YTMUSIC_ENABLED=true
BMO_YTMUSIC_AUTH_FILE=data/ytmusic_auth.json
BMO_YTMUSIC_COOKIES_FILE=
BMO_YTMUSIC_LANGUAGE=pt
BMO_YTMUSIC_LOCATION=BR
BMO_MUSIC_STREAM_BASE_URL=
```

### 5. Autenticação do YouTube Music (opcional)

Busca e reprodução funcionam **sem login**. A biblioteca pessoal
(`music_playlist_list`, `music_playlist_play`, `music_liked_songs`) exige um
arquivo de autenticação de navegador.

```bash
cd backend
.venv/bin/ytmusicapi browser
# escolha o arquivo de saída: data/ytmusic_auth.json
chmod 600 data/ytmusic_auth.json
```

Também é possível gerar com:

```bash
.venv/bin/python -m ytmusicapi browser
```

Ou use o script do projeto, que abre o navegador, aceita headers crus ou um
comando `curl` copiado do DevTools, valida a conta e salva no caminho
configurado:

```bash
./scripts/ytmusic_login.py

# somente validar a sessão existente
./scripts/ytmusic_login.py --check

# sem abrir o navegador / ler headers de um arquivo
./scripts/ytmusic_login.py --no-browser --headers /tmp/headers.txt
```

Passo a passo: faça login em `https://music.youtube.com`, abra o DevTools (F12),
vá em **Network/Rede**, recarregue a página, filtre por `browse`, clique numa
requisição `browse?...` e use **Copy as cURL** (ou copie os Request Headers).
Cole no terminal e pressione Enter duas vezes. O script grava o arquivo com
permissão `600` e só substitui a autenticação antiga se a nova sessão for
validada.

O arquivo contém cookies de sessão. Ele está no `.gitignore` e nunca deve ser
commitado, enviado em prints ou compartilhado. Se a autenticação for removida,
o BMO volta ao modo anônimo para busca.

### 6. Cookies para o yt-dlp (opcional)

Algumas faixas exigem idade, região ou conta. Exporte cookies do navegador no
formato Netscape e aponte:

```bash
BMO_YTMUSIC_COOKIES_FILE=/home/SEU_USUARIO/.config/bmo/cookies.txt
```

O arquivo também é ignorado pelo Git. Use apenas com sua própria conta.

## API HTTP

Todas as rotas exigem o mesmo token do restante do backend:

```bash
TOKEN=$(cat backend/data/token)
BASE=http://127.0.0.1:8765

curl -H "Authorization: Bearer $TOKEN" $BASE/api/music/state
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/music/search?q=legiao+urbana&filter=songs&limit=5"
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"track_id":"VIDEO_ID"}' $BASE/api/music/play
```

| Método | Rota | Função |
| --- | --- | --- |
| GET | `/api/music/state` | Estado real: status, faixa, posição, duração, volume e fila. |
| GET | `/api/music/now-playing` | Estado com o campo `now_playing`. |
| GET | `/api/music/queue` | Fila real do Mopidy com metadados. |
| GET | `/api/music/search?q=&filter=&limit=` | Busca no YouTube Music. |
| GET | `/api/music/playlists` | Playlists da conta autenticada. |
| POST | `/api/music/play` | `{"track_id":"..."}`; só retorna 200 após confirmação. |
| POST | `/api/music/pause` | Pausa e confirma o estado. |
| POST | `/api/music/resume` | Retoma e confirma o estado. |
| POST | `/api/music/stop` | Para e confirma o estado. |
| POST | `/api/music/next` | Próxima faixa; confirma que a faixa mudou. |
| POST | `/api/music/previous` | Faixa anterior; confirma que a faixa mudou. |
| POST | `/api/music/volume` | `{"volume":0..100}`; relê o volume aplicado. |
| POST | `/api/music/queue/add` | `{"track_id":"..."}`. |
| POST | `/api/music/queue/remove` | `{"index":0}`. |
| POST | `/api/music/queue/clear` | Limpa a fila. |

O proxy `GET/HEAD /api/music/stream/{video_id}?sig=...` é a única rota sem
token. A assinatura HMAC-SHA256 é gerada com `data/music_stream.secret` e só
serve para o `video_id` correspondente.

### Confirmação de reprodução

`music_play` só devolve `verified: true` depois que o Mopidy informa
`status=playing` **e** a faixa atual tem o mesmo `videoId` pedido. Caso
contrário, a API responde HTTP 409 com o estado real. O LLM recebe essa falha e
não pode dizer que a música começou.

## Ferramentas do LLM

O agente recebe estas ferramentas:

- `music_search`, `music_play`, `music_pause`, `music_resume`, `music_stop`
- `music_next`, `music_previous`
- `music_set_volume`, `music_get_volume`
- `music_get_state`, `music_get_now_playing`
- `music_queue_add`, `music_queue_remove`, `music_queue_clear`, `music_queue_list`
- `music_playlist_list`, `music_playlist_play`, `music_liked_songs`

Todas chamam métodos validados do `MusicManager`. O modelo não recebe acesso a
shell, `subprocess`, arquivos de credenciais ou à porta do Mopidy.

Para pedidos diretos como “toque Bohemian Rhapsody”, o agente chama
`music_play` com `{"query": "Bohemian Rhapsody"}`. A ferramenta pesquisa a
faixa e só retorna depois da confirmação real do Mopidy; o modelo não precisa
encadear `music_search` + `music_play` e não deve usar `music_queue_add` no
lugar de `music_play`. `music_play` também aceita `track_id` quando o id já foi
obtido por `music_search`. Os adaptadores das ferramentas aceitam sinônimos
comuns gerados por modelos pequenos (`id`/`video_id` para `track_id`,
`type`/`kind` para `filter`, `level`/`percent` para `volume`), sempre
normalizando antes da validação do `MusicManager`.

## Testes

Testes automatizados (não precisam de rede nem de Mopidy real):

```bash
cd backend
.venv/bin/python -m pytest tests/test_music.py -q
```

Teste real do Mopidy instalado:

```bash
# com o Mopidy rodando em 127.0.0.1:6680
cd backend
.venv/bin/python -m pytest tests/test_music.py -q -k mopidy
```

Smoke test manual completo (busca real, yt-dlp, Mopidy e API):

```bash
TOKEN=$(cat backend/data/token)
curl -sS -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8765/api/music/search?q=never+gonna+give+you+up&filter=songs&limit=1"
# copie o id e execute:
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"track_id":"mW5d-4PmK1U"}' http://127.0.0.1:8765/api/music/play
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/music/state
```

## Limitações reais

- O YouTube Music não possui API oficial estável. `ytmusicapi` e `yt-dlp`
  podem quebrar quando o YouTube muda; atualize as duas bibliotecas.
- A URL de áudio expira. Por isso o BMO guarda apenas a URL local assinada e
  resolve novamente no momento da reprodução.
- Faixas com restrição de idade, região, assinatura ou DRM podem exigir cookies
  válidos. Sem isso, a API devolve erro real, não sucesso falso.
- A biblioteca pessoal exige autenticação por navegador. Busca e reprodução
  anônimas continuam funcionando.
- Os metadados da fila ficam em memória. Se o backend reiniciar, a fila do
  Mopidy continua existindo, mas títulos/artistas podem virar `null` até a
  faixa ser tocada novamente.
- O BMO não baixa arquivos permanentemente; o áudio é transmitido ao Mopidy.
- Volume acima de 100% ou abaixo de 0 é rejeitado pela API.
- O Mopidy precisa estar acessível em `127.0.0.1`. Não exponha a porta 6680 na
  rede local.
