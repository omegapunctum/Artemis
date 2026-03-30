import { loadLayers } from './data.js';
import { updateMapData, setLayerLookup, focusFeatureOnMap, getMapFeatureCount, getMapBuildDiagnostics } from './map.js';
import { debounce } from './ux.js';
import { createTextElement } from './safe-dom.js';

// Инициализирует фильтры, единое состояние и синхронизацию списка с картой.
export async function initUI(map, features) {
  const allFeatures = Array.isArray(features?.features) ? features.features.filter(isFeatureLike) : [];
  const layers = await loadLayers().catch(() => []);
  const layerLookup = buildLayerLookup(layers, allFeatures);
  setLayerLookup(map, layers);
  logLayerDiagnostics(allFeatures, layerLookup);

  const elements = {
    searchInput: document.getElementById('search-input'),
    layerFilter: document.getElementById('layer-filter'),
    dateFrom: document.getElementById('date-from'),
    dateTo: document.getElementById('date-to'),
    objectList: document.getElementById('object-list'),
    sidebar: document.getElementById('sidebar'),
    sidebarToggle: document.getElementById('sidebar-toggle'),
    resultsCount: document.getElementById('results-count'),
    mapCount: document.getElementById('map-count'),
    sourceCount: document.getElementById('source-count'),
    pointValidCount: document.getElementById('point-valid-count'),
    activeFiltersCount: document.getElementById('active-filters-count'),
    statusMessage: document.getElementById('status-message')
  };

  const state = {
    filters: {
      search: '',
      layerId: '',
      dateFrom: '',
      dateTo: ''
    },
    allFeatures,
    filteredFeatures: allFeatures,
    mapFeatureCollection: { type: 'FeatureCollection', features: [] },
    layerLookup
  };

  hydrateLayerFilter(elements.layerFilter, layerLookup);

  // Применяет единое состояние фильтров к списку и карте.
  const applyState = ({ fitBounds = false } = {}) => {
    state.filteredFeatures = filterFeatures(state.allFeatures, state.filters);
    state.mapFeatureCollection = updateMapData(map, {
      type: 'FeatureCollection',
      features: state.filteredFeatures
    }, { fitBounds });

    renderList(elements.objectList, state.filteredFeatures, state.layerLookup, map);
    updateCounters(elements, state, map);
    updateStatus(elements, state, map);
  };

  const syncStateFromInputs = () => {
    state.filters.search = elements.searchInput.value.trim();
    state.filters.layerId = elements.layerFilter.value;
    state.filters.dateFrom = elements.dateFrom.value.trim();
    state.filters.dateTo = elements.dateTo.value.trim();
    applyState();
  };

  const debouncedSearchInput = debounce(syncStateFromInputs, 300);

  [elements.searchInput, elements.layerFilter, elements.dateFrom, elements.dateTo].forEach((node) => {
    const handler = node === elements.searchInput ? debouncedSearchInput : syncStateFromInputs;
    node.addEventListener('input', handler);
    node.addEventListener('change', syncStateFromInputs);
  });

  // Позволяет быстро очистить поиск клавишей Escape.
  elements.searchInput.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (!elements.searchInput.value) return;
    elements.searchInput.value = '';
    syncStateFromInputs();
    elements.searchInput.blur();
  });

  elements.sidebarToggle.addEventListener('click', () => {
    const collapsed = elements.sidebar.classList.toggle('collapsed');
    elements.sidebarToggle.setAttribute('aria-expanded', String(!collapsed));
  });

  applyState({ fitBounds: true });

  return {
    getVisibleCounts() {
      return {
        listCount: state.filteredFeatures.length,
        mapCount: getMapFeatureCount(map)
      };
    }
  };
}

function isFeatureLike(feature) {
  return feature && typeof feature === 'object' && (feature.type === 'Feature' || feature.properties || feature.geometry);
}

// Собирает человекочитаемые названия слоёв с fallback на layer_id.
function buildLayerLookup(layers, allFeatures) {
  const lookup = new Map();
  (Array.isArray(layers) ? layers : []).forEach((layer) => {
    const id = normalizeLayerValue(layer?.layer_id || layer?.id);
    if (!id) return;
    const label = normalizeLayerLabel(layer?.name_ru || layer?.label, id);
    lookup.set(id, label);
  });

  allFeatures.forEach((feature) => {
    const id = normalizeLayerValue(feature?.properties?.layer_id);
    if (!id || lookup.has(id)) return;
    lookup.set(id, id);
  });

  return lookup;
}

function hydrateLayerFilter(select, layerLookup) {
  select.replaceChildren(new Option('Все слои', ''));
  [...layerLookup.entries()]
    .sort((a, b) => a[1].localeCompare(b[1], 'ru'))
    .forEach(([id, label]) => {
      select.appendChild(new Option(label, id));
    });
}

// Фильтрует массив по названию, слою и диапазону дат.
function filterFeatures(features, filters) {
  const searchValue = String(filters.search || '').trim().toLowerCase();
  const layerValue = String(filters.layerId || '').trim();
  const from = parseYear(filters.dateFrom);
  const to = parseYear(filters.dateTo);

  return features.filter((feature) => {
    const properties = feature?.properties && typeof feature.properties === 'object' ? feature.properties : {};
    const name = String(properties.name_ru || '').toLowerCase();
    const layerId = normalizeLayerValue(properties.layer_id);
    const dateStart = parseYear(properties.date_start);
    const dateEnd = parseYear(properties.date_end);
    const effectiveStart = Number.isFinite(dateStart) ? dateStart : dateEnd;
    const effectiveEnd = Number.isFinite(dateEnd) ? dateEnd : dateStart;

    if (searchValue && !name.includes(searchValue)) return false;
    if (layerValue && layerId !== layerValue) return false;
    if (Number.isFinite(from) && (!Number.isFinite(effectiveEnd) || effectiveEnd < from)) return false;
    if (Number.isFinite(to) && (!Number.isFinite(effectiveStart) || effectiveStart > to)) return false;

    return true;
  });
}

function parseYear(value) {
  if (value === null || value === undefined || value === '') return NaN;
  const normalized = String(value).trim();
  if (!/^-?\d+$/.test(normalized)) return NaN;
  return Number.parseInt(normalized, 10);
}

// Рендерит максимум 50 элементов списка и не ломается на объектах без геометрии.
function renderList(container, features, layerLookup, map) {
  container.replaceChildren();

  if (!features.length) {
    const empty = document.createElement('li');
    empty.className = 'object-list-empty';
    empty.textContent = 'Ничего не найдено';
    container.appendChild(empty);
    return;
  }

  features.slice(0, 50).forEach((feature) => {
    const properties = feature?.properties && typeof feature.properties === 'object' ? feature.properties : {};
    const layerId = normalizeLayerValue(properties.layer_id);
    const layerLabel = layerLookup.get(layerId) || layerId || 'Слой не указан';
    const year = [properties.date_start, properties.date_end].find((value) => value !== null && value !== undefined && value !== '') || 'Год не указан';
    const hasGeometry = feature?.geometry?.type === 'Point' && Array.isArray(feature?.geometry?.coordinates);

    const item = document.createElement('li');
    item.className = 'object-list-item';
    if (!hasGeometry) item.classList.add('is-static');
    item.appendChild(createTextElement('strong', properties.name_ru, { fallback: 'Без названия' }));
    item.appendChild(createTextElement('span', layerLabel, { fallback: 'Слой не указан' }));
    item.appendChild(createTextElement('span', year, { fallback: 'Год не указан' }));

    item.addEventListener('click', () => {
      if (!focusFeatureOnMap(map, feature)) {
        item.classList.add('is-static-pulse');
        window.setTimeout(() => item.classList.remove('is-static-pulse'), 800);
      }
    });

    container.appendChild(item);
  });
}

function updateCounters(elements, state, map) {
  const diagnostics = getMapBuildDiagnostics(map);
  elements.resultsCount.textContent = String(state.filteredFeatures.length);
  elements.mapCount.textContent = String(getMapFeatureCount(map));
  elements.sourceCount.textContent = String(diagnostics.inputTotal);
  elements.pointValidCount.textContent = String(diagnostics.validPoints);
  elements.activeFiltersCount.textContent = String(countActiveFilters(state.filters));
}

function updateStatus(elements, state, map) {
  const activeFilters = countActiveFilters(state.filters);
  const diagnostics = getMapBuildDiagnostics(map);
  elements.statusMessage.textContent = `Карта готова. Загружено из файла ${diagnostics.inputTotal}, прошли Point-фильтр ${diagnostics.validPoints}, на карте ${getMapFeatureCount(map)}, после фильтров списка ${state.filteredFeatures.length}, активных фильтров ${activeFilters}.`;
}

function countActiveFilters(filters) {
  return ['search', 'layerId', 'dateFrom', 'dateTo'].reduce((count, key) => count + (String(filters[key] || '').trim() ? 1 : 0), 0);
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

function logLayerDiagnostics(features, layerLookup) {
  const featureLayerIds = new Set(features.map((feature) => normalizeLayerValue(feature?.properties?.layer_id)).filter(Boolean));
  const unknownLayerIds = [...featureLayerIds].filter((id) => !layerLookup.has(id));
  if (unknownLayerIds.length > 0) {
    console.warn('Найдены layer_id в features.geojson без соответствия в layers.json:', unknownLayerIds.slice(0, 20));
  }
}
