package com.spacexjr.saturnbmo

import com.spacexjr.saturnbmo.ui.face.BmoFaceController
import com.spacexjr.saturnbmo.ui.face.BmoFaceEmotion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BmoModelFaceTest {
    @Test
    fun nomesDoBackendSaoConvertidosEmEmocoes() {
        assertEquals(BmoFaceEmotion.HAPPY, BmoFaceEmotion.fromCode("happy"))
        assertEquals(BmoFaceEmotion.CONFUSED, BmoFaceEmotion.fromCode("CONFUSED"))
        assertEquals(BmoFaceEmotion.SURPRISED, BmoFaceEmotion.fromCode("surpreso"))
        assertEquals(BmoFaceEmotion.PROCESSING, BmoFaceEmotion.fromCode("processing"))
        assertNull(BmoFaceEmotion.fromCode("inexistente"))
    }

    @Test
    fun emocaoDoModeloVencePensandoEouvindo() {
        for (state in listOf(BmoState.THINKING, BmoState.LISTENING, BmoState.IDLE)) {
            val visual = BmoFaceController.visualFor(
                BmoUiState(faceState = state, modelEmotion = BmoFaceEmotion.CONFUSED),
            )
            assertEquals("estado $state", BmoFaceEmotion.CONFUSED, visual.emotion)
            assertEquals("estado $state", "confused", BmoFaceController.expressionKeyFor(
                BmoUiState(faceState = state, modelEmotion = BmoFaceEmotion.CONFUSED),
                visual,
            ))
        }
    }

    @Test
    fun duranteAFalaAMantemAEmocaoComBocaAnimada() {
        val ui = BmoUiState(
            faceState = BmoState.SPEAKING,
            modelEmotion = BmoFaceEmotion.CONFUSED,
            audioPlaying = true,
        )
        val visual = BmoFaceController.visualFor(ui)
        assertEquals(BmoFaceEmotion.CONFUSED, visual.emotion)
        assertEquals(true, visual.talking)
        assertEquals("confused", BmoFaceController.expressionKeyFor(ui, visual))
        // Terminado o áudio, a expressão escolhida continua na tela.
        val silent = ui.copy(audioPlaying = false)
        val silentVisual = BmoFaceController.visualFor(silent)
        assertEquals(false, silentVisual.talking)
        assertEquals("confused", BmoFaceController.expressionKeyFor(silent, silentVisual))
    }

    @Test
    fun semEmocaoDoModeloOsEstadosAutomaticosContinuam() {
        assertEquals(
            BmoFaceEmotion.THINKING,
            BmoFaceController.visualFor(BmoUiState(faceState = BmoState.THINKING)).emotion,
        )
        assertEquals(
            BmoFaceEmotion.LISTENING,
            BmoFaceController.visualFor(
                BmoUiState(faceState = BmoState.LISTENING, vadSpeaking = true),
            ).emotion,
        )
        // Com o microfone sempre ativo, o rosto repousa neutro até o VAD
        // detectar fala de verdade.
        assertEquals(
            BmoFaceEmotion.NEUTRAL,
            BmoFaceController.visualFor(BmoUiState(faceState = BmoState.LISTENING)).emotion,
        )
    }
}
