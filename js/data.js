import { showError, clearError, showLoading, hideLoading, showSystemMessage } from './ux.js';

// Кеш, чтобы не делать повторные запросы к локальным файлам.
let featuresCache = null;
let layersCache = null;
let coursesCache = null;
let featuresInFlight = null;
let layersInFlight = null;
let coursesInFlight = null;
const DATA_BASE_PATH = 'data/';
const MAP_FEED_PATH = '/api/map/feed';
let hasShownCachedMessage = false;
let hasShownNoCacheMessage = false;

export function getRecentFeatures(limit = 12, featureCollection = null) {
  const sourceFeatures = Array.isArray(featureCollection?.features)
    ? featureCollection.features
    : Array.isArray(featuresCache?.features)
      ? featuresCache.features
      : [];
  const safeLimit = Math.max(1, Number(limit) || 12);
  return sourceFeatures
    .slice()
    .sort((left, right) => getFeatureRecencyTimestamp(right) - getFeatureRecencyTimestamp(left))
    .slice(0, safeLimit);
}

export async function loadFeatures() {
  if (featuresCache) return featuresCache;
  if (featuresInFlight) return featuresInFlight;

  showLoading();

  featuresInFlight = (async () => {
    const requestUrl = new URL(`${DATA_BASE_PATH}features.geojson`, document.baseURI);
    const response = await fetchWithRetry(requestUrl.href);
    if (!response.ok) {
      notifyCacheState(response);
      throw new Error(`Не удалось загрузить features.geojson: HTTP ${response.status}`);
    }
    notifyCacheState(response);

    featuresCache = await response.json();
    const rawFeatures = Array.isArray(featuresCache?.features) ? featuresCache.features : [];
    const count = rawFeatures.length;
    const firstFeature = rawFeatures[0] || null;
    const firstGeometryType = firstFeature?.geometry?.type || null;
    const firstCoordinates = firstFeature?.geometry?.coordinates || null;

    console.info('[ARTEMIS:data] features.geojson loaded', {
      requestedUrl: requestUrl.href,
      responseUrl: response.url,
      featureCount: count,
      firstGeometryType,
      firstCoordinates
    });

    if (count === 0) {
      console.warn('data/features.geojson загружен, но не содержит объектов (features = 0).');
    }
    clearError();
    return featuresCache;
  })();

  try {
    return await featuresInFlight;
  } catch (error) {
    console.error('Ошибка при загрузке data/features.geojson:', error);
    showError('Ошибка загрузки данных');
    throw createDataLoadError('features.geojson', error);
  } finally {
    featuresInFlight = null;
    hideLoading();
  }
}

export async function loadMapFeed(params = {}) {
  showLoading();
  try {
    const requestUrl = buildMapFeedUrl(params);
    const response = await fetch(requestUrl.href);
    if (!response.ok) {
      throw new Error(`Не удалось загрузить map feed: HTTP ${response.status}`);
    }
    const payload = await response.json();
    const featureCollection = mapFeedResponseToFeatureCollection(payload);
    clearError();
    return featureCollection;
  } catch (error) {
    console.error('Ошибка при загрузке /api/map/feed:', error);
    showError('Ошибка загрузки данных');
    throw createDataLoadError('/api/map/feed', error);
  } finally {
    hideLoading();
  }
}

export async function loadLayers() {
  if (layersCache) return layersCache;
  if (layersInFlight) return layersInFlight;

  showLoading();

  layersInFlight = (async () => {
    const response = await fetchWithRetry(`${DATA_BASE_PATH}layers.json`);
    if (!response.ok) {
      throw new Error(`Не удалось загрузить layers.json: HTTP ${response.status}`);
    }

    layersCache = await response.json();
    clearError();
    return layersCache;
  })();

  try {
    return await layersInFlight;
  } catch (error) {
    console.error('Ошибка при загрузке data/layers.json:', error);
    showError('Ошибка загрузки слоёв');
    throw createDataLoadError('layers.json', error);
  } finally {
    layersInFlight = null;
    hideLoading();
  }
}

export async function loadCourses() {
  if (coursesCache) return coursesCache;
  if (coursesInFlight) return coursesInFlight;

  showLoading();
  coursesInFlight = (async () => {
    const response = await fetchWithRetry(`${DATA_BASE_PATH}courses.json`);
    if (!response.ok) {
      throw new Error(`Не удалось загрузить courses.json: HTTP ${response.status}`);
    }
    const payload = await response.json();
    coursesCache = Array.isArray(payload?.courses) ? payload : { courses: [] };
    clearError();
    return coursesCache;
  })();

  try {
    return await coursesInFlight;
  } catch (error) {
    console.error('Ошибка при загрузке data/courses.json:', error);
    showSystemMessage('Courses временно недоступны', { variant: 'warning', timeout: 2800 });
    throw createDataLoadError('courses.json', error);
  } finally {
    coursesInFlight = null;
    hideLoading();
  }
}

async function fetchWithRetry(url, retryDelay = 1000) {
  try {
    const firstResponse = await fetch(url);
    notifyCacheState(firstResponse);
    if (firstResponse.ok) return firstResponse;
  } catch (_error) {
    // Повторим запрос ниже после короткой паузы.
  }

  await new Promise((resolve) => window.setTimeout(resolve, retryDelay));

  const secondResponse = await fetch(url);
  notifyCacheState(secondResponse);
  if (secondResponse.ok) return secondResponse;

  throw new Error(`Не удалось загрузить ${url}: HTTP ${secondResponse.status}`);
}

function notifyCacheState(response) {
  if (!response) return;
  const cacheState = String(response.headers?.get('X-Artemis-Cache-State') || '').toLowerCase();
  if (cacheState === 'fallback' && !hasShownCachedMessage) {
    hasShownCachedMessage = true;
    showSystemMessage('Using last available data', { variant: 'warning', timeout: 3200 });
    return;
  }

  if (cacheState === 'no-cache' && !hasShownNoCacheMessage) {
    hasShownNoCacheMessage = true;
    showSystemMessage('No cached data available', { variant: 'warning', timeout: 3600 });
  }
}

function createDataLoadError(resourceName, cause) {
  const reason = cause?.message ? `: ${cause.message}` : '';
  const error = new Error(`Не удалось загрузить данные карты (${resourceName})${reason}`);
  error.name = 'DataLoadError';
  error.code = 'DATA_LOAD_FAILED';
  error.resource = resourceName;
  error.cause = cause;
  return error;
}

function buildMapFeedUrl(params = {}) {
  const url = new URL(MAP_FEED_PATH, document.baseURI);
  const query = url.searchParams;
  appendOptionalParam(query, 'entity_type', params.entity_type);
  appendOptionalParam(query, 'bbox', params.bbox);
  appendOptionalParam(query, 'limit', params.limit);
  appendOptionalParam(query, 'offset', params.offset);
  return url;
}

function appendOptionalParam(query, key, value) {
  if (value === null || value === undefined || value === '') return;
  query.set(key, String(value));
}

function mapFeedResponseToFeatureCollection(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return {
    type: 'FeatureCollection',
    features: items.map((item) => mapFeedItemToFeature(item))
  };
}

function mapFeedItemToFeature(item = {}) {
  const lon = Number(item?.longitude);
  const lat = Number(item?.latitude);
  const hasPoint = Number.isFinite(lon) && Number.isFinite(lat);
  const entityType = String(item?.entity_type || '').trim();
  const featureId = String(item?.id || '').trim();
  const name = String(item?.name || '').trim();
  const layerId = String(item?.layer_id || entityType || 'map_feed').trim();
  return {
    type: 'Feature',
    geometry: hasPoint ? { type: 'Point', coordinates: [lon, lat] } : null,
    properties: {
      id: featureId,
      object_id: featureId,
      name_ru: name || `Entity ${featureId || 'without-id'}`,
      title_short: name,
      layer_id: layerId,
      entity_type: entityType || 'unknown',
      geometry_type: item?.geometry_type || null,
      date_start: item?.date_start || null,
      date_end: item?.date_end || null
    }
  };
}

function getFeatureRecencyTimestamp(feature) {
  const props = feature?.properties || {};
  const candidates = [
    props.created_at,
    props.updated_at,
    props.date_start
  ];
  for (const value of candidates) {
    const ts = toTimestamp(value);
    if (Number.isFinite(ts)) return ts;
  }
  return Number.NEGATIVE_INFINITY;
}

function toTimestamp(value) {
  if (value === null || value === undefined || value === '') return Number.NaN;
  const text = String(value).trim();
  const direct = Date.parse(text);
  if (Number.isFinite(direct)) return direct;
  const year = Number.parseInt(text, 10);
  if (Number.isFinite(year)) return Date.UTC(year, 0, 1);
  return Number.NaN;
}
