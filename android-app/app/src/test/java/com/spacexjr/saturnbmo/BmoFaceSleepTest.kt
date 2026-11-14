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
    fun dormeDezSegundosDepoisDaUltimaAtividade() {
        assertFalse(BmoFaceController.shouldSleep(awake, 10_900L))
        assertTrue(BmoFaceController.shouldSleep(awake, 11_000L))
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
        // VAD de ruído pode ficar preso em `true`; não pode impedir o sono.
        assertTrue(
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
        assertFalse(BmoFaceController.shouldSleep(recent, 45_000L))
        assertTrue(BmoFaceController.shouldSleep(recent, 50_000L))
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
        assertEquals("thinking", BmoFaceController.expressionKeyFor(muted, mutedVisual))

        val loud = awake.copy(faceState = BmoState.SPEAKING, audioPlaying = true)
        val loudVisual = BmoFaceController.visualFor(loud)
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
        // A boca continua vindo dos frames "speaking".
        assertEquals("speaking", BmoFaceController.expressionKeyFor(happyAnswer, visual))
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
        assertEquals("speaking", BmoFaceController.expressionKeyFor(ui, visual))

        val silent = ui.copy(audioPlaying = false)
        assertEquals("happy", BmoFaceController.expressionKeyFor(silent, BmoFaceController.visualFor(silent)))
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
    fun codigoAceitaDormindo() {
        assertEquals(BmoFaceEmotion.SLEEPING, BmoFaceEmotion.fromCode("sleeping"))
        assertEquals(BmoFaceEmotion.SLEEPING, BmoFaceEmotion.fromCode("dormindo"))
        assertEquals(BmoFaceEmotion.SLEEPY, BmoFaceEmotion.fromCode("sonolento"))
    }
}
