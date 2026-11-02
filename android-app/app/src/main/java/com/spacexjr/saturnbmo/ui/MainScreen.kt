package com.spacexjr.saturnbmo.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.spacexjr.saturnbmo.AppSettings
import com.spacexjr.saturnbmo.BmoState
import com.spacexjr.saturnbmo.BmoUiState
import com.spacexjr.saturnbmo.ConnectionState
import kotlin.math.abs
import kotlin.math.sin

/**
 * Tela principal em modo "somente a cara": o rosto ocupa a tela inteira,
 * em paisagem. Toque no rosto para mostrar os controles; toque e segure
 * (ou use o botão de ajustes) para abrir as configurações.
 */
@Composable
fun MainScreen(
    ui: BmoUiState,
    settings: AppSettings,
    onSettings: () -> Unit,
    onConnect: () -> Unit,
    onToggleListening: () -> Unit,
    onActivate: () -> Unit,
    onInterrupt: () -> Unit,
    onSendText: (String) -> Unit,
) {
    var showControls by remember { mutableStateOf(false) }
    var showTextDialog by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(BmoGreen),
    ) {
        BmoFace(ui, Modifier.fillMaxSize(), fullBleed = true)

        // Camada de gestos fica abaixo dos controles: toque alterna a barra,
        // toque longo abre os ajustes sem precisar de botão sempre visível.
        Box(
            Modifier
                .fillMaxSize()
                .pointerInput(Unit) {
                    detectTapGestures(
                        onTap = { showControls = !showControls },
                        onLongPress = {
                            showControls = true
                            onSettings()
                        },
                    )
                }
        )

        AnimatedVisibility(
            visible = showControls,
            enter = fadeIn() + slideInVertically(initialOffsetY = { it / 4 }),
            exit = fadeOut() + slideOutVertically(targetOffsetY = { it / 4 }),
            modifier = Modifier.fillMaxSize(),
        ) {
            FaceOverlay(
                ui = ui,
                configured = settings.isConfigured,
                onSettings = onSettings,
                onConnect = onConnect,
                onToggleListening = onToggleListening,
                onActivate = onActivate,
                onInterrupt = onInterrupt,
                onText = { showTextDialog = true },
                onHide = { showControls = false },
            )
        }
    }

    if (showTextDialog) {
        TextMessageDialog(
            onDismiss = { showTextDialog = false },
            onSend = {
                showTextDialog = false
                onSendText(it)
            },
        )
    }
}

@Composable
private fun FaceOverlay(
    ui: BmoUiState,
    configured: Boolean,
    onSettings: () -> Unit,
    onConnect: () -> Unit,
    onToggleListening: () -> Unit,
    onActivate: () -> Unit,
    onInterrupt: () -> Unit,
    onText: () -> Unit,
    onHide: () -> Unit,
) {
    Box(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.TopCenter)
                .padding(horizontal = 18.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ConnectionPill(ui)
            Spacer(Modifier.width(10.dp))
            Text(
                text = ui.statusDetail,
                style = MaterialTheme.typography.labelMedium,
                color = BmoInkSoft,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            OutlinedButton(
                onClick = onSettings,
                shape = RoundedCornerShape(50),
            ) { Text("⚙ Ajustes") }
            Spacer(Modifier.width(6.dp))
            TextButton(onClick = onHide) { Text("Ocultar") }
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.BottomCenter)
                .padding(horizontal = 18.dp, vertical = 14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            if (ui.transcript.isNotBlank() || ui.assistantText.isNotBlank()) {
                Surface(
                    color = BmoPanel.copy(alpha = 0.96f),
                    shape = RoundedCornerShape(18.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                        if (ui.transcript.isNotBlank()) {
                            Text("VOCÊ", style = MaterialTheme.typography.labelMedium, color = BmoInkSoft)
                            Text(
                                ui.transcript,
                                style = MaterialTheme.typography.bodyMedium,
                                color = BmoInk,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        if (ui.assistantText.isNotBlank()) {
                            Text("BMO", style = MaterialTheme.typography.labelMedium, color = BmoInkSoft)
                            Text(
                                ui.assistantText + if (ui.streamingText) " ▍" else "",
                                style = MaterialTheme.typography.bodyMedium,
                                color = BmoInk,
                                maxLines = 3,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
            }

            AnimatedVisibility(visible = ui.lastError != null && ui.bmoState == BmoState.ERROR) {
                Surface(
                    color = BmoErrorSoft,
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
                ) {
                    Text(
                        text = ui.lastError.orEmpty(),
                        color = BmoError,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                StateChip(ui.bmoState)
                if (ui.listening) {
                    LevelMeter(ui.micLevel, Modifier.width(110.dp).height(22.dp))
                }
                Spacer(Modifier.weight(1f))
                if (ui.bmoState == BmoState.SPEAKING) {
                    TextButton(onClick = onInterrupt) { Text("Parar fala") }
                }
                if (ui.micTesting) {
                    Text(
                        "Teste de microfone em andamento",
                        style = MaterialTheme.typography.labelMedium,
                        color = BmoWarning,
                    )
                }
            }

            Spacer(Modifier.height(6.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                OutlinedButton(
                    onClick = onActivate,
                    enabled = ui.connected,
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(16.dp),
                ) { Text("Falar agora") }
                OutlinedButton(
                    onClick = onText,
                    enabled = ui.connected,
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(16.dp),
                ) { Text("Digitar") }
                Button(
                    onClick = {
                        when {
                            !configured -> onConnect()
                            !ui.connected -> onConnect()
                            else -> onToggleListening()
                        }
                    },
                    shape = CircleShape,
                    colors = ButtonDefaults.buttonColors(containerColor = BmoInk, contentColor = BmoGreen),
                    modifier = Modifier.size(64.dp),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp),
                ) {
                    when {
                        ui.connection == ConnectionState.CONNECTING ||
                            ui.connection == ConnectionState.RECONNECTING -> {
                            CircularProgressIndicator(
                                color = BmoGreen,
                                strokeWidth = 3.dp,
                                modifier = Modifier.size(24.dp),
                            )
                        }
                        !configured -> Text("⚙", fontSize = 26.sp)
                        !ui.connected -> Text("Wi-Fi", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                        else -> MicGlyph(ui.listening)
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
            Text(
                text = when {
                    !configured -> "Toque no ⚙ para configurar o PC"
                    !ui.connected -> "Toque no botão para conectar ao PC"
                    ui.listening -> "Microfone ativo — toque no botão para parar"
                    else -> "Toque no botão para ouvir pelo microfone"
                },
                style = MaterialTheme.typography.labelMedium,
                color = BmoInkSoft,
            )
        }
    }
}

@Composable
private fun ConnectionPill(ui: BmoUiState) {
    val (label, color) = when (ui.connection) {
        ConnectionState.CONNECTED -> "PC conectado" to BmoInk
        ConnectionState.CONNECTING -> "Conectando" to BmoWarning
        ConnectionState.RECONNECTING -> "Reconectando ${ui.reconnectAttempt}" to BmoWarning
        ConnectionState.DISCONNECTED -> "Desconectado" to BmoError
    }
    Surface(color = BmoPanelStrong, shape = RoundedCornerShape(50)) {
        Row(
            modifier = Modifier.padding(horizontal = 9.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(8.dp).background(color, CircleShape))
            Spacer(Modifier.width(6.dp))
            Text(label, style = MaterialTheme.typography.labelMedium, color = BmoInk)
        }
    }
}

@Composable
private fun StateChip(state: BmoState) {
    val color = when (state) {
        BmoState.ERROR -> BmoError
        BmoState.SPEAKING -> BmoInk
        BmoState.LISTENING -> BmoInk
        BmoState.THINKING -> BmoInkSoft
        else -> BmoInkSoft
    }
    Text(
        text = state.label,
        style = MaterialTheme.typography.labelLarge,
        color = color,
    )
}

@Composable
private fun MicGlyph(listening: Boolean) {
    Canvas(Modifier.size(30.dp)) {
        val tint = BmoGreen
        if (listening) {
            drawRoundRect(
                color = tint,
                topLeft = Offset(size.width * 0.32f, size.height * 0.32f),
                size = Size(size.width * 0.36f, size.height * 0.36f),
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(6f, 6f),
            )
            return@Canvas
        }
        drawRoundRect(
            color = tint,
            topLeft = Offset(size.width * 0.36f, size.height * 0.08f),
            size = Size(size.width * 0.28f, size.height * 0.48f),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(size.width * 0.14f),
        )
        drawArc(
            color = tint,
            startAngle = 0f,
            sweepAngle = 180f,
            useCenter = false,
            topLeft = Offset(size.width * 0.22f, size.height * 0.28f),
            size = Size(size.width * 0.56f, size.height * 0.44f),
            style = Stroke(width = size.width * 0.07f, cap = StrokeCap.Round),
        )
        drawLine(
            tint,
            Offset(size.width * 0.5f, size.height * 0.72f),
            Offset(size.width * 0.5f, size.height * 0.88f),
            strokeWidth = size.width * 0.07f,
            cap = StrokeCap.Round,
        )
        drawLine(
            tint,
            Offset(size.width * 0.36f, size.height * 0.9f),
            Offset(size.width * 0.64f, size.height * 0.9f),
            strokeWidth = size.width * 0.07f,
            cap = StrokeCap.Round,
        )
    }
}

@Composable
fun LevelMeter(level: Float, modifier: Modifier = Modifier) {
    val bars = 9
    val animated by animateFloatAsState(targetValue = level.coerceIn(0f, 1f), label = "nivel")
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        repeat(bars) { index ->
            val wave = abs(sin((index + 1) * 0.9)) * 0.7 + 0.3
            val height = (4 + animated * 20 * wave).dp
            Box(
                Modifier
                    .width(5.dp)
                    .height(height)
                    .background(BmoInk, RoundedCornerShape(4.dp))
            )
        }
    }
}

@Composable
private fun TextMessageDialog(onDismiss: () -> Unit, onSend: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Falar por texto") },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { if (it.length <= 1000) text = it },
                label = { Text("Mensagem para o BMO") },
                minLines = 3,
                maxLines = 6,
                modifier = Modifier.fillMaxWidth(),
            )
        },
        confirmButton = {
            TextButton(onClick = { if (text.isNotBlank()) onSend(text) }, enabled = text.isNotBlank()) {
                Text("Enviar")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}
