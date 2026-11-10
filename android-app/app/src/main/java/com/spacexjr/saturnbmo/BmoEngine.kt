package com.spacexjr.saturnbmo

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.content.ContextCompat
import com.spacexjr.saturnbmo.audio.AudioCapture
import com.spacexjr.saturnbmo.audio.AudioPlayer
import com.spacexjr.saturnbmo.location.BmoLocation
import com.spacexjr.saturnbmo.net.BmoClient
import com.spacexjr.saturnbmo.net.ServerDiscovery
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
    private var wantListening = false
    private var manualDisconnect = false
    private var captureForTest = false
    private var lastSeq = -1L
    private var currentAssistantId = ""
    private var audioStarted = false
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
        stopCaptureInternal(sendEnd = false)
        player.stop()
        if (!settings.isConfigured) {
            _ui.update {
                it.copy(
                    connection = ConnectionState.DISCONNECTED,
                    bmoState = BmoState.DISCONNECTED,
                    faceState = BmoState.DISCONNECTED,
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
        playbackJob?.cancel()
        stopCaptureInternal(sendEnd = false)
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
                listening = false,
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
        if (_ui.value.connected) return startListening()
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
        stopCaptureInternal(sendEnd = false)
        player.stop()
        playbackJob?.cancel()
        mediaPollJob?.cancel()
        mediaPollJob = null
        _ui.update {
            it.copy(
                connection = if (allowReconnect && settings.autoConnect && settings.isConfigured)
                    ConnectionState.RECONNECTING else ConnectionState.DISCONNECTED,
                bmoState = BmoState.DISCONNECTED,
                faceState = BmoState.DISCONNECTED,
                listening = false,
                micLevel = 0f,
                statusDetail = message,
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
            fail("Permissão de microfone não concedida. Autorize em Configurações do Android.")
            return false
        }
        if (capture?.isRunning == true) return true
        stopMicTest()
        val newCapture = AudioCapture(appContext, object : AudioCapture.Listener {
            override fun onLevel(level: Float) {
                _ui.update { it.copy(micLevel = level) }
            }

            override fun onPcm(bytes: ByteArray) {
                if (!captureForTest && _ui.value.listening && !audioMuted) {
                    client?.sendBytes(bytes)
                }
            }

            override fun onError(message: String) {
                fail(message)
                stopCaptureInternal(sendEnd = false)
            }
        })
        if (!newCapture.start()) {
            _ui.update { it.copy(micLevel = 0f) }
            return false
        }
        capture = newCapture
        captureForTest = false
        wantListening = true
        val sent = sendJson(
            JSONObject()
                .put("type", "audio.start")
                .put("format", "pcm_s16le")
                .put("sample_rate", AudioCapture.SAMPLE_RATE)
                .put("channels", AudioCapture.CHANNELS)
        )
        if (!sent) {
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
                bmoState = BmoState.LISTENING,
                faceState = BmoState.LISTENING,
                statusDetail = "Microfone ativo. Diga \"Ei, BMO\".",
                lastError = null,
            )
        }
        addLog("INFO", "Microfone ativo (16 kHz, mono, PCM 16 bits).")
        return true
    }

    fun stopListening() {
        wantListening = false
        if (capture?.isRunning != true && !_ui.value.listening) return
        stopCaptureInternal(sendEnd = true)
        stopMicTest()
        _ui.update {
            it.copy(
                listening = false,
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

    fun activateOnce() {
        if (!_ui.value.connected) {
            fail("Conecte-se ao PC antes de falar.")
            return
        }
        if (capture?.isRunning != true) {
            if (!startListening()) return
        }
        if (_ui.value.bmoState == BmoState.SPEAKING) interrupt()
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
        playbackJob?.cancel()
        player.stop()
        setAudioMuted(false)
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
        // /api/music/state traz posição, duração e fila reais do Mopidy.
        // /api/v1/media continua como fallback para o player MPRIS antigo.
        val primary = Request.Builder()
            .url("${settings.httpUrl}/api/music/state")
            .header("Authorization", "Bearer ${settings.token}")
            .build()
        http.newCall(primary).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (response.isSuccessful) return@use parseMusic(JSONObject(body))
            if (response.code != 404 && response.code != 503) {
                throw IllegalStateException(httpMessage(response.code, body))
            }
        }
        val fallback = Request.Builder()
            .url("${settings.httpUrl}/api/v1/media")
            .header("Authorization", "Bearer ${settings.token}")
            .build()
        http.newCall(fallback).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException(httpMessage(response.code, body))
            }
            parseMusic(JSONObject(body))
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
            _ui.update { state ->
                val merged = mergeMusic(state.music, music)
                if (merged == state.music) state else state.copy(music = merged)
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
        when (val type = json.optString("type")) {
            "hello" -> handleHello(json)
            "state" -> handleState(json)
            "transcript" -> {
                val value = json.optString("text")
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
                audioStarted = player.start(rate, channels, settings.volume)
                setAudioMuted(true)
                _ui.update {
                    it.copy(
                        bmoState = BmoState.SPEAKING,
                        faceState = BmoState.SPEAKING,
                        statusDetail = "Falando...",
                    )
                }
                if (!audioStarted) addLog("ERRO", "O aparelho não conseguiu abrir a saída de áudio.")
                addLog("INFO", "Áudio do BMO recebido (${json.optInt("duration_ms", 0)} ms, $rate Hz).")
            }
            "audio.stop" -> {
                playbackJob?.cancel()
                player.stop()
                setAudioMuted(false)
                _ui.update {
                    it.copy(
                        bmoState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                        faceState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                        statusDetail = "Áudio interrompido.",
                    )
                }
                addLog("INFO", "Reprodução interrompida pelo servidor.")
            }
            "audio.unavailable" -> {
                _ui.update { it.copy(ttsAvailable = false) }
                addLog("AVISO", json.optString("message", "Resposta sem áudio."))
            }
            "vad" -> {
                val speaking = json.optBoolean("speaking")
                _ui.update {
                    it.copy(statusDetail = if (speaking) "Ouvindo sua fala..." else "Processando...")
                }
            }
            "wakeword.detected" -> {
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
                statusDetail = "Conectado ao PC. Toque em Ouvir para começar.",
                reconnectAttempt = 0,
                lastError = null,
                serverSessionId = session,
            )
        }
        addLog("INFO", "Conectado ao backend (protocolo $protocol, sessão $session).")
        refreshServiceStatus()
        refreshFolderStatus()
        refreshMedia()
        refreshLocation()
        startMediaPolling()
        if (wantListening && capture?.isRunning != true) {
            startListening()
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
        if (!audioStarted) return
        player.write(bytes)
        if (!_ui.value.streamingText && currentAssistantId.isNotEmpty()) {
            // mantém o texto final; nada a fazer
        }
        _ui.update {
            if (it.bmoState != BmoState.SPEAKING) {
                it.copy(bmoState = BmoState.SPEAKING, faceState = BmoState.SPEAKING)
            } else {
                it
            }
        }
        if (playbackJob?.isActive != true) {
            sendJson(JSONObject().put("type", "playback.started"))
            playbackJob = scope.launch {
                val finished = player.waitForPlayback()
                if (finished) {
                    sendJson(JSONObject().put("type", "playback.done"))
                    delay(250)
                    audioStarted = false
                    setAudioMuted(false)
                    _ui.update {
                        it.copy(
                            bmoState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                            faceState = if (it.listening) BmoState.LISTENING else BmoState.IDLE,
                            statusDetail = "Pronto para ouvir.",
                        )
                    }
                    addLog("INFO", "Reprodução concluída.")
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
