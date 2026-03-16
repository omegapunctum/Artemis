async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to load ${url}: ${response.status}`);
  }
  return response.json();
}

async function loadFeatures() {
  return fetchJson('data/features.geojson');
}

async function loadLayers() {
  return fetchJson('data/layers.json');
}

async function loadMapData() {
  const [features, layers] = await Promise.all([loadFeatures(), loadLayers()]);
  return { features, layers };
}

window.loadFeatures = loadFeatures;
window.loadLayers = loadLayers;
window.loadMapData = loadMapData;
