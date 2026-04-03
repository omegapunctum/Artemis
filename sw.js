const CACHE_VERSION = '2026-04-03-v7';
const STATIC_CACHE = `artemis-static-${CACHE_VERSION}`;
const DATA_CACHE = `artemis-data-${CACHE_VERSION}`;
const RUNTIME_CACHE = `artemis-runtime-${CACHE_VERSION}`;
const MAP_STYLE_URL = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';
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
      paint: { 'background-color': '#0b1220' }
    }
  ]
};
const BASE_PATH = getBasePath();
const PRECACHE_PATHS = [
  '',
  'index.html',
  'manifest.json',
  'css/style.css',
  'js/auth.js',
  'js/data.js',
  'js/map.js',
  'js/pwa.js',
  'js/ui.js',
  'js/ui.ugc.js',
  'js/ui.moderation.js',
  'js/ugc.js',
  'js/uploads.js',
  'js/state.js',
  'js/ux.js',
  'icons/icon-192.svg',
  'icons/icon-512.svg',
];
const PRECACHE_URLS = [
  ...PRECACHE_PATHS.map((path) => toBaseUrl(path)),
  MAPLIBRE_SCRIPT_URL,
  MAPLIBRE_STYLE_URL,
  MAP_STYLE_URL
];
const INDEX_URL = toBaseUrl('index.html');

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
      const requiredFailures = results.filter((result, index) => result.status === 'rejected' && PRECACHE_URLS[index].startsWith(self.location.origin));
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

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  const hasAuthHeader = request.headers.has('Authorization');
  const isNonGetRequest = request.method !== 'GET';
  const isPrivateApiRequest = hasAuthHeader || isPrivateRequest(url);

  if (isNonGetRequest) {
    console.debug('[SW] skip non-GET:', request.method, url.pathname);
    event.respondWith(fetch(request));
    return;
  }

  // Русский комментарий: приватные/auth-запросы не кэшируем, чтобы не сохранять приватные ответы.
  if (isPrivateApiRequest) {
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
  const privatePaths = [
    'auth',
    'me',
    'profile',
    'drafts',
    'moderation',
    'uploads',
    'ugc',
    'api/private',
    'api/admin',
    'api/moderation',
    'api/drafts',
    'api/auth',
    'api/me',
    'api/uploads'
  ];
  const normalizedPath = trimBasePath(url.pathname);
  if (normalizedPath === 'api' || normalizedPath.startsWith('api/')) return true;

  return [
    ...privatePaths
  ].some((path) => normalizedPath === path || normalizedPath.startsWith(`${path}/`));
}

function isAllowedCrossOrigin(url) {
  return url.href === MAPLIBRE_SCRIPT_URL || url.href === MAPLIBRE_STYLE_URL || url.href === MAP_STYLE_URL;
}

function isDataRequest(url) {
  return trimBasePath(url.pathname).startsWith('data/') && /\.(json|geojson)$/i.test(url.pathname);
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
    const networkResponse = await fetch(request);

    if (networkResponse && networkResponse.ok) {
      const contentType = networkResponse.headers.get('Content-Type') || '';
      if (contentType.includes('text/html')) {
        await cache.put(INDEX_URL, networkResponse.clone());
      }
      console.debug('[SW] navigation network hit -> cache updated');
      return networkResponse;
    }

    const fallback = await cache.match(INDEX_URL);
    if (fallback) {
      console.debug('[SW] navigation non-OK response, fallback to cached shell');
      return fallback;
    }

    return networkResponse;
  } catch (error) {
    console.debug('[SW] navigation network failed, fallback to cached shell');
    const cache = await caches.open(STATIC_CACHE);
    const fallback = await cache.match(INDEX_URL);
    if (fallback) {
      notifyClients({ type: 'ARTEMIS_NAVIGATION_OFFLINE_FALLBACK' });
      return fallback;
    }
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
    if (isCacheableResponse(networkResponse)) {
      await cache.put(request, networkResponse.clone());
    }
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

function isCacheableResponse(response) {
  const cacheControl = String(response.headers.get('Cache-Control') || '').toLowerCase();
  if (cacheControl.includes('no-store') || cacheControl.includes('private')) {
    return false;
  }
  return true;
}

function getBasePath() {
  const registrationPath = new URL(self.registration.scope).pathname;
  return registrationPath.endsWith('/') ? registrationPath : `${registrationPath}/`;
}

function toBaseUrl(path) {
  const normalized = String(path || '').replace(/^\/+/, '');
  return new URL(normalized, self.location.origin + BASE_PATH).href;
}

function trimBasePath(pathname) {
  const normalizedPath = pathname.startsWith('/') ? pathname : `/${pathname}`;
  if (normalizedPath === BASE_PATH.slice(0, -1)) return '';
  if (normalizedPath.startsWith(BASE_PATH)) {
    return normalizedPath.slice(BASE_PATH.length);
  }
  return normalizedPath.replace(/^\/+/, '');
}

async function handleDataRequest(request) {
  const requestUrl = new URL(request.url);
  if (isPrivateRequest(requestUrl)) {
    console.debug('[SW] data request bypass cache:', requestUrl.pathname);
    return fetch(request);
  }

  try {
    const cache = await caches.open(DATA_CACHE);
    const cachedResponse = await cache.match(request);

    const networkFetch = fetch(request).then(async (networkResponse) => {
      if (networkResponse.ok && isCacheableResponse(networkResponse)) {
        await cache.put(request, networkResponse.clone());
      }
      return networkResponse;
    });

    if (cachedResponse) {
      networkFetch.catch(() => {});
      return withCacheState(cachedResponse, 'stale');
    }

    const networkResponse = await networkFetch;
    if (networkResponse.ok) {
      console.debug('[SW] data network hit:', request.url);
      return networkResponse;
    }
    return networkResponse;
  } catch (error) {
    const cache = await caches.open(DATA_CACHE);
    const cachedResponse = await cache.match(request);
    if (cachedResponse) {
      notifyClients({ type: 'ARTEMIS_DATA_CACHE_FALLBACK' });
      return withCacheState(cachedResponse, 'fallback');
    }
    console.debug('[SW] data unavailable offline:', request.url);
    notifyClients({ type: 'ARTEMIS_DATA_CACHE_MISS' });
    return new Response(JSON.stringify({
      error: 'offline',
      message: 'ARTEMIS offline cache is empty for this dataset.'
    }), {
      status: 503,
      headers: {
        'Content-Type': 'application/json',
        'X-Artemis-Cache-State': 'no-cache'
      }
    });
  }
}

function withCacheState(response, state) {
  const headers = new Headers(response.headers);
  headers.set('X-Artemis-Cache-State', state);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

function notifyClients(payload) {
  self.clients.matchAll({ includeUncontrolled: true, type: 'window' }).then((clients) => {
    clients.forEach((client) => client.postMessage(payload));
  }).catch(() => {});
}
