/**
 * M23: o Electron como cliente da API do núcleo (app/servidor.py).
 *
 * - Se o servidor já está rodando (por exemplo, iniciado sem janela para o celular), só conecta.
 * - Senão, inicia "python -u app/servidor.py" e espera ele responder em /api/saude.
 * - Eventos do núcleo chegam por SSE (/api/eventos) e viram os mesmos canais IPC de antes;
 *   comandos vão por POST (/api/mensagens e /api/comandos) com o token local do PC.
 */
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const RAIZ = __dirname;
const ARQUIVO_TOKEN = path.join(RAIZ, 'core', 'database', 'token-local.txt');

function portaConfigurada() {
    if (process.env.API_PORTA) return Number(process.env.API_PORTA);
    try {
        // Lê só a linha API_PORTA do .env (nenhum outro valor do arquivo é usado aqui)
        const linha = fs.readFileSync(path.join(RAIZ, '.env'), 'utf-8').split(/\r?\n/).find(l => /^\s*API_PORTA\s*=/.test(l));
        if (linha) return Number(linha.split('=')[1].trim()) || 8765;
    } catch (e) { /* sem .env */ }
    return 8765;
}

const BASE = `http://127.0.0.1:${portaConfigurada()}`;
const esperar = (ms) => new Promise(r => setTimeout(r, ms));

class ClienteApi {
    constructor({ python, aoEvento, aoLog, aoErro }) {
        this.python = python;
        this.aoEvento = aoEvento;
        this.aoLog = aoLog || (() => {});
        this.aoErro = aoErro || (() => {});
        this.processo = null;          // só existe se este Electron iniciou o servidor
        this.token = null;
        this.ultimoId = 0;
        this.encerrando = false;
    }

    async saudavel() {
        try {
            const r = await fetch(`${BASE}/api/saude`, { signal: AbortSignal.timeout(1500) });
            return r.ok;
        } catch (e) { return false; }
    }

    async iniciar() {
        if (await this.saudavel()) {
            this.aoLog('Servidor do assistente já estava rodando: conectando.');
        } else {
            this.aoLog('Iniciando o servidor do assistente...');
            this.processo = spawn(this.python, ['-u', 'app/servidor.py'], { cwd: RAIZ });
            this.processo.on('error', (erro) => this.aoErro(`Não foi possível iniciar o Python ("${this.python}"): ${erro.message}`));
            this.processo.stdout.on('data', (d) => console.log(`[servidor] ${d.toString().trim()}`));
            this.processo.stderr.on('data', (d) => console.error(`[servidor] ${d.toString().trim()}`));
            this.processo.on('exit', (codigo) => {
                if (!this.encerrando) this.aoErro(`O servidor do assistente encerrou (código ${codigo}).`);
            });
            let pronto = false;
            for (let i = 0; i < 240 && !pronto; i++) {   // até 2 minutos
                await esperar(500);
                pronto = await this.saudavel();
            }
            if (!pronto) throw new Error('O servidor do assistente não respondeu em 2 minutos.');
        }
        for (let i = 0; i < 40 && !this.token; i++) {
            try { this.token = fs.readFileSync(ARQUIVO_TOKEN, 'utf-8').trim(); } catch (e) { await esperar(250); }
        }
        if (!this.token) throw new Error('Token local do PC não encontrado (core/database/token-local.txt).');
        this.conectarEventos();
    }

    async conectarEventos() {
        let espera = 1000;
        while (!this.encerrando) {
            try {
                const resposta = await fetch(`${BASE}/api/eventos`, { headers: { Authorization: `Bearer ${this.token}` } });
                if (resposta.status === 401) {   // token trocado (revogado): relê o arquivo
                    try { this.token = fs.readFileSync(ARQUIVO_TOKEN, 'utf-8').trim(); } catch (e) { /* segue */ }
                    throw new Error('token recusado');
                }
                if (!resposta.ok || !resposta.body) throw new Error(`HTTP ${resposta.status}`);
                espera = 1000;
                await this.lerFluxo(resposta.body);
            } catch (erro) {
                if (this.encerrando) return;
                console.log(`Eventos desconectados (${erro.message}); tentando de novo em ${espera / 1000}s.`);
            }
            await esperar(espera);
            espera = Math.min(espera * 2, 15000);
        }
    }

    async lerFluxo(corpo) {
        const leitor = corpo.getReader();
        const decodificador = new TextDecoder('utf-8');
        let buffer = '';
        while (!this.encerrando) {
            const { value, done } = await leitor.read();
            if (done) return;
            buffer += decodificador.decode(value, { stream: true }).replace(/\r\n/g, '\n');
            let fim;
            while ((fim = buffer.indexOf('\n\n')) >= 0) {
                const bloco = buffer.slice(0, fim);
                buffer = buffer.slice(fim + 2);
                this.tratarBloco(bloco);
            }
        }
    }

    tratarBloco(bloco) {
        let tipo = 'message';
        const dados = [];
        for (const linha of bloco.split('\n')) {
            if (linha.startsWith('event:')) tipo = linha.slice(6).trim();
            else if (linha.startsWith('data:')) dados.push(linha.slice(5).replace(/^ /, ''));
        }
        if (!dados.length) return;   // comentário de manutenção (ping)
        let conteudo;
        try { conteudo = JSON.parse(dados.join('\n')); } catch (e) { return; }
        if (tipo === 'historico') {
            // Ao (re)conectar: o que ainda não foi mostrado nesta janela, e o estado atual
            for (const evento of conteudo.eventos || []) this.entregar(evento);
            if (conteudo.estado) this.aoEvento('state_changed', { state: conteudo.estado });
        } else if (tipo === 'evento') {
            this.entregar(conteudo);
        }
    }

    entregar(evento) {
        if (!evento || typeof evento.id !== 'number' || evento.id <= this.ultimoId) return;
        this.ultimoId = evento.id;
        this.aoEvento(evento.type, evento.payload);
    }

    async enviar(tipo, payload = {}) {
        const mensagem = tipo === 'send_text';
        const url = mensagem ? `${BASE}/api/mensagens` : `${BASE}/api/comandos`;
        const corpo = mensagem ? { texto: payload.text } : { type: tipo, payload };
        try {
            const r = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.token}` },
                body: JSON.stringify(corpo),
            });
            if (!r.ok) {
                const erro = await r.json().catch(() => ({}));
                this.aoErro(`O assistente recusou o pedido (${r.status}): ${erro.erro || 'erro desconhecido'}`);
            }
        } catch (erro) {
            this.aoErro(`Sem conexão com o servidor do assistente: ${erro.message}`);
        }
    }

    async encerrar() {
        this.encerrando = true;
        if (!this.processo) return;   // servidor iniciado por fora continua atendendo o celular
        await this.enviar('shutdown');
        await new Promise((resolve) => {
            const limite = setTimeout(() => { try { this.processo.kill(); } catch (e) { /* já saiu */ } resolve(); }, 6000);
            this.processo.once('exit', () => { clearTimeout(limite); resolve(); });
        });
    }
}

module.exports = { ClienteApi, BASE };
