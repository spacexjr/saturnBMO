package com.spacexjr.saturnbmo

import com.spacexjr.saturnbmo.ui.face.BmoFaceClassifier
import com.spacexjr.saturnbmo.ui.face.BmoFaceEmotion
import com.spacexjr.saturnbmo.ui.face.BmoFaceTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BmoFaceClassifierTest {
    @Test
    fun reconheceClimaEnsolaradoETemperaturaReal() {
        val data = BmoFaceClassifier.classify(
            userText = "Como está o tempo?",
            assistantText = "Agora faz 24 graus em Recife, com sensação de 26 graus e céu limpo.",
        )
        assertEquals(BmoFaceTheme.SUNNY, data.theme)
        assertEquals(24, data.temperatureC)
    }

    @Test
    fun reconheceChuvaTempestadeNeveCalorEFrio() {
        assertEquals(
            BmoFaceTheme.RAINY,
            BmoFaceClassifier.classify(
                "Está chovendo?",
                "Sim, há previsão de chuva para hoje: chance de 80% e chuva moderada.",
            ).theme,
        )
        assertEquals(
            BmoFaceTheme.STORM,
            BmoFaceClassifier.classify(
                "Como está o clima?",
                "Agora faz 21 graus com tempestade e relâmpagos.",
            ).theme,
        )
        assertEquals(
            BmoFaceTheme.SNOWY,
            BmoFaceClassifier.classify(
                "Vai nevar?",
                "Há previsão de neve moderada para amanhã.",
            ).theme,
        )
        assertEquals(
            BmoFaceTheme.HOT,
            BmoFaceClassifier.classify(
                "Como está o tempo?",
                "Agora faz 35 graus, com sensação de 38 graus.",
            ).theme,
        )
        assertEquals(
            BmoFaceTheme.COLD,
            BmoFaceClassifier.classify(
                "Como está o tempo?",
                "Agora faz 5 graus, com sensação de 2 graus.",
            ).theme,
        )
    }

    @Test
    fun extraiDistanciaTerraLuaDoTextoDaResposta() {
        val data = BmoFaceClassifier.classify(
            userText = "Qual a distância da Terra até a Lua?",
            assistantText = "A distância média é de aproximadamente 384.400 km.",
        )
        assertEquals(BmoFaceTheme.DISTANCE, data.theme)
        assertEquals("384.400 KM", data.distanceKm)
        assertEquals("TERRA", data.distanceFrom)
        assertEquals("LUA", data.distanceTo)
    }

    @Test
    fun calculaExpressaoSemInventarResultado() {
        val data = BmoFaceClassifier.classify(
            userText = "Quanto é 2 + 2?",
            assistantText = "2 + 2 = 4.",
        )
        assertEquals(BmoFaceTheme.MATH, data.theme)
        assertEquals("2+2", data.mathExpression)
        assertEquals("4", data.mathResult)
    }

    @Test
    fun duranteCalculoMostraTemaCalculandoSemResultado() {
        val data = BmoFaceClassifier.classify(
            userText = "Quanto é 12 * 7?",
            assistantText = "",
            calculating = true,
        )
        assertEquals(BmoFaceTheme.CALCULATING, data.theme)
        assertEquals("12*7", data.mathExpression)
        assertNull(data.mathResult)
    }

    @Test
    fun reconheceMusicaEqualizadorECiencia() {
        assertEquals(
            BmoFaceTheme.MUSIC,
            BmoFaceClassifier.classify("Toque uma música.", "").theme,
        )
        assertEquals(
            BmoFaceTheme.LISTENING_MUSIC,
            BmoFaceClassifier.classify("Estou ouvindo música relaxante.", "").theme,
        )
        assertEquals(
            BmoFaceTheme.EQUALIZER,
            BmoFaceClassifier.classify("Mostre o equalizador.", "").theme,
        )
        val science = BmoFaceClassifier.classify(
            "Qual é a fórmula da água?",
            "A fórmula da água é H2O.",
        )
        assertEquals(BmoFaceTheme.SCIENCE, science.theme)
        assertEquals("H2O", science.formula)
    }

    @Test
    fun reconheceTemasDeAstronomia() {
        assertEquals(
            BmoFaceTheme.EARTH,
            BmoFaceClassifier.classify("Como é o planeta Terra?", "").theme,
        )
        assertEquals(
            BmoFaceTheme.MOON,
            BmoFaceClassifier.classify("Como é a Lua?", "").theme,
        )
        assertEquals(
            BmoFaceTheme.SOLAR_SYSTEM,
            BmoFaceClassifier.classify("Explique o sistema solar.", "").theme,
        )
        assertEquals(
            BmoFaceTheme.SUN,
            BmoFaceClassifier.classify("Como é o Sol?", "").theme,
        )
        assertEquals(
            BmoFaceTheme.SPACE,
            BmoFaceClassifier.classify("O que existe no espaço?", "").theme,
        )
        assertEquals(
            BmoFaceTheme.ECLIPSE,
            BmoFaceClassifier.classify("O que é um eclipse solar?", "").theme,
        )
    }

    @Test
    fun combinaEmocaoComEstadoDeVoz() {
        val visual = com.spacexjr.saturnbmo.ui.face.BmoFaceController.visualFor(
            BmoUiState(
                transcript = "Está chovendo?",
                assistantText = "Sim, há previsão de chuva.",
                bmoState = BmoState.SPEAKING,
                faceState = BmoState.SPEAKING,
            )
        )
        assertEquals(BmoFaceTheme.RAINY, visual.theme)
        assertEquals(BmoFaceEmotion.SPEAKING, visual.emotion)
        // A boca (frames "speaking") só entra quando o áudio está tocando.
        assertEquals(
            "speaking",
            com.spacexjr.saturnbmo.ui.face.BmoFaceController.expressionKeyFor(
                BmoUiState(faceState = BmoState.SPEAKING, audioPlaying = true),
                visual,
            ),
        )
        assertEquals(
            "thinking",
            com.spacexjr.saturnbmo.ui.face.BmoFaceController.expressionKeyFor(
                BmoUiState(faceState = BmoState.SPEAKING, audioPlaying = false),
                visual,
            ),
        )
    }

    @Test
    fun emocaoExplicitaTemPrioridadeNoRepouso() {
        val love = com.spacexjr.saturnbmo.ui.face.BmoFaceController.visualFor(
            BmoUiState(
                transcript = "BMO, eu te amo!",
                assistantText = "Também gosto muito de você.",
                bmoState = BmoState.IDLE,
                faceState = BmoState.IDLE,
            )
        )
        assertEquals(BmoFaceEmotion.LOVE, love.emotion)
        assertEquals(
            "love",
            com.spacexjr.saturnbmo.ui.face.BmoFaceController.expressionKeyFor(
                BmoUiState(faceState = BmoState.IDLE),
                love,
            ),
        )
    }
}
