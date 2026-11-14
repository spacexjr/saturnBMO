package com.spacexjr.saturnbmo

import com.spacexjr.saturnbmo.ui.face.BmoFaceController
import com.spacexjr.saturnbmo.ui.face.BmoFaceEmotion
import com.spacexjr.saturnbmo.ui.face.BmoFaceTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BmoActivityFaceTest {
    @Test
    fun operacoesDoBackendSaoMapeadas() {
        assertEquals(BmoActivity.SEARCHING_WEB, BmoActivity.fromCode("searching_web"))
        assertEquals(BmoActivity.OPENING_APP, BmoActivity.fromCode("opening_app"))
        assertEquals(BmoActivity.EDITING_FILE, BmoActivity.fromCode("editing_file"))
        assertEquals(BmoActivity.WAITING_CONFIRMATION, BmoActivity.fromCode("waiting_confirmation"))
        assertEquals(BmoActivity.NONE, BmoActivity.fromCode(""))
        assertEquals(BmoActivity.OTHER, BmoActivity.fromCode("algo_novo"))
    }

    @Test
    fun musicaRealViraEqualizadorComTituloEArtista() {
        val visual = BmoFaceController.visualFor(
            BmoUiState(
                faceState = BmoState.IDLE,
                music = MusicInfo(
                    player = "org.mpris.MediaPlayer2.bitchord",
                    isBitchord = true,
                    status = "Playing",
                    title = "EXPANSÃO DE DOMÍNIO",
                    artist = "M4rkim",
                    volume = 0.53f,
                ),
            )
        )
        assertEquals(BmoFaceTheme.EQUALIZER, visual.theme)
        assertEquals("EXPANSÃO DE DOMÍNIO", visual.data.musicTitle)
        assertEquals("M4rkim", visual.data.musicArtist)
        assertEquals(true, visual.data.musicPlaying)
        assertEquals(BmoFaceEmotion.EXCITED, visual.emotion)
    }

    @Test
    fun musicaPausadaUsaTemaMusicalSemInventarMetadados() {
        val visual = BmoFaceController.visualFor(
            BmoUiState(
                faceState = BmoState.IDLE,
                music = MusicInfo(status = "Paused", player = "bitchord"),
            )
        )
        assertEquals(BmoFaceTheme.MUSIC, visual.theme)
        assertNull(visual.data.musicTitle)
        assertNull(visual.data.musicArtist)
        assertEquals(false, visual.data.musicPlaying)
    }

    @Test
    fun operacaoApareceNaFaceMesmoEmRepouso() {
        val visual = BmoFaceController.visualFor(
            BmoUiState(
                faceState = BmoState.IDLE,
                activity = ActivityInfo(
                    activity = BmoActivity.SEARCHING_FILES,
                    status = "start",
                    label = "Procurando arquivos",
                ),
            )
        )
        assertEquals(BmoActivity.SEARCHING_FILES, visual.activity)
        assertEquals(BmoFaceEmotion.PROCESSING, visual.emotion)
    }

    @Test
    fun sucessoDeixaBmoFelizNoRepouso() {
        val visual = BmoFaceController.visualFor(
            BmoUiState(
                faceState = BmoState.IDLE,
                activity = ActivityInfo(activity = BmoActivity.SUCCESS, status = "done"),
            )
        )
        assertEquals(BmoActivity.SUCCESS, visual.activity)
        assertEquals(BmoFaceEmotion.HAPPY, visual.emotion)
    }

    @Test
    fun expressaoPedidaPeloModeloVenceOEstadoAutomatico() {
        val ui = BmoUiState(
            faceState = BmoState.SPEAKING,
            faceExpression = "happy",
        )
        val visual = BmoFaceController.visualFor(ui)
        assertEquals(BmoFaceEmotion.HAPPY, visual.emotion)
        assertEquals("happy", BmoFaceController.expressionKeyFor(ui, visual))
    }

    @Test
    fun erroContinuaVencendoExpressaoDoModelo() {
        val ui = BmoUiState(
            faceState = BmoState.ERROR,
            faceExpression = "love",
        )
        val visual = BmoFaceController.visualFor(ui)
        assertEquals(BmoFaceEmotion.ERROR, visual.emotion)
        assertEquals("error", BmoFaceController.expressionKeyFor(ui, visual))
    }

    @Test
    fun expressaoDoModeloNaoFicaPresaQuandoOResetChega() {
        val withModel = BmoUiState(
            faceState = BmoState.IDLE,
            faceExpression = "confused",
        )
        assertEquals(
            "confused",
            BmoFaceController.expressionKeyFor(withModel, BmoFaceController.visualFor(withModel)),
        )

        val restored = withModel.copy(faceExpression = null, faceLabel = "")
        val visual = BmoFaceController.visualFor(restored)
        assertEquals(BmoFaceEmotion.NEUTRAL, visual.emotion)
        assertEquals("idle", BmoFaceController.expressionKeyFor(restored, visual))
    }

    @Test
    fun codigoDaFaceAceitaCanonicoEApelidos() {
        assertEquals(BmoFaceEmotion.HAPPY, BmoFaceEmotion.fromCode("happy"))
        assertEquals(BmoFaceEmotion.HAPPY, BmoFaceEmotion.fromCode("feliz"))
        assertEquals(BmoFaceEmotion.PROCESSING, BmoFaceEmotion.fromCode("processando"))
        assertEquals(BmoFaceEmotion.SLEEPY, BmoFaceEmotion.fromCode("sonolento"))
        assertNull(BmoFaceEmotion.fromCode("dançando"))
        assertNull(BmoFaceEmotion.fromCode(null))
    }
}
