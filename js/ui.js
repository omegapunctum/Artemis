import { loadLayers } from './data.js';
import { updateMapData, setLayerLookup, focusFeatureOnMap, getMapFeatureCount, getMapBuildDiagnostics, setMapFeatureClickHandler, setMapLayerFilter } from './map.js';
import { debounce } from './ux.js';

export async function initUI(map, features) {
  const allFeatures = Array.isArray(features?.features) ? features.features.filter(isFeatureLike) : [];
  const layers = await loadLayers().catch(() => []);
  const layerLookup = buildLayerLookup(layers, allFeatures);
  setLayerLookup(map, layers);

  const elements = {
    searchInput: document.getElementById('global-search') || document.getElementById('search-input'),
    legacySearch: document.getElementById('search-input'),
    timelineStart: document.getElementById('timeline-start'),
    timelineEnd: document.getElementById('timeline-end'),
    timelineLabel: document.getElementById('timeline-range-label'),
    cardsRibbon: document.getElementById('cards-ribbon') || document.getElementById('object-list'),
    cardsState: document.getElementById('cards-state'),
    floatingCard: document.getElementById('floating-card'),
    floatingCardClose: document.getElementById('floating-card-close'),
    floatingTitle: document.getElementById('floating-card-title'),
    floatingDate: document.getElementById('floating-card-date'),
    floatingDescription: document.getElementById('floating-card-description'),
    floatingImage: document.getElementById('floating-card-image'),
    filtersBtn: document.getElementById('filters-btn'),
    layerFilter: document.getElementById('layer-filter'),
    dateFrom: document.getElementById('date-from'),
    dateTo: document.getElementById('date-to'),
    resultsCount: document.getElementById('results-count'),
    mapCount: document.getElementById('map-count'),
    sourceCount: document.getElementById('source-count'),
    pointValidCount: document.getElementById('point-valid-count'),
    activeFiltersCount: document.getElementById('active-filters-count'),
    statusMessage: document.getElementById('status-message')
  };

  const years = collectYearBounds(allFeatures);
  const state = {
    allFeatures,
    filteredFeatures: [],
    layerLookup,
    search: '',
    currentStartYear: years.min,
    currentEndYear: years.max,
    loading: true,
    error: '',
    activeFeature: null
  };

  hydrateTimeline(elements, years, state);
  renderCardsState(elements, state);

  const applyState = () => {
    const text = state.search.toLowerCase();
    state.filteredFeatures = state.allFeatures.filter((feature) => {
      const props = normalizeProps(feature);
      const haystack = `${String(props.name_ru || '')} ${normalizeTags(props.tags)}`.toLowerCase();
      if (text && !haystack.includes(text)) return false;

      const start = parseYear(props.date_start ?? props.date_construction_end ?? props.date_end);
      const end = parseYear(props.date_end ?? props.date_construction_end ?? props.date_start);
      if (Number.isFinite(start) && start > state.currentEndYear) return false;
      if (Number.isFinite(end) && end < state.currentStartYear) return false;
      return true;
    });

    updateMapData(map, { type: 'FeatureCollection', features: state.filteredFeatures });
    setMapLayerFilter(map, buildMapYearFilter(state.currentStartYear, state.currentEndYear));
    renderCards(elements, state, map);
    updateCounters(elements, state, map);
    updateStatus(elements, state, map);
  };

  const debouncedSearch = debounce(() => {
    state.search = (elements.searchInput?.value || '').trim();
    if (elements.legacySearch && elements.legacySearch !== elements.searchInput) {
      elements.legacySearch.value = state.search;
    }
    applyState();
  }, 300);

  elements.searchInput?.addEventListener('input', debouncedSearch);
  elements.timelineStart?.addEventListener('input', () => {
    state.currentStartYear = Math.min(Number(elements.timelineStart.value), state.currentEndYear);
    elements.timelineStart.value = String(state.currentStartYear);
    syncLegacyDateInputs(elements, state);
    updateTimelineLabel(elements, state);
    applyState();
  });
  elements.timelineEnd?.addEventListener('input', () => {
    state.currentEndYear = Math.max(Number(elements.timelineEnd.value), state.currentStartYear);
    elements.timelineEnd.value = String(state.currentEndYear);
    syncLegacyDateInputs(elements, state);
    updateTimelineLabel(elements, state);
    applyState();
  });

  elements.filtersBtn?.addEventListener('click', () => {
    if (!elements.searchInput) return;
    elements.searchInput.focus();
  });

  setMapFeatureClickHandler(map, (feature, coordinates) => {
    state.activeFeature = feature;
    showFloatingCard(map, elements, feature, coordinates);
  });
  map.on('move', () => {
    const feature = state.activeFeature;
    if (feature && !elements.floatingCard?.hidden) {
      const coords = feature?.geometry?.coordinates;
      if (Array.isArray(coords)) positionFloatingCard(map, elements.floatingCard, coords);
    }
  });

  elements.floatingCardClose?.addEventListener('click', () => hideFloatingCard(elements));
  document.addEventListener('click', (event) => {
    if (elements.floatingCard?.hidden) return;
    const target = event.target;
    const withinFloating = elements.floatingCard.contains(target);
    const withinCard = target.closest?.('.ribbon-card');
    if (!withinFloating && !withinCard) {
      state.activeFeature = null;
      hideFloatingCard(elements);
    }
  });

  state.loading = false;
  applyState();

  return {
    getVisibleCounts() {
      return { listCount: state.filteredFeatures.length, mapCount: getMapFeatureCount(map) };
    }
  };
}

function renderCards(elements, state, map) {
  const list = elements.cardsRibbon;
  if (!list) return;
  list.replaceChildren();

  if (state.error) {
    renderCardsState(elements, { ...state, loading: false });
    return;
  }
  if (!state.filteredFeatures.length) {
    renderCardsState(elements, { ...state, loading: false, empty: true });
    return;
  }

  renderCardsState(elements, { ...state, loading: false, empty: false });
  state.filteredFeatures.slice(0, 80).forEach((feature) => {
    const props = normalizeProps(feature);
    const item = document.createElement('li');
    item.className = 'ribbon-card';

    const image = document.createElement('img');
    image.src = String(props.image_url || '').trim() || 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
    image.alt = String(props.name_ru || 'Object image');
    image.loading = 'lazy';

    const meta = document.createElement('div');
    meta.className = 'meta';
    const title = document.createElement('h4');
    title.textContent = String(props.name_ru || 'Без названия');
    const date = document.createElement('p');
    date.textContent = formatRange(props.date_start, props.date_end);
    meta.append(title, date);

    item.append(image, meta);
    item.addEventListener('click', () => {
      focusFeatureOnMap(map, feature);
      state.activeFeature = feature;
      const coords = feature?.geometry?.coordinates;
      showFloatingCard(map, elements, feature, Array.isArray(coords) ? coords : null);
    });

    list.appendChild(item);
  });
}

function showFloatingCard(map, elements, feature, coordinates) {
  const props = normalizeProps(feature);
  elements.floatingTitle.textContent = String(props.name_ru || 'Без названия');
  elements.floatingDate.textContent = formatRange(props.date_start, props.date_end);
  elements.floatingDescription.textContent = String(props.description || 'Описание отсутствует.');
  elements.floatingImage.src = String(props.image_url || '').trim() || 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
  elements.floatingImage.alt = String(props.name_ru || 'Object image');
  elements.floatingCard.hidden = false;

  if (Array.isArray(coordinates)) {
    positionFloatingCard(map, elements.floatingCard, coordinates);
  }
}

function positionFloatingCard(map, card, coordinates) {
  const px = map.project(coordinates);
  const x = Math.min(Math.max(px.x + 14, 12), window.innerWidth - card.offsetWidth - 12);
  const y = Math.min(Math.max(px.y - 50, 74), window.innerHeight - card.offsetHeight - 220);
  card.style.left = `${x}px`;
  card.style.top = `${y}px`;
}

function hideFloatingCard(elements) {
  if (elements.floatingCard) elements.floatingCard.hidden = true;
}

function renderCardsState(elements, state) {
  if (!elements.cardsState) return;
  elements.cardsState.className = 'cards-state';
  if (state.loading) {
    elements.cardsState.classList.add('is-loading');
    elements.cardsState.textContent = 'Loading events…';
  } else if (state.error) {
    elements.cardsState.classList.add('is-error');
    elements.cardsState.textContent = `Error: ${state.error}`;
  } else if (state.empty) {
    elements.cardsState.classList.add('is-empty');
    elements.cardsState.textContent = 'No results in selected time range';
  } else {
    elements.cardsState.textContent = `${state.filteredFeatures.length} objects`;
  }
}

function hydrateTimeline(elements, years, state) {
  if (!elements.timelineStart || !elements.timelineEnd) return;
  elements.timelineStart.min = String(years.min);
  elements.timelineStart.max = String(years.max);
  elements.timelineEnd.min = String(years.min);
  elements.timelineEnd.max = String(years.max);
  elements.timelineStart.value = String(state.currentStartYear);
  elements.timelineEnd.value = String(state.currentEndYear);
  syncLegacyDateInputs(elements, state);
  updateTimelineLabel(elements, state);
}

function updateTimelineLabel(elements, state) {
  if (elements.timelineLabel) {
    elements.timelineLabel.textContent = `${state.currentStartYear}–${state.currentEndYear}`;
  }
}

function syncLegacyDateInputs(elements, state) {
  if (elements.dateFrom) elements.dateFrom.value = String(state.currentStartYear);
  if (elements.dateTo) elements.dateTo.value = String(state.currentEndYear);
}

function collectYearBounds(features) {
  const years = features.flatMap((feature) => {
    const p = normalizeProps(feature);
    return [parseYear(p.date_start), parseYear(p.date_construction_end), parseYear(p.date_end)].filter(Number.isFinite);
  });
  if (!years.length) return { min: 0, max: 2026 };
  return { min: Math.min(...years), max: Math.max(...years) };
}

function buildMapYearFilter(start, end) {
  return ['all',
    ['<=', ['coalesce', ['to-number', ['get', 'date_start']], ['to-number', ['get', 'date_end']], end], end],
    ['>=', ['coalesce', ['to-number', ['get', 'date_end']], ['to-number', ['get', 'date_start']], start], start]
  ];
}

function updateCounters(elements, state, map) {
  const diagnostics = getMapBuildDiagnostics(map);
  if (elements.resultsCount) elements.resultsCount.textContent = String(state.filteredFeatures.length);
  if (elements.mapCount) elements.mapCount.textContent = String(getMapFeatureCount(map));
  if (elements.sourceCount) elements.sourceCount.textContent = String(diagnostics.inputTotal);
  if (elements.pointValidCount) elements.pointValidCount.textContent = String(diagnostics.validPoints);
  if (elements.activeFiltersCount) elements.activeFiltersCount.textContent = String(Number(Boolean(state.search)) + 1);
}

function updateStatus(elements, state, map) {
  if (!elements.statusMessage) return;
  const diagnostics = getMapBuildDiagnostics(map);
  elements.statusMessage.textContent = `Карта готова. Загружено ${diagnostics.inputTotal}, отображается ${getMapFeatureCount(map)}, в ленте ${state.filteredFeatures.length}.`;
}

function isFeatureLike(feature) {
  return feature && typeof feature === 'object' && (feature.type === 'Feature' || feature.properties || feature.geometry);
}
function normalizeProps(feature) {
  return feature?.properties && typeof feature.properties === 'object' ? feature.properties : {};
}
function buildLayerLookup(layers, allFeatures) {
  const lookup = new Map();
  (Array.isArray(layers) ? layers : []).forEach((layer) => {
    const id = String(layer?.layer_id || layer?.id || '').trim();
    if (id) lookup.set(id, String(layer?.name_ru || layer?.label || id));
  });
  allFeatures.forEach((f) => {
    const id = String(normalizeProps(f).layer_id || '').trim();
    if (id && !lookup.has(id)) lookup.set(id, id);
  });
  return lookup;
}
function parseYear(value) {
  const n = Number.parseInt(String(value ?? '').trim(), 10);
  return Number.isFinite(n) ? n : NaN;
}
function normalizeTags(tags) {
  if (Array.isArray(tags)) return tags.join(' ');
  return String(tags || '');
}
function formatRange(start, end) {
  const s = parseYear(start);
  const e = parseYear(end);
  if (Number.isFinite(s) && Number.isFinite(e)) return `${s}—${e}`;
  if (Number.isFinite(s)) return String(s);
  if (Number.isFinite(e)) return String(e);
  return 'Дата не указана';
}
