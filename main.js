const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow;
let pythonProcess;

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 800,
        height: 600,
        minWidth: 600,
        minHeight: 500,
        title: "Assistente Doméstico Inteligente",
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false
        }
    });

    mainWindow.loadFile('index.html');

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

/**
 * Envia mensagens do processo Principal (Main) para o Renderer com segurança.
 * Caso o Renderer ainda esteja carregando o HTML/DOM, aguarda o evento 'did-finish-load'.
 */
function sendToRenderer(channel, payload) {
    if (!mainWindow) return;

    if (mainWindow.webContents.isLoading()) {
        mainWindow.webContents.once('did-finish-load', () => {
            mainWindow.webContents.send(channel, payload);
        });
    } else {
        mainWindow.webContents.send(channel, payload);
    }
}

function startPythonBackend() {
    console.log("Iniciando back-end Python...");

    pythonProcess = spawn('python', ['-u', 'app/main.py'], {
        cwd: __dirname
    });

    let buffer = '';

    pythonProcess.stdout.on('data', (chunk) => {
        // Acumula os chunks no buffer para evitar JSONs truncados
        buffer += chunk.toString();
        const linhas = buffer.split('\n');

        // Mantém a última linha (incompleta ou vazia) no buffer para a próxima iteração
        buffer = linhas.pop();

        linhas.forEach(linha => {
            if (!linha.trim()) return;
            try {
                const msg = JSON.parse(linha);

                // Converte snake_case (Python) para kebab-case (Electron preload)
                const canal = msg.type.replace(/_/g, '-');

                console.log(`[MAIN -> RENDERER] Repassando evento: ${canal}`, msg.payload);
                sendToRenderer(canal, msg.payload);
            } catch (e) {
                console.log(`[PYTHON LOG]: ${linha}`);
            }
        });
    });

    pythonProcess.stderr.on('data', (data) => {
        console.error(`[Python stderr]: ${data.toString().trim()}`);
    });

    pythonProcess.on('exit', (code, signal) => {
        console.log(`Processo Python encerrou com código ${code} e sinal ${signal}`);
        sendToRenderer('error', "O back-end do assistente encerrou inesperadamente.");
        sendToRenderer('state-changed', "ERROR");
    });
}

function sendToPython(type, payload = {}) {
    if (pythonProcess && !pythonProcess.killed) {
        const msg = JSON.stringify({ type, payload }) + '\n';
        pythonProcess.stdin.write(msg);
    }
}

// =============================================================================
// Listeners IPC: Renderer → Main → Python
// =============================================================================

// Mensagem de texto do chat
ipcMain.on('send-text', (event, text) => {
    sendToPython('send_text', { text });
});

// Toggle Modo Voz (NOVO — substitui toggle-microphone)
ipcMain.on('toggle-voice-mode', (event, enabled) => {
    sendToPython('toggle_voice_mode', { enabled });
});

// Toggle Mute (silencia apenas o TTS)
ipcMain.on('toggle-mute', (event, muted) => {
    sendToPython('toggle_mute', { muted });
});

// Compatibilidade: toggle-microphone antigo redireciona para toggle_voice_mode
ipcMain.on('toggle-microphone', (event, enabled) => {
    sendToPython('toggle_voice_mode', { enabled });
});

// =============================================================================
// Cleanup & Lifecycle
// =============================================================================

let cleanupDone = false;
function cleanupAndExit() {
    if (cleanupDone) return;
    cleanupDone = true;

    console.log("Encerramento solicitado. Desconectando back-end Python...");
    sendToPython('shutdown');

    // Timeout de 2 segundos antes de matar o processo Python caso ele não encerre sozinho
    const exitTimeout = setTimeout(() => {
        if (pythonProcess && !pythonProcess.killed) {
            console.log("Python não encerrou no tempo limite. Matando processo...");
            pythonProcess.kill('SIGKILL');
        }
        app.quit();
    }, 2000);

    if (pythonProcess) {
        pythonProcess.on('exit', () => {
            clearTimeout(exitTimeout);
            app.quit();
        });
    } else {
        clearTimeout(exitTimeout);
        app.quit();
    }
}

app.whenReady().then(() => {
    createWindow();
    startPythonBackend();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on('window-all-closed', () => {
    cleanupAndExit();
});