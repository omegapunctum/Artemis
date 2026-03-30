import { showError, clearError, showLoading, hideLoading } from './ux.js';

// Кеш, чтобы не делать повторные запросы к локальным файлам.
let featuresCache = null;
let layersCache = null;
let featuresInFlight = null;
let layersInFlight = null;
const DATA_BASE_PATH = 'data/';

export async function loadFeatures() {
  if (featuresCache) return featuresCache;
  if (featuresInFlight) return featuresInFlight;

  showLoading();

  featuresInFlight = (async () => {
    const response = await fetchWithRetry(`${DATA_BASE_PATH}features.geojson`);
    if (!response.ok) {
      throw new Error(`Не удалось загрузить features.geojson: HTTP ${response.status}`);
    }

    featuresCache = await response.json();
    clearError();
    return featuresCache;
  })();

  try {
    return await featuresInFlight;
  } catch (error) {
    console.error('Ошибка при загрузке data/features.geojson:', error);
    showError('Ошибка загрузки данных');
    throw error;
  } finally {
    featuresInFlight = null;
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
    throw error;
  } finally {
    layersInFlight = null;
    hideLoading();
  }
}

async function fetchWithRetry(url, retryDelay = 1000) {
  try {
    const firstResponse = await fetch(url);
    if (firstResponse.ok) return firstResponse;
  } catch (_error) {
    // Повторим запрос ниже после короткой паузы.
  }

  await new Promise((resolve) => window.setTimeout(resolve, retryDelay));

  const secondResponse = await fetch(url);
  if (secondResponse.ok) return secondResponse;

  throw new Error(`Не удалось загрузить ${url}: HTTP ${secondResponse.status}`);
}
