package com.spacexjr.saturnbmo.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.spacexjr.saturnbmo.AppSettings
import com.spacexjr.saturnbmo.BmoEngine
import com.spacexjr.saturnbmo.service.BmoForegroundService

private enum class Screen { MAIN, SETTINGS }

@Composable
fun BmoApp(engine: BmoEngine) {
    var screen by remember { mutableStateOf(Screen.MAIN) }
    var settings by remember { mutableStateOf(engine.currentSettings()) }
    var pendingActivate by remember { mutableStateOf(false) }
    var locationPrompted by remember { mutableStateOf(false) }
    val ui by engine.uiState.collectAsStateWithLifecycle()
    val logs by engine.logs.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val view = LocalView.current

    val notificationLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* A notificação é opcional; o serviço continua ativo. */ }

    val requestNotificationPermission: (Context) -> Unit = { ctx ->
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    val micPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            if (settings.backgroundListening) {
                BmoForegroundService.start(context)
                requestNotificationPermission(context)
            }
            val started = engine.startListening()
            if (pendingActivate && started) engine.activateOnce()
        } else {
            Toast.makeText(
                context,
                "Sem a permissão de microfone o BMO não consegue ouvir. Você ainda pode conversar por texto.",
                Toast.LENGTH_LONG,
            ).show()
        }
        pendingActivate = false
    }

    val locationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        if (engine.hasLocationPermission()) {
            engine.refreshLocation()
        } else {
            Toast.makeText(
                context,
                "Sem a permissão de localização o clima não sabe onde você está.",
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    // O GPS é necessário apenas para o clima; pede uma vez após conectar.
    LaunchedEffect(ui.connected) {
        if (ui.connected && !locationPrompted && !engine.hasLocationPermission()) {
            locationPrompted = true
            locationPermissionLauncher.launch(
                arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION,
                )
            )
        }
    }

    val beginListening: (Boolean) -> Unit = { activate ->
        pendingActivate = activate
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            if (settings.backgroundListening) {
                BmoForegroundService.start(context)
                requestNotificationPermission(context)
            }
            val started = engine.startListening()
            if (activate && started) engine.activateOnce()
            pendingActivate = false
        } else {
            micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    DisposableEffect(settings.keepScreenOn) {
        view.keepScreenOn = settings.keepScreenOn
        onDispose { view.keepScreenOn = false }
    }

    BackHandler(enabled = screen == Screen.SETTINGS) { screen = Screen.MAIN }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(BmoGreen)
    ) {
        when (screen) {
            Screen.MAIN -> MainScreen(
                ui = ui,
                settings = settings,
                onSettings = { screen = Screen.SETTINGS },
                onConnect = {
                    if (!settings.isConfigured) {
                        screen = Screen.SETTINGS
                    } else {
                        engine.connect(settings)
                    }
                },
                onToggleListening = {
                    if (ui.listening) engine.stopListening() else beginListening(false)
                },
                onActivate = { beginListening(true) },
                onInterrupt = { engine.interrupt() },
                onSendText = { engine.sendText(it) },
                onConfirmation = { approved -> engine.respondConfirmation(approved) },
                onMusicToggle = { engine.musicTogglePlayback() },
                onMusicNext = { engine.musicNext() },
                onMusicPrevious = { engine.musicPrevious() },
                onMusicStop = { engine.musicStop() },
                onMusicVolume = { engine.musicSetVolume(it) },
                onMusicSearch = { query, callback -> engine.searchMusic(query, callback) },
                onMusicPlay = { engine.musicPlay(it) },
                onMusicQueueAdd = { engine.musicQueueAdd(it) },
            )

            Screen.SETTINGS -> Box(
                modifier = Modifier
                    .fillMaxSize()
                    .windowInsetsPadding(WindowInsets.safeDrawing)
            ) {
                SettingsScreen(
                    engine = engine,
                    settings = settings,
                    ui = ui,
                    logs = logs,
                    onBack = { screen = Screen.MAIN },
                    onSave = { updated: AppSettings ->
                        settings = updated
                        engine.saveSettings(updated)
                        if (updated.backgroundListening) {
                            if (Build.VERSION.SDK_INT >= 33) {
                                requestNotificationPermission(context)
                            }
                            if (ui.listening) BmoForegroundService.start(context)
                        } else {
                            BmoForegroundService.stop(context)
                        }
                        screen = Screen.MAIN
                    },
                    onTestTone = { engine.testTone() },
                    onResetHistory = { engine.resetHistory() },
                )
            }
        }
    }
}
