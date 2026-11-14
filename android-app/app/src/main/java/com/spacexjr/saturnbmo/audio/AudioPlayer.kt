package com.spacexjr.saturnbmo.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.util.Log
import kotlinx.coroutines.delay
import kotlin.math.PI
import kotlin.math.sin

/**
 * Reprodução PCM em streaming. O estado "speaking" só termina quando o
 * AudioTrack realmente consumiu os frames enviados pelo PC.
 */
class AudioPlayer {
    private var track: AudioTrack? = null
    private var channels = 1
    private var rate = 22050
    private var totalFrames = 0L
    private var volume = 0.9f

    @Volatile
    private var active = false

    val isActive: Boolean get() = active

    fun start(sampleRate: Int, channelCount: Int, volume: Float): Boolean {
        stop()
        this.rate = sampleRate.coerceIn(8000, 48000)
        this.channels = channelCount.coerceAtLeast(1)
        this.volume = volume.coerceIn(0f, 1f)
        val channelMask = if (this.channels == 2) {
            AudioFormat.CHANNEL_OUT_STEREO
        } else {
            AudioFormat.CHANNEL_OUT_MONO
        }
        val minBuffer = AudioTrack.getMinBufferSize(
            this.rate,
            channelMask,
            AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuffer <= 0) {
            Log.e(TAG, "Configuração de saída não suportada: $rate Hz")
            return false
        }
        val bufferSize = maxOf(minBuffer * 3, this.rate * this.channels * 2 / 2)
        val player = try {
            AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(this.rate)
                        .setChannelMask(channelMask)
                        .build()
                )
                .setTransferMode(AudioTrack.MODE_STREAM)
                .setBufferSizeInBytes(bufferSize)
                .build()
        } catch (exc: Exception) {
            Log.e(TAG, "Falha ao criar AudioTrack: ${exc.message}")
            return false
        }
        if (player.state != AudioTrack.STATE_INITIALIZED) {
            player.release()
            return false
        }
        player.setVolume(this.volume)
        player.play()
        track = player
        totalFrames = 0L
        active = true
        Log.i(TAG, "Reprodução iniciada: $rate Hz, $channels canal(is)")
        return true
    }

    fun write(bytes: ByteArray) {
        if (!active) return
        val player = track ?: return
        var offset = 0
        while (offset < bytes.size) {
            val written = try {
                player.write(bytes, offset, bytes.size - offset, AudioTrack.WRITE_BLOCKING)
            } catch (exc: Exception) {
                Log.w(TAG, "Falha ao escrever áudio: ${exc.message}")
                return
            }
            if (written <= 0) return
            offset += written
            totalFrames += written.toLong() / 2L / channels
        }
    }

    /**
     * Espera até o AudioTrack consumir tudo o que foi escrito.
     *
     * [serverEnded] permite que o chamador só considere a reprodução concluída
     * depois que o backend sinalizou `audio.end`; sem isso, o primeiro bloco
     * poderia esvaziar a fila enquanto o restante do áudio ainda está chegando.
     */
    suspend fun waitForPlayback(
        timeoutMs: Long = 120_000,
        serverEnded: () -> Boolean = { true },
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (active && System.currentTimeMillis() < deadline) {
            val player = track ?: return true
            if (serverEnded() && player.playbackHeadPosition.toLong() >= totalFrames) {
                return true
            }
            delay(30)
        }
        return !active
    }

    fun stop() {
        active = false
        val player = track
        track = null
        if (player != null) {
            try {
                player.pause()
                player.flush()
                player.stop()
            } catch (_: Exception) {
            }
            player.release()
        }
        totalFrames = 0L
    }

    suspend fun playTestTone(volume: Float): Boolean {
        stop()
        val toneRate = 22050
        if (!start(toneRate, 1, volume)) return false
        val samples = ByteArray(toneRate) // 0,5 s
        var index = 0
        while (index < samples.size / 2) {
            val value = (sin(2.0 * PI * 440.0 * index / toneRate) * 9000).toInt()
            samples[index * 2] = (value and 0xff).toByte()
            samples[index * 2 + 1] = ((value shr 8) and 0xff).toByte()
            index++
        }
        write(samples)
        val finished = waitForPlayback(5000)
        stop()
        return finished
    }

    fun updateVolume(value: Float) {
        volume = value.coerceIn(0f, 1f)
        try {
            track?.setVolume(volume)
        } catch (_: Exception) {
        }
    }

    companion object {
        private const val TAG = "BmoPlayer"
    }
}
