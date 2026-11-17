package com.spacexjr.saturnbmo

import com.spacexjr.saturnbmo.ui.face.BmoFaceController
import com.spacexjr.saturnbmo.ui.face.BmoFaceEmotion
import com.spacexjr.saturnbmo.ui.face.BmoFaceTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BmoFaceSleepTest {
    private val awake = BmoUiState(
        faceState = BmoState.LISTENING,
        listening = true,
        lastActivityAtMs = 1_000L,
    )

    private fun playing() = MusicInfo(
        player = "mopidy",
        status = "playing",
        title = "Song",
        artist = "Artist",
    )

    @Test
    fun dormeCincoSegundosDepoisDaUltimaAtividade() {
        assertFalse(BmoFaceController.shouldSleep(awake, 5_900L))
        assertTrue(BmoFaceController.shouldSleep(awake, 6_000L))
    }

    @Test
    fun naoDormeDuranteConversaMusicaOuOperacao() {
        assertFalse(
            BmoFaceController.shouldSleep(
                awake.copy(faceState = BmoState.SPEAKING),
                60_000L,
            )
        )
        assertFalse(
            BmoFaceController.shouldSleep(
                awake.copy(faceState = BmoState.THINKING),
                60_000L,
            )
        )
        assertFalse(
            BmoFaceController.shouldSleep(awake.copy(audioPlaying = true), 60_000L)
        )
        // Qualquer voz detectada pelo VAD acorda e mantém o rosto acordado.
        assertFalse(
            BmoFaceController.shouldSleep(awake.copy(vadSpeaking = true), 60_000L)
        )
        assertFalse(
            BmoFaceController.shouldSleep(
                awake.copy(music = playing()),
                600_000L,
            )
        )
        assertFalse(
            BmoFaceController.shouldSleep(
                awake.copy(
                    activity = ActivityInfo(activity = BmoActivity.PLAYING_MUSIC),
                ),
                60_000L,
            )
        )
        assertFalse(
            BmoFaceController.shouldSleep(
                awake.copy(pendingConfirmation = ConfirmationInfo(id = "1")),
                60_000L,
            )
        )
        assertFalse(
            BmoFaceController.shouldSleep(awake.copy(faceExpression = "happy"), 60_000L)
        )
    }

    @Test
    fun eventoNovoReiniciaAContagem() {
        val recent = awake.copy(lastActivityAtMs = 40_000L)
        assertFalse(BmoFaceController.shouldSleep(recent, 44_000L))
        assertTrue(BmoFaceController.shouldSleep(recent, 45_000L))
    }

    @Test
    fun vozDetectadaAcordaEReiniciaAContagem() {
        val falando = awake.copy(lastActivityAtMs = 1_000L, vadSpeaking = true)
        assertFalse(BmoFaceController.shouldSleep(falando, 60_000L))

        // Terminada a fala, o sono só volta 5 s depois do último trecho ouvido.
        val terminou = falando.copy(vadSpeaking = false, lastActivityAtMs = 60_000L)
        assertFalse(BmoFaceController.shouldSleep(terminou, 64_999L))
        assertTrue(BmoFaceController.shouldSleep(terminou, 65_000L))
    }

    @Test
    fun dormindoUsaORostoDeOlhosFechados() {
        val visual = BmoFaceController.visualFor(awake, sleeping = true)
        assertEquals(BmoFaceEmotion.SLEEPING, visual.emotion)
        assertEquals(BmoFaceTheme.NONE, visual.theme)
        assertEquals(
            "sleeping",
            BmoFaceController.expressionKeyFor(awake, visual, sleeping = true),
        )
    }

    @Test
    fun dormirNuncaEscondeUmErro() {
        val error = awake.copy(faceState = BmoState.ERROR, lastActivityAtMs = 1L)
        assertFalse(BmoFaceController.shouldSleep(error, 600_000L))
    }

    @Test
    fun repousoComMicrofoneAtivoNaoPareceQueEstaFalando() {
        val standby = awake.copy(faceState = BmoState.LISTENING, vadSpeaking = false)
        val visual = BmoFaceController.visualFor(standby)
        assertEquals(BmoFaceEmotion.NEUTRAL, visual.emotion)
        assertEquals("idle", BmoFaceController.expressionKeyFor(standby, visual))

        val speakingNow = standby.copy(vadSpeaking = true)
        val hearing = BmoFaceController.visualFor(speakingNow)
        assertEquals(BmoFaceEmotion.LISTENING, hearing.emotion)
        assertEquals("listening", BmoFaceController.expressionKeyFor(speakingNow, hearing))
    }

    @Test
    fun bocaSoMexeQuandoOAudioEstaTocando() {
        val muted = awake.copy(faceState = BmoState.SPEAKING, audioPlaying = false)
        val mutedVisual = BmoFaceController.visualFor(muted)
        assertFalse(mutedVisual.talking)
        assertEquals("thinking", BmoFaceController.expressionKeyFor(muted, mutedVisual))

        val loud = awake.copy(faceState = BmoState.SPEAKING, audioPlaying = true)
        val loudVisual = BmoFaceController.visualFor(loud)
        assertTrue(loudVisual.talking)
        assertEquals("speaking", BmoFaceController.expressionKeyFor(loud, loudVisual))
    }

    @Test
    fun emocaoDoTextoAcompanhaAFala() {
        val happyAnswer = awake.copy(
            faceState = BmoState.SPEAKING,
            audioPlaying = true,
            transcript = "conte uma novidade",
            assistantText = "Que bom! Adorei a notícia, fico feliz por você.",
        )
        val visual = BmoFaceController.visualFor(happyAnswer)
        assertEquals(BmoFaceEmotion.HAPPY, visual.emotion)
        assertTrue(visual.talking)
        // Mantém os olhos felizes; a boca animada é desenhada por cima.
        assertEquals("happy", BmoFaceController.expressionKeyFor(happyAnswer, visual))
    }

    @Test
    fun emocaoDoModeloNaoTravaABocaDuranteOAudio() {
        val ui = awake.copy(
            faceState = BmoState.SPEAKING,
            audioPlaying = true,
            faceExpression = "happy",
        )
        val visual = BmoFaceController.visualFor(ui)
        assertEquals(BmoFaceEmotion.HAPPY, visual.emotion)
        assertTrue(visual.talking)
        assertEquals("happy", BmoFaceController.expressionKeyFor(ui, visual))

        val silent = ui.copy(audioPlaying = false)
        val silentVisual = BmoFaceController.visualFor(silent)
        assertFalse(silentVisual.talking)
        assertEquals("happy", BmoFaceController.expressionKeyFor(silent, silentVisual))
    }

    @Test
    fun musicaParadaNaoMantemOFaceDeMusica() {
        val stopped = awake.copy(
            faceState = BmoState.IDLE,
            music = playing().copy(status = "stopped"),
            lastActivityAtMs = 1L,
        )
        assertFalse(stopped.music!!.active)
        assertEquals(BmoFaceTheme.NONE, BmoFaceController.visualFor(stopped).theme)
        assertTrue(BmoFaceController.shouldSleep(stopped, 600_000L))

        val paused = stopped.copy(music = stopped.music!!.copy(status = "paused"))
        assertTrue(paused.music!!.active)
        assertEquals(BmoFaceTheme.MUSIC, BmoFaceController.visualFor(paused).theme)
    }

    @Test
    fun musicaTocandoMantemOFaceDeMusica() {
        val music = awake.copy(
            faceState = BmoState.IDLE,
            music = playing(),
            lastActivityAtMs = 1L,
        )
        val visual = BmoFaceController.visualFor(music)
        assertEquals(BmoFaceTheme.EQUALIZER, visual.theme)
        assertFalse(BmoFaceController.shouldSleep(music, 600_000L))
    }

    @Test
    fun musicaContinuaVisivelEnquantoOOuve() {
        val listening = awake.copy(
            faceState = BmoState.LISTENING,
            vadSpeaking = true,
            transcript = "me conta sobre astronomia",
            music = playing(),
        )
        val visual = BmoFaceController.visualFor(listening)
        assertEquals(BmoFaceTheme.EQUALIZER, visual.theme)
        assertEquals("Song", visual.data.musicTitle)
        assertEquals("Artist", visual.data.musicArtist)
        assertFalse(BmoFaceController.shouldSleep(listening, 600_000L))
    }

    @Test
    fun codigoAceitaDormindo() {
        assertEquals(BmoFaceEmotion.SLEEPING, BmoFaceEmotion.fromCode("sleeping"))
        assertEquals(BmoFaceEmotion.SLEEPING, BmoFaceEmotion.fromCode("dormindo"))
        assertEquals(BmoFaceEmotion.SLEEPY, BmoFaceEmotion.fromCode("sonolento"))
    }
}
