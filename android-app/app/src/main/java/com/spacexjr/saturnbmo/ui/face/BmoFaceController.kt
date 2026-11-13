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
    fun visualFor(ui: BmoUiState): BmoFaceVisual {
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
        return BmoFaceVisual(
            data = data,
            emotion = emotionFor(data.theme, ui.faceState, data.emotionHint, activity),
            activity = activity,
        )
    }

    fun emotionFor(
        theme: BmoFaceTheme,
        state: BmoState,
        hint: BmoFaceEmotion? = null,
        activity: BmoActivity = BmoActivity.NONE,
    ): BmoFaceEmotion = when (state) {
        BmoState.ERROR -> BmoFaceEmotion.ERROR
        BmoState.SPEAKING -> BmoFaceEmotion.SPEAKING
        BmoState.LISTENING -> BmoFaceEmotion.LISTENING
        BmoState.THINKING ->
            if (theme == BmoFaceTheme.CALCULATING) BmoFaceEmotion.PROCESSING
            else BmoFaceEmotion.THINKING
        BmoState.CONNECTING, BmoState.DISCONNECTED -> BmoFaceEmotion.NEUTRAL
        BmoState.IDLE -> when (activity) {
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
     * usamos a emoção sugerida pelo tema.
     */
    fun expressionKeyFor(ui: BmoUiState, visual: BmoFaceVisual): String = when (ui.faceState) {
        BmoState.CONNECTING -> "warmup"
        BmoState.DISCONNECTED -> "idle"
        BmoState.ERROR -> "error"
        BmoState.SPEAKING -> "speaking"
        BmoState.THINKING -> "thinking"
        BmoState.LISTENING -> "listening"
        BmoState.IDLE -> expressionKeyFor(visual.emotion)
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
        BmoFaceEmotion.LOVE -> "love"
        BmoFaceEmotion.ANGRY -> "angry"
        BmoFaceEmotion.LISTENING -> "listening"
        BmoFaceEmotion.SPEAKING -> "speaking"
        BmoFaceEmotion.PROCESSING -> "thinking"
        BmoFaceEmotion.ERROR -> "error"
        BmoFaceEmotion.SCARED -> "scared"
    }
}
