package com.spacexjr.saturnbmo.ui.face

import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.StrokeCap
import kotlin.math.abs
import kotlin.math.sin

/**
 * Expressões originais do BMO desenhadas com primitivas simples e pixeladas.
 * Não carrega bitmaps adicionais: mantém baixo consumo de memória e renderização
 * determinística em aparelhos modestos como o Galaxy A22.
 */
internal fun DrawScope.drawClassicBmoFace(
    bounds: Rect,
    emotion: BmoFaceEmotion,
    time: Long,
    micLevel: Float,
    blink: Boolean,
) {
    val w = bounds.width
    val h = bounds.height
    if (w <= 0f || h <= 0f) return

    val shell = Color(0xFF55CFC0)
    val screen = Color(0xFF10191B)
    val pixel = Color(0xFFB9FFF2)
    val softPixel = Color(0xFF8FE8DC)

    // Silhueta/tela: corpo turquesa e visor preto, sem gradientes ou texturas.
    drawRoundRect(
        color = shell,
        topLeft = Offset(bounds.left, bounds.top),
        size = Size(w, h),
        cornerRadius = CornerRadius(w * 0.035f, w * 0.035f),
    )
    val insetX = w * 0.075f
    val insetY = h * 0.105f
    val screenRect = Rect(
        bounds.left + insetX,
        bounds.top + insetY,
        bounds.right - insetX,
        bounds.bottom - insetY,
    )
    drawRoundRect(
        color = screen,
        topLeft = Offset(screenRect.left, screenRect.top),
        size = Size(screenRect.width, screenRect.height),
        cornerRadius = CornerRadius(w * 0.025f, w * 0.025f),
    )

    val sw = screenRect.width
    val sh = screenRect.height
    val eyeY = screenRect.top + sh * 0.37f
    val eyeW = sw * 0.105f
    val eyeH = sh * when (emotion) {
        BmoFaceEmotion.EXCITED, BmoFaceEmotion.SURPRISED, BmoFaceEmotion.SCARED -> 0.19f
        BmoFaceEmotion.SLEEPY, BmoFaceEmotion.SAD -> 0.095f
        else -> 0.145f
    }
    val leftEyeX = screenRect.left + sw * 0.30f
    val rightEyeX = screenRect.left + sw * 0.70f

    if (emotion == BmoFaceEmotion.LOVE) {
        drawPixelHeart(Offset(leftEyeX, eyeY), eyeW * 0.72f, pixel)
        drawPixelHeart(Offset(rightEyeX, eyeY), eyeW * 0.72f, pixel)
    } else if (blink || emotion == BmoFaceEmotion.SLEEPY) {
        val lidY = if (blink) eyeY else eyeY + eyeH * 0.35f
        listOf(leftEyeX, rightEyeX).forEach { cx ->
            drawLine(
                softPixel,
                Offset(cx - eyeW * 0.58f, lidY),
                Offset(cx + eyeW * 0.58f, lidY),
                strokeWidth = sh * 0.025f,
                cap = StrokeCap.Square,
            )
        }
    } else {
        val leftTop = eyeY - eyeH / 2f
        val rightTop = when (emotion) {
            BmoFaceEmotion.CONFUSED, BmoFaceEmotion.THINKING -> leftTop - eyeH * 0.18f
            else -> leftTop
        }
        drawRect(pixel, Offset(leftEyeX - eyeW / 2f, leftTop), Size(eyeW, eyeH))
        drawRect(pixel, Offset(rightEyeX - eyeW / 2f, rightTop), Size(eyeW, eyeH))
    }

    // Sobrancelhas discretas para raiva/medo, mantendo o desenho geométrico.
    if (emotion == BmoFaceEmotion.ANGRY || emotion == BmoFaceEmotion.SCARED) {
        val brow = sh * 0.022f
        drawLine(pixel, Offset(leftEyeX - eyeW * 0.65f, eyeY - eyeH * 0.75f),
            Offset(leftEyeX + eyeW * 0.55f, eyeY - eyeH * 0.95f), brow, StrokeCap.Square)
        drawLine(pixel, Offset(rightEyeX - eyeW * 0.55f, eyeY - eyeH * 0.95f),
            Offset(rightEyeX + eyeW * 0.65f, eyeY - eyeH * 0.75f), brow, StrokeCap.Square)
    }

    val mouthCenterX = screenRect.center.x
    val mouthCenterY = screenRect.top + sh * 0.72f
    val mouthW = sw * 0.19f
    val mouthH = sh * 0.12f
    val stroke = sh * 0.024f

    when (emotion) {
        BmoFaceEmotion.SURPRISED, BmoFaceEmotion.SCARED, BmoFaceEmotion.ERROR -> {
            drawRoundRect(
                color = pixel,
                topLeft = Offset(mouthCenterX - mouthW * 0.34f, mouthCenterY - mouthH * 0.55f),
                size = Size(mouthW * 0.68f, mouthH * 1.1f),
                cornerRadius = CornerRadius(mouthW * 0.25f, mouthW * 0.25f),
                style = Stroke(width = stroke),
            )
        }
        BmoFaceEmotion.SPEAKING -> {
            val openness = 0.55f + (micLevel.coerceIn(0f, 1f) * 0.45f) +
                abs(sin(time / 95f)) * 0.18f
            drawRoundRect(
                color = pixel,
                topLeft = Offset(mouthCenterX - mouthW * 0.45f, mouthCenterY - mouthH * openness),
                size = Size(mouthW * 0.9f, mouthH * openness * 1.8f),
                cornerRadius = CornerRadius(mouthW * 0.18f, mouthW * 0.18f),
                style = Stroke(width = stroke),
            )
        }
        BmoFaceEmotion.HAPPY, BmoFaceEmotion.EXCITED, BmoFaceEmotion.LOVE -> {
            val smile = Path().apply {
                moveTo(mouthCenterX - mouthW / 2f, mouthCenterY - mouthH * 0.12f)
                quadraticTo(mouthCenterX, mouthCenterY + mouthH * 1.35f,
                    mouthCenterX + mouthW / 2f, mouthCenterY - mouthH * 0.12f)
            }
            drawPath(smile, pixel, style = Stroke(width = stroke, cap = StrokeCap.Square))
        }
        BmoFaceEmotion.SAD -> {
            val frown = Path().apply {
                moveTo(mouthCenterX - mouthW / 2f, mouthCenterY + mouthH * 0.35f)
                quadraticTo(mouthCenterX, mouthCenterY - mouthH * 0.9f,
                    mouthCenterX + mouthW / 2f, mouthCenterY + mouthH * 0.35f)
            }
            drawPath(frown, pixel, style = Stroke(width = stroke, cap = StrokeCap.Square))
        }
        BmoFaceEmotion.ANGRY -> {
            drawLine(pixel, Offset(mouthCenterX - mouthW / 2f, mouthCenterY),
                Offset(mouthCenterX + mouthW / 2f, mouthCenterY - mouthH * 0.2f),
                stroke, StrokeCap.Square)
        }
        BmoFaceEmotion.CONFUSED, BmoFaceEmotion.THINKING, BmoFaceEmotion.PROCESSING -> {
            drawLine(pixel, Offset(mouthCenterX - mouthW * 0.36f, mouthCenterY),
                Offset(mouthCenterX + mouthW * 0.36f, mouthCenterY - mouthH * 0.12f),
                stroke, StrokeCap.Square)
        }
        BmoFaceEmotion.LISTENING -> {
            drawLine(softPixel, Offset(mouthCenterX - mouthW * 0.32f, mouthCenterY),
                Offset(mouthCenterX + mouthW * 0.32f, mouthCenterY),
                stroke, StrokeCap.Square)
            val pulse = 0.5f + 0.5f * sin(time / 260f)
            drawCircle(softPixel.copy(alpha = 0.35f + pulse * 0.45f),
                sh * 0.012f, Offset(screenRect.right - sw * 0.09f, screenRect.top + sh * 0.12f))
        }
        BmoFaceEmotion.SLEEPY, BmoFaceEmotion.NEUTRAL -> {
            drawLine(pixel, Offset(mouthCenterX - mouthW * 0.3f, mouthCenterY),
                Offset(mouthCenterX + mouthW * 0.3f, mouthCenterY),
                stroke, StrokeCap.Square)
        }
    }

    if (emotion == BmoFaceEmotion.THINKING || emotion == BmoFaceEmotion.CONFUSED) {
        val bob = sin(time / 330f) * sh * 0.012f
        drawCircle(softPixel, sh * 0.012f,
            Offset(screenRect.right - sw * 0.12f, screenRect.top + sh * 0.16f + bob))
    }
    if (emotion == BmoFaceEmotion.EXCITED) {
        val sparkleY = screenRect.top + sh * 0.16f
        drawRect(pixel, Offset(screenRect.left + sw * 0.12f, sparkleY), Size(sh * 0.025f, sh * 0.025f))
        drawRect(pixel, Offset(screenRect.right - sw * 0.15f, sparkleY), Size(sh * 0.025f, sh * 0.025f))
    }
}

private fun DrawScope.drawPixelHeart(center: Offset, unit: Float, color: Color) {
    val p = unit * 0.42f
    val x = center.x
    val y = center.y
    drawRect(color, Offset(x - p * 1.6f, y - p), Size(p * 1.2f, p))
    drawRect(color, Offset(x + p * 0.4f, y - p), Size(p * 1.2f, p))
    drawRect(color, Offset(x - p * 2f, y), Size(p * 4f, p))
    drawRect(color, Offset(x - p * 1.4f, y + p), Size(p * 2.8f, p))
    drawRect(color, Offset(x - p * 0.8f, y + p * 2f), Size(p * 1.6f, p))
    drawRect(color, Offset(x - p * 0.4f, y + p * 3f), Size(p * 0.8f, p))
}
