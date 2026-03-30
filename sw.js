const CACHE_VERSION = 'v3';
const STATIC_CACHE = `artemis-static-${CACHE_VERSION}`;
const DATA_CACHE = `artemis-data-${CACHE_VERSION}`;
const RUNTIME_CACHE = `artemis-runtime-${CACHE_VERSION}`;
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
  '/icons/icon-192.svg',
  '/icons/icon-512.svg',
  MAPLIBRE_SCRIPT_URL,
  MAPLIBRE_STYLE_URL,
  MAP_STYLE_URL
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(STATIC_CACHE);
      const results = await Promise.allSettled(PRECACHE_URLS.map(async (url) => {
        try {
          await cache.add(url);
        } catch (error) {
          console.warn('Precache failed:', url, error);
          throw error;
        }
      }));
      const requiredFailures = results.filter((result, index) => result.status === 'rejected' && PRECACHE_URLS[index].startsWith('/'));
      if (requiredFailures.length) {
        throw requiredFailures[0].reason;
      }
      await self.skipWaiting();
    } catch (error) {
      console.error('Service worker install failed:', error);
      throw error;
    }
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try {
      const activeCaches = new Set([STATIC_CACHE, DATA_CACHE, RUNTIME_CACHE]);
      const keys = await caches.keys();
      await Promise.all(
        keys.map((key) => {
          if (!activeCaches.has(key)) {
            return caches.delete(key);
          }
          return undefined;
        })
      );
      await self.clients.claim();
    } catch (error) {
      console.error('Service worker activation failed:', error);
    }
  })());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  const hasAuthHeader = request.headers.has('Authorization');

  if (request.method !== 'GET') {
    console.debug('[SW] skip non-GET:', request.method, url.pathname);
    event.respondWith(fetch(request));
    return;
  }

  if (hasAuthHeader || isPrivateRequest(url)) {
    console.debug('[SW] skip private/auth request:', url.pathname);
    event.respondWith(fetch(request));
    return;
  }

  if (url.origin !== self.location.origin && !isAllowedCrossOrigin(url)) {
    console.debug('[SW] skip cross-origin:', url.origin);
    event.respondWith(fetch(request));
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(handleNavigationRequest(request));
    return;
  }

  if (isDataRequest(url)) {
    event.respondWith(handleDataRequest(request));
    return;
  }

  if (isStaticAssetRequest(url, request)) {
    event.respondWith(handleStaticRequest(request));
  }
});

function isPrivateRequest(url) {
  return [
    '/auth',
    '/me',
    '/profile',
    '/drafts',
    '/moderation',
    '/uploads',
    '/ugc',
    '/api/private',
    '/api/admin',
    '/api/moderation',
    '/api/drafts'
  ].some((path) => url.pathname === path || url.pathname.startsWith(`${path}/`));
}

function isAllowedCrossOrigin(url) {
  return url.href === MAPLIBRE_SCRIPT_URL || url.href === MAPLIBRE_STYLE_URL || url.href === MAP_STYLE_URL;
}

function isDataRequest(url) {
  return url.pathname.startsWith('/data/') && /\.(json|geojson)$/i.test(url.pathname);
}

function isStaticAssetRequest(url, request) {
  return (
    (url.origin === self.location.origin && ['document', 'style', 'script', 'worker', 'image', 'font'].includes(request.destination))
    || url.href === MAPLIBRE_SCRIPT_URL
    || url.href === MAPLIBRE_STYLE_URL
    || url.href === MAP_STYLE_URL
  );
}

async function handleNavigationRequest(request) {
  try {
    const cache = await caches.open(STATIC_CACHE);
    const cachedResponse = await cache.match('/index.html');

    if (cachedResponse) {
      console.debug('[SW] navigation cache hit');
      return cachedResponse;
    }

    const networkResponse = await fetch(request);
    await cache.put('/index.html', networkResponse.clone());
    console.debug('[SW] navigation cache miss -> network');
    return networkResponse;
  } catch (error) {
    console.debug('[SW] navigation network failed, fallback to cached shell');
    const fallback = await caches.match('/index.html');
    if (fallback) return fallback;
    return Response.error();
  }
}

async function handleStaticRequest(request) {
  try {
    const cache = await caches.open(RUNTIME_CACHE);
    const cachedResponse = await cache.match(request) || await caches.match(request);
    if (cachedResponse) {
      console.debug('[SW] static cache hit:', request.url);
      return cachedResponse;
    }

    const networkResponse = await fetch(request);
    await cache.put(request, networkResponse.clone());
    console.debug('[SW] static cache miss -> network:', request.url);
    return networkResponse;
  } catch (error) {
    console.debug('[SW] static fetch failed, fallback to cache:', request.url);

    if (request.url === MAP_STYLE_URL) {
      return new Response(JSON.stringify(OFFLINE_STYLE), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    try {
      return (await caches.match(request)) || await fetch(request);
    } catch {
      return Response.error();
    }
  }
}

async function handleDataRequest(request) {
  try {
    const cache = await caches.open(DATA_CACHE);
    try {
      const networkResponse = await fetch(request);
      if (networkResponse.ok) {
        await cache.put(request, networkResponse.clone());
      }
      console.debug('[SW] data network hit:', request.url);
      return networkResponse;
    } catch (networkError) {
      const cachedResponse = await cache.match(request);
      if (cachedResponse) {
        console.debug('[SW] data network fail -> cache fallback:', request.url);
        return cachedResponse;
      }
      throw networkError;
    }
  } catch (error) {
    console.debug('[SW] data unavailable offline:', request.url);
    return new Response(JSON.stringify({
      error: 'offline',
      message: 'ARTEMIS offline cache is empty for this dataset.'
    }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
