/**
 * M23: o Electron como cliente da API do núcleo (app/servidor.py).
 *
 * - Se o servidor já está rodando (por exemplo, iniciado sem janela para o celular), só conecta.
 * - Senão, inicia "python -u app/servidor.py" separado da janela e espera ele responder em /api/saude.
 *   Fechar a janela não desliga o servidor (o celular continua funcionando); desligar é um pedido explícito.
 * - Eventos do núcleo chegam por SSE (/api/eventos) e viram os mesmos canais IPC de antes;
 *   comandos vão por POST (/api/mensagens e /api/comandos) com o token local do PC.
 */
const fs = require('fs');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

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
            // Bibliotecas da V5.5 presentes? (o servidor roda separado: a saída dele não chega até aqui)
            const teste = spawnSync(this.python, ['-c', 'import starlette, uvicorn, sse_starlette, multipart'], { cwd: RAIZ, windowsHide: true });
            if (teste.error) throw new Error(`Não foi possível iniciar o Python ("${this.python}"): ${teste.error.message}`);
            if (teste.status !== 0) {
                throw new Error('Faltam as bibliotecas do servidor (V5.5). Feche, rode instalar-dependencias.bat e abra de novo. '
                              + 'Para usar o modo antigo enquanto isso: defina ASSISTENTE_PONTE=stdin.');
            }
            this.aoLog('Iniciando o servidor do assistente...');
            this.processo = spawn(this.python, ['-u', 'app/servidor.py'], { cwd: RAIZ, detached: true, stdio: 'ignore', windowsHide: true });
            let saiu = false;
            this.processo.on('error', (erro) => { saiu = true; this.aoErro(`Não foi possível iniciar o servidor: ${erro.message}`); });
            this.processo.on('exit', (codigo) => {
                saiu = true;
                if (!this.encerrando) this.aoErro(`O servidor do assistente encerrou (código ${codigo}). Veja a pasta Logs.`);
            });
            this.processo.unref();   // continua vivo quando a janela fecha
            let pronto = false;
            for (let i = 0; i < 240 && !pronto && !saiu; i++) {   // até 2 minutos, ou até o processo sair
                await esperar(500);
                pronto = await this.saudavel();
            }
            if (!pronto) throw new Error(saiu ? 'O servidor do assistente fechou ao iniciar (porta ocupada ou erro: veja a pasta Logs).'
                                              : 'O servidor do assistente não respondeu em 2 minutos.');
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
            // Servidor reiniciado: a numeração dos eventos recomeça
            if (conteudo.instancia && conteudo.instancia !== this.instancia) {
                if (this.instancia) this.ultimoId = 0;
                this.instancia = conteudo.instancia;
            }
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

    // Fechar a janela: só para de ouvir; o servidor continua (celular e painel seguem funcionando)
    encerrar() {
        this.encerrando = true;
    }

    // Desligar o assistente de verdade (botão ⏻): pede ao servidor para encerrar
    // Leitura com o token local (ex.: resumo de gastos para a coluna da direita)
    async obterJson(caminho) {
        if (!this.token) return null;
        const r = await fetch(`${BASE}${caminho}`, { headers: { Authorization: `Bearer ${this.token}` }, signal: AbortSignal.timeout(8000) });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    }

    async desligarServidor() {
        this.encerrando = true;
        await this.enviar('shutdown');
    }
}

module.exports = { ClienteApi, BASE };
