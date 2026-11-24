const { contextBridge, ipcRenderer, webUtils } = require('electron');

console.log('⚡ [PRELOAD] Script preload.js inicializado.');

// Caminhos dos arquivos soltos na janela. Lidos aqui, na fase de captura, porque o objeto File
// perde o vínculo com o arquivo ao passar pela contextBridge e webUtils só funciona no preload.
let caminhosSoltos = [];
window.addEventListener('drop', (e) => {
    const arquivos = e.dataTransfer ? Array.from(e.dataTransfer.files) : [];
    caminhosSoltos = arquivos.map((f) => {
        try { return webUtils.getPathForFile(f); } catch (erro) { return ''; }
    }).filter(Boolean);
}, true);

const logIPC = (canal, dados) => {
    console.log(`📡 [IPC RECEBIDO no Preload -> ${canal}]:`, dados !== undefined ? dados : '(sem payload)');
};

contextBridge.exposeInMainWorld('api', {
    // =========================================================================
    // Envio de mensagens (Renderer -> Main -> Python)
    // =========================================================================

    sendText: (text) => {
        console.log('📤 [IPC ENVIADO -> send-text]:', text);
        ipcRenderer.send('send-text', text);
    },

    // Anexos: abre a janela de escolha ou envia os arquivos arrastados.
    // Devolve os nomes aceitos (formatos: HTML, PDF, JPG, PNG, WEBP).
    escolherAnexos: () => ipcRenderer.invoke('escolher-anexos'),
    enviarAnexosSoltos: () => {
        const caminhos = caminhosSoltos;
        caminhosSoltos = [];
        return ipcRenderer.invoke('enviar-anexos', caminhos);
    },

    // NOVO: Toggle unificado de Modo Voz (microfone + TTS)
    toggleVoiceMode: (enabled) => {
        console.log('📤 [IPC ENVIADO -> toggle-voice-mode]:', enabled);
        ipcRenderer.send('toggle-voice-mode', enabled);
    },

    // Toggle Mute (silencia apenas o TTS, sem desativar microfone)
    toggleMute: (muted) => {
        console.log('📤 [IPC ENVIADO -> toggle-mute]:', muted);
        ipcRenderer.send('toggle-mute', muted);
    },

    // Compatibilidade: toggleMicrophone antigo redireciona para toggleVoiceMode
    toggleMicrophone: (enabled) => {
        console.log('📤 [IPC ENVIADO -> toggle-voice-mode (compat)]:', enabled);
        ipcRenderer.send('toggle-voice-mode', enabled);
    },

    // =========================================================================
    // Recebimento de mensagens (Python -> Main -> Renderer)
    // =========================================================================

    onStateChanged: (callback) => {
        ipcRenderer.on('state-changed', (event, data) => {
            logIPC('state-changed', data);
            callback(data);
        });
    },
    onUserMessage: (callback) => {
        ipcRenderer.on('user-message', (event, data) => {
            logIPC('user-message', data);
            callback(data);
        });
    },
    onAssistantMessage: (callback) => {
        ipcRenderer.on('assistant-message', (event, data) => {
            logIPC('assistant-message', data);
            callback(data);
        });
    },
    // Alias mantido para retrocompatibilidade se necessário
    onRespostaBackend: (callback) => {
        ipcRenderer.on('assistant-message', (event, data) => {
            logIPC('assistant-message', data);
            callback(data);
        });
    },

    // NOVO: Status detalhado do modo voz (hardware, TTS, microfone)
    onVoiceModeStatus: (callback) => {
        ipcRenderer.on('voice-mode-status', (event, data) => {
            logIPC('voice-mode-status', data);
            callback(data);
        });
    },

    // Compatibilidade: microphone-status antigo
    onMicrophoneStatus: (callback) => {
        ipcRenderer.on('microphone-status', (event, data) => {
            logIPC('microphone-status', data);
            callback(data);
        });
    },

    onDebugLog: (callback) => {
        ipcRenderer.on('debug-log', (event, data) => {
            logIPC('debug-log', data);
            callback(data);
        });
    },
    onError: (callback) => {
        ipcRenderer.on('error', (event, data) => {
            logIPC('error', data);
            callback(data);
        });
    },
    onSystemReady: (callback) => {
        ipcRenderer.on('system-ready', (event, data) => {
            logIPC('system-ready', data);
            callback(data);
        });
    }
});