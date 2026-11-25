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

    // M28: cartão da compra aguardando confirmação (dados em centavos; todo texto escapado)
    const reais = (c) => (Number(c || 0) / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    const numero = (q) => Number(q).toLocaleString('pt-BR', { maximumFractionDigits: 3 });
    const dataBr = (iso) => (iso ? String(iso).slice(0, 10).split('-').reverse().join('/') : 'sem data');

    function cartaoCompra(cartao, maxItens = 8) {
        return (cartao.compras || []).map((c) => {
            const nota = [c.numero_nf ? `NF ${escapar(c.numero_nf)}${c.serie_nf ? ` série ${escapar(c.serie_nf)}` : ''}` : '',
                          c.emissao ? `emitida às ${escapar(String(c.emissao).slice(11, 16))}` : ''].filter(Boolean).join(' · ');
            const itens = c.itens || [];
            const mostrar = itens.length > maxItens + 1 ? itens.slice(0, maxItens) : itens;
            const linhas = mostrar.map((i) => `
                <tr><td>${escapar(i.produto)}${i.obs ? `<small>📝 ${escapar(i.obs)}</small>` : ''}</td>
                    <td class="num qtd">${numero(i.quantidade)} ${escapar(i.unidade)}</td>
                    <td class="num">${reais(i.total_centavos)}</td></tr>`).join('');
            const resto = itens.length - mostrar.length;
            const extra = resto > 0 ? `<details class="cartao-mais"><summary>+ ${resto} ${resto === 1 ? 'item' : 'itens'}</summary><table>${
                itens.slice(mostrar.length).map((i) => `<tr><td>${escapar(i.produto)}</td><td class="num qtd">${numero(i.quantidade)} ${escapar(i.unidade)}</td><td class="num">${reais(i.total_centavos)}</td></tr>`).join('')
            }</table></details>` : '';
            return `<div class="cartao-compra">
                <div class="cartao-topo"><div><div class="cartao-loja">${escapar(c.loja)}</div>
                    <div class="cartao-meta">${dataBr(c.data)}${nota ? ` · ${nota}` : ''} · ${itens.length} ${itens.length === 1 ? 'item' : 'itens'}</div></div>
                    <div class="cartao-total">${reais(c.total_centavos)}</div></div>
                ${c.obs ? `<div class="cartao-obs">📝 ${escapar(c.obs)}</div>` : ''}
                <table class="cartao-itens">${linhas}</table>${extra}
                ${c.desconto_centavos ? `<div class="cartao-obs">Desconto de ${reais(c.desconto_centavos)} já distribuído nos itens.</div>` : ''}
            </div>`;
        }).join('');
    }

    const api = { escapar, formatarMensagem, botoesDeResposta, cartaoCompra };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    raiz.Formatar = api;
})(typeof window !== 'undefined' ? window : globalThis);
