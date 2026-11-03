// =============================================================================
// Elementos DOM
// =============================================================================
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const chatMessages = document.getElementById('chat-messages');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const debugLogArea = document.getElementById('debug-log-area');
const muteBtn = document.getElementById('mute-toggle-btn');
const voiceModeCheckbox = document.getElementById('voice-mode-checkbox');
const voiceModeSwitch = document.getElementById('voice-mode-switch');
const voiceStatusBadge = document.getElementById('voice-status-badge');
const voiceToggleContainer = document.querySelector('.voice-toggle-container');

// =============================================================================
// Estado Local
// =============================================================================
let isMuted = false;
let voiceModeEnabled = false;
let backendState = 'STARTING';

// =============================================================================
// Helpers
// =============================================================================
function getFormattedTime() {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function escapeHTML(str) {
    if (typeof str !== 'string') return str;
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// =============================================================================
// Chat UI
// =============================================================================
function appendMessage(sender, text) {
    const msgElement = document.createElement('div');
    msgElement.classList.add('message');
    msgElement.classList.add(sender === 'user' ? 'user-msg' : 'assistant-msg');

    const avatar = sender === 'user' ? '👤' : '🤖';
    const timeStr = getFormattedTime();

    msgElement.innerHTML = `
        <div class="msg-avatar">${avatar}</div>
        <div class="msg-content">
            <p>${escapeHTML(text)}</p>
            <span class="msg-time">${timeStr}</span>
        </div>
    `;

    chatMessages.appendChild(msgElement);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendDebug(message, type = 'system') {
    const debugMsg = document.createElement('p');
    debugMsg.classList.add('debug-msg');

    if (type === 'error') {
        debugMsg.classList.add('error-msg');
    } else if (type === 'success') {
        debugMsg.classList.add('success-msg');
    } else if (type === 'process') {
        debugMsg.classList.add('process-msg');
    } else {
        debugMsg.classList.add('system-msg');
    }

    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    debugMsg.textContent = `[${timestamp}] ${message}`;

    debugLogArea.appendChild(debugMsg);
    debugLogArea.scrollTop = debugLogArea.scrollHeight;
}

// =============================================================================
// Envio de Mensagens (Chat — sempre disponível)
// =============================================================================
function handleSendMessage() {
    const text = chatInput.value.trim();
    if (text) {
        window.api.sendText(text);
        chatInput.value = '';
    }
}

sendBtn.addEventListener('click', handleSendMessage);
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        handleSendMessage();
    }
});

// =============================================================================
// Toggle Modo Voz
// =============================================================================
voiceModeCheckbox.addEventListener('change', () => {
    const enabled = voiceModeCheckbox.checked;

    // Feedback visual imediato: estado "carregando"
    if (enabled) {
        voiceModeSwitch.classList.add('loading');
        updateVoiceBadge('loading', '⏳', 'Verificando hardware...');
    }

    window.api.toggleVoiceMode(enabled);
});

function updateVoiceBadge(state, icon, text) {
    voiceStatusBadge.className = 'voice-status-badge';
    voiceStatusBadge.classList.add(`badge-${state}`);
    voiceStatusBadge.querySelector('.badge-icon').textContent = icon;
    voiceStatusBadge.querySelector('.badge-text').textContent = text;
}

// =============================================================================
// Toggle Mute (TTS)
// =============================================================================
if (muteBtn) {
    muteBtn.addEventListener('click', () => {
        isMuted = !isMuted;

        const icon = muteBtn.querySelector('.btn-icon');
        const text = muteBtn.querySelector('.btn-text');

        if (isMuted) {
            muteBtn.className = 'btn btn-audio-off';
            if (icon) icon.textContent = '🔇';
            if (text) text.textContent = 'Modo Mudo';
            appendDebug("Áudio do assistente silenciado.");
        } else {
            muteBtn.className = 'btn btn-audio-on';
            if (icon) icon.textContent = '🔊';
            if (text) text.textContent = 'Áudio Ativado';
            appendDebug("Áudio do assistente ativado.");
        }

        window.api.toggleMute(isMuted);
    });
}

// =============================================================================
// IPC Callbacks — Estado do Sistema
// =============================================================================
window.api.onStateChanged((data) => {
    const stateRaw = typeof data === 'object' && data !== null ? data.state : data;
    const state = stateRaw ? String(stateRaw).toUpperCase() : '';
    backendState = state;

    // Limpa classes de estado anteriores
    statusDot.className = 'dot';

    switch (state) {
        case 'STARTING':
        case 'INITIALIZING':
            statusDot.classList.add('dot-initializing');
            statusText.textContent = 'Inicializando...';
            // Chat permanece habilitado — modelo Text-First!
            break;
        case 'READY':
        case 'IDLE':
        case 'WAITING_INPUT':
            statusDot.classList.add('dot-ready');
            statusText.textContent = 'Disponível';
            chatInput.disabled = false;
            sendBtn.disabled = false;
            chatInput.placeholder = "Digite sua mensagem aqui...";
            break;
        case 'PROCESSING':
            statusDot.classList.add('dot-processing');
            statusText.textContent = 'Processando...';
            chatInput.disabled = true;
            sendBtn.disabled = true;
            break;
        case 'RESPONDING':
            statusDot.classList.add('dot-responding');
            statusText.textContent = 'Respondendo por voz...';
            chatInput.disabled = true;
            sendBtn.disabled = true;
            break;
        case 'STOPPING':
            statusDot.classList.add('dot-starting');
            statusText.textContent = 'Encerrando...';
            break;
        case 'ERROR':
            statusDot.classList.add('dot-error');
            statusText.textContent = 'Erro fatal';
            chatInput.disabled = true;
            sendBtn.disabled = true;
            break;
    }
});

// =============================================================================
// IPC Callbacks — Mensagens do Chat
// =============================================================================
window.api.onUserMessage((data) => {
    const text = typeof data === 'object' && data !== null ? data.text : data;
    if (text) appendMessage('user', text);
});

window.api.onAssistantMessage((data) => {
    const text = typeof data === 'object' && data !== null ? data.text : data;
    if (text) appendMessage('assistant', text);
});

// =============================================================================
// IPC Callbacks — Status do Modo Voz (NOVO)
// =============================================================================
window.api.onVoiceModeStatus((payload) => {
    if (!payload) return;

    const { available, tts_ready, mic_ready, listening, error } = payload;

    // Remove estado de carregamento do toggle
    voiceModeSwitch.classList.remove('loading');

    if (listening) {
        // Ativamente escutando
        voiceModeEnabled = true;
        voiceModeCheckbox.checked = true;
        voiceToggleContainer.classList.add('voice-active');
        updateVoiceBadge('listening', '🎙️', 'Escutando...');
        appendDebug("Microfone ativamente escutando...", "success");

    } else if (available && (tts_ready || mic_ready)) {
        // Modo voz ativo mas não escutando neste instante
        voiceModeEnabled = true;
        voiceModeCheckbox.checked = true;
        voiceToggleContainer.classList.add('voice-active');

        if (tts_ready && mic_ready) {
            updateVoiceBadge('active', '✅', 'Voz ativa (TTS + Mic)');
        } else if (tts_ready) {
            updateVoiceBadge('partial', '🔊', 'Apenas TTS (sem mic)');
        } else if (mic_ready) {
            updateVoiceBadge('partial', '🎤', 'Apenas Mic (sem TTS)');
        }

    } else if (error) {
        // Falha ao ativar — hardware não detectado
        voiceModeEnabled = false;
        voiceModeCheckbox.checked = false;
        voiceToggleContainer.classList.remove('voice-active');
        updateVoiceBadge('error', '⚠️', error.length > 40 ? 'Hardware indisponível' : error);
        appendDebug(`Modo voz indisponível: ${error}`, 'error');

    } else {
        // Desativado normalmente
        voiceModeEnabled = false;
        voiceModeCheckbox.checked = false;
        voiceToggleContainer.classList.remove('voice-active');
        updateVoiceBadge('inactive', '🔇', 'Desativado');
    }
});

// Compatibilidade: microphone-status antigo (se usado)
window.api.onMicrophoneStatus((payload) => {
    // Redireciona para o novo handler
    if (payload) {
        window.api.onVoiceModeStatus && null; // já tratado via voice-mode-status
    }
});

// =============================================================================
// IPC Callbacks — Debug, Erros, System Ready
// =============================================================================
window.api.onDebugLog((data) => {
    const message = typeof data === 'object' && data !== null ? data.message : data;
    if (message) appendDebug(message);
});

window.api.onError((data) => {
    const message = typeof data === 'object' && data !== null ? data.message : data;
    if (message) appendDebug(`Erro: ${message}`, 'error');
});

window.api.onSystemReady(() => {
    appendDebug("Sistema pronto para interações!", 'success');
});