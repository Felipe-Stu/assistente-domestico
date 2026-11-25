/** I06: painel de gastos. Os números vêm de /api/gastos/resumo (consultas prontas em centavos, no PC). */
const reais = (c) => (c / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const esc = (t) => Formatar.escapar(t);
const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

function barrasHorizontais(el, linhas, chave) {
    const maior = Math.max(1, ...linhas.map((l) => l.centavos));
    el.innerHTML = linhas.length ? linhas.map((l) => `
        <div class="barra-h"><span>${esc(l[chave])}</span>
        <span class="trilho"><span class="cheio" style="width:${(100 * l.centavos / maior).toFixed(1)}%"></span></span>
        <span>${reais(l.centavos)}</span></div>`).join('') : '<p>Sem compras no período.</p>';
}

function graficoMeses(el, porMes) {
    const largura = 640, altura = 180, margem = 24, n = porMes.length;
    const maior = Math.max(1, ...porMes.map((m) => m.centavos));
    const passo = (largura - margem) / n, barra = passo * 0.7;
    const barras = porMes.map((m, i) => {
        const h = (altura - 40) * m.centavos / maior;
        const x = margem + i * passo + (passo - barra) / 2, y = altura - 20 - h;
        const [ano, mes] = m.mes.split('-');
        return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barra.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="#3b82f6">
                  <title>${MESES[+mes - 1]}/${ano}: ${reais(m.centavos)}</title></rect>
                <text x="${(x + barra / 2).toFixed(1)}" y="${altura - 6}" text-anchor="middle">${MESES[+mes - 1]}</text>`;
    }).join('');
    el.innerHTML = `<svg viewBox="0 0 ${largura} ${altura}" width="100%" role="img" aria-label="Gastos por mês">${barras}</svg>`;
}

async function carregar() {
    const meses = document.getElementById('meses').value;
    const aviso = document.getElementById('aviso');
    const r = await fetch(`/api/gastos/resumo?meses=${meses}`).catch(() => null);
    if (!r || !r.ok) {
        aviso.hidden = false;
        aviso.textContent = r && r.status === 401 ? 'Sem acesso: abra o link gerado no PC (novo-dispositivo.bat).'
                                                   : 'Não consegui falar com o PC de casa.';
        return;
    }
    aviso.hidden = true;
    const d = await r.json();
    const media = d.por_mes.length ? d.total_centavos / d.por_mes.length : 0;
    document.getElementById('cartoes').innerHTML = `
        <div class="cartao"><div class="rotulo">Total no período</div><div class="valor">${reais(d.total_centavos)}</div></div>
        <div class="cartao"><div class="rotulo">Média por mês</div><div class="valor">${reais(Math.round(media))}</div></div>
        <div class="cartao"><div class="rotulo">Compras</div><div class="valor">${d.compras}</div></div>`;
    graficoMeses(document.getElementById('por-mes'), d.por_mes);
    barrasHorizontais(document.getElementById('por-categoria'), d.por_categoria, 'categoria');
    barrasHorizontais(document.getElementById('por-loja'), d.por_loja, 'loja');
    document.getElementById('ultimas').innerHTML = d.ultimas.map((c) => `
        <tr><td>${esc(c.data.split('-').reverse().join('/'))}</td><td>${esc(c.loja)}${c.obs ? ` 📝 ${esc(c.obs)}` : ''}</td>
        <td class="num">${reais(c.centavos)}</td></tr>`).join('') || '<tr><td>Sem compras no período.</td></tr>';
}

document.getElementById('meses').addEventListener('change', carregar);
carregar();
