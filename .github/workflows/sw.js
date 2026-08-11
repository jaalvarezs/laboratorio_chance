const CACHE = 'lab-chance-v29';
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['./', './index.html', './manifest.json'])));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))));
});
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  // captura_automatica.js lo reescribe la captura automática todos los
  // días -- red primero (para ver el dato del día apenas haya conexión),
  // con la copia en caché como respaldo solo si no hay internet. Sin este
  // caso especial, una vez que el navegador lo cacheara una vez se
  // quedaría sirviendo esa misma copia para siempre y la autocarga nunca
  // vería nada nuevo.
  if (e.request.url.endsWith('/captura_automatica.js')) {
    e.respondWith(
      fetch(e.request).then(resp => {
        const clon = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, clon)).catch(() => {});
        return resp;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(resp => {
      const clon = resp.clone();
      caches.open(CACHE).then(c => c.put(e.request, clon)).catch(() => {});
      return resp;
    }).catch(() => caches.match('./index.html')))
  );
});

