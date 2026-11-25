/**
 * I04: página instalável do assistente no celular. Fala com a API do PC (app/servidor.py):
 * mensagens por POST, eventos por SSE (EventSource), foto/arquivo por envio de formulário.
 * A autenticação é o cookie gravado ao abrir o link de /entrar (gerado por novo-dispositivo.bat no PC).
 */
const $ = (id) => document.getElementById(id);
const lista = $('mensagens');
let ultimoId = 0;
let instancia = null;   // muda quando o servidor do PC reinicia (a numeração dos eventos recomeça)
let bolhaEmFluxo = null;

function hora() { return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }

function mostrarAviso(texto) {
    const aviso = $('aviso');
    aviso.textContent = texto || '';
    aviso.hidden = !texto;
}

function desativarBotoes() { document.querySelectorAll('.resposta-rapida button').forEach((b) => { b.disabled = true; }); }

const CORRIGIR = { rotulo: 'Corrigir', envio: null, estilo: 'neutro' };

function pedirCorrecao() {
    const campo = $('texto');
    campo.placeholder = 'O que corrigir? Ex.: o arroz custou 24,90';
    campo.focus();
}

function adicionar(tipo, texto, extra, cartao) {
    const div = document.createElement('div');
    div.className = `msg ${tipo}${cartao ? ' com-cartao' : ''}`;
    const corpo = document.createElement('div');
    corpo.className = 'corpo';
    const desenho = cartao && cartao.tipo === 'grafico' ? Formatar.cartaoGrafico(cartao) : (cartao ? Formatar.cartaoCompra(cartao, 6) : '');
    corpo.innerHTML = cartao   // M28: compra em cartão (ou gráfico), entre a abertura e o pedido de confirmação
        ? Formatar.formatarMensagem(cartao.antes || '') + desenho + Formatar.formatarMensagem(cartao.depois || '')
        : Formatar.formatarMensagem(texto);
    const abrir = corpo.querySelector('.abrir-painel');
    if (abrir) abrir.addEventListener('click', () => { location.href = '/painel' + (abrir.dataset.mes ? `?mes=${abrir.dataset.mes}` : ''); });
    div.appendChild(corpo);
    if (tipo !== 'usuario') {
        desativarBotoes();
        const botoes = cartao && cartao.confirmar
            ? [{ rotulo: 'Sim, gravar', envio: 'sim', estilo: 'confirmar' }, CORRIGIR, { rotulo: 'Não', envio: 'não', estilo: 'cancelar' }]
            : Formatar.botoesDeResposta(cartao ? cartao.texto : texto);
        if (botoes.length) {
            const barra = document.createElement('div');
            barra.className = 'resposta-rapida';
            for (const b of botoes) {
                const botao = document.createElement('button');
                botao.type = 'button';
                botao.className = b.estilo;
                botao.textContent = b.rotulo;
                botao.addEventListener('click', () => {
                    if (b.envio === null) { pedirCorrecao(); return; }   // Corrigir: a compra continua esperando
                    desativarBotoes();
                    enviarTexto(b.envio);
                });
                barra.appendChild(botao);
            }
            div.appendChild(barra);
        }
    }
    const h = document.createElement('span');
    h.className = 'hora';
    h.textContent = hora() + (extra || '');
    div.appendChild(h);
    lista.appendChild(div);
    lista.scrollTop = lista.scrollHeight;
    return div;
}

function estado(nome) {
    const el = $('estado');
    const mapa = { WAITING_INPUT: ['disponível', 'ok'], READY: ['disponível', 'ok'], PROCESSING: ['processando…', 'ocupado'],
                   RESPONDING: ['respondendo…', 'ocupado'], INITIALIZING: ['iniciando…', 'ocupado'], ERROR: ['erro', 'erro'] };
    const [texto, classe] = mapa[nome] || [String(nome || '').toLowerCase(), ''];
    el.textContent = texto;
    el.className = `estado ${classe}`;
}

function tratar(evento) {
    if (!evento || typeof evento.id !== 'number' || evento.id <= ultimoId) return;
    ultimoId = evento.id;
    const p = evento.payload || {};
    switch (evento.type) {
        case 'user_message':
            adicionar('usuario', p.text, p.canal === 'celular' ? ' · celular' : ' · PC');
            break;
        case 'assistant_delta':
            if (!bolhaEmFluxo) { bolhaEmFluxo = adicionar('assistente', ''); bolhaEmFluxo.classList.add('em-fluxo'); }
            bolhaEmFluxo.querySelector('.corpo').innerHTML = Formatar.formatarMensagem(p.text);
            lista.scrollTop = lista.scrollHeight;
            break;
        case 'assistant_message':
            if (bolhaEmFluxo) { bolhaEmFluxo.remove(); bolhaEmFluxo = null; }
            adicionar('assistente', p.text, '', p.cartao);
            break;
        case 'error':
            if (bolhaEmFluxo) { bolhaEmFluxo.remove(); bolhaEmFluxo = null; }
            adicionar('erro', (p && p.message) || String(p));
            break;
        case 'state_changed':
            estado(p.state);
            break;
    }
}

function conectar() {
    const fonte = new EventSource('/api/eventos');
    fonte.addEventListener('historico', (e) => {
        const dados = JSON.parse(e.data);
        if (dados.instancia && dados.instancia !== instancia) {
            if (instancia) ultimoId = 0;
            instancia = dados.instancia;
        }
        (dados.eventos || []).forEach(tratar);
        if (dados.estado) estado(dados.estado);
        mostrarAviso('');
    });
    fonte.addEventListener('evento', (e) => tratar(JSON.parse(e.data)));
    fonte.onerror = () => {
        estado('');
        $('estado').textContent = 'sem conexão…';
        $('estado').className = 'estado erro';
    };
}

async function enviarTexto(texto) {
    try {
        const r = await fetch('/api/mensagens', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                  body: JSON.stringify({ texto }) });
        if (r.status === 401) return mostrarAviso('Acesso expirado ou revogado. Gere um novo link no PC (novo-dispositivo.bat).');
        if (!r.ok) adicionar('erro', `Não enviado (${r.status}).`);
    } catch (e) {
        adicionar('erro', 'Sem conexão com o PC de casa. Confira o Tailscale e se o assistente está aberto.');
    }
}

async function enviarArquivos(arquivos) {
    const dados = new FormData();
    for (const a of arquivos) dados.append('arquivo', a, a.name || 'foto.jpg');
    adicionar('usuario', `📎 ${[...arquivos].map((a) => a.name || 'foto').join(', ')}`, ' · enviando…');
    try {
        const r = await fetch('/api/anexos', { method: 'POST', body: dados });
        const j = await r.json().catch(() => ({}));
        if (j.recusados && j.recusados.length) adicionar('erro', j.recusados.map((x) => `${x.nome}: ${x.motivo}`).join('\n'));
        if (!r.ok && !(j.recusados && j.recusados.length)) adicionar('erro', j.erro || `Envio recusado (${r.status}).`);
    } catch (e) {
        adicionar('erro', 'O envio falhou. Tente de novo quando a conexão voltar.');
    }
}

$('envio').addEventListener('submit', (e) => {
    e.preventDefault();
    const texto = $('texto').value.trim();
    if (!texto) return;
    $('texto').value = '';
    enviarTexto(texto);
});
for (const id of ['camera', 'anexo']) {
    $(id).addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length) enviarArquivos(e.target.files);
        e.target.value = '';
    });
}

(async () => {
    const r = await fetch('/api/eu').catch(() => null);
    if (!r) {
        mostrarAviso('Sem conexão com o PC de casa. Confira se o Tailscale está ligado neste aparelho e se o assistente está aberto no PC.');
        estado('');
        setTimeout(() => location.reload(), 15000);
        return;
    }
    if (r.status === 401) {
        mostrarAviso('Este aparelho ainda não tem acesso. No PC, rode novo-dispositivo.bat e abra aqui o link gerado.');
        estado('');
        return;
    }
    conectar();
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
})();
