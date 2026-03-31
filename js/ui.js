import { loadLayers } from './data.js';
import { updateMapData, setLayerLookup, focusFeatureOnMap, getMapFeatureCount, getMapBuildDiagnostics, setMapFeatureClickHandler, setMapLayerFilter, setSelectedFeatureId } from './map.js';
import { debounce, createInlineStateBlock } from './ux.js';
import { normalizeSafeUrl, setSafeLink } from './safe-dom.js';

let globalDataErrorRetryHandler = null;

export function showGlobalDataError({ message, onRetry } = {}) {
  const host = document.getElementById('global-data-error');
  const text = document.getElementById('global-data-error-text');
  const retryBtn = document.getElementById('global-data-error-retry');
  if (!host || !text || !retryBtn) return;

  text.textContent = message || 'Не удалось загрузить данные карты.';
  host.hidden = false;
  host.setAttribute('aria-hidden', 'false');

  if (globalDataErrorRetryHandler) {
    retryBtn.removeEventListener('click', globalDataErrorRetryHandler);
    globalDataErrorRetryHandler = null;
  }
  if (typeof onRetry === 'function') {
    globalDataErrorRetryHandler = () => onRetry();
    retryBtn.addEventListener('click', globalDataErrorRetryHandler);
  }
}

export function hideGlobalDataError() {
  const host = document.getElementById('global-data-error');
  const retryBtn = document.getElementById('global-data-error-retry');
  if (!host || !retryBtn) return;
  host.hidden = true;
  host.setAttribute('aria-hidden', 'true');
  if (globalDataErrorRetryHandler) {
    retryBtn.removeEventListener('click', globalDataErrorRetryHandler);
    globalDataErrorRetryHandler = null;
  }
}

export async function initUI(map, features) {
  hideGlobalDataError();
  const allFeatures = Array.isArray(features?.features)
    ? features.features.filter(isFeatureLike).map(enrichFeatureForUiKey)
    : [];
  let layers;
  try {
    layers = await loadLayers();
  } catch (error) {
    showGlobalDataError({ message: 'Не удалось загрузить данные карты.' });
    throw error;
  }
  const layerLookup = buildLayerLookup(layers, allFeatures);
  setLayerLookup(map, layers);

  const elements = {
    searchInput: document.getElementById('global-search') || document.getElementById('search-input'),
    searchClearBtn: document.getElementById('search-clear-btn'),
    searchDropdown: document.getElementById('search-dropdown'),
    filtersBtn: document.getElementById('filters-btn'),
    layersBtn: document.getElementById('layers-btn'),
    bookmarksBtn: document.getElementById('bookmarks-btn'),
    filtersPanel: document.getElementById('filters-panel'),
    layersPanel: document.getElementById('layers-panel'),
    bookmarksPanel: document.getElementById('bookmarks-panel'),
    topHeader: document.getElementById('top-header'),
    topActions: document.querySelector('#top-header .top-actions'),
    overflowBtn: document.getElementById('overflow-btn'),
    timelineStart: document.getElementById('timeline-start'),
    timelineEnd: document.getElementById('timeline-end'),
    timelineLabel: document.getElementById('timeline-range-label'),
    timelineCapsule: document.getElementById('timeline-range-capsule'),
    timelineActiveRange: document.getElementById('timeline-active-range'),
    timelineKnobStart: document.getElementById('timeline-knob-start'),
    timelineKnobEnd: document.getElementById('timeline-knob-end'),
    timelineAxis: document.getElementById('timeline-axis'),
    cardsRibbon: document.getElementById('cards-ribbon') || document.getElementById('object-list'),
    cardsState: document.getElementById('cards-state'),
    detailPanel: document.getElementById('detail-panel'),
    detailPanelBody: document.getElementById('detail-panel-body'),
    detailPanelClose: document.getElementById('detail-panel-close'),
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
  const confidenceValues = collectConfidenceValues(allFeatures);
  const state = {
    allFeatures,
    filteredFeatures: [],
    layerLookup,
    search: '',
    currentStartYear: years.min,
    currentEndYear: years.max,
    loading: true,
    error: '',
    selectedFeatureId: null,
    enabledLayerIds: new Set(layers.filter((layer) => layer?.is_enabled !== false).map((layer) => String(layer.layer_id || layer.id || '').trim()).filter(Boolean)),
    confidenceFilter: 'all',
    overlay: { activePrimary: null, activeModal: null },
    viewport: { mode: 'desktop', isMobile: false, isTablet: false },
    detailSheetExpanded: false,
    searchResults: [],
    bookmarks: [],
    applyState: null,
    warnings: []
  };
  initializeAnimatedPanels(elements);
  if (!state.enabledLayerIds.size) {
    allFeatures.forEach((feature) => {
      const layerId = String(normalizeProps(feature).layer_id || '').trim();
      if (layerId) state.enabledLayerIds.add(layerId);
    });
  }

  hydrateTimeline(elements, years, state);
  setupOverlayManager(elements, state, map);
  setupResponsiveUi(elements, state, map);
  renderTopPanels(elements, state, layers, confidenceValues, map);
  renderCardsState(elements, state);

  const applyState = () => {
    state.filteredFeatures = state.allFeatures.filter((feature) => isFeatureVisible(feature, state));
    updateMapData(map, { type: 'FeatureCollection', features: state.filteredFeatures });
    setMapLayerFilter(map, buildMapYearFilter(state.currentStartYear, state.currentEndYear));
    if (state.selectedFeatureId && !state.filteredFeatures.some((f) => getFeatureUiId(f) === state.selectedFeatureId)) {
      clearSelection(state, elements, map);
    }
    setSelectedFeatureId(map, state.selectedFeatureId);
    state.searchResults = buildSearchResults(state.filteredFeatures, state.search);
    renderSearchDropdown(elements, state, map);
    renderTopPanels(elements, state, layers, confidenceValues, map);
    renderCards(elements, state, map);
    updateCounters(elements, state, map);
    updateStatus(elements, state, map);
  };

  state.applyState = applyState;

  const debouncedSearch = debounce(() => {
    state.search = (elements.searchInput?.value || '').trim();
    toggleSearchClear(elements, state);
    applyState();
  }, 280);

  elements.searchInput?.addEventListener('input', debouncedSearch);
  elements.searchInput?.addEventListener('focus', () => {
    if (state.search) {
      openPrimaryPanel(elements, state, 'search', elements.searchInput);
      renderSearchDropdown(elements, state, map);
    }
  });
  elements.searchClearBtn?.addEventListener('click', () => {
    if (elements.searchInput) elements.searchInput.value = '';
    state.search = '';
    toggleSearchClear(elements, state);
    closePrimaryPanel(elements, state, 'search');
    applyState();
  });

  elements.timelineStart?.addEventListener('input', () => {
    state.currentStartYear = Math.min(Number(elements.timelineStart.value), state.currentEndYear);
    elements.timelineStart.value = String(state.currentStartYear);
    syncLegacyDateInputs(elements, state);
    updateTimelineLabel(elements, state);
    updateTimelineViz(elements, state);
    applyState();
  });
  elements.timelineEnd?.addEventListener('input', () => {
    state.currentEndYear = Math.max(Number(elements.timelineEnd.value), state.currentStartYear);
    elements.timelineEnd.value = String(state.currentEndYear);
    syncLegacyDateInputs(elements, state);
    updateTimelineLabel(elements, state);
    updateTimelineViz(elements, state);
    applyState();
  });

  elements.filtersBtn?.addEventListener('click', () => togglePrimaryPanel(elements, state, 'filters', elements.filtersBtn));
  elements.layersBtn?.addEventListener('click', () => togglePrimaryPanel(elements, state, 'layers', elements.layersBtn));
  elements.bookmarksBtn?.addEventListener('click', () => togglePrimaryPanel(elements, state, 'bookmarks', elements.bookmarksBtn));
  elements.overflowBtn?.addEventListener('click', () => {
    if (!elements.topActions) return;
    const expanded = elements.topActions.classList.toggle('is-expanded');
    elements.overflowBtn.setAttribute('aria-expanded', String(expanded));
  });

  setMapFeatureClickHandler(map, (feature, coordinates) => {
    selectFeature(state, elements, map, feature, {
      coordinates,
      openDetail: true,
      scrollCard: true
    });
  });
  elements.detailPanelClose?.addEventListener('click', () => clearSelection(state, elements, map));
  document.getElementById('detail-panel-expand')?.addEventListener('click', () => toggleDetailSheetState(state, elements));
  document.addEventListener('click', (event) => {
    const target = event.target;
    if (state.overlay.activePrimary) {
      const panel = getPanelByKey(elements, state.overlay.activePrimary);
      const button = getButtonByKey(elements, state.overlay.activePrimary);
      const inSearchShell = elements.searchDropdown?.contains(target) || elements.searchInput?.contains(target) || elements.searchClearBtn?.contains(target);
      const inPanel = panel?.contains(target) || button?.contains(target) || (state.overlay.activePrimary === 'search' && inSearchShell);
      if (!inPanel) closePrimaryPanel(elements, state, state.overlay.activePrimary);
    }
    if (elements.detailPanel?.hidden) return;
    const withinFloating = elements.detailPanel.contains(target);
    const withinCard = target.closest?.('.ribbon-card');
    if (!withinFloating && !withinCard) clearSelection(state, elements, map);
    if (elements.topActions?.classList.contains('is-expanded')) {
      const inTopActions = elements.topActions.contains(target) || elements.overflowBtn?.contains(target);
      if (!inTopActions) {
        elements.topActions.classList.remove('is-expanded');
        elements.overflowBtn?.setAttribute('aria-expanded', 'false');
      }
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented) return;
    if (event.key !== 'Escape') return;
    const closed = closeTopOverlay(elements, state, map);
    if (closed) {
      event.preventDefault();
      restoreOverlayFocus(state.overlay.lastPrimaryTrigger, elements);
    }
  });

  state.loading = false;
  applyState();
  applyResponsiveLayout(elements, state, map);

  return {
    getVisibleCounts() {
      return { listCount: state.filteredFeatures.length, mapCount: getMapFeatureCount(map) };
    }
  };
}

function isFeatureVisible(feature, state) {
  const props = normalizeProps(feature);
  const text = state.search.toLowerCase();
  const layerId = String(props.layer_id || '').trim();
  if (layerId && !state.enabledLayerIds.has(layerId)) return false;
  if (state.confidenceFilter !== 'all') {
    const confidence = String(props.coordinates_confidence || 'unknown').toLowerCase();
    if (confidence !== state.confidenceFilter) return false;
  }
  const haystack = `${String(props.name_ru || '')} ${String(props.name_en || '')} ${normalizeTags(props.tags)} ${String(props.title_short || '')}`.toLowerCase();
  if (text && !haystack.includes(text)) return false;

  const start = parseYear(props.date_start ?? props.date_construction_end ?? props.date_end);
  const end = parseYear(props.date_end ?? props.date_construction_end ?? props.date_start);
  if (Number.isFinite(start) && start > state.currentEndYear) return false;
  if (Number.isFinite(end) && end < state.currentStartYear) return false;
  return true;
}

function renderTopPanels(elements, state, layers, confidenceValues, map) {
  renderFiltersPanel(elements, state, layers, confidenceValues);
  renderLayersPanel(elements, state, layers);
  renderBookmarksPanel(elements, state, map);
}

function renderFiltersPanel(elements, state, layers, confidenceValues) {
  if (!elements.filtersPanel) return;
  const activeCount = state.filteredFeatures.length;
  const totalCount = state.allFeatures.length;
  elements.filtersPanel.replaceChildren();

  const title = document.createElement('h3');
  title.className = 'panel-title';
  title.textContent = 'Filters';
  const summary = document.createElement('p');
  summary.className = 'status-summary';
  summary.textContent = `${activeCount} of ${totalCount} objects visible`;

  const layerWrap = document.createElement('div');
  layerWrap.className = 'chips';
  (layers || []).slice(0, 14).forEach((layer) => {
    const id = String(layer?.layer_id || layer?.id || '').trim();
    if (!id) return;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = `chip${state.enabledLayerIds.has(id) ? ' is-active' : ''}`;
    chip.textContent = String(layer?.name_ru || id);
    chip.addEventListener('click', () => {
      if (state.enabledLayerIds.has(id)) state.enabledLayerIds.delete(id);
      else state.enabledLayerIds.add(id);
      state.applyState?.();
    });
    layerWrap.appendChild(chip);
  });

  elements.filtersPanel.append(title, summary, layerWrap);
  if (confidenceValues.length) {
    const group = document.createElement('div');
    group.className = 'chips';
    ['all', ...confidenceValues].forEach((mode) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `chip${state.confidenceFilter === mode ? ' is-active' : ''}`;
      button.textContent = mode[0].toUpperCase() + mode.slice(1);
      button.addEventListener('click', () => {
        state.confidenceFilter = mode;
        state.applyState?.();
      });
      group.appendChild(button);
    });
    elements.filtersPanel.appendChild(group);
  }
}

function renderLayersPanel(elements, state, layers) {
  if (!elements.layersPanel) return;
  elements.layersPanel.replaceChildren();
  const title = document.createElement('h3');
  title.className = 'panel-title';
  title.textContent = 'Layers';
  elements.layersPanel.appendChild(title);

  (layers || []).forEach((layer) => {
    const id = String(layer?.layer_id || layer?.id || '').trim();
    if (!id) return;
    const row = document.createElement('label');
    row.className = 'layer-item';

    const left = document.createElement('span');
    const dot = document.createElement('span');
    dot.className = 'layer-dot';
    dot.style.backgroundColor = String(layer?.color_hex || '#94a3b8');
    const label = document.createElement('span');
    label.textContent = String(layer?.name_ru || id);
    left.append(dot, document.createTextNode(' '), label);

    const toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.checked = state.enabledLayerIds.has(id);
    toggle.addEventListener('change', () => {
      if (toggle.checked) state.enabledLayerIds.add(id);
      else state.enabledLayerIds.delete(id);
      state.applyState?.();
    });

    row.append(left, toggle);
    elements.layersPanel.appendChild(row);
  });
}

function renderBookmarksPanel(elements, state, map) {
  if (!elements.bookmarksPanel) return;
  elements.bookmarksPanel.replaceChildren();

  const title = document.createElement('h3');
  title.className = 'panel-title';
  title.textContent = 'Bookmarks';
  elements.bookmarksPanel.appendChild(title);

  const selected = getSelectedFeature(state);
  if (selected) {
    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.textContent = 'Save bookmark';
    saveBtn.addEventListener('click', () => {
      const id = getFeatureUiId(selected);
      if (state.bookmarks.some((bookmark) => bookmark.id === id)) return;
      state.bookmarks.unshift({ id, feature: selected });
      renderBookmarksPanel(elements, state, map);
    });
    elements.bookmarksPanel.appendChild(saveBtn);
  }

  if (!state.bookmarks.length) {
    const empty = document.createElement('p');
    empty.className = 'bookmark-empty';
    empty.textContent = 'Bookmarks will be available later';
    elements.bookmarksPanel.appendChild(empty);
    return;
  }

  state.bookmarks.slice(0, 20).forEach((bookmark) => {
    const props = normalizeProps(bookmark.feature);
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'bookmark-item';
    const title = document.createElement('span');
    title.textContent = String(props.name_ru || props.title_short || 'Untitled');
    const meta = document.createElement('span');
    meta.className = 'bookmark-meta';
    meta.textContent = formatRange(props.date_start, props.date_end);
    item.append(title, meta);
    item.addEventListener('click', () => {
      selectFeature(state, elements, map, bookmark.feature, { centerOnMap: true, openDetail: true, scrollCard: true });
      closePrimaryPanel(elements, state, 'bookmarks');
    });
    elements.bookmarksPanel.appendChild(item);
  });
}

function buildSearchResults(filteredFeatures, searchText) {
  if (!searchText) return [];
  return filteredFeatures.slice(0, 5);
}

function renderSearchDropdown(elements, state, map) {
  if (!elements.searchDropdown) return;
  elements.searchDropdown.replaceChildren();
  const shouldShow = Boolean(state.search);
  if (!shouldShow) {
    closePrimaryPanel(elements, state, 'search');
    return;
  }
  openPrimaryPanel(elements, state, 'search', elements.searchInput);

  if (!state.searchResults.length) {
    const noResults = document.createElement('div');
    noResults.className = 'search-no-results';
    noResults.textContent = 'No matches';
    elements.searchDropdown.appendChild(noResults);
    return;
  }

  state.searchResults.forEach((feature) => {
    const props = normalizeProps(feature);
    const featureId = getFeatureUiId(feature);
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `search-result-item${state.selectedFeatureId === featureId ? ' is-selected' : ''}`;
    const title = String(props.name_ru || props.name_en || props.title_short || 'Untitled');
    const meta = `${formatRange(props.date_start, props.date_end)} • ${state.layerLookup.get(String(props.layer_id || '').trim()) || props.layer_id || 'Layer'}`;
    item.textContent = title;
    const metaNode = document.createElement('span');
    metaNode.className = 'search-result-meta';
    metaNode.textContent = meta;
    item.appendChild(metaNode);
    item.addEventListener('click', () => {
      selectFeature(state, elements, map, feature, { centerOnMap: true, openDetail: true, scrollCard: true });
      closePrimaryPanel(elements, state, 'search');
    });
    elements.searchDropdown.appendChild(item);
  });
}

function setupOverlayManager(elements, state, map) {
  const closeAll = () => {
    ['search', 'filters', 'layers', 'bookmarks'].forEach((key) => closePrimaryPanel(elements, state, key));
  };
  state.overlay.closeAll = closeAll;

  document.addEventListener('artemis:overlay-open', (event) => {
    const source = event?.detail?.source || '';
    if (!state.viewport.isMobile) return;
    if (source === 'detail') {
      closeAll();
      return;
    }
    if (source === 'primary') {
      hideDetailPanel(elements);
      return;
    }
    if (source === 'ugc' || source === 'moderation') {
      closeAll();
      clearSelection(state, elements, map);
    }
  });
}

function togglePrimaryPanel(elements, state, key, trigger = null) {
  if (state.overlay.activePrimary === key) closePrimaryPanel(elements, state, key);
  else openPrimaryPanel(elements, state, key, trigger);
}

function openPrimaryPanel(elements, state, key, trigger = null) {
  ['search', 'filters', 'layers', 'bookmarks'].forEach((name) => {
    const panel = getPanelByKey(elements, name);
    const button = getButtonByKey(elements, name);
    const isActive = name === key;
    if (panel) setPanelOpenState(panel, isActive);
    if (button) button.setAttribute('aria-expanded', String(isActive));
  });
  state.overlay.activePrimary = key;
  state.overlay.lastPrimaryTrigger = trigger || getButtonByKey(elements, key) || elements.searchInput || null;
  if (state.viewport.isMobile) {
    document.dispatchEvent(new CustomEvent('artemis:overlay-open', { detail: { source: 'primary', key } }));
  }
}

function closePrimaryPanel(elements, state, key) {
  const panel = getPanelByKey(elements, key);
  const button = getButtonByKey(elements, key);
  if (panel) setPanelOpenState(panel, false);
  if (button) button.setAttribute('aria-expanded', 'false');
  if (state.overlay.activePrimary === key) state.overlay.activePrimary = null;
}

function getPanelByKey(elements, key) {
  return {
    search: elements.searchDropdown,
    filters: elements.filtersPanel,
    layers: elements.layersPanel,
    bookmarks: elements.bookmarksPanel
  }[key] || null;
}

function getButtonByKey(elements, key) {
  return {
    filters: elements.filtersBtn,
    layers: elements.layersBtn,
    bookmarks: elements.bookmarksBtn
  }[key] || null;
}

function toggleSearchClear(elements, state) {
  if (!elements.searchClearBtn) return;
  elements.searchClearBtn.hidden = !state.search;
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
    const featureId = getFeatureUiId(feature);
    const item = document.createElement('li');
    item.className = `ribbon-card${state.selectedFeatureId === featureId ? ' is-selected' : ''}`;
    item.dataset.featureId = featureId;
    item.tabIndex = 0;

    const image = buildImageNode(props, 'Object image');

    const meta = document.createElement('div');
    meta.className = 'meta';
    const title = document.createElement('h4');
    title.textContent = String(props.name_ru || 'Без названия');
    const date = document.createElement('p');
    date.textContent = formatRange(props.date_start, props.date_end);
    const tag = document.createElement('p');
    tag.className = 'tag';
    tag.textContent = String(props.title_short || state.layerLookup.get(String(props.layer_id || '').trim()) || '').slice(0, 56);
    meta.append(title, date, tag);

    item.append(image, meta);
    item.addEventListener('click', () => {
      selectFeature(state, elements, map, feature, { centerOnMap: true, openDetail: true, scrollCard: false });
    });
    item.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      selectFeature(state, elements, map, feature, { centerOnMap: true, openDetail: true, scrollCard: false });
    });

    list.appendChild(item);
  });
}

function showDetailPanel(state, elements, map, feature) {
  if (!elements.detailPanel || !elements.detailPanelBody) return;
  const props = normalizeProps(feature);
  const layerLabel = state.layerLookup.get(String(props.layer_id || '').trim()) || String(props.layer_id || 'Layer');
  const dateLabel = formatRangeLabel(props.date_start, props.date_end);
  const detail = document.createElement('div');
  detail.className = 'detail-content';

  const imageNode = buildImageNode(props, 'Object image', true);
  imageNode.classList.add('detail-hero-media');
  detail.appendChild(imageNode);

  const header = document.createElement('section');
  header.className = 'detail-section detail-header';
  const title = document.createElement('h3');
  title.className = 'detail-title';
  title.textContent = getPrimaryTitle(props);
  const date = document.createElement('p');
  date.className = 'detail-date';
  date.textContent = dateLabel;
  const badges = document.createElement('div');
  badges.className = 'detail-badges';
  badges.append(buildBadge(layerLabel, 'muted'));
  const confidence = getConfidenceLabel(props.coordinates_confidence);
  if (confidence) badges.append(buildBadge(confidence, 'accent'));
  header.append(title, date, badges);

  const descriptionSection = document.createElement('section');
  descriptionSection.className = 'detail-section';
  const descriptionTitle = createSectionTitle('Context');
  const descriptionText = document.createElement('p');
  descriptionText.className = 'detail-description';
  const fullDescription = String(props.description || props.title_short || 'Контекст для этого объекта пока отсутствует.');
  descriptionText.textContent = truncateText(fullDescription, 220);
  descriptionSection.append(descriptionTitle, descriptionText);
  if (fullDescription.length > 220) {
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'detail-inline-action';
    toggle.textContent = 'Expand';
    toggle.addEventListener('click', () => {
      const expanded = toggle.dataset.expanded === 'true';
      toggle.dataset.expanded = expanded ? 'false' : 'true';
      toggle.textContent = expanded ? 'Expand' : 'Collapse';
      descriptionText.textContent = expanded ? truncateText(fullDescription, 220) : fullDescription;
    });
    descriptionSection.appendChild(toggle);
  }

  const metaSection = document.createElement('section');
  metaSection.className = 'detail-section';
  metaSection.appendChild(createSectionTitle('Meta'));
  appendMetaRow(metaSection, 'Place', props.place_name || props.region || props.country);
  appendMetaRow(metaSection, 'Coordinates', formatCoordinates(feature?.geometry?.coordinates));
  appendMetaRow(metaSection, 'Source type', props.source_type || 'Unknown');
  appendMetaRow(metaSection, 'Source domain', extractDomain(props.source_url));
  appendMetaRow(metaSection, 'Sequence', props.sequence_order);
  appendMetaRow(metaSection, 'Dates', dateLabel);

  const sourceSection = document.createElement('section');
  sourceSection.className = 'detail-section';
  sourceSection.appendChild(createSectionTitle('Source'));
  const sourceUrl = normalizeSafeUrl(String(props.source_url || '').trim());
  if (sourceUrl) {
    const sourceLink = document.createElement('a');
    sourceLink.className = 'detail-action-link';
    setSafeLink(sourceLink, sourceUrl);
    sourceLink.textContent = 'Open source';
    sourceSection.appendChild(sourceLink);
  } else {
    const unavailable = document.createElement('p');
    unavailable.className = 'detail-empty';
    unavailable.textContent = 'Source unavailable';
    sourceSection.appendChild(unavailable);
  }
  if (props.source_license) sourceSection.appendChild(buildBadge(String(props.source_license), 'muted'));

  const relatedSection = document.createElement('section');
  relatedSection.className = 'detail-section';
  relatedSection.appendChild(createSectionTitle('Related'));
  const relatedItems = getRelatedFeatures(state, feature, 3);
  if (!relatedItems.length) {
    const empty = document.createElement('p');
    empty.className = 'detail-empty';
    empty.textContent = 'No related objects';
    relatedSection.appendChild(empty);
  } else {
    relatedItems.forEach((relatedFeature) => {
      const relatedProps = normalizeProps(relatedFeature);
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'related-item';
      const itemTitle = document.createElement('span');
      itemTitle.className = 'related-title';
      itemTitle.textContent = getPrimaryTitle(relatedProps);
      const itemMeta = document.createElement('span');
      itemMeta.className = 'related-meta';
      itemMeta.textContent = `${formatRangeLabel(relatedProps.date_start, relatedProps.date_end)} • ${state.layerLookup.get(String(relatedProps.layer_id || '').trim()) || relatedProps.layer_id || 'Layer'}`;
      item.append(itemTitle, itemMeta);
      item.addEventListener('click', () => {
        selectFeature(state, elements, map, relatedFeature, { centerOnMap: true, openDetail: true, scrollCard: true });
      });
      relatedSection.appendChild(item);
    });
  }

  const actionsSection = document.createElement('section');
  actionsSection.className = 'detail-section detail-actions';
  const focusButton = document.createElement('button');
  focusButton.type = 'button';
  focusButton.textContent = 'Focus on map';
  focusButton.addEventListener('click', () => focusFeatureOnMap(map, feature));
  const sourceButton = document.createElement('button');
  sourceButton.type = 'button';
  sourceButton.textContent = 'Open source';
  sourceButton.disabled = !sourceUrl;
  if (sourceUrl) {
    sourceButton.addEventListener('click', () => window.open(sourceUrl, '_blank', 'noopener,noreferrer'));
  }
  const noteButton = document.createElement('button');
  noteButton.type = 'button';
  noteButton.textContent = 'Add note [TODO]';
  noteButton.disabled = true;
  actionsSection.append(focusButton, sourceButton, noteButton);

  detail.append(header, descriptionSection, metaSection, sourceSection, relatedSection, actionsSection);
  elements.detailPanelBody.replaceChildren(createDetailSkeleton());
  setPanelOpenState(elements.detailPanel, true);
  elements.detailPanel.classList.add('is-selected');
  if (state.viewport.isMobile) {
    elements.detailPanel.classList.add('is-mobile-sheet');
    state.detailSheetExpanded = false;
    syncDetailSheetState(state, elements);
  } else {
    elements.detailPanel.classList.remove('is-mobile-sheet', 'is-expanded');
  }
  document.dispatchEvent(new CustomEvent('artemis:overlay-open', { detail: { source: 'detail' } }));
  window.requestAnimationFrame(() => elements.detailPanelBody.replaceChildren(detail));
}

function hideDetailPanel(elements) {
  if (!elements.detailPanel) return;
  elements.detailPanel.classList.remove('is-selected');
  setPanelOpenState(elements.detailPanel, false);
}

function renderCardsState(elements, state) {
  if (!elements.cardsState) return;
  elements.cardsState.className = 'cards-state';
  elements.cardsState.replaceChildren();

  if (state.loading) {
    elements.cardsState.appendChild(createInlineStateBlock({
      variant: 'info',
      title: 'Loading',
      message: 'Loading events…'
    }));
    renderCardsSkeleton(elements, 4);
    return;
  }

  if (state.error) {
    elements.cardsState.appendChild(createInlineStateBlock({
      variant: 'error',
      title: 'Data unavailable',
      message: state.error
    }));
    if (elements.cardsRibbon) elements.cardsRibbon.replaceChildren();
    return;
  }

  if (state.empty) {
    elements.cardsState.appendChild(createInlineStateBlock({
      variant: 'warning',
      title: 'No results',
      message: 'No objects in this time range.'
    }));
    if (elements.cardsRibbon) elements.cardsRibbon.replaceChildren();
    return;
  }

  if (state.warnings?.length) {
    elements.cardsState.appendChild(createInlineStateBlock({
      variant: 'warning',
      title: 'Limited data',
      message: state.warnings[0]
    }));
    return;
  }

  elements.cardsState.textContent = `${state.filteredFeatures.length} objects`;
}

function hydrateTimeline(elements, years, state) {
  if (!elements.timelineStart || !elements.timelineEnd) return;
  elements.timelineStart.min = String(years.min);
  elements.timelineStart.max = String(years.max);
  elements.timelineEnd.min = String(years.min);
  elements.timelineEnd.max = String(years.max);
  elements.timelineStart.value = String(state.currentStartYear);
  elements.timelineEnd.value = String(state.currentEndYear);
  renderTimelineAxis(elements, years);
  syncLegacyDateInputs(elements, state);
  updateTimelineLabel(elements, state);
  updateTimelineViz(elements, state);
}

function updateTimelineLabel(elements, state) {
  if (elements.timelineLabel) elements.timelineLabel.textContent = 'Selected range';
  if (elements.timelineCapsule) elements.timelineCapsule.textContent = `${state.currentStartYear}–${state.currentEndYear}`;
}

function updateTimelineViz(elements, state) {
  if (!elements.timelineActiveRange) return;
  const min = Number(elements.timelineStart?.min ?? state.currentStartYear);
  const max = Number(elements.timelineStart?.max ?? state.currentEndYear);
  const span = Math.max(1, max - min);
  const left = ((state.currentStartYear - min) / span) * 100;
  const right = ((state.currentEndYear - min) / span) * 100;
  elements.timelineActiveRange.style.left = `${left}%`;
  elements.timelineActiveRange.style.right = `${100 - right}%`;
  if (elements.timelineKnobStart) elements.timelineKnobStart.style.left = `${left}%`;
  if (elements.timelineKnobEnd) elements.timelineKnobEnd.style.left = `${right}%`;
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

function collectConfidenceValues(features) {
  return [...new Set(features.map((f) => String(normalizeProps(f).coordinates_confidence || '').trim().toLowerCase()).filter(Boolean))].slice(0, 3);
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
  const activeFilters = Number(Boolean(state.search))
    + Number(state.confidenceFilter !== 'all')
    + Number(state.enabledLayerIds.size !== state.layerLookup.size)
    + 1;
  if (elements.activeFiltersCount) elements.activeFiltersCount.textContent = String(activeFilters);
}

function updateStatus(elements, state, map) {
  if (!elements.statusMessage) return;
  const diagnostics = getMapBuildDiagnostics(map);
  elements.statusMessage.textContent = `Карта готова. Загружено ${diagnostics.inputTotal}, отображается ${getMapFeatureCount(map)}, в ленте ${state.filteredFeatures.length}.`;
}

function selectFeature(state, elements, map, feature, options = {}) {
  const selectedFeature = state.allFeatures.find((candidate) => getFeatureUiId(candidate) === getFeatureUiId(feature));
  if (!selectedFeature) return;
  state.selectedFeatureId = getFeatureUiId(selectedFeature);
  setSelectedFeatureId(map, state.selectedFeatureId);
  renderCards(elements, state, map);
  renderBookmarksPanel(elements, state, map);
  if (options.centerOnMap) focusFeatureOnMap(map, selectedFeature);
  if (options.openDetail !== false) {
    showDetailPanel(state, elements, map, selectedFeature);
  }
  if (options.scrollCard) {
    const selectedNode = elements.cardsRibbon?.querySelector(`.ribbon-card[data-feature-id="${CSS.escape(state.selectedFeatureId)}"]`);
    selectedNode?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  }
}

function clearSelection(state, elements, map) {
  state.selectedFeatureId = null;
  setSelectedFeatureId(map, null);
  hideDetailPanel(elements);
  renderCards(elements, state, map);
}

function getSelectedFeature(state) {
  return state.allFeatures.find((feature) => getFeatureUiId(feature) === state.selectedFeatureId) || null;
}

function renderCardsSkeleton(elements, count = 4) {
  if (!elements.cardsRibbon) return;
  const skeletons = Array.from({ length: count }, () => {
    const item = document.createElement('li');
    item.className = 'skeleton-card';
    return item;
  });
  elements.cardsRibbon.replaceChildren(...skeletons);
}

function initializeAnimatedPanels(elements) {
  [elements.searchDropdown, elements.filtersPanel, elements.layersPanel, elements.bookmarksPanel, elements.detailPanel]
    .filter(Boolean)
    .forEach((panel) => {
      panel.classList.remove('is-open', 'is-closing');
      panel.setAttribute('aria-hidden', 'true');
    });
}

function setPanelOpenState(panel, open) {
  if (!panel) return;
  if (open) {
    panel.hidden = false;
    panel.classList.remove('is-closing');
    panel.classList.add('is-open');
    panel.setAttribute('aria-hidden', 'false');
    panel.dataset.state = 'open';
    return;
  }
  panel.classList.remove('is-open');
  panel.classList.add('is-closing');
  panel.setAttribute('aria-hidden', 'true');
  panel.dataset.state = 'closed';
  window.setTimeout(() => {
    if (panel.classList.contains('is-open')) return;
    panel.hidden = true;
    panel.classList.remove('is-closing');
  }, 260);
}

function closeTopOverlay(elements, state, map) {
  const rejectModal = document.getElementById('moderation-reject-modal');
  if (rejectModal && !rejectModal.hidden) {
    document.querySelector('[data-moderation-action="close-reject-modal"]')?.click();
    return true;
  }
  const loginModal = document.getElementById('login-modal');
  if (loginModal && !loginModal.hidden) {
    loginModal.querySelector('[data-close-modal]')?.click();
    return true;
  }
  const moderationWorkspace = document.getElementById('moderation-workspace');
  if (moderationWorkspace && !moderationWorkspace.hidden && moderationWorkspace.classList.contains('is-open')) {
    moderationWorkspace.querySelector('[data-moderation-action="close-workspace"]')?.click();
    return true;
  }
  const ugcPanel = document.getElementById('ugc-panel');
  if (ugcPanel && !ugcPanel.hidden) {
    document.getElementById('ugc-close-btn')?.click();
    return true;
  }
  if (state.overlay.activePrimary) {
    closePrimaryPanel(elements, state, state.overlay.activePrimary);
    return true;
  }
  if (!elements.detailPanel?.hidden) {
    clearSelection(state, elements, map);
    return true;
  }
  return false;
}

function restoreOverlayFocus(lastTrigger, elements) {
  const fallback = elements.filtersBtn || elements.layersBtn || elements.bookmarksBtn || elements.searchInput;
  const target = lastTrigger && typeof lastTrigger.focus === 'function' ? lastTrigger : fallback;
  target?.focus?.({ preventScroll: true });
}

function renderTimelineAxis(elements, years) {
  if (!elements.timelineAxis) return;
  const points = [years.min, Math.round((years.min + years.max) / 2), years.max];
  elements.timelineAxis.replaceChildren(...points.map((year) => {
    const node = document.createElement('span');
    node.textContent = String(year);
    return node;
  }));
}

function isFeatureLike(feature) {
  return feature && typeof feature === 'object' && (feature.type === 'Feature' || feature.properties || feature.geometry);
}
function enrichFeatureForUiKey(feature, index) {
  const properties = normalizeProps(feature);
  const sourceId = String(properties.id || properties.object_id || properties.slug || '').trim();
  const coords = Array.isArray(feature?.geometry?.coordinates) ? feature.geometry.coordinates.join(':') : String(index);
  const uiKey = sourceId || `${String(properties.name_ru || 'feature').trim()}::${coords}::${index}`;
  return {
    ...feature,
    properties: {
      ...properties,
      _ui_id: uiKey
    }
  };
}
function getFeatureUiId(feature) {
  return String(normalizeProps(feature)._ui_id || '');
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
  return formatRangeLabel(start, end);
}
function formatRangeLabel(start, end) {
  const s = parseYear(start);
  const e = parseYear(end);
  if (Number.isFinite(s) && Number.isFinite(e)) return `${formatYearLabel(s)}—${formatYearLabel(e)}`;
  if (Number.isFinite(s)) return formatYearLabel(s);
  if (Number.isFinite(e)) return formatYearLabel(e);
  return 'Дата не указана';
}
function formatYearLabel(year) {
  const value = Number(year);
  if (!Number.isFinite(value)) return 'Unknown';
  if (value < 0) return `${Math.abs(value)} BCE`;
  if (value === 0) return '1 BCE/1 CE';
  return `${value} CE`;
}
function truncateText(value, limit) {
  if (value.length <= limit) return value;
  return `${value.slice(0, limit - 1).trimEnd()}…`;
}
function buildImageNode(props, fallbackAlt, large = false) {
  const safeImage = normalizeSafeUrl(String(props.image_url || '').trim(), { allowRelative: true });
  if (safeImage) {
    const image = document.createElement('img');
    image.src = safeImage;
    image.alt = String(props.name_ru || fallbackAlt);
    image.loading = 'lazy';
    image.referrerPolicy = 'no-referrer';
    image.addEventListener('error', () => {
      image.replaceWith(createPlaceholderImage(large));
    }, { once: true });
    return image;
  }
  return createPlaceholderImage(large);
}
function createPlaceholderImage(large = false) {
  const placeholder = document.createElement('div');
  placeholder.className = `img-placeholder${large ? ' is-large' : ''}`;
  placeholder.textContent = 'No image available';
  return placeholder;
}
function getPrimaryTitle(props) {
  return String(props.name_ru || props.name_en || props.title_short || 'Без названия');
}
function getConfidenceLabel(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (!normalized) return '';
  if (normalized === 'exact') return 'Exact coordinates';
  if (normalized === 'approximate') return 'Approximate coordinates';
  if (normalized === 'conditional') return 'Conditional coordinates';
  return normalized;
}
function buildBadge(label, tone = '') {
  const badge = document.createElement('span');
  badge.className = `detail-badge${tone ? ` is-${tone}` : ''}`;
  badge.textContent = String(label || 'Unknown');
  return badge;
}
function createSectionTitle(value) {
  const title = document.createElement('h4');
  title.className = 'detail-section-title';
  title.textContent = String(value || '');
  return title;
}
function appendMetaRow(parent, label, value) {
  if (!parent || value === null || value === undefined || value === '') return;
  const row = document.createElement('div');
  row.className = 'detail-meta-row';
  const key = document.createElement('span');
  key.className = 'detail-meta-label';
  key.textContent = String(label || '');
  const val = document.createElement('span');
  val.className = 'detail-meta-value';
  val.textContent = String(value);
  row.append(key, val);
  parent.appendChild(row);
}
function formatCoordinates(coords) {
  if (!Array.isArray(coords) || coords.length < 2) return '';
  const [lng, lat] = coords;
  if (!Number.isFinite(Number(lng)) || !Number.isFinite(Number(lat))) return '';
  return `${Number(lat).toFixed(4)}, ${Number(lng).toFixed(4)}`;
}
function extractDomain(value) {
  const safeUrl = normalizeSafeUrl(String(value || '').trim());
  if (!safeUrl) return '';
  try {
    return new URL(safeUrl).hostname.replace(/^www\./, '');
  } catch (_error) {
    return '';
  }
}
function getRelatedFeatures(state, feature, limit = 3) {
  const currentProps = normalizeProps(feature);
  const currentId = getFeatureUiId(feature);
  const currentLayer = String(currentProps.layer_id || '').trim();
  const currentStart = parseYear(currentProps.date_start ?? currentProps.date_end);
  const currentEnd = parseYear(currentProps.date_end ?? currentProps.date_start);
  return state.allFeatures
    .filter((candidate) => getFeatureUiId(candidate) !== currentId)
    .map((candidate) => {
      const props = normalizeProps(candidate);
      const layerScore = String(props.layer_id || '').trim() === currentLayer ? 2 : 0;
      const candidateStart = parseYear(props.date_start ?? props.date_end);
      const candidateEnd = parseYear(props.date_end ?? props.date_start);
      const hasDates = Number.isFinite(currentStart) && Number.isFinite(currentEnd) && Number.isFinite(candidateStart) && Number.isFinite(candidateEnd);
      const overlap = hasDates && candidateStart <= currentEnd && candidateEnd >= currentStart;
      const rangeDistance = hasDates ? Math.abs(((candidateStart + candidateEnd) / 2) - ((currentStart + currentEnd) / 2)) : Number.MAX_SAFE_INTEGER;
      const timeScore = overlap ? 1 : 0;
      return { candidate, score: layerScore + timeScore, rangeDistance };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || a.rangeDistance - b.rangeDistance)
    .slice(0, limit)
    .map((entry) => entry.candidate);
}
function createDetailSkeleton() {
  const skeleton = document.createElement('div');
  skeleton.className = 'detail-skeleton';
  for (let index = 0; index < 5; index += 1) {
    const line = document.createElement('div');
    line.className = 'detail-skeleton-line';
    skeleton.appendChild(line);
  }
  return skeleton;
}


function setupResponsiveUi(elements, state, map) {
  const apply = debounce(() => applyResponsiveLayout(elements, state, map), 80);
  window.addEventListener('resize', apply, { passive: true });
  window.addEventListener('orientationchange', apply, { passive: true });
}

function applyResponsiveLayout(elements, state, map) {
  const width = window.innerWidth || document.documentElement.clientWidth || 1280;
  const mode = width <= 720 ? 'mobile' : (width <= 1080 ? 'tablet' : 'desktop');
  state.viewport = { mode, isMobile: mode === 'mobile', isTablet: mode === 'tablet' };
  document.body.dataset.viewport = mode;
  if (elements.topActions) {
    elements.topActions.classList.toggle('is-collapsed', mode !== 'desktop');
    if (mode === 'desktop') elements.topActions.classList.remove('is-expanded');
  }
  if (elements.overflowBtn) {
    elements.overflowBtn.hidden = mode === 'desktop';
    elements.overflowBtn.setAttribute('aria-expanded', elements.topActions?.classList.contains('is-expanded') ? 'true' : 'false');
  }
  if (!state.viewport.isMobile) {
    state.detailSheetExpanded = false;
    elements.detailPanel?.classList.remove('is-mobile-sheet', 'is-expanded');
  } else if (elements.detailPanel && !elements.detailPanel.hidden) {
    elements.detailPanel.classList.add('is-mobile-sheet');
    syncDetailSheetState(state, elements);
  }
  map?.resize?.();
}

function toggleDetailSheetState(state, elements) {
  if (!state.viewport.isMobile || elements.detailPanel?.hidden) return;
  state.detailSheetExpanded = !state.detailSheetExpanded;
  syncDetailSheetState(state, elements);
}

function syncDetailSheetState(state, elements) {
  const panel = elements.detailPanel;
  const expandBtn = document.getElementById('detail-panel-expand');
  if (!panel) return;
  panel.classList.toggle('is-expanded', Boolean(state.detailSheetExpanded));
  if (expandBtn) {
    expandBtn.setAttribute('aria-expanded', String(Boolean(state.detailSheetExpanded)));
    expandBtn.textContent = state.detailSheetExpanded ? '⇩' : '⇧';
    expandBtn.setAttribute('aria-label', state.detailSheetExpanded ? 'Collapse detail panel' : 'Expand detail panel');
  }
}
