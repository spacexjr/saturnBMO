package com.spacexjr.saturnbmo.ui

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.spacexjr.saturnbmo.AppSettings
import com.spacexjr.saturnbmo.BmoEngine
import com.spacexjr.saturnbmo.BmoState
import com.spacexjr.saturnbmo.BmoUiState
import com.spacexjr.saturnbmo.ConnectionState
import com.spacexjr.saturnbmo.LogEntry
import com.spacexjr.saturnbmo.ServiceStatus
import com.spacexjr.saturnbmo.net.ServerDiscovery

@Composable
fun SettingsScreen(
    engine: BmoEngine,
    settings: AppSettings,
    ui: BmoUiState,
    logs: List<LogEntry>,
    onBack: () -> Unit,
    onSave: (AppSettings) -> Unit,
    onTestTone: () -> Unit,
    onResetHistory: () -> Unit,
) {
    val context = LocalContext.current
    var host by remember(settings) { mutableStateOf(settings.host) }
    var port by remember(settings) { mutableStateOf(settings.port.toString()) }
    var token by remember(settings) { mutableStateOf(settings.token) }
    var showToken by remember { mutableStateOf(false) }
    var volume by remember(settings) { mutableFloatStateOf(settings.volume) }
    var keepScreen by remember(settings) { mutableStateOf(settings.keepScreenOn) }
    var background by remember(settings) { mutableStateOf(settings.backgroundListening) }
    var autoConnect by remember(settings) { mutableStateOf(settings.autoConnect) }
    var formError by remember { mutableStateOf<String?>(null) }
    var testing by remember { mutableStateOf(false) }
    var testResult by remember { mutableStateOf<ServiceStatus?>(null) }
    var testError by remember { mutableStateOf<String?>(null) }
    var searching by remember { mutableStateOf(false) }
    var found by remember { mutableStateOf<List<ServerDiscovery.FoundServer>>(emptyList()) }
    var showFound by remember { mutableStateOf(false) }
    var locationGranted by remember { mutableStateOf(engine.hasLocationPermission()) }
    var folderBusy by remember { mutableStateOf(false) }
    var folderError by remember { mutableStateOf<String?>(null) }
    var folderNotice by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(ui.connected) {
        if (ui.connected) engine.refreshFolderStatus()
    }

    val micLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) engine.startMicTest() else formError = "Permissão de microfone negada."
    }

    val locationLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        locationGranted = engine.hasLocationPermission()
        if (locationGranted) {
            engine.refreshLocation()
        } else {
            formError = "Permissão de localização negada. O clima não terá coordenadas."
        }
    }

    fun candidate(): AppSettings? {
        val portValue = port.toIntOrNull()
        if (host.isBlank()) {
            formError = "Informe o endereço IP ou nome do PC."
            return null
        }
        if (portValue == null || portValue !in 1..65535) {
            formError = "A porta deve estar entre 1 e 65535."
            return null
        }
        if (token.isBlank()) {
            formError = "Informe o token exibido pelo backend."
            return null
        }
        formError = null
        return AppSettings(
            host = host.trim(),
            port = portValue,
            token = token.trim(),
            volume = volume,
            keepScreenOn = keepScreen,
            backgroundListening = background,
            autoConnect = autoConnect,
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(top = 8.dp, bottom = 30.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("← Voltar", color = BmoInk) }
            Spacer(Modifier.weight(1f))
            Text("Ajustes", style = MaterialTheme.typography.titleLarge)
        }
        Spacer(Modifier.height(6.dp))

        SectionCard(title = "Conexão com o PC") {
            OutlinedTextField(
                value = host,
                onValueChange = { host = it },
                label = { Text("Endereço do servidor (IP ou nome)") },
                placeholder = { Text("Ex.: 192.168.0.10") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = port,
                onValueChange = { value -> port = value.filter { it.isDigit() }.take(5) },
                label = { Text("Porta") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = token,
                onValueChange = { token = it },
                label = { Text("Token de acesso") },
                singleLine = true,
                visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { showToken = !showToken }) {
                    Text(if (showToken) "Ocultar token" else "Mostrar token")
                }
                Spacer(Modifier.weight(1f))
                if (ui.connected) Text("Conectado", color = BmoInk, style = MaterialTheme.typography.labelMedium)
            }
            Text(
                "No PC, o token fica em backend/data/token (ou na variável BMO_TOKEN).",
                style = MaterialTheme.typography.bodyMedium,
                color = BmoInkSoft,
            )
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = {
                        val config = candidate() ?: return@Button
                        onSave(config)
                    },
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.weight(1f),
                ) { Text("Salvar e conectar") }
                OutlinedButton(
                    onClick = {
                        val config = candidate() ?: return@OutlinedButton
                        testing = true
                        testError = null
                        testResult = null
                        engine.testConnection(config) { result ->
                            testing = false
                            result.onSuccess { testResult = it }
                            result.onFailure { testError = it.message ?: "Falha desconhecida." }
                        }
                    },
                    enabled = !testing,
                    shape = RoundedCornerShape(14.dp),
                ) { Text(if (testing) "Testando..." else "Testar") }
            }
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = {
                    searching = true
                    found = emptyList()
                    engine.discoverServers { servers ->
                        searching = false
                        found = servers
                        if (servers.isNotEmpty()) showFound = true
                        else formError = "Nenhum BMO encontrado. Confira o Wi-Fi e o firewall do PC."
                    }
                },
                enabled = !searching,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
            ) { Text(if (searching) "Procurando na rede..." else "Procurar BMO na rede local") }
            formError?.let {
                Spacer(Modifier.height(6.dp))
                Text(it, color = BmoError, style = MaterialTheme.typography.bodyMedium)
            }
            testError?.let {
                Spacer(Modifier.height(6.dp))
                Text(it, color = BmoError, style = MaterialTheme.typography.bodyMedium)
            }
            testResult?.let { status ->
                Spacer(Modifier.height(8.dp))
                Surface(color = BmoPanelStrong, shape = RoundedCornerShape(14.dp)) {
                    Column(Modifier.padding(12.dp)) {
                        Text("Teste concluído", style = MaterialTheme.typography.titleMedium)
                        Text("Protocolo: ${status.protocol} • Backend: ${status.version}")
                        Text("LLM: ${ok(status.llmAvailable)} • STT: ${ok(status.sttAvailable)} • TTS: ${ok(status.ttsAvailable)}")
                        if (status.llmModel.isNotBlank()) Text("Modelo: ${status.llmModel}")
                    }
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        SectionCard(title = "Áudio") {
            Text("Volume da voz do BMO", style = MaterialTheme.typography.titleMedium)
            Slider(
                value = volume,
                onValueChange = {
                    volume = it
                    engine.setVolume(it)
                },
                valueRange = 0f..1f,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onTestTone, modifier = Modifier.weight(1f), shape = RoundedCornerShape(14.dp)) {
                    Text("Testar alto-falante")
                }
                OutlinedButton(
                    onClick = {
                        if (ui.micTesting) {
                            engine.stopMicTest()
                        } else if (engine.hasMicrophonePermission()) {
                            engine.startMicTest()
                        } else {
                            micLauncher.launch(Manifest.permission.RECORD_AUDIO)
                        }
                    },
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Text(if (ui.micTesting) "Parar microfone" else "Testar microfone")
                }
            }
            if (ui.micTesting) {
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Nível:", style = MaterialTheme.typography.labelMedium)
                    Spacer(Modifier.width(8.dp))
                    LevelMeter(ui.micLevel, Modifier.weight(1f).height(24.dp))
                    Spacer(Modifier.width(8.dp))
                    TextButton(onClick = { engine.stopMicTest() }) { Text("Parar") }
                }
            }
            Text(
                "O áudio do microfone não é gravado em arquivo e não sai da rede local.",
                style = MaterialTheme.typography.bodyMedium,
                color = BmoInkSoft,
            )
        }

        Spacer(Modifier.height(12.dp))
        SectionCard(title = "Localização (clima)") {
            Text(
                when {
                    !locationGranted -> "Permissão não concedida. O clima precisa do GPS para saber onde você está."
                    ui.locationReady -> "Localização obtida. As coordenadas são enviadas apenas para a consulta de clima."
                    else -> "Permissão concedida. Obtendo a localização do aparelho..."
                },
                style = MaterialTheme.typography.bodyMedium,
                color = if (locationGranted) BmoInk else BmoWarning,
            )
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = {
                    if (locationGranted) {
                        engine.refreshLocation()
                    } else {
                        locationLauncher.launch(
                            arrayOf(
                                Manifest.permission.ACCESS_FINE_LOCATION,
                                Manifest.permission.ACCESS_COARSE_LOCATION,
                            )
                        )
                    }
                },
                shape = RoundedCornerShape(14.dp),
            ) {
                Text(if (locationGranted) "Atualizar localização" else "Permitir localização")
            }
            Text(
                "Coordenada aproximada por GPS ou Wi-Fi. Não há histórico de localização no app.",
                style = MaterialTheme.typography.bodyMedium,
                color = BmoInkSoft,
            )
        }

        Spacer(Modifier.height(12.dp))
        SectionCard(title = "Pasta de acesso do BMO") {
            val folder = ui.folderStatus
            Text(
                when {
                    folder == null -> "Toque em atualizar para consultar o PC."
                    folder.authorized -> "Pasta autorizada:\n${folder.path}"
                    else -> "Nenhuma pasta autorizada. O BMO não pode ler nem alterar arquivos até você escolher uma pasta."
                },
                style = MaterialTheme.typography.bodyMedium,
                color = if (folder?.authorized == true) BmoInk else BmoWarning,
            )
            if (folder != null) {
                Text(
                    "Sistema: ${folder.os.ifBlank { "não informado" }}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = BmoInkSoft,
                )
                if (folder.selectedAt.isNotBlank()) {
                    Text(
                        "Autorizada em: ${folder.selectedAt}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = BmoInkSoft,
                    )
                }
                Text(
                    "Seletor no PC: ${folder.picker.ifBlank { "indisponível" }} • " +
                        "Sessão gráfica: ${if (folder.displayAvailable) "disponível" else "indisponível"}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = BmoInkSoft,
                )
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = {
                        folderBusy = true
                        folderError = null
                        folderNotice = null
                        engine.selectFolder { result ->
                            folderBusy = false
                            result.onSuccess { state ->
                                folderNotice = if (state.authorized) {
                                    "Pasta autorizada no PC."
                                } else {
                                    "Seleção cancelada."
                                }
                            }
                            result.onFailure { error ->
                                folderError = error.message ?: "O seletor de pastas falhou."
                            }
                        }
                    },
                    enabled = ui.connected && !folderBusy,
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (folderBusy) "Aguardando o PC..." else "Escolher pasta no PC")
                }
                OutlinedButton(
                    onClick = {
                        folderBusy = true
                        folderError = null
                        folderNotice = null
                        engine.revokeFolder { result ->
                            folderBusy = false
                            result.onSuccess { folderNotice = "Acesso revogado." }
                            result.onFailure { error ->
                                folderError = error.message ?: "Não foi possível revogar."
                            }
                        }
                    },
                    enabled = ui.connected && !folderBusy && folder?.authorized == true,
                    shape = RoundedCornerShape(14.dp),
                ) { Text("Revogar") }
            }
            folderNotice?.let {
                Spacer(Modifier.height(6.dp))
                Text(it, color = BmoInk, style = MaterialTheme.typography.bodyMedium)
            }
            folderError?.let {
                Spacer(Modifier.height(6.dp))
                Text(it, color = BmoError, style = MaterialTheme.typography.bodyMedium)
            }
            Text(
                "O seletor nativo abre na tela do PC (KDE: kdialog; alternativa: zenity). " +
                    "Todas as ferramentas de arquivo do BMO ficam presas a essa pasta.",
                style = MaterialTheme.typography.bodyMedium,
                color = BmoInkSoft,
            )
        }

        Spacer(Modifier.height(12.dp))
        SectionCard(title = "Comportamento") {
            SwitchRow(
                title = "Conectar automaticamente",
                subtitle = "Tenta reconectar quando o app abre ou perde a rede.",
                checked = autoConnect,
                onChange = { autoConnect = it },
            )
            HorizontalDivider(color = BmoPanelStrong)
            SwitchRow(
                title = "Manter tela ligada",
                subtitle = "Útil enquanto o celular está na carcaça do BMO.",
                checked = keepScreen,
                onChange = { keepScreen = it },
            )
            HorizontalDivider(color = BmoPanelStrong)
            SwitchRow(
                title = "Escuta com tela desligada",
                subtitle = "Usa um serviço em primeiro plano com notificação. " +
                    "O Android pode pedir permissão de notificações.",
                checked = background,
                onChange = { background = it },
            )
        }

        Spacer(Modifier.height(12.dp))
        SectionCard(title = "Estado do servidor") {
            Text(
                when (ui.connection) {
                    ConnectionState.CONNECTED -> "Conectado"
                    ConnectionState.CONNECTING -> "Conectando..."
                    ConnectionState.RECONNECTING -> "Reconectando (tentativa ${ui.reconnectAttempt})"
                    ConnectionState.DISCONNECTED -> "Desconectado"
                },
                style = MaterialTheme.typography.titleMedium,
                color = if (ui.connected) BmoInk else BmoWarning,
            )
            val status = testResult ?: ui.serviceStatus
            if (status == null) {
                Text(
                    "Conecte-se para ver o estado do LLM, STT e TTS.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = BmoInkSoft,
                )
            } else {
                Text("Protocolo ${status.protocol} • versão ${status.version}")
                Text("LLM: ${ok(status.llmAvailable)}  •  STT: ${ok(status.sttAvailable)}  •  TTS: ${ok(status.ttsAvailable)}")
                if (status.llmModel.isNotBlank()) Text("Modelo: ${status.llmModel}")
                if (status.wakeMode.isNotBlank()) Text("Ativação: ${status.wakeMode}")
            }
            if (ui.bmoState == BmoState.ERROR && ui.lastError != null) {
                Spacer(Modifier.height(6.dp))
                Text(ui.lastError, color = BmoError, style = MaterialTheme.typography.bodyMedium)
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = onResetHistory,
                    enabled = ui.connected,
                    shape = RoundedCornerShape(14.dp),
                ) { Text("Apagar histórico") }
                OutlinedButton(
                    onClick = { engine.disconnect() },
                    enabled = ui.connected,
                    shape = RoundedCornerShape(14.dp),
                ) { Text("Desconectar") }
            }
        }

        Spacer(Modifier.height(12.dp))
        SectionCard(title = "Como conectar") {
            Text(
                "1. No PC, execute backend/run.sh.\n" +
                    "2. Copie o token de backend/data/token.\n" +
                    "3. Deixe o celular e o PC na mesma rede Wi-Fi.\n" +
                    "4. Informe o IP do PC (ou use Procurar na rede) e o token.\n" +
                    "5. Toque em Testar e depois em Salvar e conectar.\n\n" +
                    "Sem internet: o PC precisa apenas da rede local e dos modelos já instalados.",
                style = MaterialTheme.typography.bodyMedium,
                color = BmoInkSoft,
            )
        }

        Spacer(Modifier.height(12.dp))
        SectionCard(title = "Logs do aplicativo") {
            if (logs.isEmpty()) {
                Text("Nenhum log ainda.", color = BmoInkSoft, style = MaterialTheme.typography.bodyMedium)
            } else {
                logs.takeLast(20).forEach { entry ->
                    val color = when (entry.level) {
                        "ERRO" -> BmoError
                        "AVISO" -> BmoWarning
                        "USUÁRIO", "STT", "BMO" -> BmoInkSoft
                        else -> BmoInk
                    }
                    Text(
                        "${entry.time} [${entry.level}] ${entry.message}",
                        color = color,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp,
                        lineHeight = 15.sp,
                        maxLines = 4,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { engine.clearLogs() }) { Text("Limpar logs") }
            }
        }
    }

    if (showFound) {
        AlertDialog(
            onDismissRequest = { showFound = false },
            title = { Text("BMO encontrado na rede") },
            text = {
                Column {
                    found.forEach { server ->
                        OutlinedButton(
                            onClick = {
                                host = server.host
                                port = server.port.toString()
                                showFound = false
                            },
                            modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                        ) {
                            Column(Modifier.fillMaxWidth()) {
                                Text(server.name)
                                Text(
                                    "${server.host}:${server.port} • ${server.protocol}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = BmoInkSoft,
                                )
                            }
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { showFound = false }) { Text("Fechar") } },
        )
    }
}

@Composable
private fun SectionCard(title: String, content: @Composable () -> Unit) {
    Surface(
        color = BmoPanel.copy(alpha = 0.96f),
        shape = RoundedCornerShape(24.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, color = BmoInk)
            Spacer(Modifier.height(10.dp))
            content()
        }
    }
}

@Composable
private fun SwitchRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = BmoInk)
            Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = BmoInkSoft)
        }
        Spacer(Modifier.width(8.dp))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

private fun ok(value: Boolean) = if (value) "ok" else "indisponível"
