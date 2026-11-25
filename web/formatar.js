/**
 * M28: formatação das mensagens, usada pela janela do PC (renderer.js) e pela página do celular (web/app.js).
 * Markdown simples e seguro: o texto é escapado antes; só **negrito**, `código`, listas com "- " e quebras de linha.
 * Também decide quais botões de resposta rápida mostrar ("sim", "não", "pular").
 */
(function (raiz) {
    function escapar(texto) {
        return String(texto == null ? '' : texto)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    function emLinha(texto) {
        return texto
            .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`\n]+)`/g, '<code>$1</code>');
    }

    function formatarMensagem(texto) {
        const linhas = escapar(texto).split(/\r?\n/);
        const partes = [];
        let lista = null;
        for (const linha of linhas) {
            const item = linha.match(/^\s*(?:[-*•])\s+(.*)$/);
            if (item) {
                if (!lista) { lista = []; }
                lista.push(`<li>${emLinha(item[1])}</li>`);
                continue;
            }
            if (lista) { partes.push(`<ul>${lista.join('')}</ul>`); lista = null; }
            partes.push(linha.trim() === '' ? '<br>' : `<span class="linha">${emLinha(linha)}</span><br>`);
        }
        if (lista) partes.push(`<ul>${lista.join('')}</ul>`);
        return partes.join('').replace(/(<br>)+$/, '');
    }

    function botoesDeResposta(texto) {
        const t = String(texto || '');
        const botoes = [];
        if (/"sim"/i.test(t) && /"n[ãa]o"/i.test(t)) {
            botoes.push({ rotulo: 'Sim', envio: 'sim', estilo: 'confirmar' });
            botoes.push({ rotulo: 'Não', envio: 'não', estilo: 'cancelar' });
        }
        if (/"pular"/i.test(t)) botoes.push({ rotulo: 'Pular', envio: 'pular', estilo: 'neutro' });
        return botoes;
    }

    const api = { escapar, formatarMensagem, botoesDeResposta };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    raiz.Formatar = api;
})(typeof window !== 'undefined' ? window : globalThis);
