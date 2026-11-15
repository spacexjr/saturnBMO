package com.spacexjr.saturnbmo.ui.face

import com.spacexjr.saturnbmo.BmoActivity
import com.spacexjr.saturnbmo.BmoState
import com.spacexjr.saturnbmo.BmoUiState

/**
 * Combina o assunto (tema) com a expressão emocional e o frame correto do PNG.
 * O estado de voz sempre tem prioridade para a boca/olhos, mas as animações do
 * tema continuam rodando ao redor do rosto.
 */
object BmoFaceController {
    /** Tempo sem nenhuma atividade em que o BMO continua acordado. */
    const val SLEEP_AFTER_MS = 10_000L

    fun visualFor(ui: BmoUiState, sleeping: Boolean = false): BmoFaceVisual {
        if (sleeping) {
            // Dormindo: rosto calmo, olhos fechados e Zzz, sem tema nem operação.
            return BmoFaceVisual(
                data = BmoFaceData(),
                emotion = BmoFaceEmotion.SLEEPING,
                activity = BmoActivity.NONE,
            )
        }
        var data = BmoFaceClassifier.classify(
            userText = ui.transcript,
            assistantText = ui.assistantText,
            calculating = ui.faceState == BmoState.THINKING,
        )
        val music = ui.music
        if (music != null && music.active) {
            val musicContext = data.theme == BmoFaceTheme.NONE ||
                data.theme.category == BmoFaceCategory.MUSIC ||
                ui.activity?.activity == BmoActivity.PLAYING_MUSIC
            if (musicContext) {
                data = data.copy(
                    theme = if (music.isPlaying) BmoFaceTheme.EQUALIZER else BmoFaceTheme.MUSIC,
                    musicTitle = music.title.takeIf { it.isNotBlank() },
                    musicArtist = music.artist.takeIf { it.isNotBlank() },
                    musicPlaying = music.isPlaying,
                    musicVolume = music.volume,
                )
            }
        }
        val activity = ui.activity?.activity ?: BmoActivity.NONE
        // Emoção pedida explicitamente pelo modelo via `change_face`. Vale até
        // o próximo turno, mas perde para erro e para a fala em andamento.
        val requestedEmotion = ui.modelEmotion ?: BmoFaceEmotion.fromCode(ui.faceExpression)
        val automaticEmotion = emotionFor(
            theme = data.theme,
            state = ui.faceState,
            hint = data.emotionHint,
            activity = activity,
            vadSpeaking = ui.vadSpeaking,
            model = requestedEmotion,
        )
        // Erro nunca é escondido. Nos demais estados a emoção pedida pelo
        // modelo entra como camada e a boca de "falando" continua vindo dos
        // frames de fala.
        val emotion = when (ui.faceState) {
            BmoState.ERROR -> BmoFaceEmotion.ERROR
            else -> requestedEmotion ?: automaticEmotion
        }
        return BmoFaceVisual(
            data = data,
            emotion = emotion,
            activity = activity,
        )
    }

    /**
     * O rosto deve dormir? Só depois de [SLEEP_AFTER_MS] sem nenhum evento do
     * servidor e sem conversa, música ou operação em andamento.
     */
    fun shouldSleep(ui: BmoUiState, nowMs: Long): Boolean {
        when (ui.faceState) {
            BmoState.THINKING, BmoState.SPEAKING, BmoState.ERROR,
            BmoState.DISCONNECTED, BmoState.CONNECTING -> return false
            else -> Unit
        }
        if (ui.audioPlaying || ui.streamingText) return false
        if (ui.music?.isPlaying == true) return false
        if (ui.pendingConfirmation != null) return false
        if (ui.micTesting) return false
        if (ui.faceExpression != null) return false
        if (ui.modelEmotion != null) return false
        if (ui.activity?.activity?.let { it != BmoActivity.NONE } == true) return false
        if (ui.lastActivityAtMs <= 0L) return false
        return nowMs - ui.lastActivityAtMs >= SLEEP_AFTER_MS
    }

    fun emotionFor(
        theme: BmoFaceTheme,
        state: BmoState,
        hint: BmoFaceEmotion? = null,
        activity: BmoActivity = BmoActivity.NONE,
        vadSpeaking: Boolean = false,
        model: BmoFaceEmotion? = null,
    ): BmoFaceEmotion = when (state) {
        BmoState.ERROR -> BmoFaceEmotion.ERROR
        // Enquanto fala, a boca vem dos frames "speaking"; a emoção do texto
        // (alegria, surpresa, tristeza) entra como camada por cima.
        BmoState.SPEAKING -> hint ?: BmoFaceEmotion.SPEAKING
        // O microfone fica sempre ativo esperando a wake word. O rosto só
        // "ouve" de verdade quando o VAD detecta fala, mas a emoção pedida
        // pelo modelo continua visível sobre o repouso.
        BmoState.LISTENING -> when {
            model != null -> model
            vadSpeaking -> BmoFaceEmotion.LISTENING
            else -> hint ?: BmoFaceEmotion.NEUTRAL
        }
        BmoState.THINKING ->
            // Emoção pedida pelo modelo vence o "pensando" logo após a tool call.
            model ?: (
                if (theme == BmoFaceTheme.CALCULATING) BmoFaceEmotion.PROCESSING
                else BmoFaceEmotion.THINKING
            )
        BmoState.CONNECTING, BmoState.DISCONNECTED -> BmoFaceEmotion.NEUTRAL
        BmoState.IDLE -> model ?: when (activity) {
            BmoActivity.SUCCESS -> BmoFaceEmotion.HAPPY
            BmoActivity.OPENING_APP, BmoActivity.CLOSING_APP,
            BmoActivity.PLAYING_MUSIC, BmoActivity.WAITING_CONFIRMATION ->
                BmoFaceEmotion.EXCITED
            BmoActivity.SEARCHING_WEB, BmoActivity.SEARCHING_APPS,
            BmoActivity.SEARCHING_FILES, BmoActivity.READING_WEB,
            BmoActivity.READING_FILE, BmoActivity.PROCESSING ->
                BmoFaceEmotion.PROCESSING
            else -> hint ?: emotionForTheme(theme)
        }
    }

    fun emotionForTheme(theme: BmoFaceTheme): BmoFaceEmotion = when (theme) {
        BmoFaceTheme.NONE -> BmoFaceEmotion.NEUTRAL
        BmoFaceTheme.SUNNY, BmoFaceTheme.SUN, BmoFaceTheme.MUSIC -> BmoFaceEmotion.HAPPY
        BmoFaceTheme.CLOUDY -> BmoFaceEmotion.NEUTRAL
        BmoFaceTheme.RAINY -> BmoFaceEmotion.SAD
        BmoFaceTheme.STORM -> BmoFaceEmotion.ANGRY
        BmoFaceTheme.SNOWY, BmoFaceTheme.COLD, BmoFaceTheme.LISTENING_MUSIC ->
            BmoFaceEmotion.SLEEPY
        BmoFaceTheme.HOT -> BmoFaceEmotion.SURPRISED
        BmoFaceTheme.EARTH, BmoFaceTheme.MOON -> BmoFaceEmotion.HAPPY
        BmoFaceTheme.SOLAR_SYSTEM, BmoFaceTheme.SPACE, BmoFaceTheme.ECLIPSE ->
            BmoFaceEmotion.EXCITED
        BmoFaceTheme.DISTANCE, BmoFaceTheme.MATH, BmoFaceTheme.SCIENCE ->
            BmoFaceEmotion.THINKING
        BmoFaceTheme.CALCULATING -> BmoFaceEmotion.PROCESSING
        BmoFaceTheme.EQUALIZER -> BmoFaceEmotion.EXCITED
    }

    /**
     * Chave usada pelo FaceController para escolher os PNGs. Estados de voz
     * (ouvindo, falando, pensando, erro) mandam na expressão; no repouso,
     * usamos a emoção sugerida pelo tema. Uma expressão pedida pelo modelo
     * tem prioridade sobre o estado automático, exceto em erro.
     */
    fun expressionKeyFor(
        ui: BmoUiState,
        visual: BmoFaceVisual,
        sleeping: Boolean = false,
    ): String {
        if (sleeping && ui.faceState != BmoState.ERROR) return "sleeping"
        when (ui.faceState) {
            BmoState.CONNECTING -> return "warmup"
            BmoState.DISCONNECTED -> return "idle"
            BmoState.ERROR -> return "error"
            else -> Unit
        }
        // Uma expressão pedida pelo modelo vence ouvindo/pensando/repouso.
        // Enquanto fala com áudio, a boca continua vindo dos frames "speaking".
        val requested = ui.modelEmotion ?: BmoFaceEmotion.fromCode(ui.faceExpression)
        if (requested != null) {
            if (ui.faceState == BmoState.SPEAKING && ui.audioPlaying) return "speaking"
            return expressionKeyFor(requested)
        }
        return when (ui.faceState) {
            // Boca só se mexe quando há som saindo do alto-falante.
            BmoState.SPEAKING -> if (ui.audioPlaying) "speaking" else "thinking"
            BmoState.THINKING -> "thinking"
            BmoState.LISTENING -> if (ui.vadSpeaking) "listening" else "idle"
            BmoState.IDLE -> expressionKeyFor(visual.emotion)
            else -> "idle"
        }
    }

    fun expressionKeyFor(emotion: BmoFaceEmotion): String = when (emotion) {
        BmoFaceEmotion.NEUTRAL -> "idle"
        BmoFaceEmotion.HAPPY -> "happy"
        BmoFaceEmotion.SAD -> "sad"
        BmoFaceEmotion.THINKING -> "thinking"
        BmoFaceEmotion.CONFUSED -> "confused"
        BmoFaceEmotion.SURPRISED -> "surprised"
        BmoFaceEmotion.EXCITED -> "excited"
        BmoFaceEmotion.SLEEPY -> "sleepy"
        BmoFaceEmotion.SLEEPING -> "sleeping"
        BmoFaceEmotion.LOVE -> "love"
        BmoFaceEmotion.ANGRY -> "angry"
        BmoFaceEmotion.LISTENING -> "listening"
        BmoFaceEmotion.SPEAKING -> "speaking"
        BmoFaceEmotion.PROCESSING -> "thinking"
        BmoFaceEmotion.ERROR -> "error"
    }
}
