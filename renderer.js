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
const ICONE_PESSOA = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>';
const ICONE_CELULAR = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-label="pelo celular"><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></svg>';

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
// M28: botões de resposta rápida ficam só na última mensagem que os pede
function desativarBotoesAntigos() {
    document.querySelectorAll('.resposta-rapida button').forEach((b) => { b.disabled = true; });
}

function adicionarBotoes(msgElement, text) {
    const botoes = window.Formatar ? window.Formatar.botoesDeResposta(text) : [];
    if (!botoes.length) return;
    const barra = document.createElement('div');
    barra.className = 'resposta-rapida';
    for (const botao of botoes) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = `btn-rapido btn-${botao.estilo}`;
        b.textContent = botao.rotulo;
        b.addEventListener('click', () => {
            desativarBotoesAntigos();
            window.api.sendText(botao.envio);
        });
        barra.appendChild(b);
    }
    msgElement.querySelector('.msg-content').insertBefore(barra, msgElement.querySelector('.msg-time'));
}

function appendMessage(sender, text, retryText = null, opcoes = {}) {
    const msgElement = document.createElement('div');
    msgElement.classList.add('message');
    msgElement.classList.add(sender === 'user' ? 'user-msg' : 'assistant-msg');
    if (sender === 'erro') msgElement.classList.add('erro-msg');

    const avatar = sender === 'user' ? (opcoes.canal === 'celular' ? ICONE_CELULAR : ICONE_PESSOA) : (sender === 'erro' ? '!' : '');
    const timeStr = getFormattedTime();
    const corpo = window.Formatar ? window.Formatar.formatarMensagem(text) : escapeHTML(text);

    msgElement.innerHTML = `
        <div class="msg-avatar" aria-hidden="${avatar === '' ? 'true' : 'false'}">${avatar}</div>
        <div class="msg-content">
            <div class="msg-texto">${corpo}</div>
            <span class="msg-time">${timeStr}${opcoes.canal === 'celular' ? ' · pelo celular' : ''}</span>
        </div>
    `;
    if (sender !== 'user') {
        desativarBotoesAntigos();
        adicionarBotoes(msgElement, text);
    }

    // Botão "Tentar de novo" quando a IA local estava indisponível (reenvia o mesmo texto)
    if (retryText) {
        const retryBtn = document.createElement('button');
        retryBtn.type = 'button';
        retryBtn.className = 'retry-btn';
        retryBtn.textContent = '↻ Tentar de novo';
        retryBtn.addEventListener('click', () => {
            retryBtn.disabled = true;
            retryBtn.textContent = 'Reenviado';
            window.api.sendText(retryText);
        });
        msgElement.querySelector('.msg-content').insertBefore(retryBtn, msgElement.querySelector('.msg-time'));
    }

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
const painelBtn = document.getElementById('painel-btn');
if (painelBtn) painelBtn.addEventListener('click', () => window.api.abrirPainel());
const resumoPainelBtn = document.getElementById('resumo-painel');
if (resumoPainelBtn) resumoPainelBtn.addEventListener('click', () => window.api.abrirPainel());

// =============================================================================
// M28: tema escuro (padrão) / claro, guardado nesta janela
// =============================================================================
const temaBtn = document.getElementById('tema-btn');
function aplicarTema(tema) {
    document.documentElement.dataset.tema = tema;
    try { localStorage.setItem('tema', tema); } catch (e) { /* sem armazenamento: vale só até fechar */ }
    if (temaBtn) {
        const proximo = tema === 'escuro' ? 'claro' : 'escuro';
        document.getElementById('tema-rotulo').textContent = proximo === 'claro' ? 'Claro' : 'Escuro';
        temaBtn.setAttribute('aria-label', `Mudar para o tema ${proximo}`);
    }
}
if (temaBtn) {
    aplicarTema(document.documentElement.dataset.tema === 'claro' ? 'claro' : 'escuro');
    temaBtn.addEventListener('click', () => aplicarTema(document.documentElement.dataset.tema === 'claro' ? 'escuro' : 'claro'));
}

// =============================================================================
// M28: resumo do mês (coluna da direita), lido do servidor
// =============================================================================
const MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const reais = (c) => (c / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
let resumoEmCurso = false;
let ultimoResumo = 0;

async function atualizarResumo(forcar = false) {
    const painel = document.getElementById('resumo');
    if (!painel || !window.api.resumoGastos || resumoEmCurso) return;
    if (!forcar && Date.now() - ultimoResumo < 5000) return;
    resumoEmCurso = true;
    try {
        const dados = await window.api.resumoGastos();
        if (!dados) { painel.hidden = true; return; }   // ponte antiga ou servidor indisponível
        painel.hidden = false;
        const { resumo, mes } = dados;
        const nomeMes = mes.trilha && mes.trilha[0] ? mes.trilha[0].rotulo : 'Este mês';
        document.getElementById('resumo-mes').textContent = `${nomeMes} até agora`;
        document.getElementById('resumo-total').textContent = reais(mes.total_centavos);
        document.getElementById('resumo-compras').textContent = `${mes.compras} ${mes.compras === 1 ? 'compra' : 'compras'}`;
        const maior = Math.max(1, ...resumo.por_mes.map((m) => m.centavos));
        const atual = mes.periodo.inicio.slice(0, 7);
        document.getElementById('resumo-meses').innerHTML = resumo.por_mes.map((m) => {
            const [ano, n] = m.mes.split('-');
            return `<div class="barra-mes${m.mes === atual ? ' atual' : ''}" title="${MESES_CURTOS[+n - 1]}/${ano}: ${reais(m.centavos)}">
                      <span class="coluna" style="height:${(100 * m.centavos / maior).toFixed(1)}%"></span>${MESES_CURTOS[+n - 1]}</div>`;
        }).join('');
        const linhas = (mes.linhas || []).slice(0, 4);
        document.getElementById('resumo-categorias').innerHTML = linhas.length
            ? linhas.map((l) => `<div class="linha"><span>${escapeHTML(l.rotulo)}</span><b>${reais(l.centavos)}</b></div>`).join('')
            : '<p class="vazio">Sem compras neste mês.</p>';
        ultimoResumo = Date.now();
    } catch (erro) {
        appendDebug(`Resumo de gastos indisponível: ${erro.message || erro}`, 'error');
    } finally {
        resumoEmCurso = false;
    }
}
atualizarResumo(true);
setInterval(() => atualizarResumo(true), 60000);
const desligarBtn = document.getElementById('desligar-btn');
if (desligarBtn) desligarBtn.addEventListener('click', () => window.api.desligarAssistente());

// =============================================================================
// Anexos: botão 📎 e arrastar-e-soltar
// =============================================================================
const attachBtn = document.getElementById('attach-btn');
const chatPanel = document.querySelector('.chat-input-area')?.parentElement || document.body;

function mostrarAnexosEnviados(nomes, tentados) {
    if (nomes.length) {
        appendMessage('user', `📎 ${nomes.join(', ')}`);
    }
    if (tentados > nomes.length) {
        appendMessage('assistant', 'Alguns arquivos foram ignorados: envio só HTML da nota, PDF ou foto (JPG, PNG, WEBP).');
    }
}

if (attachBtn) {
    attachBtn.addEventListener('click', async () => {
        const nomes = await window.api.escolherAnexos();
        mostrarAnexosEnviados(nomes, nomes.length);
    });
}

chatPanel.addEventListener('dragover', (e) => {
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types).includes('Files')) return;
    e.preventDefault();
    chatPanel.classList.add('arrastando');
});
chatPanel.addEventListener('dragleave', (e) => {
    if (!chatPanel.contains(e.relatedTarget)) chatPanel.classList.remove('arrastando');
});
chatPanel.addEventListener('drop', async (e) => {
    e.preventDefault();
    chatPanel.classList.remove('arrastando');
    const arquivos = e.dataTransfer ? e.dataTransfer.files : [];
    if (!arquivos.length) return;
    const nomes = await window.api.enviarAnexosSoltos();
    mostrarAnexosEnviados(nomes, arquivos.length);
});
// Arquivo solto fora da área do chat não abre no lugar do aplicativo
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => e.preventDefault());
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
            chatInput.placeholder = "Ex.: quanto gastei no Moreschi este mês?";
            break;
        case 'PROCESSING':
            statusDot.classList.add('dot-processing');
            statusText.textContent = 'Processando...';
            chatInput.disabled = true;
            sendBtn.disabled = true;
            break;
        case 'RESPONDING':
            statusDot.classList.add('dot-responding');
            statusText.textContent = 'Respondendo...';
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
    const isObj = typeof data === 'object' && data !== null;
    const text = isObj ? data.text : data;
    if (text) appendMessage('user', text, null, { canal: isObj ? data.canal : null });
});

// M22: resposta em fluxo — a mesma bolha é atualizada até chegar a mensagem final
let bolhaEmFluxo = null;

window.api.onAssistantDelta((data) => {
    const text = typeof data === 'object' && data !== null ? data.text : data;
    if (!text) return;
    if (!bolhaEmFluxo) {
        appendMessage('assistant', '');
        bolhaEmFluxo = chatMessages.lastElementChild;
        bolhaEmFluxo.classList.add('em-fluxo');
    }
    bolhaEmFluxo.querySelector('.msg-texto').innerHTML = window.Formatar ? window.Formatar.formatarMensagem(text) : escapeHTML(text);
    chatMessages.scrollTop = chatMessages.scrollHeight;
});

window.api.onAssistantMessage((data) => {
    const isObj = typeof data === 'object' && data !== null;
    const text = isObj ? data.text : data;
    if (!text) return;
    if (bolhaEmFluxo) {   // troca o texto parcial pelo final
        bolhaEmFluxo.remove();
        bolhaEmFluxo = null;
    }
    appendMessage('assistant', text, isObj ? data.tentar_novamente || null : null);
    atualizarResumo();   // uma compra pode ter sido gravada ou corrigida
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
    if (!message) return;
    appendDebug(`Erro: ${message}`, 'error');
    if (bolhaEmFluxo) { bolhaEmFluxo.remove(); bolhaEmFluxo = null; }
    appendMessage('erro', message);   // M28: o erro aparece no chat, não só no terminal interno
});

window.api.onSystemReady(() => {
    appendDebug("Sistema pronto para interações!", 'success');
});