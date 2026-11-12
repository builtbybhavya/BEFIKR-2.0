const CACHE = "befikr-shell-v7";
const SHELL = ["/", "/styles.css?v=5", "/app.js", "/manifest.webmanifest", "/assets/befikr-home-logo.png", "/assets/befikr-favicon.png?v=2", "/assets/befikr-icon-180.png?v=2", "/assets/befikr-icon-192.png?v=2", "/assets/befikr-icon-512.png?v=2", "/assets/befikr-icon-maskable-512.png?v=2"];
self.addEventListener("install", event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))));
self.addEventListener("activate", event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  event.respondWith(fetch(event.request).then(response => {
    const copy = response.clone();
    caches.open(CACHE).then(cache => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request).then(cached => cached || caches.match("/"))));
});
