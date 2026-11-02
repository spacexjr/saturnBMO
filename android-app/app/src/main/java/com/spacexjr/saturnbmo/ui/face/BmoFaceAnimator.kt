package com.spacexjr.saturnbmo.ui.face

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.isActive

/**
 * Relógio único das animações procedurais. Atualiza no máximo a ~30 fps e
 * pausa quando o app sai do primeiro plano, economizando bateria no A22.
 *
 * O valor é entregue como [State] e lido dentro do DrawScope para invalidar
 * somente o desenho, sem recompor a árvore inteira a cada quadro.
 */
@Composable
fun rememberBmoResumed(): Boolean {
    val lifecycleOwner = LocalLifecycleOwner.current
    var resumed by remember {
        mutableStateOf(lifecycleOwner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
    }

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> resumed = true
                Lifecycle.Event.ON_PAUSE -> resumed = false
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    return resumed
}

@Composable
fun rememberBmoFaceClock(enabled: Boolean): State<Long> {
    val time = remember { mutableLongStateOf(0L) }
    val resumed = rememberBmoResumed()

    LaunchedEffect(enabled, resumed) {
        if (!enabled || !resumed) return@LaunchedEffect
        var lastFrame = 0L
        var startNanos = 0L
        while (isActive) {
            withFrameNanos { nanos ->
                if (startNanos == 0L) startNanos = nanos
                if (lastFrame == 0L || nanos - lastFrame >= FRAME_INTERVAL_NANOS) {
                    lastFrame = nanos
                    time.longValue = (nanos - startNanos) / 1_000_000L
                }
            }
        }
    }

    return time
}

private const val FRAME_INTERVAL_NANOS = 33_000_000L
