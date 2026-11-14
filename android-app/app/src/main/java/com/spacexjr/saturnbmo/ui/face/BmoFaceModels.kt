package com.spacexjr.saturnbmo.ui.face

import com.spacexjr.saturnbmo.BmoActivity

/** Categoria macro usada para agrupar as animações 8-bit. */
enum class BmoFaceCategory {
    NEUTRAL,
    WEATHER,
    ASTRONOMY,
    MATH,
    MUSIC,
}

/**
 * Assunto da conversa. Cada tema possui uma cena procedural própria, desenhada
 * com Canvas sobre os PNGs originais do BMO.
 */
enum class BmoFaceTheme(val category: BmoFaceCategory) {
    NONE(BmoFaceCategory.NEUTRAL),

    SUNNY(BmoFaceCategory.WEATHER),
    CLOUDY(BmoFaceCategory.WEATHER),
    RAINY(BmoFaceCategory.WEATHER),
    STORM(BmoFaceCategory.WEATHER),
    SNOWY(BmoFaceCategory.WEATHER),
    HOT(BmoFaceCategory.WEATHER),
    COLD(BmoFaceCategory.WEATHER),

    EARTH(BmoFaceCategory.ASTRONOMY),
    MOON(BmoFaceCategory.ASTRONOMY),
    SOLAR_SYSTEM(BmoFaceCategory.ASTRONOMY),
    SUN(BmoFaceCategory.ASTRONOMY),
    SPACE(BmoFaceCategory.ASTRONOMY),
    ECLIPSE(BmoFaceCategory.ASTRONOMY),
    DISTANCE(BmoFaceCategory.ASTRONOMY),

    MATH(BmoFaceCategory.MATH),
    CALCULATING(BmoFaceCategory.MATH),
    SCIENCE(BmoFaceCategory.MATH),

    MUSIC(BmoFaceCategory.MUSIC),
    LISTENING_MUSIC(BmoFaceCategory.MUSIC),
    EQUALIZER(BmoFaceCategory.MUSIC),
}

/** Expressões emocionais. Reaproveitam os frames existentes sempre que possível. */
enum class BmoFaceEmotion {
    NEUTRAL,
    HAPPY,
    SAD,
    THINKING,
    CONFUSED,
    SURPRISED,
    EXCITED,
    SLEEPY,
    SLEEPING,
    LOVE,
    ANGRY,
    LISTENING,
    SPEAKING,
    PROCESSING,
    ERROR;

    companion object {
        /** Converte o valor canônico enviado pelo backend (aceita apelidos comuns). */
        fun fromCode(code: String?): BmoFaceEmotion? {
            val value = code?.trim()?.lowercase().orEmpty()
            if (value.isEmpty()) return null
            return when (
                java.text.Normalizer.normalize(value, java.text.Normalizer.Form.NFD)
                    .replace(Regex("\\p{M}+"), "")
            ) {
                "neutral", "idle", "neutro" -> NEUTRAL
                "happy", "feliz", "alegre" -> HAPPY
                "sad", "triste" -> SAD
                "thinking", "pensando" -> THINKING
                "confused", "confuso" -> CONFUSED
                "surprised", "surpreso" -> SURPRISED
                "excited", "animado" -> EXCITED
                "sleepy", "sonolento", "sono" -> SLEEPY
                "sleeping", "dormindo", "dormir" -> SLEEPING
                "love", "amor", "apaixonado" -> LOVE
                "angry", "bravo", "raiva" -> ANGRY
                "listening", "ouvindo" -> LISTENING
                "speaking", "falando" -> SPEAKING
                "processing", "processando" -> PROCESSING
                "error", "erro" -> ERROR
                else -> null
            }
        }
    }
}

/**
 * Dados reais extraídos da resposta. Nada é inventado: quando um número não
 * aparece no texto, o campo fica nulo e o renderer simplesmente o omite.
 */
data class BmoFaceData(
    val theme: BmoFaceTheme = BmoFaceTheme.NONE,
    val temperatureC: Int? = null,
    val distanceKm: String? = null,
    val distanceFrom: String? = null,
    val distanceTo: String? = null,
    val mathExpression: String? = null,
    val mathResult: String? = null,
    val formula: String? = null,
    val musicTitle: String? = null,
    val musicArtist: String? = null,
    val musicPlaying: Boolean = false,
    val musicVolume: Float? = null,
    val emotionHint: BmoFaceEmotion? = null,
)

/** Resultado completo da seleção de face: assunto + emoção + operação real. */
data class BmoFaceVisual(
    val data: BmoFaceData = BmoFaceData(),
    val emotion: BmoFaceEmotion = BmoFaceEmotion.NEUTRAL,
    val activity: BmoActivity = BmoActivity.NONE,
) {
    val theme: BmoFaceTheme get() = data.theme
}
