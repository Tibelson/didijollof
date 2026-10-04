/* Service worker.
 *
 * Scope for this pass: the app opens and browses offline. Submitting still
 * needs a connection — queued offline submits are deliberately out of scope
 * because they need conflict handling we have not designed yet, and a request
 * that silently "sends" while offline would be worse than one that refuses.
 *
 * Strategy:
 *   app shell (html/css/js/fonts) → cache-first, so a cold start on no signal
 *                                   still paints
 *   GET /api/*                    → network-first with a cache fallback, so a
 *                                   chef sees the last known inventory rather
 *                                   than an error
 *   POST/PUT /api/*               → never cached, never queued; fails loudly
 */

const VERSION = 'didi-v8';
const SHELL = `${VERSION}-shell`;
const DATA = `${VERSION}-data`;

const SHELL_URLS = [
  '/',
  '/index.html',
  '/app.css',
  '/manifest.webmanifest',
  '/js/app.js',
  '/js/api.js',
  '/js/store.js',
  '/js/ui.js',
  '/js/views/login.js',
  '/js/views/check.js',
  '/js/views/review.js',
  '/js/views/sent.js',
  '/js/views/requests.js',
  '/fonts/geist.woff2',
  '/fonts/gabarito.woff2',
  '/fonts/jost.woff2',
  '/fonts/caveat.woff2',
  '/icons/icon.svg',
  '/icons/badge.webp',
  '/icons/mark.webp',
  '/icons/cat/all.webp',
  '/icons/cat/produce.webp',
  '/icons/cat/protein.webp',
  '/icons/cat/spices.webp',
  '/icons/cat/packaging.webp',
];

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL);
    // addAll fails the whole install if any single URL 404s; add individually
    // so one missing icon cannot stop the app being installable.
    await Promise.all(SHELL_URLS.map(url =>
      cache.add(url).catch(() => console.warn('[sw] could not cache', url))));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names
      .filter(n => n !== SHELL && n !== DATA)
      .map(n => caches.delete(n)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;             // writes always hit the network

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request));
    return;
  }
  event.respondWith(cacheFirst(request));
});

async function networkFirst(request) {
  const cache = await caches.open(DATA);
  try {
    const response = await fetch(request);
    // Never cache an auth failure — doing so would pin a signed-out state.
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) {
      // Mark it so the UI could tell this is stale if it ever wants to.
      const headers = new Headers(cached.headers);
      headers.set('X-Didi-From-Cache', '1');
      return new Response(await cached.blob(), {
        status: cached.status, statusText: cached.statusText, headers,
      });
    }
    return new Response(
      JSON.stringify({ detail: 'You are offline and this has not been loaded yet.' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } });
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(SHELL);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // A navigation with nothing cached still gets the shell.
    if (request.mode === 'navigate') {
      const shell = await caches.match('/index.html');
      if (shell) return shell;
    }
    return new Response('Offline', { status: 503 });
  }
}
