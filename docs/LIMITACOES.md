# Limitações conhecidas

Este documento lista o que o projeto **não** garante. Ele é intencionalmente conservador: não trate como concluído o que ainda não foi validado com o hardware/ambiente real.

## 1. Palavra de ativação

O modo padrão é **hybrid**:

```text
áudio -> classificador acústico ONNX (wakeword/saturnbmo.onnx)
      -> (fallback) Faster-Whisper -> texto -> normalização -> frases
```

- O detector acústico é independente do STT e do LLM.
- Há cooldown e o áudio do próprio BMO é ignorado durante a fala.
- O modelo `wakeword/saturnbmo.onnx` foi treinado com `livekit-wakeword` e dados sintéticos.
- **A validação com voz humana real ainda está pendente.** Áudios sintéticos gerados com Piper/espeak-ng ficaram abaixo do limiar padrão (0,75); isso não prova que o modelo falha com voz humana, mas também não prova que funciona.
- Frases como “Ei BMO”, “Hey BMO”, “Hey Beemo” e “Be eme ó” são aceitas pelo fallback de transcrição. O classificador acústico tem um único alvo de wake word.
- Ruído, sotaque, distância do microfone e eco podem causar falsos negativos ou positivos.
- Se o modelo acústico não detectar, o modo híbrido ainda tenta a transcrição; no modo `acoustic` puro não há esse fallback.

O arquivo `assets/wakeword_hey_jarvis.onnx` é o modelo **“Hey Jarvis”** do projeto original e é preservado apenas como referência. Ele não é usado.

## 2. STT

- Motor principal: **Faster-Whisper** em CPU, modelo `medium`, `compute_type=int8`, idioma `pt`.
- Modelo, dispositivo, `compute_type`, `beam_size`, `num_workers`, filtro VAD e idioma são configuráveis em `backend/config.json`.
- O modelo é baixado/carregado no primeiro uso e pode demorar.
- Pode errar nomes, números, acentos e palavras parecidas.
- Frases longas ou fala sobreposta podem ser cortadas.
- O VAD é por energia, não neural; em ambiente barulhento pode cortar fala ou detectar ruído.
- O limite de fala é de 15 s por padrão (`audio.max_utterance_s`).
- Não há separação de locutores.
- O fallback `whisper.cpp` só funciona se o binário e o modelo existirem; neste repositório o binário pode estar ausente. Faster-Whisper é o caminho principal.

## 3. LLM

- Ollama local; padrão `qwen3:8b`, configurável.
- Pode alucinar, inventar fatos ou responder de forma inconsistente.
- As ferramentas são validadas pelo backend, mas o modelo ainda escolhe qual chamar e com quais argumentos.
- Hora e data são resolvidas localmente antes do LLM.
- Histórico é em memória, por sessão; não há persistência entre reinícios.
- Modelos maiores podem ser lentos em CPU e consumir muita memória.
- `think: false` reduz latência, mas não elimina erros de raciocínio.

## 4. Ferramentas e internet

- `web_search` usa a página HTML do DuckDuckGo; mudanças no site podem quebrar a busca.
- Conteúdo web é tratado como **não confiável**: o modelo recebe texto de terceiros e pode ser induzido a erro por prompt injection.
- URLs privadas/loopback são bloqueadas por padrão (`allow_private_urls=false`).
- `open_url` abre o navegador padrão do desktop; não controla o conteúdo da página.
- A qualidade do resumo depende do modelo local e do tamanho da página.
- Sem acesso a APIs pagas, e-mail, calendário ou redes sociais.

## 5. Controle de aplicativos (KDE/Nobara)

- A descoberta usa arquivos `.desktop`, XDG, Flatpak e AppImage.
- O controle de janelas depende do ambiente gráfico. Em **Wayland**, alguns compositores restringem foco, minimizar, maximizar e fechar janelas de outros aplicativos.
- Fechar aplicativos usa sinais/atalhos suportados pelo ambiente; não há shell arbitrário.
- Processos críticos do sistema são protegidos contra fechamento acidental.
- Nomes de aplicativos podem variar entre instalações e idiomas.
- Não há automação de cliques, teclado ou leitura de tela.

## 6. BitChord 1.8 / música

- Integração exclusivamente por **MPRIS/D-Bus**; o BitChord não é modificado nem reinstalado.
- Descoberta dinâmica de `org.mpris.MediaPlayer2.*`, priorizando `bitchord`.
- Suportado: play, pause, alternar, próxima, anterior, parar e volume.
- **Pesquisar e tocar uma faixa por voz não é possível** pela interface pública do BitChord 1.8. O backend informa essa limitação em vez de fingir que executou.
- Se nenhum player MPRIS estiver ativo, as ferramentas de música retornam indisponível.
- O rosto mostra título/artista/estado quando o backend envia metadados reais.
- O waveform/equalizador é procedural; não é uma análise espectral da faixa.

## 7. Arquivos

- Todas as operações são confinadas à pasta autorizada em `backend/data/access.json`.
- Sem pasta autorizada, as ferramentas recusam tudo.
- Caminhos com `..`, links simbólicos para fora da raiz e escapes são bloqueados.
- Exclusão de arquivo/pasta exige confirmação explícita no app ou por “sim/não”.
- O BMO não pede nem usa privilégios de administrador.
- Não há lixeira: exclusão confirmada remove o item.
- Arquivos binários grandes e codificações exóticas podem não ser lidos corretamente.
- O seletor de pasta exige sessão gráfica no PC e `kdialog` ou `zenity`.

## 8. Informações do sistema

- Apenas leitura de dados do sistema (CPU, memória, disco, uptime etc.).
- Não há shell arbitrário, instalação de pacotes, `sudo` automático ou alteração de serviços.
- Serviços permitidos são uma lista fechada em `tools.system.allowed_services`.

## 9. TTS e áudio

- Piper `pt_BR-faber-medium`, 22.050 Hz, quando disponível.
- Fallback para espeak-ng, com voz mais robótica.
- A latência depende do texto e do PC.
- Não há controle de emoção/prosódia além do modelo.
- O áudio é transmitido em streaming; o app espera o `AudioTrack` consumir os frames.
- Não há cancelamento de eco (AEC) dedicado. O app silencia o microfone enquanto fala, mas o alto-falante pode vazar para o microfone em volumes altos.
- Os arquivos `tools/piper/piper_phonemize` e `libtashkeel_model.ort` podem estar como placeholders LFS; o Piper funciona para PT-BR nos testes atuais, mas esses recursos não estão garantidos.

## 10. Android

- `minSdk 26` (Android 8.0), `targetSdk 36`.
- O app força **paisagem** (`sensorLandscape`).
- O modo principal mostra somente o rosto; os controles são revelados por toque.
- Otimizado para aparelhos modestos (referência: Galaxy A22, 4 GB RAM, 720×1600). O celular não executa STT/LLM.
- O serviço em primeiro plano depende das políticas do fabricante. Xiaomi/HyperOS e alguns Samsung podem encerrar o app; é preciso liberar autostart/bateria.
- A permissão de notificações pode ser negada; o serviço continua, mas a notificação pode não aparecer.
- Há testes unitários JVM, mas não há teste automatizado de instrumentação Android; a validação de UI/áudio é manual.
- O APK release é assinado com uma chave local, não com uma chave de loja.
- O app não tem câmera, permissão de câmera, gravação de áudio em arquivo ou upload para nuvem.

## 11. Rede

- A API é **HTTP/WS sem TLS**, para uso em LAN offline.
- O token e o áudio podem ser observados por quem tiver acesso à rede.
- Não há autenticação de múltiplos usuários, papéis ou revogação central de tokens.
- O backend escuta em `0.0.0.0` por padrão. Não exponha a porta 8765 à internet.
- AP isolation, firewall e redes de convidados podem impedir a conexão.
- A descoberta UDP é limitada à mesma sub-rede e pode ser bloqueada por roteadores.
- O `adb reverse` é apenas para desenvolvimento via USB.

## 12. Escopo do produto

- Um BMO por vez, uma sessão por WebSocket.
- Sem aplicativo iOS, desktop ou web.
- Sem integração com calendário, mensagens, câmera, automação residencial ou APIs pagas.
- Sem comandos de shell ou controle arbitrário do PC.
- Sem persistência de conversa no backend.
- Sem treinamento de modelo ou fine-tuning em tempo de execução.
- Sem garantia de uso contínuo 24/7.

## 13. O que ainda precisa de validação

- Reconhecimento de “Ei, BMO” com **voz humana ao vivo**, em diferentes distâncias e ruídos.
- Medição de latência ponta a ponta em Wi-Fi real (captura → wakeword → STT → LLM → ferramentas → TTS → alto-falante).
- Teste prolongado de escuta com tela apagada e serviço em primeiro plano.
- Teste de áudio com o celular dentro da carcaça do BMO (eco, vibração, volume).
- Teste em outros modelos de celular e versões do Android, especialmente Galaxy A22.
- Teste de controle de janelas em Wayland e X11 com o ambiente KDE real.
- Teste do seletor nativo de pastas em KDE/Wayland e com `zenity`.
- Teste de token revogado, reconexão após queda de Wi-Fi e troca de rede.
- Teste de carga com modelos maiores de LLM/STT.

Se for necessário um detector acústico mais robusto, o próximo passo é coletar amostras de voz humana, reavaliar o limiar e, se preciso, retreinar o modelo de wake word.
