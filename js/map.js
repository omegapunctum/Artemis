import { appendText, createTextElement, normalizeSafeUrl, setSafeLink, setText, toSafeText } from './safe-dom.js';

const SOURCE_ID = 'artemis-features';
const LAYER_ID = 'artemis-points';
const CLUSTER_LAYER_ID = 'artemis-clusters';
const CLUSTER_COUNT_LAYER_ID = 'artemis-cluster-count';
const POPUP_CLASS_NAME = 'artemis-popup';

// Нормализует FeatureCollection и исключает битые объекты из карты.
function buildMapFeatureCollection(features) {
  const inputFeatures = Array.isArray(features?.features) ? features.features : [];
  const total = inputFeatures.length;
  let pointValid = 0;
  let dropped = 0;

  const safeFeatures = inputFeatures.filter((feature) => {
    const valid = hasPointGeometry(feature);
    if (valid) {
      pointValid += 1;
    } else {
      dropped += 1;
    }
    return valid;
  });

  console.info('[ARTEMIS:map] buildMapFeatureCollection', {
    inputTotal: total,
    validPoints: pointValid,
    dropped
  });
  if (total > 0 && safeFeatures.length === 0) {
    console.warn('[ARTEMIS:map] Все features были отброшены фильтром геометрии (hasPointGeometry).');
  }

  return {
    collection: {
      type: 'FeatureCollection',
      features: safeFeatures.map((feature) => ({
        ...feature,
        properties: feature?.properties && typeof feature.properties === 'object' ? feature.properties : {}
      }))
    },
    diagnostics: {
      inputTotal: total,
      validPoints: pointValid,
      dropped
    }
  };
}

// Проверяет, что feature можно безопасно показать на карте как точку.
function hasPointGeometry(feature) {
  const geometry = feature?.geometry;
  const coordinates = geometry?.coordinates;
  return geometry?.type === 'Point'
    && Array.isArray(coordinates)
    && coordinates.length >= 2
    && Number.isFinite(Number(coordinates[0]))
    && Number.isFinite(Number(coordinates[1]));
}

// Инициализация карты и подготовка единого источника данных.
export function initMap(containerId, features) {
  const map = new maplibregl.Map({
    container: containerId,
    style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    center: [37.6176, 55.7558],
    zoom: 4
  });

  map.addControl(new maplibregl.NavigationControl(), 'top-right');
  const initialBuild = buildMapFeatureCollection(features);
  map.__artemis = {
    popup: null,
    layerLookup: new Map(),
    lastMapFeatureCount: 0,
    lastBuildDiagnostics: initialBuild.diagnostics,
    pendingFeatureCollection: initialBuild.collection
  };

  map.on('load', () => {
    const mapData = map.__artemis.pendingFeatureCollection;
    loadGeoJSON(map, mapData);
    bindPopupHandlers(map);
    map.__artemis.lastMapFeatureCount = mapData.features.length;
    fitToFeatures(map, mapData);
  });

  return map;
}

// Обновляет данные source без пересоздания карты.
export function updateMapData(map, featureCollection, options = {}) {
  const buildResult = buildMapFeatureCollection(featureCollection);
  const mapData = buildResult.collection;
  map.__artemis = map.__artemis || {};
  map.__artemis.lastBuildDiagnostics = buildResult.diagnostics;
  map.__artemis.pendingFeatureCollection = mapData;
  const source = map.getSource(SOURCE_ID);
  if (source) {
    source.setData(mapData);
    map.__artemis.lastMapFeatureCount = mapData.features.length;
    if (options.fitBounds) {
      fitToFeatures(map, mapData);
    }
  } else {
    map.__artemis.lastMapFeatureCount = mapData.features.length;
  }
  return mapData;
}

// Сохраняет справочник слоёв для popup и списка.
export function setLayerLookup(map, layers = []) {
  const lookup = new Map();
  (Array.isArray(layers) ? layers : []).forEach((layer) => {
    const id = normalizeLayerValue(layer?.layer_id || layer?.id);
    if (!id) return;
    lookup.set(id, normalizeLayerLabel(layer?.name_ru || layer?.label, id));
  });
  map.__artemis = map.__artemis || {};
  map.__artemis.layerLookup = lookup;
}

// Возвращает количество объектов, реально попавших в map source.
export function getMapFeatureCount(map) {
  return Number(map?.__artemis?.lastMapFeatureCount || 0);
}

export function getMapBuildDiagnostics(map) {
  return map?.__artemis?.lastBuildDiagnostics || { inputTotal: 0, validPoints: 0, dropped: 0 };
}

// Открывает popup и переводит карту к объекту, если геометрия существует.
export function focusFeatureOnMap(map, feature) {
  if (!hasPointGeometry(feature)) return false;
  const coordinates = feature.geometry.coordinates;
  map.flyTo({
    center: coordinates,
    zoom: 10,
    essential: true
  });
  openFeaturePopup(map, feature, coordinates);
  return true;
}

function loadGeoJSON(map, featureCollection) {
  const shouldCluster = featureCollection.features.length > 500;

  map.addSource(SOURCE_ID, {
    type: 'geojson',
    data: featureCollection,
    cluster: shouldCluster,
    clusterMaxZoom: 14,
    clusterRadius: 50
  });

  if (shouldCluster) {
    map.addLayer({
      id: CLUSTER_LAYER_ID,
      type: 'circle',
      source: SOURCE_ID,
      filter: ['has', 'point_count'],
      paint: {
        'circle-color': '#3b82f6',
        'circle-radius': ['step', ['get', 'point_count'], 14, 25, 20, 100, 26],
        'circle-opacity': 0.84
      }
    });

    map.addLayer({
      id: CLUSTER_COUNT_LAYER_ID,
      type: 'symbol',
      source: SOURCE_ID,
      filter: ['has', 'point_count'],
      layout: {
        'text-field': ['get', 'point_count_abbreviated'],
        'text-size': 12
      },
      paint: {
        'text-color': '#ffffff'
      }
    });
  }

  // === ИСПРАВЛЕННЫЙ ОСНОВНОЙ СЛОЙ ТОЧЕК ===
  const pointLayer = {
    id: LAYER_ID,
    type: 'circle',
    source: SOURCE_ID,
    paint: {
      'circle-radius': 8,
      'circle-color': '#d9786d',        // ярко-красный — сразу видно
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 2,
      'circle-opacity': 0.95
    }
  };

  // Добавляем filter ТОЛЬКО если нужен (MapLibre не принимает undefined)
  if (shouldCluster) {
    pointLayer.filter = ['!', ['has', 'point_count']];
  }

  map.addLayer(pointLayer);
  // =========================================
}

function bindPopupHandlers(map) {
  map.on('click', LAYER_ID, (event) => {
    const feature = event.features?.[0];
    if (!feature) return;
    const coordinates = feature?.geometry?.coordinates;
    openFeaturePopup(map, feature, Array.isArray(coordinates) ? coordinates : event.lngLat);
  });

  map.on('click', CLUSTER_LAYER_ID, (event) => {
    const feature = event.features?.[0];
    if (!feature) return;

    const clusterId = feature.properties?.cluster_id;
    const source = map.getSource(SOURCE_ID);
    if (!source || typeof source.getClusterExpansionZoom !== 'function') return;

    source.getClusterExpansionZoom(clusterId, (error, zoom) => {
      if (error) {
        console.debug('Не удалось раскрыть кластер:', error);
        return;
      }

      map.easeTo({
        center: feature.geometry.coordinates,
        zoom
      });
    });
  });

  [LAYER_ID, CLUSTER_LAYER_ID].forEach((layerId) => {
    map.on('mouseenter', layerId, () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', layerId, () => {
      map.getCanvas().style.cursor = '';
    });
  });
}

// Безопасно открывает popup даже при неполных данных.
function openFeaturePopup(map, feature, lngLat) {
  try {
    const content = buildPopupContent(feature, map?.__artemis?.layerLookup);
    if (map.__artemis?.popup) {
      map.__artemis.popup.remove();
    }
    map.__artemis.popup = new maplibregl.Popup({ closeButton: true, maxWidth: '320px', className: POPUP_CLASS_NAME })
      .setLngLat(lngLat)
      .setDOMContent(content)
      .addTo(map);
  } catch (error) {
    console.debug('Popup fallback:', error);
    new maplibregl.Popup({ closeButton: true, maxWidth: '280px', className: POPUP_CLASS_NAME })
      .setLngLat(lngLat)
      .setText('Не удалось отобразить карточку объекта.')
      .addTo(map);
  }
}

// Строит содержимое popup из feature и layers.json.
function buildPopupContent(feature, layerLookup = new Map()) {
  const props = feature?.properties && typeof feature.properties === 'object' ? feature.properties : {};
  const article = document.createElement('article');
  article.className = 'popup-card';

  const title = createTextElement('h3', props.name_ru, { fallback: 'Без названия' });
  article.appendChild(title);

  const safeImageUrl = normalizeSafeUrl(props.image_url, { allowRelative: true });
  if (safeImageUrl) {
    const image = document.createElement('img');
    image.className = 'popup-image';
    image.src = safeImageUrl;
    image.alt = toSafeText(props.name_ru, 'Без названия');
    image.loading = 'lazy';
    image.referrerPolicy = 'no-referrer';
    image.addEventListener('error', () => {
      image.replaceWith(createImageFallback());
    }, { once: true });
    article.appendChild(image);
  } else {
    article.appendChild(createImageFallback());
  }

  article.appendChild(createTextElement('p', props.description, { fallback: 'Описание отсутствует' }));

  const layerId = normalizeLayerValue(props.layer_id);
  article.appendChild(buildPopupMeta('Слой:', String(layerLookup.get(layerId) || layerId || 'Слой не указан')));
  const dateText = [props?.date_start, props?.date_end].filter((value) => value !== null && value !== undefined && value !== '').join(' — ') || 'Даты не указаны';
  article.appendChild(buildPopupMeta('Даты:', String(dateText)));

  if (props?.source_license) {
    article.appendChild(buildPopupMeta('Лицензия:', props.source_license));
  }

  const safeSourceUrl = normalizeSafeUrl(props?.source_url);
  if (safeSourceUrl) {
    const row = document.createElement('p');
    const strong = document.createElement('strong');
    strong.textContent = 'Источник:';
    row.append(strong, ' ');
    const link = document.createElement('a');
    setSafeLink(link, safeSourceUrl);
    setText(link, safeSourceUrl);
    row.appendChild(link);
    article.appendChild(row);
  }

  return article;
}

function buildPopupMeta(label, value) {
  const row = document.createElement('p');
  const strong = createTextElement('strong', label);
  row.appendChild(strong);
  appendText(row, ' ');
  appendText(row, value);
  return row;
}

function createImageFallback() {
  return createTextElement('div', 'Изображение отсутствует', { className: 'popup-image placeholder' });
}

function normalizeLayerValue(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const arrayMatch = raw.match(/^\[\s*['"]([^'"]+)['"]\s*\]$/);
  return arrayMatch ? arrayMatch[1].trim() : raw;
}

function normalizeLayerLabel(value, fallback) {
  const cleaned = normalizeLayerValue(value);
  if (!cleaned) return fallback;
  return /^rec[A-Za-z0-9]{10,}$/.test(cleaned) ? fallback : cleaned;
}

function fitToFeatures(map, geojson) {
  const features = geojson?.features || [];
  if (!features.length) return;

  const bounds = new maplibregl.LngLatBounds();
  for (const feature of features) {
    const coords = feature?.geometry?.coordinates;
    if (Array.isArray(coords) && coords.length >= 2) {
      bounds.extend(coords);
    }
  }

  if (!bounds.isEmpty()) {
    map.fitBounds(bounds, { padding: 40, maxZoom: 11 });
  }
}
