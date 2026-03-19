const SOURCE_ID = 'artemis-features';
const LAYER_ID = 'artemis-points';
const CLUSTER_LAYER_ID = 'artemis-clusters';
const CLUSTER_COUNT_LAYER_ID = 'artemis-cluster-count';
const POPUP_CLASS_NAME = 'artemis-popup';

// Нормализует FeatureCollection и исключает битые объекты из карты.
function buildMapFeatureCollection(features) {
  const safeFeatures = Array.isArray(features?.features) ? features.features : [];
  return {
    type: 'FeatureCollection',
    features: safeFeatures.filter(hasPointGeometry).map((feature) => ({
      ...feature,
      properties: feature?.properties && typeof feature.properties === 'object' ? feature.properties : {}
    }))
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
  map.__artemis = {
    popup: null,
    layerLookup: new Map(),
    lastMapFeatureCount: 0,
    pendingFeatureCollection: buildMapFeatureCollection(features)
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
  const mapData = buildMapFeatureCollection(featureCollection);
  map.__artemis = map.__artemis || {};
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
    const id = String(layer?.id || '').trim();
    if (!id) return;
    lookup.set(id, layer?.name_ru || layer?.label || id);
  });
  map.__artemis = map.__artemis || {};
  map.__artemis.layerLookup = lookup;
}

// Возвращает количество объектов, реально попавших в map source.
export function getMapFeatureCount(map) {
  return Number(map?.__artemis?.lastMapFeatureCount || 0);
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

  map.addLayer({
    id: LAYER_ID,
    type: 'circle',
    source: SOURCE_ID,
    filter: shouldCluster ? ['!', ['has', 'point_count']] : undefined,
    paint: {
      'circle-radius': 6,
      'circle-color': '#2563eb',
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1
    }
  });
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
    const html = buildPopupHtml(feature, map?.__artemis?.layerLookup);
    if (map.__artemis?.popup) {
      map.__artemis.popup.remove();
    }
    map.__artemis.popup = new maplibregl.Popup({ closeButton: true, maxWidth: '320px', className: POPUP_CLASS_NAME })
      .setLngLat(lngLat)
      .setHTML(html)
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
function buildPopupHtml(feature, layerLookup = new Map()) {
  const props = feature?.properties && typeof feature.properties === 'object' ? feature.properties : {};
  const name = escapeHtml(props.name_ru || 'Без названия');
  const description = escapeHtml(props.description || 'Описание отсутствует');
  const imageUrl = String(props.image_url || '').trim();
  const layerId = String(props.layer_id || '').trim();
  const layerLabel = escapeHtml(layerLookup.get(layerId) || layerId || 'Слой не указан');
  const dateText = [props.date_start, props.date_end].filter((value) => value !== null && value !== undefined && value !== '').join(' — ') || 'Даты не указаны';
  const sourceUrl = String(props.source_url || '').trim();
  const imageBlock = imageUrl
    ? `<img class="popup-image" src="${escapeAttribute(imageUrl)}" alt="${name}" loading="lazy" />`
    : '<div class="popup-image placeholder">Изображение отсутствует</div>';
  const sourceBlock = sourceUrl
    ? `<p><strong>Источник:</strong> <a href="${escapeAttribute(sourceUrl)}" target="_blank" rel="noopener noreferrer">Открыть</a></p>`
    : '';

  return `
    <article class="popup-card">
      <h3>${name}</h3>
      ${imageBlock}
      <p>${description}</p>
      <p><strong>Слой:</strong> ${layerLabel}</p>
      <p><strong>Даты:</strong> ${escapeHtml(dateText)}</p>
      ${sourceBlock}
    </article>
  `;
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

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
