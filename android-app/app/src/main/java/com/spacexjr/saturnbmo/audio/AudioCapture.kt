package com.spacexjr.saturnbmo.audio

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Process
import android.util.Log
import androidx.core.content.ContextCompat
import kotlin.math.sqrt
import kotlin.concurrent.thread

/**
 * Captura PCM mono 16-bit a 16 kHz, em blocos de 20 ms (640 bytes).
 * O áudio nunca é gravado em arquivo; os blocos são enviados ao PC.
 */
class AudioCapture(
    private val context: Context,
    private val listener: Listener,
) {
    interface Listener {
        fun onLevel(level: Float)
        fun onPcm(bytes: ByteArray)
        fun onError(message: String)
    }

    @Volatile
    private var running = false

    @Volatile
    var muted: Boolean = false

    private var record: AudioRecord? = null
    private var worker: Thread? = null
    private var lastLevelAt = 0L

    val isRunning: Boolean get() = running

    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        if (running) return true
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            listener.onError("Permissão de microfone não concedida.")
            return false
        }
        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuffer <= 0) {
            listener.onError("O microfone não aceitou a configuração de áudio.")
            return false
        }
        val bufferSize = maxOf(minBuffer * 2, FRAME_BYTES * 8)
        val recorder = try {
            AudioRecord.Builder()
                .setAudioSource(MediaRecorder.AudioSource.MIC)
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(SAMPLE_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                        .build()
                )
                .setBufferSizeInBytes(bufferSize)
                .build()
        } catch (exc: Exception) {
            listener.onError("Não foi possível abrir o microfone: ${exc.message}")
            return false
        }
        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            listener.onError("O microfone está ocupado ou indisponível.")
            return false
        }
        record = recorder
        running = true
        try {
            recorder.startRecording()
        } catch (exc: Exception) {
            running = false
            recorder.release()
            record = null
            listener.onError("Falha ao iniciar a captura: ${exc.message}")
            return false
        }
        worker = thread(name = "bmo-audio-capture", isDaemon = true) {
            Process.setThreadPriority(Process.THREAD_PRIORITY_AUDIO)
            val buffer = ByteArray(FRAME_BYTES)
            var failure: String? = null
            try {
                while (running) {
                    val read = try {
                        recorder.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING)
                    } catch (exc: Exception) {
                        if (running) failure = "Erro ao ler o microfone: ${exc.message}"
                        break
                    }
                    if (read > 0) {
                        val now = System.currentTimeMillis()
                        if (now - lastLevelAt > 80) {
                            lastLevelAt = now
                            listener.onLevel(rms(buffer, read))
                        }
                        if (!muted) listener.onPcm(buffer.copyOf(read))
                    } else if (read < 0) {
                        if (running) failure = "O microfone retornou um erro de leitura."
                        break
                    }
                }
            } finally {
                // Uma falha de leitura encerra o worker: o estado precisa refletir
                // isso para que o BmoEngine possa recriar a captura.
                running = false
            }
            failure?.let(listener::onError)
        }
        Log.i(TAG, "Captura iniciada em $SAMPLE_RATE Hz")
        return true
    }

    fun stop() {
        running = false
        val recorder = record
        record = null
        try {
            recorder?.stop()
        } catch (_: Exception) {
        }
        try {
            worker?.join(500)
        } catch (_: InterruptedException) {
        }
        worker = null
        recorder?.release()
        listener.onLevel(0f)
        Log.i(TAG, "Captura parada")
    }

    private fun rms(buffer: ByteArray, length: Int): Float {
        if (length < 2) return 0f
        var sum = 0.0
        var count = 0
        var index = 0
        while (index + 1 < length) {
            val sample = (buffer[index].toInt() and 0xff) or (buffer[index + 1].toInt() shl 8)
            val signed = sample.toShort().toInt().toDouble()
            sum += signed * signed
            count++
            index += 2
        }
        if (count == 0) return 0f
        return (sqrt(sum / count) / 32768.0).toFloat().coerceIn(0f, 1f)
    }

    companion object {
        const val SAMPLE_RATE = 16000
        const val CHANNELS = 1
        const val FRAME_MS = 20
        const val FRAME_BYTES = SAMPLE_RATE * FRAME_MS / 1000 * 2
        private const val TAG = "BmoAudio"
    }
}
