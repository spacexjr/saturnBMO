package com.spacexjr.saturnbmo.ui.face

import com.spacexjr.saturnbmo.BmoState
import com.spacexjr.saturnbmo.BmoUiState

/**
 * Combina o assunto (tema) com a expressão emocional e o frame correto do PNG.
 * O estado de voz sempre tem prioridade para a boca/olhos, mas as animações do
 * tema continuam rodando ao redor do rosto.
 */
object BmoFaceController {
    fun visualFor(ui: BmoUiState): BmoFaceVisual {
        val data = BmoFaceClassifier.classify(
            userText = ui.transcript,
            assistantText = ui.assistantText,
            calculating = ui.faceState == BmoState.THINKING,
        )
        return BmoFaceVisual(
            data = data,
            emotion = emotionFor(data.theme, ui.faceState, data.emotionHint),
        )
    }

    fun emotionFor(
        theme: BmoFaceTheme,
        state: BmoState,
        hint: BmoFaceEmotion? = null,
    ): BmoFaceEmotion = when (state) {
        BmoState.ERROR -> BmoFaceEmotion.ERROR
        BmoState.SPEAKING -> BmoFaceEmotion.SPEAKING
        BmoState.LISTENING -> BmoFaceEmotion.LISTENING
        BmoState.THINKING ->
            if (theme == BmoFaceTheme.CALCULATING) BmoFaceEmotion.PROCESSING
            else BmoFaceEmotion.THINKING
        BmoState.CONNECTING, BmoState.DISCONNECTED -> BmoFaceEmotion.NEUTRAL
        BmoState.IDLE -> hint ?: emotionForTheme(theme)
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
    }
}
