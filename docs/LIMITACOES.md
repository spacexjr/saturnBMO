# Limitações conhecidas

Este documento lista o que o projeto **não** garante. Ele é intencionalmente conservador: não trate como pronto para produção o que ainda não foi validado.

## 1. Palavra de ativação

A detecção de “Ei, BMO” é **baseada na transcrição** do Whisper.cpp. O fluxo é:

```text
áudio -> whisper.cpp -> texto -> normalização -> comparação com frases
```

Isso não é um detector acústico dedicado. Consequências:

- se o Whisper transcrever errado, a palavra não é detectada;
- ruído, sotaque, microfone longe e eco atrapalham;
- a latência inclui o tempo de transcrição;
- a palavra “BMO” sozinha também ativa, o que pode gerar falsos positivos;
- não há modelo treinado especificamente para “Ei, BMO” neste projeto.

O arquivo `assets/wakeword_hey_jarvis.onnx` é o modelo **“Hey Jarvis”** do projeto original. Ele foi preservado como referência e **não** é usado como detector principal, porque não reconhece “Ei, BMO”.

No teste E2E sintético, a fala “Ei, BMO, que horas são?” foi transcrita como **“E BMO, que horas são?”** e ainda assim foi detectada pela frase normalizada `e bmo`. Isso mostra que a normalização ajuda, mas também que a transcrição não é perfeita.

## 2. STT

- Modelo usado: `ggml-base.bin` (whisper.cpp).
- Português do Brasil, mono 16 kHz.
- Pode errar nomes, números, acentos e palavras parecidas.
- Frases longas ou fala sobreposta podem ser cortadas.
- O VAD é por energia, não neural; em ambiente barulhento pode cortar fala ou detectar ruído.
- O limite de fala é de 15 s por padrão (`audio.max_utterance_s`).
- Não há separação de locutores.

## 3. LLM

- Ollama local, modelo padrão `qwen3.5:2b`.
- Pode alucinar, inventar fatos ou responder de forma inconsistente.
- O backend tenta conter o modelo com prompt e ações autorizadas, mas não há garantia semântica.
- Hora e data são resolvidas localmente antes do LLM.
- Histórico é em memória, por sessão; não há persistência entre reinícios.
- Modelos maiores podem ser lentos em CPU.
- Não há ferramenta de busca na internet, notícias, e-mails etc. O clima é uma exceção: temperatura e previsão de chuva são consultadas no Open-Meteo usando as coordenadas do GPS do celular. Sem permissão de localização no app, a consulta de clima não funciona.

## 4. TTS

- Piper `pt_BR-faber-medium`, 22.050 Hz, quando disponível.
- Fallback para espeak-ng, com voz mais robótica.
- A latência depende do texto e do PC.
- Não há controle de emoção/prosódia além do modelo.
- O áudio é transmitido em streaming; o app espera o `AudioTrack` consumir os frames.
- Não há cancelamento de eco (AEC) dedicado. O app silencia o microfone enquanto fala, mas o alto-falante pode vazar para o microfone em volumes altos.

## 5. Áudio e hardware

- Testes de interface, conexão Wi-Fi, descoberta UDP e APK foram feitos em um **Xiaomi 2412DPC0AI real** (Android 17).
- O áudio do microfone e do alto-falante **não foi validado acusticamente** de forma objetiva (sem medição de sala, SNR ou reconhecimento com voz humana ao vivo).
- O teste E2E usa fala sintetizada pelo Piper, não uma pessoa falando ao vivo.
- Não há garantia de latência máxima; depende de Wi-Fi, CPU, modelo e aparelho.
- Alguns aparelhos aplicam processamento de áudio (cancelamento de ruído, ganho automático) que altera a captura.
- O app usa `AudioRecord`/`AudioTrack`; não usa WebRTC, AEC ou codecs com perda.

## 6. Android

- `minSdk 26` (Android 8.0), `targetSdk 36`.
- O app força **paisagem** (`sensorLandscape`).
- O modo principal mostra somente o rosto; os controles são revelados por toque.
- A tela de Ajustes também é em paisagem e usa rolagem.
- O serviço em primeiro plano depende das políticas do fabricante. Xiaomi/HyperOS pode encerrar o app; é preciso liberar autostart/bateria.
- A permissão de notificações pode ser negada; o serviço continua, mas a notificação pode não aparecer.
- Há testes unitários JVM de configuração, mas não há teste automatizado de instrumentação Android; a validação de UI/áudio é manual.
- O APK release é assinado com uma chave local, não com uma chave de loja. Não há publicação na Play Store.
- O app não tem câmera, permissão de câmera, gravação de áudio em arquivo ou upload para nuvem.

## 7. Rede

- A API é **HTTP/WS sem TLS**, para uso em LAN offline.
- O token e o áudio podem ser observados por quem tiver acesso à rede.
- Não há autenticação de múltiplos usuários, papéis ou revogação central de tokens.
- O backend escuta em `0.0.0.0` por padrão. Não exponha a porta 8765 à internet.
- AP isolation, firewall e redes de convidados podem impedir a conexão.
- A descoberta UDP é limitada à mesma sub-rede e pode ser bloqueada por roteadores.
- O `adb reverse` é apenas para desenvolvimento via USB.

## 8. Escopo do produto

- Um BMO por vez, uma sessão por WebSocket.
- Sem aplicativo iOS, desktop ou web.
- Sem integração com calendário, mensagens, música, câmera, automação residencial ou APIs externas.
- Sem comandos de shell ou controle arbitrário do PC.
- Apenas as ações `get_time` e `get_date` são autorizadas.
- Sem persistência de conversa no backend.
- Sem treinamento de modelo ou fine-tuning.
- Sem garantia de uso contínuo 24/7.

## 9. O que ainda precisa de validação

- Reconhecimento de “Ei, BMO” com voz humana ao vivo, em diferentes distâncias e ruídos.
- Medição de latência ponta a ponta em Wi-Fi real (captura → STT → LLM → TTS → alto-falante).
- Teste prolongado de escuta com tela apagada e serviço em primeiro plano.
- Teste de áudio com o celular dentro da carcaça do BMO (eco, vibração, volume).
- Teste em outros modelos de celular e versões do Android.
- Teste de token revogado, reconexão após queda de Wi-Fi e troca de rede.
- Teste de carga com modelos maiores de LLM/STT.

Se você precisa de um detector acústico robusto de “Ei, BMO”, o próximo passo é treinar/adaptar um modelo de wake word específico e integrá-lo ao app ou ao backend. O modo atual por transcrição é uma solução funcional e transparente, não a ideal para todos os ambientes.
