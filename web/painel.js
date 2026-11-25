/**
 * I06: painel de gastos. Os números vêm do PC (consultas prontas, em centavos):
 *   /api/gastos/resumo   cartões, meses, lojas e últimas compras
 *   /api/gastos/detalhe  categorias > grupos (ex.: Carnes > Frango) > itens, no período ou num mês
 */
const reais = (c) => (c / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const esc = (t) => Formatar.escapar(t);
const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const CORES = ['#14b8a6', '#f59e0b', '#60a5fa', '#f87171', '#a78bfa', '#f472b6', '#84cc16', '#fb923c', '#22d3ee', '#94a3b8'];
const $ = (id) => document.getElementById(id);

const estado = { meses: '12', mes: null, categoria: null, grupo: null };
try {   // vindo de um gráfico da conversa: abre direto no mês
    const mesUrl = new URLSearchParams(location.search).get('mes');
    if (/^\d{4}-(0[1-9]|1[0-2])$/.test(mesUrl || '')) estado.mes = mesUrl;
} catch (e) { /* sem URL */ }
const dataBr = (iso) => iso.split('-').reverse().join('/');
const qtd = (q, u) => `${Number(q).toLocaleString('pt-BR', { maximumFractionDigits: 3 })} ${esc(u)}`;

function aviso(r) {
    const el = $('aviso');
    el.hidden = false;
    el.textContent = r && r.status === 401 ? 'Sem acesso: abra o link gerado no PC (novo-dispositivo.bat).'
                                           : 'Não consegui falar com o PC de casa.';
}

async function pedir(url) {
    const r = await fetch(url).catch(() => null);
    if (!r || !r.ok) { aviso(r); return null; }
    $('aviso').hidden = true;
    return r.json();
}

function barrasHorizontais(el, linhas, chave) {
    const maior = Math.max(1, ...linhas.map((l) => l.centavos));
    el.innerHTML = linhas.length ? linhas.map((l) => `
        <div class="barra-h"><span>${esc(l[chave])}</span>
        <span class="trilho"><span class="cheio" style="width:${(100 * l.centavos / maior).toFixed(1)}%"></span></span>
        <span>${reais(l.centavos)}</span></div>`).join('') : '<p>Sem compras no período.</p>';
}

function graficoMeses(el, porMes) {
    // Desenhado na largura real do quadro: texto legível no celular e sem gráfico gigante no PC
    const largura = Math.max(300, Math.round(el.clientWidth || 640)), altura = 210, margem = 8, n = porMes.length;
    const comValor = (largura - margem) / n >= 54;
    const maior = Math.max(1, ...porMes.map((m) => m.centavos));
    const passo = (largura - margem) / n, barra = passo * 0.7;
    const barras = porMes.map((m, i) => {
        const h = Math.max(m.centavos ? 2 : 0, (altura - 50) * m.centavos / maior);
        const x = margem + i * passo + (passo - barra) / 2, y = altura - 20 - h;
        const [ano, mes] = m.mes.split('-');
        const ativo = estado.mes === m.mes, apagado = estado.mes && !ativo;
        return `<g class="mes-clicavel" data-mes="${m.mes}" tabindex="0" role="button" aria-label="${MESES[+mes - 1]}/${ano}: ${reais(m.centavos)}">
                  <rect x="${(margem + i * passo).toFixed(1)}" y="0" width="${passo.toFixed(1)}" height="${altura}" fill="transparent"/>
                  <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barra.toFixed(1)}" height="${h.toFixed(1)}" rx="3"
                        class="coluna-mes${ativo ? ' ativa' : ''}" opacity="${apagado ? 0.45 : 1}"><title>${MESES[+mes - 1]}/${ano}: ${reais(m.centavos)}</title></rect>
                  <text x="${(x + barra / 2).toFixed(1)}" y="${altura - 6}" text-anchor="middle" class="${ativo ? 'mes-ativo' : ''}">${MESES[+mes - 1]}</text>
                  ${comValor && m.centavos ? `<text x="${(x + barra / 2).toFixed(1)}" y="${(y - 5).toFixed(1)}" text-anchor="middle" class="valor-mes">${reais(m.centavos).replace(',00', '').replace(/,\d\d$/, '')}</text>` : ''}
                </g>`;
    }).join('');
    el.innerHTML = `<svg viewBox="0 0 ${largura} ${altura}" width="${largura}" height="${altura}" role="img" aria-label="Gastos por mês">${barras}</svg>`;
}

function rosca(linhas, total) {
    // Até 8 fatias; o resto vira "Outros" (só no gráfico: a lista ao lado mostra tudo)
    const fatias = linhas.slice(0, 8).map((l, i) => ({ ...l, cor: CORES[i] }));
    const resto = linhas.slice(8).reduce((s, l) => s + l.centavos, 0);
    if (resto > 0) fatias.push({ rotulo: 'Outros', centavos: resto, cor: CORES[9] });
    const r = 60, volta = 2 * Math.PI * r;
    let andado = 0;
    const arcos = fatias.map((f) => {
        const parte = total ? (f.centavos / total) * volta : 0;
        const arco = `<circle r="${r}" cx="80" cy="80" fill="none" stroke="${f.cor}" stroke-width="28"
                        stroke-dasharray="${parte.toFixed(2)} ${(volta - parte).toFixed(2)}" stroke-dashoffset="${(-andado).toFixed(2)}"
                        transform="rotate(-90 80 80)"><title>${esc(f.rotulo)}: ${reais(f.centavos)}</title></circle>`;
        andado += parte;
        return arco;
    }).join('');
    return `<svg class="rosca" viewBox="0 0 160 160" role="img" aria-label="Divisão dos gastos">${arcos}
              <text x="80" y="76" text-anchor="middle" class="rosca-rotulo">total</text>
              <text x="80" y="94" text-anchor="middle" class="rosca-valor">${reais(total)}</text></svg>`;
}

function listaClicavel(linhas, total) {
    return `<div class="lista-nivel">${linhas.map((l, i) => {
        const pct = total ? (100 * l.centavos / total) : 0;
        return `<button type="button" class="linha-nivel" data-chave="${esc(l.chave)}">
                  <span class="ponto" style="background:${CORES[Math.min(i, 9)]}"></span>
                  <span class="nome">${esc(l.rotulo)}<small>${l.itens} ${l.itens === 1 ? 'item' : 'itens'}</small></span>
                  <span class="trilho"><span class="cheio" style="width:${pct.toFixed(1)}%;background:${CORES[Math.min(i, 9)]}"></span></span>
                  <span class="valor">${reais(l.centavos)}<small>${pct.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%</small></span>
                  <span class="seta">›</span>
                </button>`;
    }).join('')}</div>`;
}

function tabelaItens(itens) {
    return `<table class="tabela itens"><thead><tr><th>Data</th><th>Produto e loja</th><th class="num">Qtd.</th><th class="num">Valor</th></tr></thead>
            <tbody>${itens.map((i) => `<tr><td>${dataBr(i.data)}</td><td>${esc(i.produto)}${i.obs ? ` 📝 ${esc(i.obs)}` : ''}<small>${esc(i.loja)}</small></td>
            <td class="num">${qtd(i.quantidade, i.unidade)}</td><td class="num">${reais(i.centavos)}</td></tr>`).join('')}</tbody></table>`;
}

async function carregarDetalhe() {
    const p = new URLSearchParams({ meses: estado.meses });
    if (estado.mes) p.set('mes', estado.mes);
    if (estado.categoria) p.set('categoria', estado.categoria);
    if (estado.grupo) p.set('grupo', estado.grupo);
    const d = await pedir(`/api/gastos/detalhe?${p}`);
    if (!d) return;
    $('trilha').innerHTML = d.trilha.map((t, i) => {
        const ultimo = i === d.trilha.length - 1;
        return ultimo ? `<span class="atual">${esc(t.rotulo)}</span>`
                      : `<button type="button" data-nivel="${t.nivel}">${esc(t.rotulo)}</button><span class="sep">›</span>`;
    }).join('') + (estado.mes ? ` <button type="button" class="limpar-mes" title="Voltar ao período inteiro">✕ todos os meses</button>` : '');
    $('resumo-nivel').textContent = `${reais(d.total_centavos)} em ${d.compras} ${d.compras === 1 ? 'compra' : 'compras'}`
        + (d.nivel === 'categorias' ? ' · toque numa categoria para abrir' : d.nivel === 'grupos' ? ' · toque num grupo para ver os itens' : '');
    const el = $('detalhe');
    if (d.nivel === 'itens') {
        el.innerHTML = d.itens.length ? tabelaItens(d.itens) : '<p>Sem itens.</p>';
    } else if (!d.linhas.length) {
        el.innerHTML = '<p>Sem compras neste período.</p>';
    } else {
        el.innerHTML = `<div class="grafico-nivel">${rosca(d.linhas, d.total_centavos)}${listaClicavel(d.linhas, d.total_centavos)}</div>`;
    }
}

async function carregarResumo() {
    const d = await pedir(`/api/gastos/resumo?meses=${estado.meses}`);
    if (!d) return;
    const comGasto = d.por_mes.filter((m) => m.centavos > 0).length;
    const media = comGasto ? d.total_centavos / comGasto : 0;
    $('cartoes').innerHTML = `
        <div class="cartao principal"><div class="rotulo">Total no período</div><div class="valor"><span>${reais(d.total_centavos)}</span></div></div>
        <div class="cartao"><div class="rotulo">Média por mês com compras</div><div class="valor">${reais(Math.round(media))}</div></div>
        <div class="cartao"><div class="rotulo">Compras</div><div class="valor">${d.compras}</div></div>`;
    estado.porMes = d.por_mes;
    graficoMeses($('por-mes'), d.por_mes);
    barrasHorizontais($('por-loja'), d.por_loja, 'loja');
    $('ultimas').innerHTML = d.ultimas.map((c) => `
        <tr><td>${esc(dataBr(c.data))}</td><td>${esc(c.loja)}${c.obs ? ` 📝 ${esc(c.obs)}` : ''}</td>
        <td class="num">${reais(c.centavos)}</td></tr>`).join('') || '<tr><td>Sem compras no período.</td></tr>';
}

function escolherMes(mes) {
    estado.mes = estado.mes === mes ? null : mes;   // tocar de novo no mesmo mês volta ao período
    estado.categoria = null;
    estado.grupo = null;
    if (estado.porMes) graficoMeses($('por-mes'), estado.porMes);
    carregarDetalhe();
    $('bloco-detalhe').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

$('por-mes').addEventListener('click', (e) => {
    const g = e.target.closest('[data-mes]');
    if (g) escolherMes(g.dataset.mes);
});
$('por-mes').addEventListener('keydown', (e) => {
    const g = e.target.closest('[data-mes]');
    if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); escolherMes(g.dataset.mes); }
});
$('detalhe').addEventListener('click', (e) => {
    const b = e.target.closest('.linha-nivel');
    if (!b) return;
    if (!estado.categoria) estado.categoria = b.dataset.chave;
    else estado.grupo = b.dataset.chave;
    carregarDetalhe();
});
$('trilha').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.classList.contains('limpar-mes')) { escolherMes(estado.mes); return; }
    if (b.dataset.nivel === 'periodo') { estado.categoria = null; estado.grupo = null; }
    if (b.dataset.nivel === 'categoria') estado.grupo = null;
    carregarDetalhe();
});
$('meses').addEventListener('change', (e) => {
    Object.assign(estado, { meses: e.target.value, mes: null, categoria: null, grupo: null });
    carregarResumo();
    carregarDetalhe();
});
let espera = null;
window.addEventListener('resize', () => {
    clearTimeout(espera);
    espera = setTimeout(() => { if (estado.porMes) graficoMeses($('por-mes'), estado.porMes); }, 150);
});
carregarResumo();
carregarDetalhe();
