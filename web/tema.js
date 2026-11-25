// M28: tema escuro por padrão. ?tema=claro|escuro (vindo da janela do PC) vale primeiro; depois a escolha guardada.
(function () {
    let tema = null;
    try { tema = new URLSearchParams(location.search).get('tema'); } catch (e) { /* sem URL */ }
    try { tema = tema || localStorage.getItem('tema'); } catch (e) { /* sem armazenamento */ }
    tema = tema === 'claro' ? 'claro' : 'escuro';
    document.documentElement.dataset.tema = tema;
    const meta = () => document.querySelector('meta[name="theme-color"]');
    const aplicar = (novo) => {
        document.documentElement.dataset.tema = novo;
        try { localStorage.setItem('tema', novo); } catch (e) { /* vale até fechar */ }
        if (meta()) meta().setAttribute('content', novo === 'claro' ? '#ffffff' : '#171c1a');
        const b = document.getElementById('tema-btn');
        if (b) b.setAttribute('aria-label', novo === 'claro' ? 'Mudar para o tema escuro' : 'Mudar para o tema claro');
    };
    document.addEventListener('DOMContentLoaded', () => {
        aplicar(document.documentElement.dataset.tema);
        const b = document.getElementById('tema-btn');
        if (b) b.addEventListener('click', () => aplicar(document.documentElement.dataset.tema === 'claro' ? 'escuro' : 'claro'));
    });
})();
