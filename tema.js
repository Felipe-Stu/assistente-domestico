// M28: tema escuro por padrão; a escolha fica guardada nesta janela (localStorage). Roda no <head> para não piscar.
(function () {
    let tema = 'escuro';
    try { tema = localStorage.getItem('tema') || 'escuro'; } catch (e) { /* sem armazenamento: escuro */ }
    document.documentElement.dataset.tema = tema === 'claro' ? 'claro' : 'escuro';
})();
