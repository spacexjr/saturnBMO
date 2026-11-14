package com.spacexjr.saturnbmo

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import androidx.core.content.ContextCompat
import com.spacexjr.saturnbmo.audio.AudioCapture
import com.spacexjr.saturnbmo.audio.AudioPlayer
import com.spacexjr.saturnbmo.location.BmoLocation
import com.spacexjr.saturnbmo.net.BmoClient
import com.spacexjr.saturnbmo.net.ServerDiscovery
import com.spacexjr.saturnbmo.ui.face.BmoFaceEmotion
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit
import kotlin.math.min

/**
 * Núcleo do app: conexão WebSocket, microfone, reprodução e estado da UI.
 * Um único singleton atende a Activity e o serviço em primeiro plano.
 */
class BmoEngine private constructor(context: Context) {
    private val appContext = context.applicationContext
    private val store = SettingsStore(appContext)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val locationProvider = BmoLocation(appContext)
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .build()

    // O seletor de pasta nativo espera a pessoa escolher no PC; pode demorar.
    private val httpLong = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(300, TimeUnit.SECONDS)
        .build()

    private val _ui = MutableStateFlow(BmoUiState())
    val uiState: StateFlow<BmoUiState> = _ui.asStateFlow()

    private val _logs = MutableStateFlow<List<LogEntry>>(emptyList())
    val logs: StateFlow<List<LogEntry>> = _logs.asStateFlow()

    @Volatile
    private var settings: AppSettings = store.load()

    private var client: BmoClient? = null
    private var capture: AudioCapture? = null
    private var testCapture: AudioCapture? = null
    private val player = AudioPlayer()
    private var reconnectJob: Job? = null
    private var connectTimeoutJob: Job? = null
    private var playbackJob: Job? = null
    private var mediaPollJob: Job? = null
    private var faceExpiryJob: Job? = null
    private var captureRecoveryJob: Job? = null
    private var captureRecoveryAttempt = 0
    private var wantListening = false
    private var manualDisconnect = false
    private var captureForTest = false
    private var lastSeq = -1L
    private var currentAssistantId = ""
    private var audioStarted = false
    private var audioStreamEnded = false
    private var playbackDoneSent = false
    private var audioStreamId = 0
    private var currentDurationMs = 0L
    private var currentSampleRate = 22050
    private var currentChannels = 1
    @Volatile
    private var lastLocation: Location? = null
    @Volatile
    private var lastLocationAt = 0L

    init {
        player.updateVolume(settings.volume)
        addLog("INFO", "Aplicativo iniciado. Servidor: ${if (settings.isConfigured) settings.host else "não configurado"}.")
        if (settings.autoConnect && settings.isConfigured) connect(settings, automatic = true)
    }

    // ------------------------------------------------------------------
    // Configuração e conexão
    // ------------------------------------------------------------------

    fun currentSettings(): AppSettings = settings

    fun saveSettings(newSettings: AppSettings, reconnect: Boolean = true) {
        settings = newSettings.copy(host = newSettings.host.trim())
        store.save(settings)
        player.updateVolume(settings.volume)
        addLog("INFO", "Configurações salvas. Servidor ${settings.host}:${settings.port}.")
        if (reconnect) connect(settings)
    }

    fun setVolume(value: Float) {
        settings = settings.copy(volume = value.coerceIn(0f, 1f))
        store.saveVolume(settings.volume)
        player.updateVolume(settings.volume)
    }

    fun connect(newSettings: AppSettings = settings, automatic: Boolean = false) {
        settings = newSettings.copy(host = newSettings.host.trim())
        manualDisconnect = false
        reconnectJob?.cancel()
        connectTimeoutJob?.cancel()
        mediaPollJob?.cancel()
        mediaPollJob = null
        client?.close()
        client = null
        // Uma reconexão automática preserva o AudioRecord: recriar o microfone a
        // cada queda era o que deixava a conversa seguinte sem captura.
        if (!automatic) {
            wantListening = false
            stopCaptureInternal(sendEnd = false)
            cancelCaptureRecovery()
        }
        stopLocalPlayback()
        clearModelFace()
        if (!settings.isConfigured) {
            _ui.update {
                it.copy(
                    connection = ConnectionState.DISCONNECTED,
                    bmoState = BmoState.DISCONNECTED,
                    faceState = BmoState.DISCONNECTED,
                    listening = false,
                    listeningRequested = false,
                    statusDetail = "Configure o endereço do PC nas opções.",
                    lastError = "Servidor não configurado.",
                )
            }
            addLog("AVISO", "Conexão cancelada: servidor não configurado.")
            return
        }
        lastSeq = -1
        _ui.update {
            it.copy(
                connection = if (automatic) ConnectionState.RECONNECTING else ConnectionState.CONNECTING,
                bmoState = BmoState.CONNECTING,
                faceState = BmoState.CONNECTING,
                listening = if (automatic) it.listening else false,
                listeningRequested = if (automatic) it.listeningRequested else false,
                statusDetail = "Conectando a ${settings.host}:${settings.port}...",
                lastError = null,
            )
        }
        addLog("INFO", "Conectando a ${settings.wsUrl}${if (automatic) " (automático)" else ""}.")
        val newClient = BmoClient(object : BmoClient.Listener {
            override fun onOpen() {
                addLog("INFO", "Canal aberto. Aguardando saudação do backend.")
            }

            override fun onText(text: String) = handleServerText(text)

            override fun onBinary(bytes: ByteArray) = handleServerAudio(bytes)

            override fun onClosed(code: Int, reason: String) {
                if (manualDisconnect) return
                connectionLost(closeMessageFor(code), allowReconnect = !isAuthCloseCode(code))
            }

            override fun onFailure(message: String) {
                if (manualDisconnect) return
                connectionLost("Falha de conexão: $message")
            }
        })
        client = newClient
        newClient.connect(settings)
        connectTimeoutJob = scope.launch {
            delay(15_000)
            if (_ui.value.connection == ConnectionState.CONNECTING ||
                _ui.value.connection == ConnectionState.RECONNECTING
            ) {
                connectionLost("Tempo esgotado ao conectar. Confira o IP, a porta e o Wi-Fi.")
            }
        }
    }

    fun disconnect() {
        manualDisconnect = true
        wantListening = false
        reconnectJob?.cancel()
        connectTimeoutJob?.cancel()
        cancelCaptureRecovery()
        stopCaptureInternal(sendEnd = false)
        stopLocalPlayback()
        clearModelFace()
        stopMicTest()
        player.stop()
        mediaPollJob?.cancel()
        mediaPollJob = null
        client?.close()
        client = null
        _ui.update {
            it.copy(
                connection = ConnectionState.DISCONNECTED,
                bmoState = BmoState.DISCONNECTED,
                faceState = BmoState.DISCONNECTED,
                faceExpression = null,
                faceLabel = "",
                listening = false,
                listeningRequested = false,
                statusDetail = "Desconectado.",
                micLevel = 0f,
                pendingConfirmation = null,
                activity = null,
            )
        }
        addLog("INFO", "Desconectado manualmente.")
    }

    fun ensureConnected() {
        if (!_ui.value.connected && settings.isConfigured) connect(settings, automatic = true)
    }

    /**
     * Pede para manter o microfone ativo (inclusive após uma reconexão).
     * O serviço em primeiro plano usa este método porque pode ser iniciado
     * antes de o WebSocket terminar de conectar.
     */
    fun requestListening(): Boolean {
        wantListening = true
        _ui.update { it.copy(listeningRequested = true) }
        if (_ui.value.connected) {
            val started = startListening()
            if (!started) scheduleCaptureRecovery()
            return started
        }
        if (settings.isConfigured) {
            addLog("INFO", "Escuta solicitada; aguardando conexão com o PC.")
            ensureConnected()
        } else {
            wantListening = false
            fail("Configure o servidor do PC antes de ativar o microfone.")
        }
        return false
    }

    /** 4401 = token recusado; 4400 = protocolo recusado. */
    private fun isAuthCloseCode(code: Int): Boolean = code == 4401 || code == 4400

    private fun closeMessageFor(code: Int): String = when (code) {
        4401 -> "Token inválido ou ausente. Copie o token atual de backend/data/token e salve em Ajustes."
        4400 -> "O servidor recusou o protocolo. Atualize o app e o backend."
        else -> "Conexão encerrada pelo servidor (código $code)."
    }

    private fun connectionLost(message: String, allowReconnect: Boolean = true) {
        connectTimeoutJob?.cancel()
        client?.close()
        client = null
        // Falhas de rede mantêm o microfone vivo; ele só é encerrado em
        // desconexão manual ou quando o servidor recusa autenticação/protocolo.
        if (!allowReconnect) {
            wantListening = false
            cancelCaptureRecovery()
            stopCaptureInternal(sendEnd = false)
        }
        stopLocalPlayback()
        clearModelFace()
        mediaPollJob?.cancel()
        mediaPollJob = null
        val keepCapture = allowReconnect && wantListening && capture?.isRunning == true
        _ui.update {
            it.copy(
                connection = if (allowReconnect && settings.autoConnect && settings.isConfigured)
                    ConnectionState.RECONNECTING else ConnectionState.DISCONNECTED,
                bmoState = BmoState.DISCONNECTED,
                faceState = BmoState.DISCONNECTED,
                faceExpression = null,
                faceLabel = "",
                listening = keepCapture,
                listeningRequested = allowReconnect && wantListening,
                micLevel = 0f,
                statusDetail = if (keepCapture)
                    "Conexão perdida. O microfone será retomado ao reconectar."
                else message,
                lastError = message,
                pendingConfirmation = null,
                activity = null,
            )
        }
        addLog("ERRO", message)
        if (allowReconnect && settings.autoConnect && settings.isConfigured && !manualDisconnect) {
            val attempt = _ui.value.reconnectAttempt + 1
            val waitMs = min(15_000L, 1000L * (1 shl min(attempt, 4)))
            _ui.update { it.copy(reconnectAttempt = attempt) }
            addLog("INFO", "Nova tentativa em ${waitMs / 1000}s.")
            reconnectJob?.cancel()
            reconnectJob = scope.launch {
                delay(waitMs)
                if (!manualDisconnect) connect(settings, automatic = true)
            }
        }
    }

    // ------------------------------------------------------------------
    // Microfone
    // ------------------------------------------------------------------

    fun hasMicrophonePermission(): Boolean =
        ContextCompat.checkSelfPermission(appContext, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    // ------------------------------------------------------------------
    // Localização (clima)
    // ------------------------------------------------------------------

    fun hasLocationPermission(): Boolean = locationProvider.hasPermission()

    /** Obtém uma leitura nova e a envia ao backend para as consultas de clima. */
    fun refreshLocation() {
        if (!_ui.value.connected) return
        if (!hasLocationPermission()) {
            addLog("AVISO", "Localização sem permissão; o clima ficará sem coordenadas.")
            return
        }
        if (lastLocation != null &&
            System.currentTimeMillis() - lastLocationAt < LOCATION_MAX_AGE_MS
        ) {
            sendCurrentLocation()
            return
        }
        locationProvider.requestCurrent { location ->
            if (location == null) {
                addLog("AVISO", "Não foi possível obter a localização do celular.")
                return@requestCurrent
            }
            lastLocation = location
            lastLocationAt = System.currentTimeMillis()
            _ui.update { it.copy(locationReady = true) }
            addLog(
                "INFO",
                "Localização obtida (precisão de aproximadamente ${location.accuracy.toInt()} m).",
            )
            sendCurrentLocation()
        }
    }

    private fun sendCurrentLocation() {
        val location = lastLocation ?: return
        if (!_ui.value.connected) return
        sendJson(
            JSONObject()
                .put("type", "location")
                .put("latitude", location.latitude)
                .put("longitude", location.longitude)
                .put("accuracy", location.accuracy.toDouble())
        )
    }

    fun startListening(): Boolean {
        if (!_ui.value.connected) {
            fail("Conecte-se ao PC antes de ativar o microfone.")
            return false
        }
        if (!hasMicrophonePermission()) {
            _ui.update { it.copy(listeningRequested = false) }
            fail("Permissão de microfone não concedida. Autorize em Configurações do Android.")
            return false
        }
        if (capture?.isRunning == true) return true
        // Captura antiga que morreu por falha de leitura: descarta antes de abrir outra.
        capture?.let { stale ->
            capture = null
            stale.stop()
        }
        stopMicTest()
        val newCapture = AudioCapture(appContext, object : AudioCapture.Listener {
            override fun onLevel(level: Float) {
                _ui.update { it.copy(micLevel = level) }
            }

            override fun onPcm(bytes: ByteArray) {
                // `wantListening` mantém o envio durante uma reconexão do WebSocket;
                // se o cliente estiver nulo, o bloco é descartado.
                if (!captureForTest && wantListening && !audioMuted) {
                    client?.sendBytes(bytes)
                }
            }

            override fun onError(message: String) {
                scope.launch { handleCaptureFailure(message) }
            }
        })
        if (!newCapture.start()) {
            _ui.update { it.copy(micLevel = 0f) }
            scheduleCaptureRecovery()
            return false
        }
        capture = newCapture
        captureForTest = false
        wantListening = true
        captureRecoveryAttempt = 0
        if (!sendAudioStart()) {
            newCapture.stop()
            capture = null
            fail("Não foi possível avisar o servidor sobre o áudio.")
            return false
        }
        sendCurrentLocation()
        refreshLocation()
        _ui.update {
            it.copy(
                listening = true,
                listeningRequested = true,
                bmoState = BmoState.LISTENING,
                faceState = BmoState.LISTENING,
                statusDetail = "Microfone ativo. Diga \"Ei, BMO\".",
                lastError = null,
            )
        }
        addLog("INFO", "Microfone ativo (16 kHz, mono, PCM 16 bits).")
        return true
    }

    private fun sendAudioStart(): Boolean = sendJson(
        JSONObject()
            .put("type", "audio.start")
            .put("format", "pcm_s16le")
            .put("sample_rate", AudioCapture.SAMPLE_RATE)
            .put("channels", AudioCapture.CHANNELS)
    )

    fun stopListening() {
        wantListening = false
        cancelCaptureRecovery()
        _ui.update { it.copy(listeningRequested = false) }
        if (capture?.isRunning != true && !_ui.value.listening) return
        stopCaptureInternal(sendEnd = true)
        stopMicTest()
        _ui.update {
            it.copy(
                listening = false,
                listeningRequested = false,
                micLevel = 0f,
                bmoState = if (it.bmoState == BmoState.LISTENING) BmoState.IDLE else it.bmoState,
                faceState = if (it.faceState == BmoState.LISTENING) BmoState.IDLE else it.faceState,
                statusDetail = "Microfone pausado.",
            )
        }
        addLog("INFO", "Microfone pausado.")
    }

    fun toggleListening() {
        if (_ui.value.listening) stopListening() else startListening()
    }

    private fun stopCaptureInternal(sendEnd: Boolean) {
        val current = capture
        capture = null
        current?.stop()
        captureForTest = false
        if (sendEnd) sendJson(JSONObject().put("type", "audio.end"))
    }

    private fun cancelCaptureRecovery() {
        captureRecoveryJob?.cancel()
        captureRecoveryJob = null
        captureRecoveryAttempt = 0
    }

    private fun handleCaptureFailure(message: String) {
        if (manualDisconnect) return
        if (!wantListening) {
            addLog("AVISO", message)
            return
        }
        val current = capture
        if (current != null && current.isRunning) {
            // Callback atrasado de uma captura antiga; a atual continua válida.
            return
        }
        capture = null
        // Libera o AudioRecord que falhou antes de tentar abrir outro.
        current?.stop()
        captureForTest = false
        _ui.update {
            it.copy(
                listening = false,
                listeningRequested = true,
                micLevel = 0f,
                statusDetail = "Microfone indisponível; reiniciando...",
                lastError = message,
            )
        }
        addLog("ERRO", message)
        scheduleCaptureRecovery()
    }

    /** Recria o AudioRecord com espera progressiva, sem encerrar a sessão. */
    private fun scheduleCaptureRecovery() {
        if (!wantListening || manualDisconnect) return
        if (captureRecoveryJob?.isActive == true) return
        if (!hasMicrophonePermission()) {
            wantListening = false
            _ui.update { it.copy(listeningRequested = false) }
            addLog("ERRO", "Sem permissão de microfone; recuperação cancelada.")
            return
        }
        captureRecoveryJob = scope.launch {
            var attempt = 0
            while (wantListening && !manualDisconnect) {
                if (capture?.isRunning == true) break
                if (!_ui.value.connected) {
                    delay(1000)
                    continue
                }
                val waitMs = min(10_000L, 500L * (1 shl min(attempt, 4)))
                addLog("AVISO", "Reiniciando microfone em ${waitMs / 1000.0}s.")
                delay(waitMs)
                if (!wantListening || manualDisconnect) break
                if (!_ui.value.connected) {
                    attempt++
                    continue
                }
                if (startListening()) {
                    addLog("INFO", "Microfone restaurado após falha.")
                    captureRecoveryAttempt = 0
                    break
                }
                attempt++
            }
        }
    }

    private fun resetStreamState() {
        audioStarted = false
        audioStreamEnded = false
        playbackDoneSent = false
    }

    /**
     * Interrompe a reprodução local e invalida o job antigo. O incremento do id
     * evita que o `finally` de um stream antigo pare o AudioTrack do próximo.
     */
    private fun stopLocalPlayback() {
        audioStreamId++
        playbackJob?.cancel()
        playbackJob = null
        player.stop()
        resetStreamState()
        setAudioMuted(false)
        _ui.update { it.copy(audioPlaying = false, vadSpeaking = false) }
    }

    private fun clearModelFace() {
        faceExpiryJob?.cancel()
        faceExpiryJob = null
        if (_ui.value.faceExpression != null || _ui.value.faceLabel.isNotEmpty()) {
            _ui.update { it.copy(faceExpression = null, faceLabel = "") }
        }
    }

    private fun handleModelFace(json: JSONObject) {
        val emotion = BmoFaceEmotion.fromCode(json.optString("expression"))
        if (emotion == null) {
            addLog("AVISO", "Expressão facial inválida recebida do servidor.")
            return
        }
        val expression = emotion.name.lowercase(Locale.ROOT)
        val label = json.optString("label").ifBlank { expression }
        val holdMs = json.optLong("hold_ms", 8000L).coerceIn(500L, 60_000L)
        faceExpiryJob?.cancel()
        _ui.update { it.copy(faceExpression = expression, faceLabel = label) }
        addLog("INFO", "Expressão facial: $label.")
        // Mesmo que o backend não envie face.restore, a expressão não fica presa.
        faceExpiryJob = scope.launch {
            delay(holdMs + 2_000L)
            if (_ui.value.faceExpression == expression) {
                _ui.update { it.copy(faceExpression = null, faceLabel = "") }
                addLog("INFO", "Expressão facial voltou ao estado automático.")
            }
        }
    }

    private fun handleFaceRestore(json: JSONObject) {
        val expression = BmoFaceEmotion.fromCode(json.optString("expression"))?.name?.lowercase(Locale.ROOT)
        val graceMs = json.optLong("grace_ms", 0L).coerceIn(0L, 10_000L)
        faceExpiryJob?.cancel()
        faceExpiryJob = null
        if (graceMs <= 0L) {
            clearModelFace()
            return
        }
        faceExpiryJob = scope.launch {
            delay(graceMs)
            if (expression == null || _ui.value.faceExpression == expression) {
                _ui.update { it.copy(faceExpression = null, faceLabel = "") }
            }
        }
    }

    fun activateOnce() {
        if (!_ui.value.connected) {
            fail("Conecte-se ao PC antes de falar.")
            return
        }
        if (capture?.isRunning != true) {
            if (!startListening()) return
        }
        if (_ui.value.bmoState == BmoState.SPEAKING) interrupt()
        clearModelFace()
        sendJson(JSONObject().put("type", "activate"))
        _ui.update {
            it.copy(
                bmoState = BmoState.LISTENING,
                faceState = BmoState.LISTENING,
                statusDetail = "Ativação manual. Pode falar.",
            )
        }
        addLog("INFO", "Ativação manual solicitada (sem palavra de ativação).")
    }

    @Volatile
    private var audioMuted = false

    private fun setAudioMuted(muted: Boolean) {
        audioMuted = muted
        capture?.muted = muted
    }

    fun startMicTest() {
        if (testCapture?.isRunning == true) return
        if (capture?.isRunning == true) {
            _ui.update { it.copy(micTesting = true) }
            addLog("INFO", "Teste de microfone usando a captura já ativa.")
            return
        }
        if (!hasMicrophonePermission()) {
            fail("Permissão de microfone não concedida.")
            return
        }
        val test = AudioCapture(appContext, object : AudioCapture.Listener {
            override fun onLevel(level: Float) {
                _ui.update { it.copy(micLevel = level) }
            }

            override fun onPcm(bytes: ByteArray) {
                // Teste local: não envia áudio a lugar nenhum.
            }

            override fun onError(message: String) {
                fail(message)
                stopMicTest()
            }
        })
        if (!test.start()) return
        testCapture = test
        captureForTest = true
        _ui.update { it.copy(micTesting = true) }
        addLog("INFO", "Teste de microfone iniciado (somente nível local).")
    }

    fun stopMicTest() {
        val test = testCapture
        val wasTesting = _ui.value.micTesting
        testCapture = null
        test?.stop()
        captureForTest = false
        _ui.update { it.copy(micTesting = false, micLevel = 0f) }
        if (wasTesting) {
            val message = if (capture?.isRunning == true) {
                "Teste de microfone encerrado; a captura principal continua."
            } else {
                "Teste de microfone encerrado."
            }
            addLog("INFO", message)
        }
    }

    // ------------------------------------------------------------------
    // Comandos
    // ------------------------------------------------------------------

    fun sendText(text: String) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        if (!_ui.value.connected) {
            fail("Conecte-se ao PC antes de enviar uma mensagem.")
            return
        }
        if (clean.length > 1000) {
            fail("A mensagem é longa demais (máximo de 1000 caracteres).")
            return
        }
        if (_ui.value.bmoState == BmoState.SPEAKING) interrupt()
        scope.launch {
            // Se o GPS ainda não respondeu ou está antigo, espera um pouco para
            // que a pergunta de clima já tenha coordenadas atualizadas.
            val locationAge = System.currentTimeMillis() - lastLocationAt
            if (hasLocationPermission() &&
                (lastLocation == null || locationAge > LOCATION_MAX_AGE_MS)
            ) {
                locationProvider.awaitLocation(2500)?.let { location ->
                    lastLocation = location
                    lastLocationAt = System.currentTimeMillis()
                    _ui.update { it.copy(locationReady = true) }
                }
            }
            sendCurrentLocation()
            val sent = sendJson(JSONObject().put("type", "text").put("text", clean))
            if (sent) {
                currentAssistantId = ""
                clearModelFace()
                _ui.update {
                    it.copy(
                        transcript = clean,
                        assistantText = "",
                        streamingText = false,
                        statusDetail = "Mensagem enviada.",
                    )
                }
                addLog("USUÁRIO", if (clean.length > 120) clean.take(120) + "..." else clean)
            } else {
                fail("Não foi possível enviar a mensagem.")
            }
        }
    }

    fun interrupt() {
        if (_ui.value.connected) sendJson(JSONObject().put("type", "interrupt"))
        stopLocalPlayback()
        clearModelFace()
        _ui.update {
            it.copy(
                bmoState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                faceState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                streamingText = false,
                statusDetail = "Fala interrompida.",
            )
        }
        addLog("INFO", "Fala interrompida pelo usuário.")
    }

    fun resetHistory() {
        if (!_ui.value.connected) {
            fail("Conecte-se ao PC para apagar o histórico.")
            return
        }
        sendJson(JSONObject().put("type", "reset"))
        _ui.update { it.copy(transcript = "", assistantText = "") }
        addLog("INFO", "Pedido para apagar o histórico da conversa.")
    }

    fun testTone() {
        scope.launch {
            addLog("INFO", "Reproduzindo tom de teste no alto-falante.")
            val ok = player.playTestTone(settings.volume)
            addLog(if (ok) "INFO" else "AVISO",
                if (ok) "Tom de teste concluído." else "Falha ao reproduzir o tom de teste.")
        }
    }

    fun discoverServers(callback: (List<ServerDiscovery.FoundServer>) -> Unit) {
        scope.launch {
            addLog("INFO", "Procurando o BMO na rede local (UDP).")
            val found = ServerDiscovery.discover()
            addLog(
                "INFO",
                if (found.isEmpty()) "Nenhum servidor encontrado na rede."
                else "${found.size} servidor(es) encontrado(s)."
            )
            mainHandler.post { callback(found) }
        }
    }

    fun testConnection(target: AppSettings, callback: (Result<ServiceStatus>) -> Unit) {
        scope.launch {
            val result = runCatching {
                val health = http.newCall(
                    Request.Builder().url("${target.httpUrl}/health").build()
                ).execute()
                health.use {
                    if (!it.isSuccessful) throw IllegalStateException("Servidor respondeu HTTP ${it.code}.")
                }
                val infoRequest = Request.Builder()
                    .url("${target.httpUrl}/api/v1/info")
                    .header("Authorization", "Bearer ${target.token}")
                    .build()
                http.newCall(infoRequest).execute().use { response ->
                    if (response.code == 401) {
                        throw IllegalStateException("Token inválido. Copie o token do arquivo backend/data/token.")
                    }
                    if (!response.isSuccessful) {
                        throw IllegalStateException("O servidor respondeu HTTP ${response.code}.")
                    }
                    val body = response.body?.string() ?: throw IllegalStateException("Resposta vazia.")
                    val json = JSONObject(body)
                    val llm = json.optJSONObject("llm")
                    val stt = json.optJSONObject("stt")
                    val tts = json.optJSONObject("tts")
                    ServiceStatus(
                        protocol = json.optString("protocol"),
                        version = json.optString("version"),
                        llmAvailable = llm?.optBoolean("available") == true,
                        sttAvailable = stt?.optBoolean("available") == true,
                        ttsAvailable = tts?.optBoolean("available") == true,
                        llmModel = llm?.optString("model").orEmpty(),
                        wakeMode = json.optJSONObject("wakeword")?.optString("mode").orEmpty(),
                        serverTime = json.optString("server_time"),
                    )
                }
            }.mapCatching { it }
            mainHandler.post { callback(result) }
        }
    }

    private fun refreshServiceStatus() {
        testConnection(settings) { result ->
            result.onSuccess { status ->
                _ui.update { it.copy(serviceStatus = status, ttsAvailable = status.ttsAvailable) }
                addLog(
                    if (status.llmAvailable && status.sttAvailable && status.ttsAvailable) "INFO" else "AVISO",
                    "Serviços do PC — LLM: ${sim(status.llmAvailable)}, " +
                        "STT: ${sim(status.sttAvailable)}, TTS: ${sim(status.ttsAvailable)}."
                )
            }
            result.onFailure { error ->
                addLog("AVISO", "Diagnóstico do servidor: ${error.message}")
            }
        }
    }

    // ------------------------------------------------------------------
    // Pasta autorizada e mídia (HTTP autenticado)
    // ------------------------------------------------------------------

    fun refreshFolderStatus(callback: ((Result<FolderStatus>) -> Unit)? = null) {
        if (!settings.isConfigured) return
        scope.launch {
            val result = runCatching {
                val request = Request.Builder()
                    .url("${settings.httpUrl}/api/v1/folder")
                    .header("Authorization", "Bearer ${settings.token}")
                    .build()
                http.newCall(request).execute().use { response ->
                    val body = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        throw IllegalStateException(httpMessage(response.code, body))
                    }
                    parseFolder(JSONObject(body))
                }
            }
            result.onSuccess { folder ->
                _ui.update { it.copy(folderStatus = folder) }
            }
            mainHandler.post { callback?.invoke(result) }
        }
    }

    /** Abre o seletor nativo de pastas no PC (kdialog/zenity). */
    fun selectFolder(callback: ((Result<FolderStatus>) -> Unit)? = null) {
        if (!_ui.value.connected) {
            fail("Conecte-se ao PC para escolher a pasta de acesso.")
            return
        }
        scope.launch {
            val result = runCatching {
                val request = Request.Builder()
                    .url("${settings.httpUrl}/api/v1/folder/select")
                    .header("Authorization", "Bearer ${settings.token}")
                    .post(ByteArray(0).toRequestBody())
                    .build()
                httpLong.newCall(request).execute().use { response ->
                    val body = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        throw IllegalStateException(httpMessage(response.code, body))
                    }
                    val json = JSONObject(body)
                    if (json.optBoolean("cancelled", false)) {
                        _ui.value.folderStatus ?: parseFolder(json)
                    } else {
                        parseFolder(json)
                    }
                }
            }
            result.onSuccess { folder ->
                _ui.update { it.copy(folderStatus = folder) }
                addLog(
                    "INFO",
                    if (folder.authorized) "Pasta autorizada: ${folder.path}" else "Nenhuma pasta autorizada.",
                )
            }
            result.onFailure { error ->
                addLog("ERRO", "Seletor de pastas: ${error.message}")
            }
            mainHandler.post { callback?.invoke(result) }
        }
    }

    fun revokeFolder(callback: ((Result<FolderStatus>) -> Unit)? = null) {
        if (!_ui.value.connected) {
            fail("Conecte-se ao PC para revogar o acesso à pasta.")
            return
        }
        scope.launch {
            val result = runCatching {
                val request = Request.Builder()
                    .url("${settings.httpUrl}/api/v1/folder/revoke")
                    .header("Authorization", "Bearer ${settings.token}")
                    .post(ByteArray(0).toRequestBody())
                    .build()
                http.newCall(request).execute().use { response ->
                    val body = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        throw IllegalStateException(httpMessage(response.code, body))
                    }
                    parseFolder(JSONObject(body))
                }
            }
            result.onSuccess { folder ->
                _ui.update { it.copy(folderStatus = folder) }
                addLog("INFO", "Acesso à pasta revogado.")
            }
            result.onFailure { error ->
                addLog("ERRO", "Não foi possível revogar a pasta: ${error.message}")
            }
            mainHandler.post { callback?.invoke(result) }
        }
    }

    fun refreshMedia(callback: ((Result<MusicInfo>) -> Unit)? = null) {
        if (!settings.isConfigured) return
        scope.launch {
            val result = fetchMedia()
            applyMedia(result)
            mainHandler.post { callback?.invoke(result) }
        }
    }

    private fun fetchMedia(): Result<MusicInfo> = runCatching {
        // /api/music/state traz o Mopidy; /api/v1/media cobre o player MPRIS
        // (navegador/VLC/BitChord). Consulta os dois: antes, um Mopidy parado
        // escondia a música que estava tocando em outro aplicativo.
        val primary = runCatching { requestMusicInfo("/api/music/state") }
        val fallback = runCatching { requestMusicInfo("/api/v1/media") }
        val candidates = listOfNotNull(primary.getOrNull(), fallback.getOrNull())
        candidates.firstOrNull { it.isPlaying }
            ?: primary.getOrNull()
            ?: fallback.getOrNull()
            ?: throw (primary.exceptionOrNull()
                ?: fallback.exceptionOrNull()
                ?: IllegalStateException("Nenhum player de música respondeu."))
    }

    private fun requestMusicInfo(path: String): MusicInfo {
        val request = Request.Builder()
            .url("${settings.httpUrl}$path")
            .header("Authorization", "Bearer ${settings.token}")
            .build()
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException(httpMessage(response.code, body))
            }
            return parseMusic(JSONObject(body))
        }
    }

    // ------------------------------------------------------------------
    // Controles de música (HTTP autenticado)
    // ------------------------------------------------------------------

    private fun musicRequest(path: String, payload: JSONObject? = null): JSONObject {
        val builder = Request.Builder()
            .url("${settings.httpUrl}$path")
            .header("Authorization", "Bearer ${settings.token}")
        val request = if (payload == null) {
            builder.get().build()
        } else {
            builder.post(payload.toString().toRequestBody(jsonMediaType)).build()
        }
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException(httpMessage(response.code, body))
            }
            return JSONObject(body)
        }
    }

    private fun musicCommand(
        path: String,
        payload: JSONObject? = null,
        callback: ((Result<MusicInfo>) -> Unit)? = null,
    ) {
        if (!settings.isConfigured) {
            callback?.invoke(Result.failure(IllegalStateException("Configure o servidor do PC.")))
            return
        }
        scope.launch {
            val result = runCatching {
                val json = musicRequest(path, payload)
                val info = parseMusic(json)
                _ui.update { it.copy(music = mergeMusic(it.music, info)) }
                info
            }
            result.onFailure { error -> addLog("ERRO", "Música: ${error.message}") }
            mainHandler.post { callback?.invoke(result) }
        }
    }

    fun musicPlay(trackId: String, callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand("/api/music/play", JSONObject().put("track_id", trackId), callback)
    }

    fun musicPause(callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand("/api/music/pause", JSONObject(), callback)
    }

    fun musicResume(callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand("/api/music/resume", JSONObject(), callback)
    }

    fun musicStop(callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand("/api/music/stop", JSONObject(), callback)
    }

    fun musicNext(callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand("/api/music/next", JSONObject(), callback)
    }

    fun musicPrevious(callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand("/api/music/previous", JSONObject(), callback)
    }

    fun musicSetVolume(percent: Int, callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand(
            "/api/music/volume",
            JSONObject().put("volume", percent.coerceIn(0, 100)),
            callback,
        )
    }

    fun musicTogglePlayback(callback: ((Result<MusicInfo>) -> Unit)? = null) {
        val music = _ui.value.music
        when {
            music?.isPlaying == true -> musicPause(callback)
            music?.isPaused == true -> musicResume(callback)
            else -> callback?.invoke(
                Result.failure(IllegalStateException("Nada está tocando. Pesquise uma música."))
            )
        }
    }

    fun searchMusic(query: String, callback: (Result<List<MusicSearchResult>>) -> Unit) {
        val clean = query.trim()
        if (clean.isBlank()) {
            callback(Result.failure(IllegalArgumentException("Digite o nome da música.")))
            return
        }
        if (!settings.isConfigured) {
            callback(Result.failure(IllegalStateException("Configure o servidor do PC.")))
            return
        }
        scope.launch {
            val result = runCatching {
                val encoded = java.net.URLEncoder.encode(clean, "UTF-8")
                val json = musicRequest("/api/music/search?q=$encoded&filter=songs&limit=12")
                val array = json.optJSONArray("results") ?: org.json.JSONArray()
                buildList {
                    for (index in 0 until array.length()) {
                        val item = array.optJSONObject(index) ?: continue
                        add(
                            MusicSearchResult(
                                id = item.optString("id"),
                                type = item.optString("type"),
                                title = item.optString("title"),
                                artist = item.optString("artist"),
                                album = item.optString("album"),
                                durationMs = optLongOrNull(item, "duration_ms"),
                                thumbnail = item.optString("thumbnail"),
                            )
                        )
                    }
                }
            }
            result.onFailure { error -> addLog("ERRO", "Busca musical: ${error.message}") }
            mainHandler.post { callback(result) }
        }
    }

    fun fetchMusicQueue(callback: (Result<List<MusicQueueItem>>) -> Unit) {
        if (!settings.isConfigured) {
            callback(Result.failure(IllegalStateException("Configure o servidor do PC.")))
            return
        }
        scope.launch {
            val result = runCatching {
                val json = musicRequest("/api/music/queue")
                val array = json.optJSONArray("queue") ?: org.json.JSONArray()
                buildList {
                    for (index in 0 until array.length()) {
                        val item = array.optJSONObject(index) ?: continue
                        add(
                            MusicQueueItem(
                                index = item.optInt("index", index),
                                trackId = item.optString("track_id"),
                                title = item.optString("title"),
                                artist = item.optString("artist"),
                                durationMs = optLongOrNull(item, "duration_ms"),
                            )
                        )
                    }
                }
            }
            mainHandler.post { callback(result) }
        }
    }

    fun musicQueueAdd(trackId: String, callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand("/api/music/queue/add", JSONObject().put("track_id", trackId), callback)
    }

    fun musicQueueRemove(index: Int, callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand("/api/music/queue/remove", JSONObject().put("index", index), callback)
    }

    fun musicQueueClear(callback: ((Result<MusicInfo>) -> Unit)? = null) {
        musicCommand("/api/music/queue/clear", JSONObject(), callback)
    }

    private fun optLongOrNull(json: JSONObject, key: String): Long? =
        if (json.has(key) && !json.isNull(key)) json.optLong(key) else null

    private fun applyMedia(result: Result<MusicInfo>) {
        result.onSuccess { music ->
            val before = _ui.value.music
            _ui.update { state ->
                val merged = mergeMusic(state.music, music)
                if (merged == state.music) state else state.copy(music = merged)
            }
            if (before?.isPlaying != true && music.isPlaying) {
                addLog(
                    "INFO",
                    "Música tocando: ${listOf(music.title, music.artist).filter { it.isNotBlank() }.joinToString(" — ").ifBlank { music.player }}",
                )
            } else if (before?.isPlaying == true && !music.isPlaying) {
                addLog("INFO", "Música pausada ou parada.")
                // O sono conta a partir do fim da música, não do último evento
                // de conversa (que pode ter sido há muitos minutos).
                _ui.update { it.copy(lastActivityAtMs = SystemClock.elapsedRealtime()) }
            }
        }
    }

    /** Mantém título/artista/estado atualizados mesmo sem o usuário pedir. */
    private fun startMediaPolling() {
        mediaPollJob?.cancel()
        mediaPollJob = scope.launch {
            while (true) {
                delay(4_000)
                applyMedia(fetchMedia())
            }
        }
    }

    private fun parseFolder(json: JSONObject): FolderStatus = FolderStatus(
        path = json.optString("path"),
        os = json.optString("os"),
        selectedAt = json.optString("selected_at"),
        authorized = json.optBoolean("authorized", false),
        picker = json.optString("picker"),
        displayAvailable = json.optBoolean("display_available", false),
    )

    private fun parseMusic(json: JSONObject): MusicInfo = MusicInfo(
        player = json.optString("player"),
        isBitchord = json.optBoolean("is_bitchord", false),
        status = json.optString("status"),
        title = json.optString("title"),
        artist = json.optString("artist"),
        album = json.optString("album"),
        lengthS = if (json.has("length_s") && !json.isNull("length_s")) {
            json.optDouble("length_s")
        } else {
            null
        },
        volume = if (json.has("volume") && !json.isNull("volume")) {
            json.optDouble("volume").toFloat()
        } else {
            null
        },
        volumePercent = if (json.has("volume_percent") && !json.isNull("volume_percent")) {
            json.optInt("volume_percent")
        } else {
            null
        },
        positionMs = json.optLong("position_ms", 0L).coerceAtLeast(0L),
        durationMs = optLongOrNull(json, "duration_ms"),
        queueLength = if (json.has("queue_length") && !json.isNull("queue_length")) {
            json.optInt("queue_length")
        } else {
            null
        },
        verified = json.optBoolean("verified", false),
        artUrl = json.optString("art_url"),
    )

    /** Eventos de controle de mídia podem vir sem metadados; preserva o que já existe. */
    private fun mergeMusic(current: MusicInfo?, incoming: MusicInfo): MusicInfo {
        if (current == null || incoming.title.isNotBlank()) return incoming
        // Estado parado é autoritativo: limpa a faixa antiga em vez de manter
        // metadados obsoletos depois de stop/queue clear.
        if (incoming.status.equals("stopped", ignoreCase = true)) return incoming
        return incoming.copy(
            title = current.title,
            artist = current.artist,
            album = current.album,
            lengthS = incoming.lengthS ?: current.lengthS,
            volume = incoming.volume ?: current.volume,
            volumePercent = incoming.volumePercent ?: current.volumePercent,
            durationMs = incoming.durationMs ?: current.durationMs,
            queueLength = incoming.queueLength ?: current.queueLength,
            verified = incoming.verified,
            artUrl = incoming.artUrl.ifBlank { current.artUrl },
        )
    }

    private fun httpMessage(code: Int, body: String): String {
        val detail = runCatching { JSONObject(body).optString("error") }.getOrNull()
        return if (detail.isNullOrBlank()) "O PC respondeu HTTP $code." else detail
    }

    // ------------------------------------------------------------------
    // Eventos do servidor
    // ------------------------------------------------------------------

    private fun handleServerText(text: String) {
        val json = try {
            JSONObject(text)
        } catch (exc: Exception) {
            addLog("ERRO", "O servidor enviou um JSON inválido.")
            return
        }
        val seq = json.optLong("seq", -1)
        if (seq > 0) {
            if (seq <= lastSeq) return
            lastSeq = seq
        }
        val type = json.optString("type")
        // Só eventos de conversa, operação ou música contam como atividade.
        // Ruído do microfone (vad, transcrição vazia, wakeword.not_detected)
        // não pode reiniciar o relógio do sono, senão o BMO nunca dorme com o
        // microfone ativo esperando a wake word.
        if (isActivityEvent(type, json)) {
            _ui.update { it.copy(lastActivityAtMs = SystemClock.elapsedRealtime()) }
        }
        when (type) {
            "hello" -> handleHello(json)
            "state" -> handleState(json)
            "transcript" -> {
                val value = json.optString("text")
                clearModelFace()
                _ui.update {
                    it.copy(
                        transcript = value,
                        assistantText = "",
                        streamingText = false,
                        statusDetail = if (value.isBlank()) "Não entendi." else "Fala reconhecida.",
                    )
                }
                addLog("STT", if (value.isBlank()) "(vazio)" else value)
            }
            "assistant.text.delta" -> {
                val id = json.optString("id", "")
                val piece = json.optString("text", "")
                if (id.isNotEmpty() && id != currentAssistantId) {
                    currentAssistantId = id
                    _ui.update { it.copy(assistantText = "") }
                }
                _ui.update {
                    it.copy(
                        assistantText = it.assistantText + piece,
                        streamingText = true,
                        statusDetail = "Respondendo...",
                    )
                }
            }
            "assistant.text.done" -> {
                val answer = json.optString("text", "")
                currentAssistantId = json.optString("id", currentAssistantId)
                _ui.update {
                    it.copy(
                        assistantText = answer,
                        streamingText = false,
                        ttsAvailable = json.optBoolean("audio_available", it.ttsAvailable),
                        statusDetail = "Resposta recebida.",
                    )
                }
                addLog("BMO", if (answer.length > 200) answer.take(200) + "..." else answer)
            }
            "audio.start" -> {
                val rate = json.optInt("sample_rate", 22050)
                val channels = json.optInt("channels", 1)
                currentSampleRate = rate
                currentChannels = channels
                currentDurationMs = json.optLong("duration_ms", 0L)
                // Novo stream invalida qualquer job anterior antes de tocar o novo.
                audioStreamId += 1
                val streamId = audioStreamId
                playbackJob?.cancel()
                playbackJob = null
                player.stop()
                resetStreamState()
                audioStarted = player.start(rate, channels, settings.volume)
                setAudioMuted(true)
                _ui.update {
                    it.copy(
                        bmoState = BmoState.SPEAKING,
                        faceState = BmoState.SPEAKING,
                        audioPlaying = audioStarted,
                        statusDetail = "Falando...",
                    )
                }
                if (audioStarted) {
                    startPlaybackJob(streamId)
                } else {
                    audioStarted = false
                    addLog("ERRO", "O aparelho não conseguiu abrir a saída de áudio.")
                }
                addLog("INFO", "Áudio do BMO recebido (${json.optInt("duration_ms", 0)} ms, $rate Hz).")
            }
            "audio.end" -> {
                // O servidor terminou de enviar; a reprodução só acaba depois que
                // o AudioTrack consumir a fila (ver startPlaybackJob).
                audioStreamEnded = true
                if (!audioStarted && !playbackDoneSent) {
                    playbackDoneSent = true
                    sendJson(JSONObject().put("type", "playback.done"))
                    setAudioMuted(false)
                }
                _ui.update {
                    if (it.bmoState == BmoState.SPEAKING) {
                        it.copy(statusDetail = "Finalizando áudio...")
                    } else {
                        it
                    }
                }
            }
            "audio.stop" -> {
                stopLocalPlayback()
                _ui.update {
                    it.copy(
                        bmoState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                        faceState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                        audioPlaying = false,
                        statusDetail = "Áudio interrompido.",
                    )
                }
                addLog("INFO", "Reprodução interrompida pelo servidor.")
            }
            "audio.unavailable" -> {
                // Sem TTS não há playback.done: libera o microfone imediatamente.
                stopLocalPlayback()
                _ui.update {
                    it.copy(
                        ttsAvailable = false,
                        bmoState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                        faceState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                        audioPlaying = false,
                    )
                }
                addLog("AVISO", json.optString("message", "Resposta sem áudio."))
            }
            "face" -> handleModelFace(json)
            "face.restore" -> handleFaceRestore(json)
            "vad" -> {
                val speaking = json.optBoolean("speaking")
                _ui.update {
                    it.copy(
                        vadSpeaking = speaking,
                        statusDetail = when {
                            speaking -> "Ouvindo sua fala..."
                            it.faceState == BmoState.THINKING -> "Processando..."
                            it.listening -> "Aguardando \"Ei, BMO\"."
                            else -> it.statusDetail
                        },
                    )
                }
            }
            "wakeword.detected" -> {
                clearModelFace()
                _ui.update { it.copy(statusDetail = "Palavra de ativação reconhecida.") }
                addLog("INFO", "Palavra de ativação detectada.")
            }
            "wakeword.activated" -> {
                addLog("INFO", "Ativação manual aceita pelo servidor.")
            }
            "wakeword.not_detected" -> {
                val message = json.optString("message", "Palavra de ativação não detectada.")
                _ui.update { it.copy(statusDetail = message) }
                addLog("AVISO", message)
            }
            "activity" -> handleActivity(json)
            "music" -> {
                val incoming = parseMusic(json)
                _ui.update { state ->
                    state.copy(music = mergeMusic(state.music, incoming))
                }
                val title = incoming.title.ifBlank { _ui.value.music?.title.orEmpty() }
                val artist = incoming.artist.ifBlank { _ui.value.music?.artist.orEmpty() }
                if (title.isNotBlank() || artist.isNotBlank()) {
                    addLog("INFO", "Música: ${listOf(title, artist).filter { it.isNotBlank() }.joinToString(" — ")}")
                }
            }
            "confirmation.request" -> {
                val info = ConfirmationInfo(
                    id = json.optString("id"),
                    tool = json.optString("tool"),
                    prompt = json.optString("prompt", "Confirme a ação no PC."),
                )
                _ui.update {
                    it.copy(
                        pendingConfirmation = info,
                        statusDetail = info.prompt,
                    )
                }
                addLog("AVISO", info.prompt)
            }
            "confirmation.result" -> {
                val approved = json.optBoolean("approved", false)
                val ok = json.optBoolean("ok", false)
                val message = json.optString("message", "")
                _ui.update { it.copy(pendingConfirmation = null) }
                addLog(
                    if (ok) "INFO" else "AVISO",
                    message.ifBlank {
                        if (approved) "Ação confirmada." else "Ação cancelada."
                    },
                )
            }
            "request.accepted" -> {
                _ui.update { it.copy(statusDetail = "Pedido recebido.") }
            }
            "error" -> handleError(json)
            "pong" -> Unit
            "history.reset" -> {
                _ui.update { it.copy(transcript = "", assistantText = "") }
                addLog("INFO", "Histórico da conversa apagado no PC.")
            }
            "audio.ready" -> addLog("INFO", "Servidor pronto para receber áudio.")
            "hello.ok" -> Unit
            else -> Log.d(TAG, "Evento não tratado: $type")
        }
    }

    /**
     * Eventos que representam interação real. `vad`, `pong`, transcrição
     * vazia e `wakeword.not_detected` ficam de fora de propósito: são ruído
     * de fundo e impediriam o sono com o microfone ativo.
     */
    private fun isActivityEvent(type: String, json: JSONObject): Boolean = when (type) {
        "hello", "assistant.text.delta", "assistant.text.done",
        "audio.start", "audio.end", "audio.stop", "audio.unavailable",
        "face", "face.restore", "activity", "confirmation.request",
        "confirmation.result", "request.accepted", "error", "history.reset",
        "wakeword.detected", "wakeword.activated" -> true
        "transcript" -> json.optString("text").isNotBlank()
        "music" -> {
            val status = json.optString("status")
            status.equals("playing", ignoreCase = true) ||
                status.equals("paused", ignoreCase = true) ||
                json.optString("title").isNotBlank()
        }
        else -> false
    }

    private fun handleHello(json: JSONObject) {
        val protocol = json.optString("protocol")
        if (protocol.isNotEmpty() && protocol != "bmo/1") {
            fail("Protocolo $protocol não suportado. Atualize o app ou o backend.")
            client?.close()
            return
        }
        connectTimeoutJob?.cancel()
        val session = json.optString("session_id")
        _ui.update {
            it.copy(
                connection = ConnectionState.CONNECTED,
                bmoState = BmoState.IDLE,
                faceState = BmoState.IDLE,
                vadSpeaking = false,
                audioPlaying = false,
                statusDetail = "Conectado ao PC.",
                reconnectAttempt = 0,
                lastError = null,
                serverSessionId = session,
            )
        }
        addLog("INFO", "Conectado ao backend (protocolo $protocol, sessão $session).")
        resetStreamState()
        refreshServiceStatus()
        refreshFolderStatus()
        refreshMedia()
        refreshLocation()
        startMediaPolling()
        if (wantListening) {
            if (capture?.isRunning == true) {
                // Reconexão: o AudioRecord continuou vivo, mas a nova sessão do
                // backend ainda não sabe disso. Reanuncia o áudio sem recriar nada.
                if (sendAudioStart()) {
                    sendCurrentLocation()
                    _ui.update {
                        it.copy(
                            listening = true,
                            listeningRequested = true,
                            bmoState = BmoState.LISTENING,
                            faceState = BmoState.LISTENING,
                            statusDetail = "Microfone retomado após reconexão.",
                        )
                    }
                    addLog("INFO", "Microfone preservado e reanunciado ao servidor.")
                }
            } else {
                startListening()
            }
        }
    }

    private fun handleState(json: JSONObject) {
        val state = json.optString("state", "idle")
        val detail = json.optString("detail")
        val mapped = when (state) {
            "listening" -> BmoState.LISTENING
            "thinking" -> BmoState.THINKING
            "speaking" -> BmoState.SPEAKING
            "error" -> BmoState.ERROR
            "idle" -> BmoState.IDLE
            else -> BmoState.IDLE
        }
        if (mapped == BmoState.THINKING || mapped == BmoState.SPEAKING) setAudioMuted(true)
        if (mapped == BmoState.LISTENING || mapped == BmoState.IDLE) {
            if (!player.isActive) setAudioMuted(false)
        }
        if (mapped == BmoState.LISTENING && capture?.isRunning != true && wantListening) {
            // O servidor voltou a ouvir, mas a captura local não está ativa.
            startListening()
        }
        _ui.update {
            it.copy(
                bmoState = mapped,
                faceState = mapped,
                statusDetail = detail.ifBlank { mapped.label },
                lastError = if (mapped == BmoState.ERROR) detail else it.lastError,
            )
        }
        addLog(
            if (mapped == BmoState.ERROR) "ERRO" else "INFO",
            "Estado: ${mapped.label}${if (detail.isNotBlank()) " — $detail" else ""}"
        )
    }

    private fun handleActivity(json: JSONObject) {
        val info = ActivityInfo(
            activity = BmoActivity.fromCode(json.optString("activity")),
            status = json.optString("status"),
            label = json.optString("label"),
            tool = json.optString("tool"),
        )
        if (info.activity == BmoActivity.NONE) return
        _ui.update {
            it.copy(
                activity = info,
                statusDetail = info.label.ifBlank { info.activity.label },
            )
        }
        if (info.status == "start") {
            addLog("INFO", info.label.ifBlank { info.activity.label })
        }
        // Sucesso/erro ficam visíveis por alguns segundos e depois somem.
        if (info.status == "done" || info.status == "error") {
            scope.launch {
                delay(ACTIVITY_LINGER_MS)
                _ui.update { state ->
                    if (state.activity == info) state.copy(activity = null) else state
                }
            }
        }
        if (info.activity == BmoActivity.PLAYING_MUSIC) {
            refreshMedia()
        }
    }

    /** Resposta explícita a uma exclusão/ação destrutiva pendente. */
    fun respondConfirmation(approved: Boolean) {
        val pending = _ui.value.pendingConfirmation ?: return
        if (!_ui.value.connected) {
            fail("Conecte-se ao PC para confirmar a ação.")
            return
        }
        val sent = sendJson(
            JSONObject()
                .put("type", "confirmation")
                .put("id", pending.id)
                .put("approved", approved)
        )
        if (sent) {
            _ui.update {
                it.copy(
                    pendingConfirmation = null,
                    statusDetail = if (approved) "Confirmando..." else "Cancelando...",
                )
            }
            addLog("INFO", if (approved) "Ação confirmada." else "Ação cancelada.")
        } else {
            fail("Não foi possível enviar a confirmação.")
        }
    }

    private fun handleServerAudio(bytes: ByteArray) {
        if (!audioStarted || audioStreamEnded) return
        player.write(bytes)
        _ui.update {
            if (it.bmoState != BmoState.SPEAKING || !it.audioPlaying) {
                it.copy(
                    bmoState = BmoState.SPEAKING,
                    faceState = BmoState.SPEAKING,
                    audioPlaying = true,
                )
            } else {
                it
            }
        }
    }

    /**
     * Um único job por stream: só considera concluído depois de `audio.end` e
     * de o AudioTrack esvaziar a fila. O `finally` sempre libera o microfone e
     * encerra o AudioTrack, evitando o estado "falando" preso.
     */
    private fun startPlaybackJob(streamId: Int) {
        sendJson(JSONObject().put("type", "playback.started"))
        playbackJob = scope.launch {
            try {
                val finished = player.waitForPlayback(
                    timeoutMs = (currentDurationMs + 15_000L).coerceAtLeast(15_000L),
                ) {
                    streamId == audioStreamId && audioStreamEnded
                }
                if (!finished) {
                    addLog("AVISO", "A reprodução excedeu o tempo limite.")
                }
                if (streamId != audioStreamId) return@launch
                if (!playbackDoneSent) {
                    playbackDoneSent = true
                    sendJson(JSONObject().put("type", "playback.done"))
                }
                delay(120)
                setAudioMuted(false)
                _ui.update {
                    it.copy(
                        bmoState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                        faceState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                        audioPlaying = false,
                        statusDetail = "Pronto para ouvir.",
                        // O sono conta a partir do fim real do áudio, não do
                        // momento em que o servidor terminou de enviá-lo.
                        lastActivityAtMs = SystemClock.elapsedRealtime(),
                    )
                }
                addLog("INFO", "Reprodução concluída; microfone liberado.")
            } finally {
                if (streamId == audioStreamId) {
                    player.stop()
                    resetStreamState()
                    setAudioMuted(false)
                }
            }
        }
    }

    private fun handleError(json: JSONObject) {
        val code = json.optString("code")
        val message = json.optString("message", "Erro no servidor.")
        val fatal = json.optBoolean("fatal", false)
        _ui.update {
            it.copy(
                lastError = message,
                bmoState = BmoState.ERROR,
                faceState = BmoState.ERROR,
                statusDetail = message,
                streamingText = false,
            )
        }
        addLog("ERRO", "$message${if (code.isNotBlank()) " (código: $code)" else ""}")
        if (fatal) {
            client?.close()
            connectionLost(message)
        }
    }

    // ------------------------------------------------------------------
    // Utilidades
    // ------------------------------------------------------------------

    private fun sendJson(payload: JSONObject): Boolean {
        val sent = client?.sendJson(payload) ?: false
        if (!sent) Log.w(TAG, "Tentativa de envio sem WebSocket ativo: ${payload.optString("type")}")
        return sent
    }

    private fun fail(message: String) {
        _ui.update {
            it.copy(
                lastError = message,
                statusDetail = message,
                bmoState = BmoState.ERROR,
                faceState = BmoState.ERROR,
            )
        }
        addLog("ERRO", message)
    }

    fun clearLogs() {
        _logs.value = emptyList()
    }

    private fun addLog(level: String, message: String) {
        val entry = LogEntry(
            time = SimpleDateFormat("HH:mm:ss", Locale.forLanguageTag("pt-BR")).format(Date()),
            level = level,
            message = message,
        )
        _logs.update { (it + entry).takeLast(300) }
        Log.i(TAG, "[$level] $message")
    }

    private fun sim(value: Boolean) = if (value) "ok" else "indisponível"

    companion object {
        private const val TAG = "BmoEngine"
        private const val LOCATION_MAX_AGE_MS = 120_000L
        private const val ACTIVITY_LINGER_MS = 3_500L

        @Volatile
        private var instance: BmoEngine? = null

        fun get(context: Context): BmoEngine {
            return instance ?: synchronized(this) {
                instance ?: BmoEngine(context).also { instance = it }
            }
        }
    }
}
