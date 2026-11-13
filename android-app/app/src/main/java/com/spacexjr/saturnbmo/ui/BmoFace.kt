package com.spacexjr.saturnbmo.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import com.spacexjr.saturnbmo.BmoState
import com.spacexjr.saturnbmo.BmoUiState
import com.spacexjr.saturnbmo.ui.face.BmoFaceController
import com.spacexjr.saturnbmo.ui.face.BmoFaceData
import com.spacexjr.saturnbmo.ui.face.BmoFaceRenderer
import com.spacexjr.saturnbmo.ui.face.BmoFaceTheme
import com.spacexjr.saturnbmo.ui.face.BmoFaceVisual
import com.spacexjr.saturnbmo.ui.face.rememberBmoFaceClock
import com.spacexjr.saturnbmo.ui.face.rememberBmoResumed
import kotlinx.coroutines.delay

/** Compatibilidade de nomes de estados legados; as expressões agora são desenhadas em Canvas. */
object FaceController {
    fun framesFor(expression: String): List<String> = when (expression.lowercase()) {
        "listening" -> listOf("listening/listen 01.png", "listening/listen 02.png")
        "thinking", "processing" -> listOf(
            "thinking/thinking 05.png",
            "thinking/thinking 06.png",
        )
        "speaking" -> listOf(
            "speaking/speaking 01.png",
            "speaking/speaking 02.png",
            "speaking/speaking 03.png",
        )
        "error" -> listOf("error/error 01.png")
        "warmup", "connecting", "reconnecting" -> listOf("warmup/warmup 01.png")
        "happy", "excited", "love" ->
            listOf("listening/listen 01.png", "listening/listen 02.png")
        "sad", "confused", "angry" ->
            listOf("thinking/thinking 03.png", "thinking/thinking 04.png")
        "surprised" -> listOf("capturing/capturing 01.png")
        "sleepy", "sleeping" ->
            listOf("sleeping/sleeping 01.png", "sleeping/sleeping 02.png")
        "neutral" -> listOf("idle/idle 01.png")
        "capturing" -> listOf("capturing/capturing 01.png")
        else -> listOf("idle/idle 01.png")
    }

    fun intervalFor(expression: String): Long = when (expression.lowercase()) {
        "thinking", "processing" -> 480
        "speaking" -> 130
        "listening" -> 380
        "sleepy", "sleeping" -> 900
        "happy", "excited", "love" -> 420
        "sad", "confused", "angry" -> 520
        "warmup", "connecting", "reconnecting" -> 500
        else -> 700
    }

    fun expressionFor(state: BmoState): String = when (state) {
        BmoState.DISCONNECTED -> "idle"
        BmoState.CONNECTING -> "warmup"
        BmoState.IDLE -> "idle"
        BmoState.LISTENING -> "listening"
        BmoState.THINKING -> "thinking"
        BmoState.SPEAKING -> "speaking"
        BmoState.ERROR -> "error"
    }
}

@Composable
fun BmoFace(
    ui: BmoUiState,
    modifier: Modifier = Modifier,
    fullBleed: Boolean = false,
) {
    val context = LocalContext.current
    val derived = remember(
        ui.transcript,
        ui.assistantText,
        ui.faceState,
        ui.music,
        ui.activity,
    ) {
        BmoFaceController.visualFor(ui)
    }
    var visual by remember { mutableStateOf(derived) }

    LaunchedEffect(ui.transcript, ui.assistantText, ui.faceState, ui.music, ui.activity) {
        visual = derived
        when (ui.faceState) {
            BmoState.THINKING, BmoState.SPEAKING -> Unit
            BmoState.IDLE -> if (derived.theme != BmoFaceTheme.NONE && !ui.musicActive) {
                delay(THEME_IDLE_LINGER_MS)
                visual = neutralVisual(ui.faceState, derived.activity)
            }
            else -> visual = neutralVisual(ui.faceState, derived.activity)
        }
    }

    val expressionKey = BmoFaceController.expressionKeyFor(ui, visual)
    val resumed = rememberBmoResumed()

    // Arte de nuvens fornecida em assets/faces/clouds.png (fundo transparente).
    val cloudArt: ImageBitmap? = remember {
        runCatching {
            context.assets.open("faces/clouds.png").use { stream ->
                BitmapFactory.decodeStream(stream)?.asImageBitmap()
            }
        }.getOrNull()
    }

    var blink by remember { mutableStateOf(false) }
    LaunchedEffect(expressionKey, resumed) {
        blink = false
        if (!resumed || expressionKey != "idle") return@LaunchedEffect
        val random = kotlin.random.Random(84)
        while (true) {
            delay(random.nextLong(2600L, 6200L))
            blink = true
            delay(150L)
            blink = false
        }
    }

    val clock = rememberBmoFaceClock(
        enabled = visual.theme != BmoFaceTheme.NONE ||
            visual.emotion != com.spacexjr.saturnbmo.ui.face.BmoFaceEmotion.NEUTRAL ||
            visual.activity != com.spacexjr.saturnbmo.BmoActivity.NONE,
    )

    Box(
        modifier = if (fullBleed) {
            modifier.fillMaxSize()
        } else {
            modifier.fillMaxWidth().aspectRatio(800f / 480f)
        },
    ) {
        BmoFaceRenderer(
            face = null,
            cloudArt = cloudArt,
            visual = visual,
            clock = clock,
            micLevel = ui.micLevel,
            blink = blink,
            fullBleed = fullBleed,
            modifier = Modifier.fillMaxSize(),
        )
    }
}

private const val THEME_IDLE_LINGER_MS = 4_000L

private fun neutralVisual(
    state: BmoState,
    activity: com.spacexjr.saturnbmo.BmoActivity = com.spacexjr.saturnbmo.BmoActivity.NONE,
): BmoFaceVisual = BmoFaceVisual(
    data = BmoFaceData(),
    emotion = BmoFaceController.emotionFor(BmoFaceTheme.NONE, state, activity = activity),
    activity = activity,
)
