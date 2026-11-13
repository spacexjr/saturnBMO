package com.spacexjr.saturnbmo.ui.face

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.spacexjr.saturnbmo.BmoActivity
import com.spacexjr.saturnbmo.ui.BmoGreen
import com.spacexjr.saturnbmo.ui.BmoInk
import com.spacexjr.saturnbmo.ui.BmoWhite
import java.util.Locale
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.random.Random

private const val TAU = (PI * 2.0).toFloat()

private val SunYellow = Color(0xFFFFD93D)
private val SunOrange = Color(0xFFFFA726)
private val RainBlue = Color(0xFF4F86C6)
private val RainDeep = Color(0xFF2E5F96)
private val StormDark = Color(0xFF18262E)
private val Lightning = Color(0xFFFFF176)
private val SnowWhite = Color(0xFFF8FFFF)
private val IceBlue = Color(0xFFB3E5FC)
private val HeatOrange = Color(0xFFFF7043)
private val SweatBlue = Color(0xFF64B5F6)
private val SpaceDark = Color(0xFF090F22)
private val StarWhite = Color(0xFFFFFFFF)
private val NebulaPurple = Color(0xFF8E6BFF)
private val NebulaBlue = Color(0xFF3FA9F5)
private val PlanetGreen = Color(0xFF4CAF50)
private val PlanetBlue = Color(0xFF2196F3)
private val PlanetGray = Color(0xFFB0BEC5)
private val PlanetOrange = Color(0xFFFF8A65)
private val MoonGray = Color(0xFFCFD8DC)
private val CraterGray = Color(0xFF90A4AE)
private val HeartRed = Color(0xFFFF5A7A)
private val AngryRed = Color(0xFFD32F2F)
private val MagicCyan = Color(0xFF00E5FF)

@Composable
fun BmoFaceRenderer(
    face: ImageBitmap?,
    cloudArt: ImageBitmap? = null,
    visual: BmoFaceVisual,
    clock: State<Long>,
    micLevel: Float,
    blink: Boolean,
    fullBleed: Boolean,
    modifier: Modifier = Modifier,
) {
    val shape = if (fullBleed) RoundedCornerShape(0.dp) else RoundedCornerShape(34.dp)
    val particles = remember(visual.theme) { SceneParticles.forTheme(visual.theme) }

    Box(
        modifier = modifier
            .clip(shape)
            .background(BmoGreen),
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val time = clock.value
            val faceRect = fitRect(size, face)

            drawRect(BmoGreen)
            if (face != null) {
                val jitter = when (visual.theme) {
                    BmoFaceTheme.COLD -> sin(time / 90f) * 2.2f
                    BmoFaceTheme.HOT -> sin(time / 120f) * 1.2f
                    else -> 0f
                }
                drawImage(
                    image = face,
                    srcOffset = IntOffset.Zero,
                    srcSize = IntSize(face.width, face.height),
                    dstOffset = IntOffset(
                        (faceRect.left + jitter).roundToInt(),
                        faceRect.top.roundToInt(),
                    ),
                    dstSize = IntSize(
                        faceRect.width.roundToInt(),
                        faceRect.height.roundToInt(),
                    ),
                    filterQuality = FilterQuality.None,
                )
            }

            if (blink) {
                drawEyelids(faceRect, 1f)
            }

            drawTheme(visual.theme, time, faceRect, particles, micLevel, cloudArt)
            drawActivity(visual.activity, time, faceRect, micLevel)
            drawEmotion(visual.emotion, visual.theme, time, faceRect, particles)
        }

        FaceReadouts(visual, Modifier.fillMaxSize())
    }
}

@Composable
private fun FaceReadouts(visual: BmoFaceVisual, modifier: Modifier) {
    val data = visual.data
    val dark = data.theme in setOf(
        BmoFaceTheme.STORM,
        BmoFaceTheme.SPACE,
        BmoFaceTheme.ECLIPSE,
        BmoFaceTheme.MOON,
    )
    val color = if (dark) BmoWhite else BmoInk

    Box(modifier) {
        data.temperatureC?.let { temperature ->
            PixelText(
                text = "$temperature°C",
                fontSize = 26.sp,
                color = color,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(start = 26.dp, top = 22.dp),
            )
        }

        if (data.musicTitle != null || data.musicArtist != null) {
            Column(
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(start = 26.dp, top = 20.dp),
            ) {
                data.musicTitle?.let { title ->
                    PixelText(faceTrim(title, 24), 13.sp, color)
                }
                data.musicArtist?.let { artist ->
                    PixelText(faceTrim(artist, 30), 9.sp, color.copy(alpha = 0.8f))
                }
                if (data.musicTitle != null) {
                    PixelText(
                        text = if (data.musicPlaying) "TOCANDO" else "PAUSADO",
                        fontSize = 8.sp,
                        color = color.copy(alpha = 0.7f),
                    )
                }
            }
        }

        if (visual.activity != BmoActivity.NONE) {
            Row(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(end = 24.dp, top = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Canvas(Modifier.size(16.dp)) {
                    drawOperationIcon(visual.activity, color)
                }
                Spacer(Modifier.width(5.dp))
                PixelText(visual.activity.shortLabel, 8.sp, color)
            }
        }

        when (data.theme) {
            BmoFaceTheme.DISTANCE -> {
                Column(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .padding(horizontal = 54.dp, vertical = 14.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        PixelText(data.distanceFrom ?: "A", 14.sp, color)
                        PixelText(data.distanceTo ?: "B", 14.sp, color)
                    }
                    PixelText(
                        text = data.distanceKm ?: "DISTANCIA",
                        fontSize = 16.sp,
                        color = color,
                    )
                }
            }

            BmoFaceTheme.MATH, BmoFaceTheme.CALCULATING -> {
                Column(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = 18.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    val expression = data.mathExpression
                    val result = data.mathResult
                    if (expression != null) {
                        PixelText(
                            text = if (result != null) "$expression = $result" else expression,
                            fontSize = 18.sp,
                            color = color,
                        )
                    }
                    if (data.theme == BmoFaceTheme.CALCULATING && result == null) {
                        PixelText(
                            text = "CALCULANDO...",
                            fontSize = 11.sp,
                            color = color.copy(alpha = 0.75f),
                        )
                    }
                }
            }

            BmoFaceTheme.SCIENCE -> {
                data.formula?.let { formula ->
                    PixelText(
                        text = formula,
                        fontSize = 16.sp,
                        color = color,
                        modifier = Modifier
                            .align(Alignment.TopStart)
                            .padding(start = 26.dp, top = 22.dp),
                    )
                }
            }

            else -> Unit
        }
    }
}

@Composable
private fun PixelText(
    text: String,
    fontSize: androidx.compose.ui.unit.TextUnit,
    color: Color,
    modifier: Modifier = Modifier,
) {
    val shadow = if (color == BmoWhite) {
        Shadow(Color.Black.copy(alpha = 0.75f), Offset(2f, 2f), 0f)
    } else {
        Shadow(Color.White.copy(alpha = 0.8f), Offset(2f, 2f), 0f)
    }
    Text(
        text = text,
        modifier = modifier,
        color = color,
        fontFamily = BmoPixelFont,
        fontSize = fontSize,
        fontWeight = FontWeight.Normal,
        maxLines = 1,
        style = TextStyle(shadow = shadow),
    )
}

private fun faceTrim(text: String, max: Int): String {
    val clean = text.trim().replace(Regex("""\s+"""), " ")
    if (clean.length <= max) return clean
    return clean.take((max - 3).coerceAtLeast(1)).trimEnd() + "..."
}

/** Ícone 8-bit da operação, desenhado com primitivas (sem novos assets). */
private fun DrawScope.drawOperationIcon(activity: BmoActivity, color: Color) {
    val w = size.width
    val h = size.height
    when (activity) {
        BmoActivity.SEARCHING_WEB, BmoActivity.SEARCHING_APPS,
        BmoActivity.SEARCHING_FILES -> {
            drawCircle(
                color,
                w * 0.28f,
                Offset(w * 0.42f, h * 0.42f),
                style = Stroke(width = w * 0.12f),
            )
            drawLine(
                color,
                Offset(w * 0.62f, h * 0.62f),
                Offset(w * 0.92f, h * 0.92f),
                strokeWidth = w * 0.14f,
                cap = StrokeCap.Square,
            )
        }

        BmoActivity.OPENING_APP, BmoActivity.CLOSING_APP -> {
            val up = activity == BmoActivity.OPENING_APP
            val tipY = if (up) h * 0.12f else h * 0.88f
            val baseY = if (up) h * 0.6f else h * 0.4f
            val wingY = if (up) h * 0.38f else h * 0.62f
            drawLine(color, Offset(w * 0.5f, tipY), Offset(w * 0.5f, baseY), w * 0.16f, StrokeCap.Square)
            drawLine(color, Offset(w * 0.5f, tipY), Offset(w * 0.22f, wingY), w * 0.16f, StrokeCap.Square)
            drawLine(color, Offset(w * 0.5f, tipY), Offset(w * 0.78f, wingY), w * 0.16f, StrokeCap.Square)
            drawRect(
                color,
                Offset(w * 0.2f, if (up) h * 0.8f else h * 0.12f),
                Size(w * 0.6f, h * 0.1f),
            )
        }

        BmoActivity.PLAYING_MUSIC -> {
            drawOval(color, Offset(w * 0.08f, h * 0.62f), Size(w * 0.42f, h * 0.3f))
            drawLine(color, Offset(w * 0.48f, h * 0.75f), Offset(w * 0.48f, h * 0.16f), w * 0.12f, StrokeCap.Square)
            drawLine(color, Offset(w * 0.48f, h * 0.16f), Offset(w * 0.88f, h * 0.28f), w * 0.12f, StrokeCap.Square)
        }

        BmoActivity.READING_WEB, BmoActivity.READING_FILE -> {
            drawRect(color, Offset(w * 0.2f, h * 0.1f), Size(w * 0.6f, h * 0.8f), style = Stroke(w * 0.1f))
            repeat(3) { index ->
                val y = h * (0.3f + index * 0.18f)
                drawLine(color, Offset(w * 0.32f, y), Offset(w * 0.68f, y), w * 0.08f)
            }
        }

        BmoActivity.CREATING_FILE, BmoActivity.EDITING_FILE -> {
            drawLine(color, Offset(w * 0.18f, h * 0.82f), Offset(w * 0.62f, h * 0.24f), w * 0.16f, StrokeCap.Square)
            drawRect(color, Offset(w * 0.58f, h * 0.1f), Size(w * 0.3f, h * 0.3f))
        }

        BmoActivity.CHECKING_SYSTEM -> {
            drawCircle(color, w * 0.32f, Offset(w * 0.5f, h * 0.5f), style = Stroke(w * 0.1f))
            repeat(4) { index ->
                val angle = index * PI.toFloat() / 2f
                drawLine(
                    color,
                    Offset(w * 0.5f + cos(angle) * w * 0.36f, h * 0.5f + sin(angle) * h * 0.36f),
                    Offset(w * 0.5f + cos(angle) * w * 0.48f, h * 0.5f + sin(angle) * h * 0.48f),
                    w * 0.1f,
                )
            }
        }

        BmoActivity.WAITING_CONFIRMATION ->
            drawPixelText("?", w * 0.14f, h * 0.1f, pixel = w * 0.16f, color = color)

        BmoActivity.SUCCESS -> {
            drawLine(color, Offset(w * 0.14f, h * 0.55f), Offset(w * 0.42f, h * 0.82f), w * 0.15f, StrokeCap.Square)
            drawLine(color, Offset(w * 0.42f, h * 0.82f), Offset(w * 0.88f, h * 0.18f), w * 0.15f, StrokeCap.Square)
        }

        BmoActivity.ERROR ->
            drawPixelText("!", w * 0.3f, h * 0.1f, pixel = w * 0.18f, color = color)

        BmoActivity.PROCESSING -> repeat(3) { index ->
            drawRect(
                color.copy(alpha = if (index == 1) 1f else 0.45f),
                Offset(w * (0.1f + index * 0.3f), h * 0.42f),
                Size(w * 0.2f, h * 0.2f),
            )
        }

        else -> drawRect(color, Offset(w * 0.2f, h * 0.2f), Size(w * 0.6f, h * 0.6f))
    }
}

/** Camada procedural que acompanha a operação real em andamento. */
private fun DrawScope.drawActivity(
    activity: BmoActivity,
    time: Long,
    faceRect: Rect,
    micLevel: Float,
) {
    when (activity) {
        BmoActivity.SEARCHING_WEB, BmoActivity.SEARCHING_APPS,
        BmoActivity.SEARCHING_FILES -> {
            val progress = (time / 1200f) % 1f
            val y = faceRect.top + faceRect.height * (0.12f + progress * 0.76f)
            drawLine(
                BmoInk.copy(alpha = 0.2f),
                Offset(faceRect.left + faceRect.width * 0.04f, y),
                Offset(faceRect.right - faceRect.width * 0.04f, y),
                strokeWidth = 3f,
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(12f, 9f)),
            )
        }

        BmoActivity.OPENING_APP, BmoActivity.CLOSING_APP -> {
            val up = activity == BmoActivity.OPENING_APP
            repeat(3) { index ->
                val phase = ((time / 420f + index * 0.25f) % 1f)
                val y = faceRect.top + faceRect.height *
                    (if (up) 0.86f - phase * 0.5f else 0.24f + phase * 0.5f)
                val x = faceRect.left + faceRect.width * (0.12f + index * 0.07f)
                val alpha = 0.28f * (1f - phase)
                val wing = if (up) 10f else -10f
                drawLine(
                    BmoInk.copy(alpha = alpha),
                    Offset(x - 8f, y + wing),
                    Offset(x, y),
                    3f,
                    StrokeCap.Square,
                )
                drawLine(
                    BmoInk.copy(alpha = alpha),
                    Offset(x, y),
                    Offset(x + 8f, y + wing),
                    3f,
                    StrokeCap.Square,
                )
            }
        }

        BmoActivity.READING_WEB, BmoActivity.READING_FILE -> {
            repeat(4) { index ->
                val y = faceRect.top + faceRect.height * (0.2f + index * 0.1f)
                val width = faceRect.width * (0.25f + 0.08f * ((time / 280L + index) % 4L))
                drawLine(
                    BmoInk.copy(alpha = 0.16f),
                    Offset(faceRect.left + faceRect.width * 0.06f, y),
                    Offset(faceRect.left + faceRect.width * 0.06f + width, y),
                    strokeWidth = 3f,
                )
            }
        }

        BmoActivity.CREATING_FILE, BmoActivity.EDITING_FILE -> {
            val phase = ((time / 260f) % 1f)
            listOf(0.08f, 0.92f).forEachIndexed { index, fx ->
                val y = faceRect.top + faceRect.height * (0.2f + phase * 0.6f)
                drawRect(
                    BmoInk.copy(alpha = 0.2f * (1f - phase)),
                    Offset(faceRect.left + faceRect.width * fx, y),
                    Size(10f + index * 3f, 10f + index * 3f),
                )
            }
        }

        BmoActivity.WAITING_CONFIRMATION -> {
            val pulse = 0.5f + 0.5f * sin(time / 260f)
            drawRect(
                BmoInk.copy(alpha = 0.1f + 0.18f * pulse),
                Offset(faceRect.left + faceRect.width * 0.04f, faceRect.top + faceRect.height * 0.06f),
                Size(faceRect.width * 0.92f, faceRect.height * 0.88f),
                style = Stroke(width = 4f),
            )
        }

        BmoActivity.SUCCESS -> {
            val pulse = 0.5f + 0.5f * sin(time / 220f)
            drawPixelText(
                "OK",
                faceRect.left + faceRect.width * 0.5f,
                faceRect.top + faceRect.height * 0.76f,
                pixel = 4f + pulse * 2f,
                color = BmoInk.copy(alpha = 0.32f),
            )
        }

        BmoActivity.CHECKING_SYSTEM -> {
            val angle = time * 0.0022f
            val cx = faceRect.left + faceRect.width * 0.5f
            val cy = faceRect.top + faceRect.height * 0.5f
            val radius = faceRect.width * (0.3f + 0.03f * sin(time / 300f))
            drawCircle(
                BmoInk.copy(alpha = 0.18f),
                radius,
                Offset(cx, cy),
                style = Stroke(width = 3f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f), angle)),
            )
        }

        BmoActivity.PROCESSING -> {
            val active = ((time / 300L) % 4L).toInt()
            repeat(4) { index ->
                drawRect(
                    if (index == active) BmoInk.copy(alpha = 0.4f) else BmoInk.copy(alpha = 0.14f),
                    Offset(faceRect.left + faceRect.width * 0.08f + index * 14f, faceRect.top + faceRect.height * 0.1f),
                    Size(9f, 9f),
                )
            }
        }

        BmoActivity.PLAYING_MUSIC -> if (micLevel <= 0.02f) {
            val pulse = 0.5f + 0.5f * sin(time / 260f)
            drawCircle(
                BmoInk.copy(alpha = 0.12f + 0.1f * pulse),
                faceRect.width * 0.06f,
                Offset(faceRect.left + faceRect.width * 0.8f, faceRect.top + faceRect.height * 0.62f),
                style = Stroke(width = 3f),
            )
        }

        else -> Unit
    }
}

// ----------------------------------------------------------------------------
// Temas
// ----------------------------------------------------------------------------

private fun DrawScope.drawTheme(
    theme: BmoFaceTheme,
    time: Long,
    faceRect: Rect,
    particles: SceneParticles,
    micLevel: Float,
    cloudArt: ImageBitmap?,
) {
    when (theme) {
        BmoFaceTheme.NONE -> Unit
        BmoFaceTheme.SUNNY -> drawSunny(time)
        BmoFaceTheme.CLOUDY -> drawCloudy(time, particles, cloudArt)
        BmoFaceTheme.RAINY -> drawRainy(time, particles)
        BmoFaceTheme.STORM -> drawStorm(time, particles, cloudArt)
        BmoFaceTheme.SNOWY -> drawSnowy(time, particles)
        BmoFaceTheme.HOT -> drawHot(time, particles)
        BmoFaceTheme.COLD -> drawCold(time, particles)
        BmoFaceTheme.EARTH -> drawEarth(time, particles)
        BmoFaceTheme.MOON -> drawMoon(time, particles)
        BmoFaceTheme.SOLAR_SYSTEM -> drawSolarSystem(time, particles)
        BmoFaceTheme.SUN -> drawBigSun(time)
        BmoFaceTheme.SPACE -> drawSpace(time, particles)
        BmoFaceTheme.ECLIPSE -> drawEclipse(time, particles)
        BmoFaceTheme.DISTANCE -> drawDistance(time)
        BmoFaceTheme.MATH -> drawMath(time, particles, fast = false)
        BmoFaceTheme.CALCULATING -> drawMath(time, particles, fast = true)
        BmoFaceTheme.SCIENCE -> drawScience(time, particles)
        BmoFaceTheme.MUSIC -> drawMusic(time, particles, relax = false)
        BmoFaceTheme.LISTENING_MUSIC -> drawMusic(time, particles, relax = true)
        BmoFaceTheme.EQUALIZER -> drawEqualizer(time, particles, micLevel)
    }
}

private fun DrawScope.drawSunny(time: Long) {
    val cx = size.width * 0.855f
    val cy = size.height * 0.30f
    val base = size.minDimension * 0.085f
    val pulse = 1f + 0.1f * sin(time / 330f)

    repeat(12) { i ->
        val angle = i * (TAU / 12f) + time * 0.00035f
        val inner = base * 1.28f
        val outer = base * (1.55f + 0.18f * pulse)
        drawLine(
            color = SunOrange,
            start = Offset(cx + cos(angle) * inner, cy + sin(angle) * inner),
            end = Offset(cx + cos(angle) * outer, cy + sin(angle) * outer),
            strokeWidth = base * 0.18f,
            cap = StrokeCap.Square,
        )
    }
    drawCircle(SunYellow, base * pulse, Offset(cx, cy))
    drawCircle(SunOrange, base * 0.62f * pulse, Offset(cx, cy))
    drawRect(
        color = Color(0xFFFFF59D),
        topLeft = Offset(cx - base * 0.34f, cy - base * 0.5f),
        size = Size(base * 0.3f, base * 0.26f),
    )
}

private fun DrawScope.drawCloudy(
    time: Long,
    particles: SceneParticles,
    cloudArt: ImageBitmap?,
) {
    drawRect(Color(0xFF90A4AE).copy(alpha = 0.05f))
    if (cloudArt != null) {
        // Arte fornecida (assets/faces/clouds.png) em camadas que derivam
        // lentamente pelas bordas, deixando o rosto do BMO livre no centro.
        val scales = floatArrayOf(0.32f, 0.20f, 0.26f, 0.16f)
        val heights = floatArrayOf(-0.22f, -0.10f, 0.62f, 0.76f)
        val speeds = floatArrayOf(0.000012f, 0.000020f, 0.000009f, 0.000024f)
        val alphas = floatArrayOf(0.55f, 0.65f, 0.55f, 0.62f)
        repeat(4) { index ->
            val dstWidth = size.width * scales[index]
            val dstHeight = dstWidth * cloudArt.height / cloudArt.width
            val travel = size.width + dstWidth * 2f
            val x = ((index * size.width * 0.31f + time * speeds[index] * travel) % travel) - dstWidth
            drawImage(
                image = cloudArt,
                srcOffset = IntOffset.Zero,
                srcSize = IntSize(cloudArt.width, cloudArt.height),
                dstOffset = IntOffset(x.roundToInt(), (size.height * heights[index]).roundToInt()),
                dstSize = IntSize(dstWidth.roundToInt(), dstHeight.roundToInt()),
                alpha = alphas[index],
                filterQuality = FilterQuality.Medium,
            )
        }
        return
    }
    particles.primary.forEachIndexed { index, particle ->
        val scale = 0.8f + particle.size * 0.12f
        val cloudWidth = size.width * 0.2f * scale
        val travel = size.width + cloudWidth * 2f
        val x = ((particle.x * travel + time * 0.000035f * (0.7f + particle.speed) * travel) % travel) - cloudWidth
        val y = size.height * (0.34f + (index % 4) * 0.10f)
        drawCloud(x, y, scale, Color(0xFFF7FFFA).copy(alpha = 0.92f))
    }
}

private fun DrawScope.drawCloud(x: Float, y: Float, scale: Float, color: Color) {
    val block = 10f * scale
    drawRect(color, Offset(x, y), Size(block * 7f, block * 2.8f))
    drawRect(color, Offset(x + block * 1.1f, y - block * 1.5f), Size(block * 4.2f, block * 2.2f))
    drawRect(color, Offset(x + block * 3.8f, y - block * 2.2f), Size(block * 3.1f, block * 2.8f))
    drawRect(
        Color(0xFF7C9B8B).copy(alpha = 0.55f),
        Offset(x, y + block * 2.8f),
        Size(block * 7f, block * 0.42f),
    )
}

private fun DrawScope.drawRainy(time: Long, particles: SceneParticles) {
    drawRect(RainBlue.copy(alpha = 0.06f))
    particles.primary.forEach { drop ->
        val speed = size.height * (0.35f + drop.speed * 2.1f)
        val y = (drop.y * size.height + time * 0.001f * speed) % (size.height + 40f) - 20f
        val x = drop.x * size.width
        drawLine(
            color = RainBlue,
            start = Offset(x, y),
            end = Offset(x - 7f, y + 16f + drop.size * 2.5f),
            strokeWidth = 4f,
            cap = StrokeCap.Square,
        )
    }
    drawRainRipples(time)
}

private fun DrawScope.drawRainRipples(time: Long) {
    repeat(6) { index ->
        val progress = ((time / 420f + index * 0.17f) % 1f)
        val cx = size.width * (0.12f + index * 0.155f)
        val cy = size.height * 0.93f
        val radius = size.width * 0.015f + progress * size.width * 0.035f
        drawOval(
            color = RainDeep.copy(alpha = 0.35f * (1f - progress)),
            topLeft = Offset(cx - radius, cy - radius * 0.28f),
            size = Size(radius * 2f, radius * 0.56f),
            style = Stroke(width = 2.5f),
        )
    }
}

private fun DrawScope.drawStorm(
    time: Long,
    particles: SceneParticles,
    cloudArt: ImageBitmap?,
) {
    drawRect(StormDark.copy(alpha = 0.24f))
    particles.primary.forEach { drop ->
        val speed = size.height * (0.5f + drop.speed * 2.6f)
        val y = (drop.y * size.height + time * 0.0012f * speed) % (size.height + 40f) - 20f
        val x = drop.x * size.width
        drawLine(
            color = RainBlue.copy(alpha = 0.8f),
            start = Offset(x, y),
            end = Offset(x - 9f, y + 20f + drop.size * 3f),
            strokeWidth = 5f,
            cap = StrokeCap.Square,
        )
    }
    if (cloudArt != null) {
        // Arte fornecida (assets/faces/clouds.png) apenas no tema de tempestade,
        // escurecida e concentrada no topo para não cobrir o rosto.
        val scales = floatArrayOf(0.40f, 0.26f, 0.30f)
        val heights = floatArrayOf(-0.24f, -0.12f, -0.18f)
        val speeds = floatArrayOf(0.000008f, 0.000012f, 0.000006f)
        val alphas = floatArrayOf(0.92f, 0.82f, 0.88f)
        repeat(3) { index ->
            val dstWidth = size.width * scales[index]
            val dstHeight = dstWidth * cloudArt.height / cloudArt.width
            val travel = size.width + dstWidth * 2f
            val x = ((index * size.width * 0.37f + time * speeds[index] * travel) % travel) - dstWidth
            drawImage(
                image = cloudArt,
                srcOffset = IntOffset.Zero,
                srcSize = IntSize(cloudArt.width, cloudArt.height),
                dstOffset = IntOffset(x.roundToInt(), (size.height * heights[index]).roundToInt()),
                dstSize = IntSize(dstWidth.roundToInt(), dstHeight.roundToInt()),
                alpha = alphas[index],
                colorFilter = ColorFilter.tint(Color(0xFF35434C), BlendMode.Modulate),
                filterQuality = FilterQuality.Medium,
            )
        }
    } else {
        val cloudShift = (time * 0.00004f * size.width) % (size.width * 0.4f)
        repeat(4) { index ->
            drawCloud(
                x = index * size.width * 0.3f - cloudShift,
                y = size.height * (0.06f + index % 2 * 0.08f),
                scale = 1.8f,
                color = Color(0xFF37474F).copy(alpha = 0.88f),
            )
        }
    }
    drawLightning(time)
}

private fun DrawScope.drawLightning(time: Long) {
    val cycle = time % 3200L
    if (cycle > 460L) return
    val strike = (time / 3200L).toInt()
    val baseX = size.width * (0.18f + ((strike * 37) % 60) / 100f)
    val top = size.height * 0.08f
    val path = Path().apply {
        moveTo(baseX, top)
        lineTo(baseX + size.width * 0.05f, top + size.height * 0.08f)
        lineTo(baseX + size.width * 0.012f, top + size.height * 0.09f)
        lineTo(baseX + size.width * 0.072f, top + size.height * 0.2f)
        lineTo(baseX + size.width * 0.03f, top + size.height * 0.19f)
        lineTo(baseX + size.width * 0.09f, top + size.height * 0.32f)
    }
    drawPath(path, Lightning, style = Stroke(width = 7f, cap = StrokeCap.Square))
    drawPath(path, Color.White.copy(alpha = 0.55f), style = Stroke(width = 2.5f, cap = StrokeCap.Square))
    if (cycle < 90L) {
        drawRect(Color.White.copy(alpha = 0.22f))
    }
}

private fun DrawScope.drawSnowy(time: Long, particles: SceneParticles) {
    drawRect(SnowWhite.copy(alpha = 0.06f))
    particles.primary.forEach { flake ->
        val speed = size.height * (0.05f + flake.speed * 0.35f)
        val y = (flake.y * size.height + time * 0.001f * speed) % (size.height + 30f) - 15f
        val sway = sin(time / 620f + flake.phase) * size.width * 0.025f
        val x = flake.x * size.width + sway
        val arm = 2.5f + flake.size * 0.9f
        val color = SnowWhite.copy(alpha = 0.72f + 0.28f * sin(time / 500f + flake.phase))
        drawLine(color, Offset(x - arm, y), Offset(x + arm, y), strokeWidth = 2.5f, cap = StrokeCap.Square)
        drawLine(color, Offset(x, y - arm), Offset(x, y + arm), strokeWidth = 2.5f, cap = StrokeCap.Square)
    }
    repeat(4) { index ->
        drawIceCrystal(
            cx = size.width * (0.08f + index * 0.28f),
            cy = size.height * 0.9f,
            radius = size.minDimension * 0.05f,
            alpha = 0.4f,
        )
    }
}

private fun DrawScope.drawHot(time: Long, particles: SceneParticles) {
    drawRect(HeatOrange.copy(alpha = 0.06f))
    repeat(4) { index ->
        val path = Path()
        val baseY = size.height * (0.16f + index * 0.19f)
        path.moveTo(0f, baseY)
        var x = 0f
        while (x <= size.width) {
            path.lineTo(x, baseY + sin(x / 52f + time / 260f + index) * 7f)
            x += 10f
        }
        drawPath(
            path = path,
            color = if (index % 2 == 0) HeatOrange.copy(alpha = 0.3f) else SunOrange.copy(alpha = 0.22f),
            style = Stroke(width = 3f),
        )
    }
    particles.primary.forEach { drop ->
        val progress = ((time / 900f + drop.phase) % 1f)
        val x = size.width * (0.22f + drop.x * 0.56f) + sin(time / 300f + drop.phase) * 8f
        val y = size.height * 0.42f + progress * size.height * 0.34f
        val radius = 3.5f + drop.size * 0.7f
        drawCircle(SweatBlue, radius, Offset(x, y))
        drawRect(
            SweatBlue,
            Offset(x - radius * 0.45f, y - radius * 2.1f),
            Size(radius * 0.9f, radius * 1.4f),
        )
    }
}

private fun DrawScope.drawCold(time: Long, particles: SceneParticles) {
    drawRect(IceBlue.copy(alpha = 0.07f))
    particles.primary.take(8).forEachIndexed { index, crystal ->
        val x = size.width * (0.06f + (index % 3) * 0.38f)
        val y = size.height * (0.1f + (index / 3) * 0.5f)
        drawIceCrystal(
            cx = x,
            cy = y,
            radius = size.minDimension * (0.035f + crystal.size * 0.004f),
            alpha = 0.55f,
        )
    }
    repeat(3) { index ->
        val y = size.height * (0.3f + index * 0.18f)
        val x = size.width * (0.03f + index * 0.02f)
        drawLine(
            IceBlue.copy(alpha = 0.5f),
            Offset(x, y),
            Offset(x + size.width * 0.09f, y - 5f + sin(time / 110f + index) * 4f),
            strokeWidth = 3f,
            cap = StrokeCap.Square,
        )
    }
}

private fun DrawScope.drawIceCrystal(cx: Float, cy: Float, radius: Float, alpha: Float) {
    val color = SnowWhite.copy(alpha = alpha)
    repeat(3) { index ->
        val angle = index * PI.toFloat() / 3f
        val dx = cos(angle) * radius
        val dy = sin(angle) * radius
        drawLine(color, Offset(cx - dx, cy - dy), Offset(cx + dx, cy + dy), 2.5f)
        drawLine(
            color,
            Offset(cx + dx * 0.45f, cy + dy * 0.45f),
            Offset(cx + dx * 0.75f - dy * 0.25f, cy + dy * 0.75f + dx * 0.25f),
            2f,
        )
        drawLine(
            color,
            Offset(cx + dx * 0.45f, cy + dy * 0.45f),
            Offset(cx + dx * 0.75f + dy * 0.25f, cy + dy * 0.75f - dx * 0.25f),
            2f,
        )
    }
}

private fun DrawScope.drawEarth(time: Long, particles: SceneParticles) {
    drawRect(SpaceDark.copy(alpha = 0.10f))
    drawStars(time, particles, alphaScale = 0.8f)
    val cx = size.width * 0.15f
    val cy = size.height * 0.27f
    val radius = size.minDimension * 0.13f
    val globe = Path().apply {
        addOval(Rect(cx - radius, cy - radius, cx + radius, cy + radius))
    }
    drawCircle(PlanetBlue, radius, Offset(cx, cy))
    clipPath(globe) {
        rotate(time * 0.006f, Offset(cx, cy)) {
            val offset = (time * 0.012f) % (radius * 2f)
            val lands = listOf(
                Triple(-0.58f, -0.42f, 0.44f to 0.3f),
                Triple(-0.3f, 0.05f, 0.34f to 0.42f),
                Triple(0.12f, -0.55f, 0.5f to 0.26f),
                Triple(0.38f, 0.18f, 0.36f to 0.38f),
                Triple(1.24f, -0.4f, 0.44f to 0.3f),
                Triple(1.52f, 0.1f, 0.34f to 0.42f),
            )
            lands.forEach { (lx, ly, dims) ->
                drawRect(
                    PlanetGreen,
                    Offset(cx + lx * radius + offset, cy + ly * radius),
                    Size(dims.first * radius, dims.second * radius),
                )
            }
        }
    }
    drawCircle(SnowWhite.copy(alpha = 0.5f), radius, Offset(cx, cy), style = Stroke(width = 3f))
    drawCircle(SnowWhite.copy(alpha = 0.2f), radius * 1.14f, Offset(cx, cy), style = Stroke(width = 2f))
}

private fun DrawScope.drawMoon(time: Long, particles: SceneParticles) {
    drawRect(SpaceDark.copy(alpha = 0.16f))
    drawStars(time, particles)
    val cx = size.width * 0.84f
    val cy = size.height * 0.2f
    val radius = size.minDimension * 0.105f

    val orbitRadius = radius * 2.3f
    drawCircle(
        StarWhite.copy(alpha = 0.25f),
        orbitRadius,
        Offset(cx, cy),
        style = Stroke(width = 2f),
    )
    val angle = time * 0.0011f
    val ox = cx + cos(angle) * orbitRadius
    val oy = cy + sin(angle) * orbitRadius
    drawCircle(MagicCyan, 5f, Offset(ox, oy))

    drawCircle(MoonGray, radius, Offset(cx, cy))
    drawCircle(CraterGray.copy(alpha = 0.7f), radius * 0.22f, Offset(cx - radius * 0.35f, cy - radius * 0.28f))
    drawCircle(CraterGray.copy(alpha = 0.55f), radius * 0.16f, Offset(cx + radius * 0.32f, cy - radius * 0.04f))
    drawCircle(CraterGray.copy(alpha = 0.5f), radius * 0.12f, Offset(cx - radius * 0.05f, cy + radius * 0.4f))
    drawCircle(StarWhite.copy(alpha = 0.6f), radius, Offset(cx, cy), style = Stroke(width = 3f))
}

private fun DrawScope.drawSolarSystem(time: Long, particles: SceneParticles) {
    drawRect(SpaceDark.copy(alpha = 0.32f))
    drawStars(time, particles, alphaScale = 0.9f)
    val cx = size.width * 0.16f
    val cy = size.height * 0.34f
    val sunRadius = size.minDimension * 0.035f
    val maxRadius = size.minDimension * 0.22f

    val planets = listOf(
        Triple(0.42f, 0.0013f, PlanetGray),
        Triple(0.62f, 0.0009f, PlanetOrange),
        Triple(0.82f, 0.0006f, PlanetBlue),
        Triple(1.0f, 0.0004f, PlanetGreen),
    )
    planets.forEachIndexed { index, (scale, speed, color) ->
        val orbit = maxRadius * scale
        drawCircle(
            StarWhite.copy(alpha = 0.18f),
            orbit,
            Offset(cx, cy),
            style = Stroke(width = 1.5f),
        )
        val angle = time * speed + index * 1.7f
        val px = cx + cos(angle) * orbit
        val py = cy + sin(angle) * orbit
        drawCircle(color, sunRadius * (0.38f + index * 0.08f), Offset(px, py))
    }
    drawCircle(SunYellow, sunRadius, Offset(cx, cy))
    drawCircle(SunOrange, sunRadius * 0.62f, Offset(cx, cy))
}

private fun DrawScope.drawBigSun(time: Long) {
    val cx = size.width * 0.85f
    val cy = size.height * 0.30f
    val base = size.minDimension * 0.11f
    val pulse = 1f + 0.12f * sin(time / 280f)
    repeat(16) { i ->
        val angle = i * (TAU / 16f) + time * 0.0005f
        val inner = base * 1.2f
        val outer = base * (1.55f + 0.25f * pulse)
        drawLine(
            SunOrange,
            Offset(cx + cos(angle) * inner, cy + sin(angle) * inner),
            Offset(cx + cos(angle) * outer, cy + sin(angle) * outer),
            strokeWidth = base * 0.13f,
            cap = StrokeCap.Square,
        )
    }
    drawCircle(SunYellow, base * pulse, Offset(cx, cy))
    drawCircle(SunOrange, base * 0.7f * pulse, Offset(cx, cy))
    drawCircle(Color(0xFFFFF59D), base * 0.34f * pulse, Offset(cx, cy))
}

private fun DrawScope.drawSpace(time: Long, particles: SceneParticles) {
    drawRect(SpaceDark.copy(alpha = 0.46f))
    val nebulaAlpha = 0.10f + 0.03f * sin(time / 1800f)
    drawCircle(
        NebulaPurple.copy(alpha = nebulaAlpha),
        size.minDimension * 0.26f,
        Offset(size.width * 0.76f, size.height * 0.7f),
    )
    drawCircle(
        NebulaBlue.copy(alpha = nebulaAlpha * 0.9f),
        size.minDimension * 0.2f,
        Offset(size.width * 0.2f, size.height * 0.74f),
    )
    particles.secondary.forEach { dust ->
        val x = dust.x * size.width + sin(time / 1200f + dust.phase) * 12f
        val y = dust.y * size.height + cos(time / 1500f + dust.phase) * 10f
        drawCircle(
            if (dust.phase > PI.toFloat()) MagicCyan.copy(alpha = 0.25f)
            else NebulaPurple.copy(alpha = 0.22f),
            dust.size * 0.9f,
            Offset(x, y),
        )
    }
    drawStars(time, particles, alphaScale = 1f)
    repeat(8) { index ->
        val angle = time * 0.00035f + index
        val x = size.width * 0.5f + cos(angle) * size.width * 0.38f
        val y = size.height * 0.52f + sin(angle) * size.height * 0.24f
        drawRect(
            StarWhite.copy(alpha = 0.35f),
            Offset(x.roundToInt().toFloat(), y.roundToInt().toFloat()),
            Size(3f, 3f),
        )
    }
}

private fun DrawScope.drawEclipse(time: Long, particles: SceneParticles) {
    drawRect(SpaceDark.copy(alpha = 0.34f))
    drawStars(time, particles)
    val cx = size.width * 0.82f
    val cy = size.height * 0.2f
    val radius = size.minDimension * 0.13f

    drawCircle(SunYellow.copy(alpha = 0.24f), radius * 1.28f, Offset(cx, cy))
    drawCircle(SunYellow, radius, Offset(cx, cy))
    drawCircle(SunOrange, radius * 0.72f, Offset(cx, cy))

    val cycle = (time % 9000L) / 9000f
    val moonX = cx - radius * 2.5f + cycle * radius * 5f
    drawCircle(StormDark, radius * 0.98f, Offset(moonX, cy))
    drawCircle(StarWhite.copy(alpha = 0.4f), radius * 0.98f, Offset(moonX, cy), style = Stroke(width = 2f))
}

private fun DrawScope.drawDistance(time: Long) {
    val y = size.height * 0.76f
    val left = Offset(size.width * 0.16f, y)
    val right = Offset(size.width * 0.84f, y)
    val pathEffect = PathEffect.dashPathEffect(floatArrayOf(14f, 10f), phase = (time / 26f) % 24f)
    drawLine(
        BmoInk.copy(alpha = 0.75f),
        start = left,
        end = right,
        strokeWidth = 4f,
        pathEffect = pathEffect,
    )
    drawCircle(BmoInk, 8f, left)
    drawCircle(BmoInk, 8f, right)
    drawCircle(BmoInk.copy(alpha = 0.3f), 15f, left, style = Stroke(width = 3f))
    drawCircle(BmoInk.copy(alpha = 0.3f), 15f, right, style = Stroke(width = 3f))
}

private fun DrawScope.drawMath(time: Long, particles: SceneParticles, fast: Boolean) {
    val symbols = particles.symbols.ifEmpty {
        listOf("+", "-", "=", "X", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0")
    }
    particles.primary.forEachIndexed { index, particle ->
        val symbol = symbols[index % symbols.size]
        val pixel = 3.5f + particle.size * 0.35f
        val speed = if (fast) 0.22f else 0.045f
        val y = if (fast) {
            size.height * (0.3f + (index % 5) * 0.08f) +
                sin(time / 240f + index) * 10f
        } else {
            (particle.y * size.height - time * 0.001f * speed * size.height) % (size.height + 80f)
        }
        val x = (particle.x * size.width + time * 0.001f * speed * (if (fast) 3f else 1f) * size.width) %
            (size.width + 80f) - 40f
        val alpha = if (fast) 0.55f else 0.32f
        drawPixelText(
            text = symbol,
            x = x,
            y = y,
            pixel = pixel,
            color = BmoInk.copy(alpha = alpha),
        )
    }
}

private fun DrawScope.drawScience(time: Long, particles: SceneParticles) {
    val formulas = particles.symbols.ifEmpty {
        listOf("E=MC2", "H2O", "F=MA", "DNA", "PV=NRT")
    }
    particles.primary.forEachIndexed { index, particle ->
        val formula = formulas[index % formulas.size]
        val pixel = 2.6f + particle.size * 0.18f
        val x = (particle.x * size.width +
            sin(time / 1500f + particle.phase) * 30f) % size.width
        val y = size.height * (0.14f + particle.y * 0.7f) +
            cos(time / 1800f + particle.phase) * 18f
        drawPixelText(
            text = formula,
            x = x,
            y = y,
            pixel = pixel,
            color = BmoInk.copy(alpha = 0.2f),
        )
    }
    drawAtom(size.width * 0.84f, size.height * 0.24f, size.minDimension * 0.09f, time)
}

private fun DrawScope.drawAtom(cx: Float, cy: Float, radius: Float, time: Long) {
    drawCircle(MagicCyan, radius * 0.22f, Offset(cx, cy))
    repeat(2) { index ->
        rotate(if (index == 0) 0f else 60f, Offset(cx, cy)) {
            drawOval(
                BmoInk.copy(alpha = 0.4f),
                topLeft = Offset(cx - radius, cy - radius * 0.38f),
                size = Size(radius * 2f, radius * 0.76f),
                style = Stroke(width = 2.5f),
            )
        }
    }
    val angle = time * 0.0016f
    drawCircle(
        MagicCyan,
        4.5f,
        Offset(cx + cos(angle) * radius, cy + sin(angle) * radius * 0.38f),
    )
}

private fun DrawScope.drawMusic(time: Long, particles: SceneParticles, relax: Boolean) {
    val speed = if (relax) 0.55f else 1f
    particles.primary.forEachIndexed { index, note ->
        val y = size.height - ((note.y * size.height + time * 0.001f * speed * size.height *
            (0.22f + note.speed)) % (size.height + 60f))
        val x = size.width * (0.08f + note.x * 0.84f) +
            sin(time / 700f + note.phase) * size.width * 0.045f
        drawNote(
            cx = x,
            cy = y,
            scale = 7f + note.size * 0.8f,
            color = BmoInk.copy(alpha = if (index % 3 == 0) 0.7f else 0.45f),
        )
    }
}

private fun DrawScope.drawNote(cx: Float, cy: Float, scale: Float, color: Color) {
    val head = scale * 0.62f
    drawOval(
        color,
        topLeft = Offset(cx - head, cy - head * 0.42f),
        size = Size(head * 1.25f, head * 0.82f),
    )
    drawLine(
        color,
        Offset(cx + head * 0.48f, cy),
        Offset(cx + head * 0.48f, cy - scale * 2.2f),
        strokeWidth = scale * 0.24f,
        cap = StrokeCap.Square,
    )
    drawLine(
        color,
        Offset(cx + head * 0.48f, cy - scale * 2.2f),
        Offset(cx + head * 1.25f, cy - scale * 1.7f),
        strokeWidth = scale * 0.24f,
        cap = StrokeCap.Square,
    )
    drawLine(
        color,
        Offset(cx + head * 1.25f, cy - scale * 1.7f),
        Offset(cx + head * 1.25f, cy - scale * 1.1f),
        strokeWidth = scale * 0.24f,
        cap = StrokeCap.Square,
    )
}

private fun DrawScope.drawEqualizer(time: Long, particles: SceneParticles, micLevel: Float) {
    val bars = particles.primary.ifEmpty { List(24) { SceneParticles.particle(0, it) } }
    val baseline = size.height * 0.97f
    val maxHeight = size.height * 0.24f
    val energy = if (micLevel > 0.02f) micLevel.coerceIn(0f, 1f)
    else 0.3f + 0.18f * ((sin(time / 300f) + 1f) / 2f)
    val barWidth = size.width / (bars.size * 1.7f)
    val gap = barWidth * 0.7f
    bars.forEachIndexed { index, bar ->
        val idle = 0.18f + 0.12f * ((sin(time / 260f + index * 0.55f) + 1f) / 2f)
        val reactive = 0.2f + energy * (0.55f + 0.45f * ((sin(time / 190f + index * 0.8f) + 1f) / 2f))
        val height = maxHeight * (idle * 0.4f + reactive * 0.6f) * (0.7f + bar.size * 0.05f)
        val x = size.width * 0.06f + index * (barWidth + gap)
        val color = when {
            height > maxHeight * 0.62f -> AngryRed
            height > maxHeight * 0.4f -> SunOrange
            else -> BmoInk
        }
        drawRect(
            color,
            Offset(x, baseline - height),
            Size(barWidth, height),
        )
        drawRect(
            color.copy(alpha = 0.35f),
            Offset(x, baseline + 3f),
            Size(barWidth, 3f),
        )
    }
}

private fun DrawScope.drawStars(time: Long, particles: SceneParticles, alphaScale: Float = 1f) {
    particles.primary.forEach { star ->
        val x = star.x * size.width
        val y = star.y * size.height
        val twinkle = 0.35f + 0.65f * ((sin(time / 520f + star.phase) + 1f) / 2f)
        val radius = 1.5f + star.size * 0.35f
        drawCircle(StarWhite.copy(alpha = twinkle * alphaScale), radius, Offset(x, y))
    }
}

// ----------------------------------------------------------------------------
// Emoções
// ----------------------------------------------------------------------------

private fun DrawScope.drawEmotion(
    emotion: BmoFaceEmotion,
    theme: BmoFaceTheme,
    time: Long,
    faceRect: Rect,
    particles: SceneParticles,
) {
    when (emotion) {
        BmoFaceEmotion.LOVE -> drawHearts(time, particles)
        BmoFaceEmotion.ANGRY -> drawAngry(time, theme)
        BmoFaceEmotion.SLEEPY -> drawSleepy(time)
        BmoFaceEmotion.SAD -> if (theme != BmoFaceTheme.RAINY && theme != BmoFaceTheme.STORM) {
            drawTears(time, faceRect)
        }
        BmoFaceEmotion.SURPRISED -> drawSurprise(time)
        BmoFaceEmotion.EXCITED -> drawSparkles(time, particles)
        BmoFaceEmotion.HAPPY -> drawSparkles(time, particles)
        BmoFaceEmotion.CONFUSED -> drawQuestions(time)
        BmoFaceEmotion.PROCESSING -> drawProcessing(time)
        BmoFaceEmotion.ERROR, BmoFaceEmotion.SCARED -> drawGlitch(time)
        BmoFaceEmotion.LISTENING -> drawListeningWaves(time, faceRect)
        else -> Unit
    }
}

private fun DrawScope.drawHearts(time: Long, particles: SceneParticles) {
    val hearts = particles.primary.ifEmpty { List(9) { SceneParticles.particle(701, it) } }
    hearts.take(9).forEachIndexed { index, particle ->
        val progress = ((time / 2600f + particle.phase) % 1f)
        val y = size.height * (0.95f - progress * 0.82f)
        val x = size.width * (0.12f + particle.x * 0.76f) +
            sin(time / 600f + particle.phase) * 22f
        drawPixelHeart(
            cx = x,
            cy = y,
            pixel = 3f + particle.size * 0.35f,
            color = HeartRed.copy(alpha = 0.35f + 0.55f * (1f - progress)),
        )
    }
}

private fun DrawScope.drawPixelHeart(cx: Float, cy: Float, pixel: Float, color: Color) {
    val pattern = arrayOf(
        "0110110",
        "1111111",
        "1111111",
        "0111110",
        "0011100",
        "0001000",
    )
    pattern.forEachIndexed { row, line ->
        line.forEachIndexed { col, value ->
            if (value == '1') {
                drawRect(
                    color,
                    Offset(cx + (col - 3) * pixel, cy + (row - 3) * pixel),
                    Size(pixel, pixel),
                )
            }
        }
    }
}

private fun DrawScope.drawAngry(time: Long, theme: BmoFaceTheme) {
    drawRect(AngryRed.copy(alpha = 0.07f))
    if (theme != BmoFaceTheme.STORM) {
        drawRect(AngryRed.copy(alpha = 0.06f))
    }
    val pulse = 0.5f + 0.5f * sin(time / 240f)
    drawPixelText(
        "!",
        size.width * 0.08f,
        size.height * 0.2f,
        pixel = 5f + pulse * 3f,
        color = AngryRed.copy(alpha = 0.75f),
    )
    drawPixelText(
        "!",
        size.width * 0.88f,
        size.height * 0.26f,
        pixel = 5f + (1f - pulse) * 3f,
        color = AngryRed.copy(alpha = 0.75f),
    )
}

private fun DrawScope.drawSleepy(time: Long) {
    repeat(3) { index ->
        val progress = ((time / 2800f + index * 0.33f) % 1f)
        val y = size.height * (0.3f - progress * 0.22f)
        val x = size.width * (0.78f + index * 0.045f)
        drawPixelText(
            "Z",
            x,
            y,
            pixel = 3f + index * 1.2f,
            color = BmoInk.copy(alpha = 0.55f * (1f - progress)),
        )
    }
}

private fun DrawScope.drawTears(time: Long, faceRect: Rect) {
    listOf(0.272f, 0.727f).forEachIndexed { index, nx ->
        val progress = ((time / 1500f + index * 0.5f) % 1f)
        val x = faceRect.left + faceRect.width * nx
        val y = faceRect.top + faceRect.height * (0.44f + progress * 0.2f)
        drawCircle(SweatBlue.copy(alpha = 0.75f), 5f, Offset(x, y))
        drawRect(
            SweatBlue.copy(alpha = 0.75f),
            Offset(x - 2f, y - 10f),
            Size(4f, 7f),
        )
    }
}

private fun DrawScope.drawSurprise(time: Long) {
    val pulse = 0.5f + 0.5f * sin(time / 260f)
    drawPixelText(
        "!",
        size.width * 0.1f,
        size.height * 0.26f,
        pixel = 6f + pulse * 2f,
        color = BmoInk.copy(alpha = 0.7f),
    )
    drawPixelText(
        "?",
        size.width * 0.86f,
        size.height * 0.3f,
        pixel = 5f + (1f - pulse) * 2f,
        color = BmoInk.copy(alpha = 0.7f),
    )
}

private fun DrawScope.drawSparkles(time: Long, particles: SceneParticles) {
    val sparkles = particles.primary.ifEmpty { List(10) { SceneParticles.particle(702, it) } }
    sparkles.take(10).forEachIndexed { index, particle ->
        val progress = ((time / 1800f + particle.phase) % 1f)
        val x = size.width * (0.08f + particle.x * 0.84f)
        val y = size.height * (0.16f + particle.y * 0.5f) +
            sin(time / 400f + index) * 8f
        val alpha = (0.35f + 0.5f * sin(time / 300f + particle.phase)) * (1f - progress)
        val arm = 4f + particle.size * 0.7f
        val color = if (index % 2 == 0) SunYellow.copy(alpha = alpha) else MagicCyan.copy(alpha = alpha)
        drawLine(color, Offset(x - arm, y), Offset(x + arm, y), 2.5f)
        drawLine(color, Offset(x, y - arm), Offset(x, y + arm), 2.5f)
    }
}

private fun DrawScope.drawQuestions(time: Long) {
    repeat(3) { index ->
        val progress = ((time / 2200f + index * 0.33f) % 1f)
        val x = size.width * (0.12f + index * 0.37f) +
            sin(time / 600f + index) * 12f
        val y = size.height * (0.18f + progress * 0.24f)
        drawPixelText(
            "?",
            x,
            y,
            pixel = 4f + index,
            color = BmoInk.copy(alpha = 0.55f * (1f - progress)),
        )
    }
}

private fun DrawScope.drawProcessing(time: Long) {
    val baseX = size.width * 0.08f
    val baseY = size.height * 0.2f
    repeat(4) { index ->
        val active = ((time / 240L) % 4L).toInt() == index
        drawRect(
            if (active) BmoInk else BmoInk.copy(alpha = 0.25f),
            Offset(baseX + index * 18f, baseY),
            Size(12f, 12f),
        )
    }
}

private fun DrawScope.drawGlitch(time: Long) {
    repeat(7) { index ->
        val y = ((time / 55L + index * 61L) % size.height.toLong()).toFloat()
        val width = size.width * (0.15f + ((index * 37) % 50) / 100f)
        val x = ((time / 40L + index * 97L) % size.width.toLong()).toFloat()
        drawRect(
            if (index % 2 == 0) MagicCyan.copy(alpha = 0.16f) else AngryRed.copy(alpha = 0.12f),
            Offset(x, y),
            Size(width, 3f),
        )
    }
}

private fun DrawScope.drawListeningWaves(time: Long, faceRect: Rect) {
    val pulse = 0.5f + 0.5f * sin(time / 500f)
    listOf(-1f, 1f).forEach { side ->
        val cx = if (side < 0) faceRect.left + faceRect.width * 0.07f
        else faceRect.left + faceRect.width * 0.93f
        repeat(3) { index ->
            val radius = faceRect.width * (0.02f + index * 0.02f) * (0.8f + pulse * 0.4f)
            drawCircle(
                BmoInk.copy(alpha = 0.18f - index * 0.04f),
                radius,
                Offset(cx, faceRect.top + faceRect.height * 0.4f),
                style = Stroke(width = 3f),
            )
        }
    }
}

private fun DrawScope.drawEyelids(faceRect: Rect, closed: Float) {
    listOf(0.272f, 0.727f).forEach { nx ->
        val cx = faceRect.left + faceRect.width * nx
        val cy = faceRect.top + faceRect.height * 0.4f
        val width = faceRect.width * 0.085f
        val height = faceRect.height * 0.075f
        val lidY = cy - height / 2f + height * closed
        drawRect(
            BmoGreen,
            Offset(cx - width / 2f, cy - height / 2f),
            Size(width, height * closed),
        )
        drawLine(
            BmoInk,
            Offset(cx - width / 2f, lidY),
            Offset(cx + width / 2f, lidY),
            strokeWidth = 4f,
            cap = StrokeCap.Round,
        )
    }
}

// ----------------------------------------------------------------------------
// Texto pixelado para elementos decorativos (sem depender de fonte externa)
// ----------------------------------------------------------------------------

private val PIXEL_GLYPHS: Map<Char, Array<String>> = mapOf(
    'A' to arrayOf("010", "101", "111", "101", "101"),
    'B' to arrayOf("110", "101", "110", "101", "110"),
    'C' to arrayOf("011", "100", "100", "100", "011"),
    'D' to arrayOf("110", "101", "101", "101", "110"),
    'E' to arrayOf("111", "100", "110", "100", "111"),
    'F' to arrayOf("111", "100", "110", "100", "100"),
    'G' to arrayOf("011", "100", "101", "101", "011"),
    'H' to arrayOf("101", "101", "111", "101", "101"),
    'I' to arrayOf("111", "010", "010", "010", "111"),
    'J' to arrayOf("001", "001", "001", "101", "010"),
    'K' to arrayOf("101", "101", "110", "101", "101"),
    'L' to arrayOf("100", "100", "100", "100", "111"),
    'M' to arrayOf("101", "111", "111", "101", "101"),
    'N' to arrayOf("101", "111", "111", "111", "101"),
    'O' to arrayOf("010", "101", "101", "101", "010"),
    'P' to arrayOf("110", "101", "110", "100", "100"),
    'Q' to arrayOf("010", "101", "101", "110", "011"),
    'R' to arrayOf("110", "101", "110", "101", "101"),
    'S' to arrayOf("011", "100", "010", "001", "110"),
    'T' to arrayOf("111", "010", "010", "010", "010"),
    'U' to arrayOf("101", "101", "101", "101", "111"),
    'V' to arrayOf("101", "101", "101", "101", "010"),
    'W' to arrayOf("101", "101", "111", "111", "101"),
    'X' to arrayOf("101", "101", "010", "101", "101"),
    'Y' to arrayOf("101", "101", "010", "010", "010"),
    'Z' to arrayOf("111", "001", "010", "100", "111"),
    '0' to arrayOf("111", "101", "101", "101", "111"),
    '1' to arrayOf("010", "110", "010", "010", "111"),
    '2' to arrayOf("111", "001", "111", "100", "111"),
    '3' to arrayOf("111", "001", "111", "001", "111"),
    '4' to arrayOf("101", "101", "111", "001", "001"),
    '5' to arrayOf("111", "100", "111", "001", "111"),
    '6' to arrayOf("111", "100", "111", "101", "111"),
    '7' to arrayOf("111", "001", "010", "010", "010"),
    '8' to arrayOf("111", "101", "111", "101", "111"),
    '9' to arrayOf("111", "101", "111", "001", "111"),
    '+' to arrayOf("000", "010", "111", "010", "000"),
    '-' to arrayOf("000", "000", "111", "000", "000"),
    '=' to arrayOf("000", "111", "000", "111", "000"),
    '.' to arrayOf("000", "000", "000", "000", "010"),
    ',' to arrayOf("000", "000", "000", "010", "100"),
    '/' to arrayOf("001", "001", "010", "100", "100"),
    '?' to arrayOf("111", "001", "010", "000", "010"),
    '!' to arrayOf("010", "010", "010", "000", "010"),
    '%' to arrayOf("101", "001", "010", "100", "101"),
    ' ' to arrayOf("000", "000", "000", "000", "000"),
)

private fun DrawScope.drawPixelText(
    text: String,
    x: Float,
    y: Float,
    pixel: Float,
    color: Color,
    spacing: Float = pixel,
) {
    var cursor = x
    text.uppercase(Locale.ROOT).forEach { char ->
        val glyph = PIXEL_GLYPHS[char]
        if (glyph != null) {
            glyph.forEachIndexed { row, line ->
                line.forEachIndexed { col, value ->
                    if (value == '1') {
                        drawRect(
                            color,
                            Offset(cursor + col * pixel, y + row * pixel),
                            Size(pixel, pixel),
                        )
                    }
                }
            }
        }
        cursor += 3f * pixel + spacing
    }
}

// ----------------------------------------------------------------------------
// Partículas
// ----------------------------------------------------------------------------

private data class Particle(
    val x: Float,
    val y: Float,
    val speed: Float,
    val size: Float,
    val phase: Float,
)

private class SceneParticles(
    val primary: List<Particle> = emptyList(),
    val secondary: List<Particle> = emptyList(),
    val symbols: List<String> = emptyList(),
) {
    companion object {
        fun particle(seed: Int, index: Int): Particle {
            val random = Random(seed * 131 + index)
            return Particle(
                x = random.nextFloat(),
                y = random.nextFloat(),
                speed = random.nextFloat(),
                size = random.nextFloat(),
                phase = random.nextFloat() * TAU,
            )
        }

        private fun list(seed: Int, count: Int): List<Particle> =
            List(count) { particle(seed, it) }

        fun forTheme(theme: BmoFaceTheme): SceneParticles {
            val seed = theme.ordinal * 977 + 17
            return when (theme) {
                BmoFaceTheme.RAINY -> SceneParticles(primary = list(seed, 72))
                BmoFaceTheme.STORM -> SceneParticles(primary = list(seed, 96))
                BmoFaceTheme.SNOWY -> SceneParticles(primary = list(seed, 58))
                BmoFaceTheme.CLOUDY -> SceneParticles(primary = list(seed, 5))
                BmoFaceTheme.HOT -> SceneParticles(primary = list(seed, 7))
                BmoFaceTheme.COLD -> SceneParticles(primary = list(seed, 9))
                BmoFaceTheme.SPACE -> SceneParticles(
                    primary = list(seed, 96),
                    secondary = list(seed + 3, 26),
                )
                BmoFaceTheme.MOON -> SceneParticles(primary = list(seed, 52))
                BmoFaceTheme.ECLIPSE -> SceneParticles(primary = list(seed, 52))
                BmoFaceTheme.EARTH -> SceneParticles(primary = list(seed, 34))
                BmoFaceTheme.SOLAR_SYSTEM -> SceneParticles(primary = list(seed, 34))
                BmoFaceTheme.MATH, BmoFaceTheme.CALCULATING -> SceneParticles(
                    primary = list(seed, 18),
                    symbols = listOf("+", "-", "=", "X", "/", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"),
                )
                BmoFaceTheme.SCIENCE -> SceneParticles(
                    primary = list(seed, 13),
                    symbols = listOf("E=MC2", "H2O", "F=MA", "DNA", "PV=NRT", "CO2"),
                )
                BmoFaceTheme.MUSIC, BmoFaceTheme.LISTENING_MUSIC ->
                    SceneParticles(primary = list(seed, 12))
                BmoFaceTheme.EQUALIZER -> SceneParticles(primary = list(seed, 22))
                else -> SceneParticles()
            }
        }
    }
}

private fun fitRect(size: Size, face: ImageBitmap?): Rect {
    if (face == null) return Rect(0f, 0f, size.width, size.height)
    val scale = min(size.width / face.width, size.height / face.height)
    val width = face.width * scale
    val height = face.height * scale
    return Rect(
        left = (size.width - width) / 2f,
        top = (size.height - height) / 2f,
        right = (size.width + width) / 2f,
        bottom = (size.height + height) / 2f,
    )
}
