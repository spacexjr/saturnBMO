package com.spacexjr.saturnbmo.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
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

/**
 * Seleção de frames das expressões em `assets/faces/`. Cada estado/emoção tem
 * sua própria pasta com frames numerados; o renderer continua aplicando as
 * camadas procedurais (Zzz, lágrimas, brilhos, clima) por cima do PNG.
 */
object FaceController {
    fun framesFor(expression: String): List<String> = when (expression.lowercase()) {
        "listening" -> listOf("listening/listening_01.png", "listening/listening_02.png")
        "thinking" -> listOf(
            "thinking/thinking_01.png",
            "thinking/thinking_02.png",
            "thinking/thinking_03.png",
            "thinking/thinking_04.png",
            "thinking/thinking_05.png",
            "thinking/thinking_06.png",
        )
        "processing" -> listOf(
            "thinking/thinking_05.png",
            "thinking/thinking_06.png",
        )
        "speaking" -> listOf(
            "speaking/speaking_01.png",
            "speaking/speaking_02.png",
            "speaking/speaking_03.png",
            "speaking/speaking_04.png",
        )
        "error" -> listOf("error/error_01.png")
        "warmup", "connecting", "reconnecting" -> listOf("warmup/warmup_01.png")
        "happy" -> listOf("happy/happy_01.png", "happy/happy_02.png")
        "excited" -> listOf("excited/excited_01.png", "excited/excited_02.png")
        "love" -> listOf("love/love_01.png", "love/love_02.png")
        "sad" -> listOf("sad/sad_01.png", "sad/sad_02.png")
        "confused" -> listOf("confused/confused_01.png", "confused/confused_02.png")
        "angry" -> listOf("angry/angry_01.png", "angry/angry_02.png")
        "surprised" -> listOf("surprised/surprised_01.png")
        "sleepy" -> listOf("sleepy/sleepy_01.png", "sleepy/sleepy_02.png")
        "sleeping" -> listOf("sleeping/sleeping_01.png", "sleeping/sleeping_02.png")
        "neutral" -> listOf("idle/idle_01.png")
        "capturing" -> listOf("capturing/capturing_01.png")
        else -> listOf("idle/idle_01.png")
    }

    fun intervalFor(expression: String): Long = when (expression.lowercase()) {
        "thinking", "processing" -> 480
        "speaking" -> 130
        "listening" -> 380
        "sleepy", "sleeping" -> 900
        "happy" -> 420
        "excited" -> 300
        "love" -> 520
        "sad" -> 620
        "confused" -> 560
        "angry" -> 380
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
    val paths = remember(expressionKey) { FaceController.framesFor(expressionKey) }
    val frames: List<ImageBitmap> = remember(paths) {
        paths.mapNotNull { path ->
            runCatching {
                context.assets.open("faces/$path").use { stream ->
                    BitmapFactory.decodeStream(stream)?.asImageBitmap()
                }
            }.getOrNull()
        }
    }
    var frameIndex by remember(expressionKey) { mutableIntStateOf(0) }
    val resumed = rememberBmoResumed()
    LaunchedEffect(expressionKey, frames.size, resumed) {
        if (!resumed || frames.size <= 1) return@LaunchedEffect
        while (true) {
            delay(FaceController.intervalFor(expressionKey))
            frameIndex = (frameIndex + 1) % frames.size
        }
    }

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
    val frame = frames.getOrNull(frameIndex % frames.size.coerceAtLeast(1))

    Box(
        modifier = if (fullBleed) {
            modifier.fillMaxSize()
        } else {
            modifier.fillMaxWidth().aspectRatio(800f / 480f)
        },
    ) {
        BmoFaceRenderer(
            face = frame,
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
