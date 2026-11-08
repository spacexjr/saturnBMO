package com.spacexjr.saturnbmo

/** Configuração persistida no aparelho. O token é guardado cifrado. */
data class AppSettings(
    val host: String = "",
    val port: Int = 8765,
    val token: String = "",
    val volume: Float = 0.9f,
    val keepScreenOn: Boolean = false,
    val backgroundListening: Boolean = false,
    val autoConnect: Boolean = true,
) {
    val isConfigured: Boolean get() = host.isNotBlank() && port in 1..65535
    val wsUrl: String
        get() {
            val cleanHost = host.trim().removePrefix("ws://").removePrefix("http://").trimEnd('/')
            return "ws://$cleanHost:$port/ws"
        }
    val httpUrl: String
        get() {
            val cleanHost = host.trim().removePrefix("ws://").removePrefix("http://").trimEnd('/')
            return "http://$cleanHost:$port"
        }
}

enum class ConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
    RECONNECTING,
}

enum class BmoState(val label: String) {
    DISCONNECTED("Desconectado"),
    CONNECTING("Conectando"),
    IDLE("Aguardando"),
    LISTENING("Ouvindo"),
    THINKING("Pensando"),
    SPEAKING("Falando"),
    ERROR("Erro"),
}

data class ServiceStatus(
    val protocol: String = "",
    val version: String = "",
    val llmAvailable: Boolean = false,
    val sttAvailable: Boolean = false,
    val ttsAvailable: Boolean = false,
    val llmModel: String = "",
    val wakeMode: String = "",
    val serverTime: String = "",
)

data class LogEntry(
    val time: String,
    val level: String,
    val message: String,
)

/** Operação real em andamento no PC, informada pelo backend. */
enum class BmoActivity(val label: String, val shortLabel: String) {
    NONE("", ""),
    PROCESSING("Processando", "PENSANDO"),
    SEARCHING_WEB("Pesquisando na web", "BUSCANDO"),
    READING_WEB("Lendo página", "LENDO"),
    SUMMARIZING_WEB("Resumindo conteúdo", "RESUMINDO"),
    OPENING_APP("Abrindo aplicativo", "ABRINDO"),
    CLOSING_APP("Fechando aplicativo", "FECHANDO"),
    SEARCHING_APPS("Procurando aplicativo", "BUSCANDO"),
    PLAYING_MUSIC("Música", "MÚSICA"),
    READING_FILE("Lendo arquivo", "LENDO"),
    CREATING_FILE("Criando arquivo", "CRIANDO"),
    EDITING_FILE("Editando arquivo", "EDITANDO"),
    SEARCHING_FILES("Procurando arquivos", "BUSCANDO"),
    CHECKING_SYSTEM("Verificando sistema", "SISTEMA"),
    WAITING_CONFIRMATION("Aguardando confirmação", "CONFIRMAR?"),
    SUCCESS("Pronto", "PRONTO"),
    ERROR("Erro", "ERRO"),
    OTHER("Trabalhando", "TRABALHANDO");

    companion object {
        fun fromCode(code: String): BmoActivity = when (code.trim().lowercase()) {
            "", "none" -> NONE
            "processing" -> PROCESSING
            "searching_web" -> SEARCHING_WEB
            "reading_web" -> READING_WEB
            "summarizing_web" -> SUMMARIZING_WEB
            "opening_app" -> OPENING_APP
            "closing_app" -> CLOSING_APP
            "searching_apps" -> SEARCHING_APPS
            "playing_music" -> PLAYING_MUSIC
            "reading_file" -> READING_FILE
            "creating_file" -> CREATING_FILE
            "editing_file" -> EDITING_FILE
            "searching_files" -> SEARCHING_FILES
            "checking_system" -> CHECKING_SYSTEM
            "waiting_confirmation" -> WAITING_CONFIRMATION
            "success" -> SUCCESS
            "error" -> ERROR
            else -> OTHER
        }
    }
}

data class ActivityInfo(
    val activity: BmoActivity = BmoActivity.NONE,
    val status: String = "",
    val label: String = "",
    val tool: String = "",
)

/** Metadados reais do player MPRIS (BitChord e outros) enviados pelo PC. */
data class MusicInfo(
    val player: String = "",
    val isBitchord: Boolean = false,
    val status: String = "",
    val title: String = "",
    val artist: String = "",
    val album: String = "",
    val lengthS: Double? = null,
    val volume: Float? = null,
    val artUrl: String = "",
) {
    val isPlaying: Boolean get() = status.equals("playing", ignoreCase = true)
    val active: Boolean get() = title.isNotBlank() || player.isNotBlank()
}

data class ConfirmationInfo(
    val id: String = "",
    val tool: String = "",
    val prompt: String = "",
)

data class FolderStatus(
    val path: String = "",
    val os: String = "",
    val selectedAt: String = "",
    val authorized: Boolean = false,
    val picker: String = "",
    val displayAvailable: Boolean = false,
)

data class BmoUiState(
    val connection: ConnectionState = ConnectionState.DISCONNECTED,
    val bmoState: BmoState = BmoState.DISCONNECTED,
    val statusDetail: String = "Configure o servidor do PC para começar.",
    val listening: Boolean = false,
    val micLevel: Float = 0f,
    val transcript: String = "",
    val assistantText: String = "",
    val streamingText: Boolean = false,
    val lastError: String? = null,
    val ttsAvailable: Boolean = true,
    val serviceStatus: ServiceStatus? = null,
    val reconnectAttempt: Int = 0,
    val micTesting: Boolean = false,
    val serverSessionId: String = "",
    val faceState: BmoState = BmoState.DISCONNECTED,
    val locationReady: Boolean = false,
    val activity: ActivityInfo? = null,
    val music: MusicInfo? = null,
    val pendingConfirmation: ConfirmationInfo? = null,
    val folderStatus: FolderStatus? = null,
) {
    val connected: Boolean get() = connection == ConnectionState.CONNECTED
    val musicActive: Boolean get() = music?.active == true
    val operationActive: Boolean get() = activity?.activity?.let { it != BmoActivity.NONE } == true
}
