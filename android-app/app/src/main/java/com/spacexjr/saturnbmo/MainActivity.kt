package com.spacexjr.saturnbmo

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.spacexjr.saturnbmo.ui.BmoApp
import com.spacexjr.saturnbmo.ui.BmoTheme

class MainActivity : ComponentActivity() {
    private val engine by lazy { BmoEngine.get(this) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = true
            isAppearanceLightNavigationBars = true
            // Modo quiosque: a cara do BMO ocupa a tela inteira em paisagem.
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }

        applyDebugConnectionExtras()

        setContent {
            BmoTheme {
                BmoApp(engine)
            }
        }
    }

    /**
     * Extras usados apenas em builds de depuração para testes automatizados.
     * Em produção o usuário configura tudo pela tela de Ajustes.
     */
    private fun applyDebugConnectionExtras() {
        if (!BuildConfig.DEBUG) return
        val host = intent.getStringExtra("bmo_host") ?: return
        if (host.isBlank()) return
        val current = engine.currentSettings()
        val port = intent.getIntExtra("bmo_port", current.port)
        val token = intent.getStringExtra("bmo_token") ?: current.token
        val updated = current.copy(
            host = host,
            port = port,
            token = token,
            backgroundListening = intent.getBooleanExtra("bmo_background", current.backgroundListening),
        )
        engine.saveSettings(updated, reconnect = false)
        engine.connect(updated)
    }

    override fun onResume() {
        super.onResume()
        // Reaplica ao voltar do segundo plano ou após recriar a janela.
        applyKeepScreenOn()
    }

    private fun applyKeepScreenOn() {
        if (engine.currentSettings().keepScreenOn) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    override fun onStop() {
        super.onStop()
        if (!engine.currentSettings().backgroundListening) {
            engine.stopListening()
        }
    }

    override fun onDestroy() {
        if (isFinishing && !engine.currentSettings().backgroundListening) {
            engine.disconnect()
        }
        super.onDestroy()
    }
}
