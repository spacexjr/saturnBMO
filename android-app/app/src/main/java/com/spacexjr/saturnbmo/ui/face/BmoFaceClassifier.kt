package com.spacexjr.saturnbmo.ui.face

import java.text.Normalizer
import java.util.Locale

/**
 * Classifica o assunto da conversa usando apenas o texto já existente no app
 * (transcrição do usuário e resposta do assistente). Não conversa com o
 * backend e não inventa dados: números só são exibidos quando aparecem no
 * texto recebido.
 */
object BmoFaceClassifier {
    private const val HOT_C = 30
    private const val COLD_C = 11

    private val distanceRegex = Regex(
        """(\d[\d.\s]*)\s*(mil\s+)?(km|quilometros?)\b""",
        RegexOption.IGNORE_CASE,
    )
    private val temperatureRegex = Regex("""(-?\d{1,3})\s*graus\b""", RegexOption.IGNORE_CASE)
    private val arithmeticRegex = Regex(
        """(-?\d+(?:[.,]\d+)?)\s*([+\-*/x])\s*(-?\d+(?:[.,]\d+)?)""",
        RegexOption.IGNORE_CASE,
    )
    private val equalsResultRegex = Regex("""=\s*(-?\d+(?:[.,]\d+)?)""")
    private val answerResultRegex = Regex(
        """(?:resultado|resposta|total|igual a|e)\s*:?\s*(-?\d+(?:[.,]\d+)?)""",
        RegexOption.IGNORE_CASE,
    )
    private val numberRegex = Regex("""-?\d+(?:[.,]\d+)?""")

    private val stormWords = listOf(
        "tempestade", "trovao", "trovejando", "relampago", "relampagos",
        "granizo", "vendaval", "ciclone",
    )
    private val snowWords = listOf(
        "neve", "nevando", "nevou", "graos de neve", "geada", "congelante",
        "neblina com geada",
    )
    private val rainWords = listOf(
        "chuva", "chuvas", "chover", "chovendo", "garoa", "pancadas",
        "precipitacao", "molhado", "guarda chuva",
    )
    private val cloudWords = listOf(
        "nublado", "nuvem", "nuvens", "neblina", "nevoa", "encoberto",
        "parcialmente nublado", "tempo estavel",
    )
    private val sunWords = listOf(
        "ceu limpo", "predominio de sol", "ensolarado", "sol", "limpo",
    )
    private val hotWords = listOf("calor", "quente", "abafado", "muito calor", "calor intenso")
    private val coldWords = listOf("frio", "gelado", "friagem", "muito frio", "frio intenso")

    private val weatherContextWords = listOf(
        "clima", "tempo", "previsao", "chuva", "chover", "temperatura",
        "graus", "neve", "nublado", "ensolarado", "calor", "frio", "umidade",
        "garoa", "tempestade", "granizo", "geada", "sensacao",
    )

    private val assistantWeatherWords = listOf(
        "graus", "chuva", "chover", "nublado", "neve", "tempestade",
        "granizo", "geada", "ensolarado", "ceu limpo", "predominio de sol",
        "precipitacao", "sensacao", "umidade", "garoa", "neblina", "calor",
        "frio",
    )

    private val astronomyWords = listOf(
        "lua", "sol", "terra", "marte", "jupiter", "saturno", "venus", "mercurio",
        "netuno", "urano", "plutao", "planeta", "planetas", "sistema solar",
        "galaxia", "galaxias", "nebulosa", "universo", "espaco", "estrela",
        "estrelas", "asteroide", "cometa", "orbita", "cosmos", "via lactea",
        "eclipse", "satelite", "buraco negro",
    )

    private val musicWords = listOf(
        "musica", "canção", "cancao", "tocar", "toque", "playlist", "banda",
        "melodia", "nota musical", "notas musicais", "som", "cantar", "audio",
        "equalizador", "volume", "batida", "ritmo", "instrumento",
    )

    private val scienceWords = listOf(
        "ciencia", "cientifico", "formula", "fisica", "quimica", "biologia",
        "atomo", "molecula", "energia", "gravidade", "relatividade", "newton",
        "einstein", "experimento", "laboratorio", "teoria", "equacao",
    )

    private val mathWords = listOf(
        "matematica", "calcul", "quanto e", "quanto sao", "resultado",
        "soma", "subtracao", "multiplic", "divis", "equacao", "conta",
    )

    fun classify(
        userText: String,
        assistantText: String,
        calculating: Boolean = false,
    ): BmoFaceData {
        val user = normalize(userText)
        val assistant = normalize(assistantText)
        val all = "$user $assistant".trim()
        if (all.isEmpty()) return BmoFaceData()

        val weather = isWeather(user, assistant, all)
        val astronomy = hasAny(all, astronomyWords) ||
            (all.contains("distancia") && hasAny(all, astronomyWords))
        val math = detectMath(user, assistant)

        val data = when {
            math != null -> {
                if (calculating && math.mathResult == null) math.copy(theme = BmoFaceTheme.CALCULATING)
                else math
            }

            weather -> weatherData(user, assistant)

            astronomy -> astronomyData(user, assistant)

            hasAny(all, listOf("equalizador")) -> BmoFaceData(theme = BmoFaceTheme.EQUALIZER)

            hasAny(all, musicWords) -> musicData(user, assistant)

            hasAny(all, scienceWords) -> BmoFaceData(
                theme = BmoFaceTheme.SCIENCE,
                formula = formulaFor(all),
            )

            else -> BmoFaceData()
        }
        return data.copy(emotionHint = detectEmotion(user, assistant))
    }

    // ------------------------------------------------------------------
    // Clima
    // ------------------------------------------------------------------

    private fun isWeather(user: String, assistant: String, all: String): Boolean {
        if (hasAny(assistant, assistantWeatherWords)) return true
        // "sol" isolado é astronomia; clima precisa de contexto explícito.
        val userWeather = hasAny(user, weatherContextWords) ||
            hasAny(user, rainWords + snowWords + cloudWords + stormWords)
        return userWeather && !hasAny(all, listOf("sistema solar", "galaxia", "eclipse"))
    }

    private fun weatherData(user: String, assistant: String): BmoFaceData {
        val all = "$user $assistant"
        val temp = temperatureRegex.find(assistant)?.groupValues?.get(1)?.toIntOrNull()
            ?: temperatureRegex.find(user)?.groupValues?.get(1)?.toIntOrNull()
        val theme = when {
            hasAny(all, stormWords) -> BmoFaceTheme.STORM
            hasAny(all, snowWords) -> BmoFaceTheme.SNOWY
            hasAny(all, rainWords) -> BmoFaceTheme.RAINY
            temp != null && temp >= HOT_C -> BmoFaceTheme.HOT
            temp != null && temp <= COLD_C -> BmoFaceTheme.COLD
            hasAny(all, coldWords) -> BmoFaceTheme.COLD
            hasAny(all, hotWords) -> BmoFaceTheme.HOT
            hasAny(all, cloudWords) -> BmoFaceTheme.CLOUDY
            hasAny(all, sunWords) -> BmoFaceTheme.SUNNY
            else -> BmoFaceTheme.CLOUDY
        }
        return BmoFaceData(theme = theme, temperatureC = temp)
    }

    // ------------------------------------------------------------------
    // Astronomia
    // ------------------------------------------------------------------

    private fun astronomyData(user: String, assistant: String): BmoFaceData {
        val all = "$user $assistant"
        val distance = distanceRegex.find(assistant) ?: distanceRegex.find(user)
        val asksDistance = all.contains("distancia") ||
            all.contains("longe") ||
            all.contains("quao longe")
        val celestial = hasAny(all, astronomyWords)

        if (distance != null && celestial && (asksDistance || distance.value.isNotBlank())) {
            val (from, to) = distanceLabels(all)
            return BmoFaceData(
                theme = BmoFaceTheme.DISTANCE,
                distanceKm = formatKm(distance.groupValues[1]),
                distanceFrom = from,
                distanceTo = to,
            )
        }

        val theme = when {
            all.contains("eclipse") -> BmoFaceTheme.ECLIPSE
            all.contains("sistema solar") || all.contains("planetas") -> BmoFaceTheme.SOLAR_SYSTEM
            all.contains("lua") -> BmoFaceTheme.MOON
            all.contains("terra") && !all.contains("distancia") -> BmoFaceTheme.EARTH
            all.contains("sol") && !isWeather(user, assistant, all) -> BmoFaceTheme.SUN
            else -> BmoFaceTheme.SPACE
        }
        return BmoFaceData(theme = theme)
    }

    private fun distanceLabels(text: String): Pair<String, String> {
        val bodies = listOf("terra", "lua", "sol", "marte")
            .filter { text.contains(it) }
            .sortedBy { text.indexOf(it) }
            .map { it.uppercase(Locale.ROOT) }
        val from = bodies.getOrNull(0) ?: "A"
        val to = bodies.getOrNull(1) ?: "B"
        return from to to
    }

    // ------------------------------------------------------------------
    // Matemática e ciência
    // ------------------------------------------------------------------

    private fun detectMath(user: String, assistant: String): BmoFaceData? {
        val expression = arithmeticRegex.find(user)
            ?: arithmeticRegex.find(assistant)
        val wantsMath = expression != null ||
            hasAny(user, mathWords) ||
            (user.contains("quanto") && user.any { it.isDigit() } && hasOperator(user))

        if (!wantsMath) return null

        val displayExpression = expression?.let { match ->
            val (a, op, b) = match.destructured
            "${a.replace(",", ".")}$op${b.replace(",", ".")}"
        } ?: if (hasAny(user, mathWords)) user.trim().take(28).uppercase(Locale.ROOT) else null

        val result = extractMathResult(assistant, expression)
        return BmoFaceData(
            theme = if (result != null) BmoFaceTheme.MATH else BmoFaceTheme.CALCULATING,
            mathExpression = displayExpression,
            mathResult = result,
        )
    }

    private fun hasOperator(text: String): Boolean =
        text.any { it == '+' || it == '-' || it == '*' || it == '/' || it == 'x' }

    private fun extractMathResult(assistant: String, expression: MatchResult?): String? {
        if (assistant.isBlank()) return null
        equalsResultRegex.find(assistant)?.groupValues?.get(1)?.let { return it.replace(",", ".") }
        answerResultRegex.find(assistant)?.groupValues?.get(1)?.let { return it.replace(",", ".") }
        val operands = expression?.destructured?.let { listOf(it.component1(), it.component2(), it.component3()) }
            ?.map { it.replace(",", ".").toDoubleOrNull() }
            ?.filterNotNull()
            .orEmpty()
        val numbers = numberRegex.findAll(assistant)
            .mapNotNull { it.value.replace(",", ".").toDoubleOrNull() }
            .toList()
        return numbers.firstOrNull { candidate -> operands.none { it == candidate } }
            ?.let { formatNumber(it) }
    }

    private fun formulaFor(text: String): String = when {
        text.contains("agua") -> "H2O"
        text.contains("gravidade") || text.contains("newton") -> "F=MA"
        text.contains("energia") || text.contains("einstein") || text.contains("relatividade") -> "E=MC2"
        text.contains("fisica") -> "E=MC2"
        text.contains("quimica") || text.contains("atomo") || text.contains("molecula") -> "H2O"
        text.contains("biologia") -> "DNA"
        else -> "E=MC2"
    }

    // ------------------------------------------------------------------
    // Música
    // ------------------------------------------------------------------

    private fun musicData(user: String, assistant: String): BmoFaceData {
        val all = "$user $assistant"
        val theme = when {
            all.contains("equalizador") -> BmoFaceTheme.EQUALIZER
            all.contains("ouvindo musica") || all.contains("escutando musica") ||
                all.contains("musica relaxante") || all.contains("tocando musica") -> BmoFaceTheme.LISTENING_MUSIC
            else -> BmoFaceTheme.MUSIC
        }
        return BmoFaceData(theme = theme)
    }

    // ------------------------------------------------------------------
    // Emoções explícitas
    // ------------------------------------------------------------------

    private val loveWords = listOf("te amo", "amo voce", "amor", "apaixonado", "apaixonada", "carinho", "querido", "querida")
    private val angryWords = listOf("raiva", "irritado", "irritada", "odio", "bravo", "brava", "furioso", "furiosa")
    private val sadWords = listOf("triste", "tristeza", "chateado", "chateada", "chorar", "deprimido", "deprimida")
    private val happyWords = listOf("feliz", "felicidade", "alegre", "contente", "que bom", "otimo", "maravilhoso")
    private val surprisedWords = listOf("uau", "incrivel", "surpreso", "surpresa", "nossa", "caramba")
    private val excitedWords = listOf("animado", "animada", "empolgado", "empolgada", "eba", "adorei", "vamos la")
    private val sleepyWords = listOf("sono", "dormir", "cansado", "cansada", "boa noite")
    private val confusedWords = listOf("confuso", "confusa", "nao entendi", "nao sei", "duvida")

    private fun detectEmotion(user: String, assistant: String): BmoFaceEmotion? {
        val text = user.ifBlank { assistant }
        return when {
            hasAny(text, loveWords) -> BmoFaceEmotion.LOVE
            hasAny(text, angryWords) -> BmoFaceEmotion.ANGRY
            hasAny(text, sadWords) -> BmoFaceEmotion.SAD
            hasAny(text, happyWords) -> BmoFaceEmotion.HAPPY
            hasAny(text, surprisedWords) -> BmoFaceEmotion.SURPRISED
            hasAny(text, excitedWords) -> BmoFaceEmotion.EXCITED
            hasAny(text, sleepyWords) -> BmoFaceEmotion.SLEEPY
            hasAny(text, confusedWords) -> BmoFaceEmotion.CONFUSED
            else -> null
        }
    }

    // ------------------------------------------------------------------
    // Utilidades
    // ------------------------------------------------------------------

    private fun normalize(text: String): String {
        if (text.isBlank()) return ""
        val decomposed = Normalizer.normalize(text, Normalizer.Form.NFD)
        val noAccents = buildString(decomposed.length) {
            decomposed.forEach { char ->
                if (char.code in 0x0300..0x036F) return@forEach
                append(char)
            }
        }
        return noAccents.lowercase(Locale.ROOT).replace(Regex("""\s+"""), " ").trim()
    }

    private fun hasAny(text: String, words: List<String>): Boolean = words.any { text.contains(it) }

    private fun formatKm(raw: String): String {
        val digits = raw.filter { it.isDigit() }
        if (digits.isEmpty()) return raw.trim().uppercase(Locale.ROOT)
        val grouped = digits.trimStart('0').ifEmpty { "0" }
            .reversed()
            .chunked(3)
            .joinToString(".")
            .reversed()
        return "$grouped KM"
    }

    private fun formatNumber(value: Double): String {
        if (value % 1.0 == 0.0) return value.toLong().toString()
        return value.toString().replace('.', ',')
    }
}
