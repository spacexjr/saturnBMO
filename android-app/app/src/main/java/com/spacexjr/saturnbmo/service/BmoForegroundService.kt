package com.spacexjr.saturnbmo.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.spacexjr.saturnbmo.BmoEngine
import com.spacexjr.saturnbmo.ConnectionState
import com.spacexjr.saturnbmo.MainActivity
import com.spacexjr.saturnbmo.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * Mantém o microfone ativo com a tela desligada. O Android exige uma
 * notificação persistente e o tipo "microphone" para esse caso.
 */
class BmoForegroundService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var observeJob: Job? = null
    private var emptySince: Long? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                BmoEngine.get(this).stopListening()
                stopForegroundCompat()
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                startForegroundCompat(buildNotification("Iniciando escuta...", "Conectando ao PC"))
                val engine = BmoEngine.get(this)
                if (!engine.hasMicrophonePermission()) {
                    stopForegroundCompat()
                    stopSelf()
                    return START_NOT_STICKY
                }
                engine.ensureConnected()
                engine.requestListening()
                observeJob?.cancel()
                observeJob = scope.launch {
                    engine.uiState.collectLatest { state ->
                        val text = when {
                            state.listening -> "Microfone ativo"
                            state.connection.name == "CONNECTED" -> "Microfone pausado"
                            else -> "Sem conexão com o PC"
                        }
                        val detail = state.statusDetail.take(100)
                        val manager = getSystemService(NotificationManager::class.java)
                        manager.notify(NOTIFICATION_ID, buildNotification(text, detail))
                        // Encerra o serviço quando o usuário pausa o microfone.
                        // Enquanto ainda está conectando, a notificação permanece.
                        if (state.connection == ConnectionState.CONNECTED &&
                            !state.listening && !state.listeningRequested
                        ) {
                            val since = emptySince ?: System.currentTimeMillis().also { emptySince = it }
                            if (System.currentTimeMillis() - since > 4000) {
                                stopForegroundCompat()
                                stopSelf()
                            }
                        } else {
                            emptySince = null
                        }
                    }
                }
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        observeJob?.cancel()
        // Precisa ser síncrono: depois de super.onDestroy() o escopo é cancelado.
        BmoEngine.get(this).stopListening()
        scope.coroutineContext[Job]?.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Escuta do BMO",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Mostra quando o microfone do BMO está ativo."
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(title: String, text: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, BmoForegroundService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_bmo_notification)
            .setContentTitle("BMO — $title")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openIntent)
            .addAction(R.drawable.ic_bmo_notification, "Parar escuta", stopIntent)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    private fun startForegroundCompat(notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
    }

    companion object {
        const val ACTION_START = "com.spacexjr.saturnbmo.START_ESCUTA"
        const val ACTION_STOP = "com.spacexjr.saturnbmo.STOP_ESCUTA"
        private const val CHANNEL_ID = "bmo_escuta"
        private const val NOTIFICATION_ID = 42

        fun start(context: Context) {
            val intent = Intent(context, BmoForegroundService::class.java)
                .setAction(ACTION_START)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            val intent = Intent(context, BmoForegroundService::class.java)
                .setAction(ACTION_STOP)
            context.startService(intent)
        }
    }
}
