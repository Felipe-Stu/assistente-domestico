// I04: guarda a "casca" da página para abrir instalada; a conversa e os dados sempre vêm do PC (nada da API fica em cache).
const CACHE = 'assistente-v1';
const CASCA = ['/', '/web/estilo.css', '/web/app.js', '/web/formatar.js', '/web/icone-192.png', '/web/icone-512.png', '/manifest.webmanifest'];
self.addEventListener('install', (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CASCA)).then(() => self.skipWaiting())));
self.addEventListener('activate', (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))));
self.addEventListener('fetch', (e) => {
    const url = new URL(e.request.url);
    if (e.request.method !== 'GET' || url.pathname.startsWith('/api/') || url.pathname.startsWith('/entrar')) return;
    e.respondWith(fetch(e.request).then((r) => {
        const copia = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copia));
        return r;
    }).catch(() => caches.match(e.request)));
});
