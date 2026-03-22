const APP_VERSION = 'v2';
const STATIC_CACHE = `artemis-static-${APP_VERSION}`;
const DATA_CACHE = `artemis-data-${APP_VERSION}`;
const RUNTIME_CACHE = `artemis-runtime-${APP_VERSION}`;
const MAP_STYLE_URL = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';
const MAPLIBRE_SCRIPT_URL = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js';
const MAPLIBRE_STYLE_URL = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css';
const OFFLINE_STYLE = {
  version: 8,
  name: 'ARTEMIS Offline',
  center: [37.6176, 55.7558],
  zoom: 4,
  sources: {},
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#e5e7eb' }
    }
  ]
};
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/css/style.css',
  '/js/auth.js',
  '/js/data.js',
  '/js/map.js',
  '/js/pwa.js',
  '/js/ui.js',
  '/js/ui.ugc.js',
  '/js/ui.moderation.js',
  '/js/ugc.js',
  '/js/uploads.js',
  '/js/state.js',
  '/js/ux.js',
  '/data/features.geojson',
  '/data/features.json',
  '/data/layers.json',
  '/icons/icon-192.svg',
  '/icons/icon-512.svg',
  MAPLIBRE_SCRIPT_URL,
  MAPLIBRE_STYLE_URL,
  MAP_STYLE_URL
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);
    const results = await Promise.allSettled(PRECACHE_URLS.map((url) => cache.add(url)));
    const requiredFailures = results.filter((result, index) => result.status === 'rejected' && PRECACHE_URLS[index].startsWith('/'));
    if (requiredFailures.length) {
      throw requiredFailures[0].reason;
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys();
    await Promise.all(
      cacheNames
        .filter((cacheName) => ![STATIC_CACHE, DATA_CACHE, RUNTIME_CACHE].includes(cacheName))
        .map((cacheName) => caches.delete(cacheName))
    );
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  if (isPrivateRequest(url)) return;

  if (request.mode === 'navigate') {
    event.respondWith(handleNavigationRequest(request));
    return;
  }

  if (url.pathname.startsWith('/data/')) {
    event.respondWith(handleDataRequest(request));
    return;
  }

  if (isStaticAssetRequest(url, request)) {
    event.respondWith(handleStaticRequest(request));
    return;
  }
});

function isPrivateRequest(url) {
  return url.pathname.startsWith('/auth/') || url.pathname.startsWith('/ugc/') || url.pathname.startsWith('/api/');
}

function isStaticAssetRequest(url, request) {
  return url.origin === self.location.origin
    || url.href === MAPLIBRE_SCRIPT_URL
    || url.href === MAPLIBRE_STYLE_URL
    || url.href === MAP_STYLE_URL
    || ['style', 'script', 'worker', 'image', 'font'].includes(request.destination);
}

async function handleNavigationRequest(request) {
  const cache = await caches.open(STATIC_CACHE);

  try {
    const networkResponse = await fetch(request);
    cache.put('/index.html', networkResponse.clone());
    return networkResponse;
  } catch (_error) {
    return (await cache.match(request)) || (await cache.match('/index.html'));
  }
}

async function handleStaticRequest(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cachedResponse = await cache.match(request) || await caches.match(request);
  if (cachedResponse) return cachedResponse;

  try {
    const networkResponse = await fetch(request);
    cache.put(request, networkResponse.clone());
    return networkResponse;
  } catch (_error) {
    if (request.url === MAP_STYLE_URL) {
      return new Response(JSON.stringify(OFFLINE_STYLE), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    return (await caches.match(request)) || Response.error();
  }
}

async function handleDataRequest(request) {
  const cache = await caches.open(DATA_CACHE);
  const cachedResponse = await cache.match(request);

  const networkPromise = fetch(request)
    .then((response) => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  if (cachedResponse) {
    eventWaitUntil(networkPromise);
    return cachedResponse;
  }

  const networkResponse = await networkPromise;
  if (networkResponse) return networkResponse;

  return new Response(JSON.stringify({
    error: 'offline',
    message: 'ARTEMIS offline cache is empty for this dataset.'
  }), {
    status: 503,
    headers: { 'Content-Type': 'application/json' }
  });
}

function eventWaitUntil(promise) {
  if (!promise) return;
  promise.catch(() => undefined);
}
