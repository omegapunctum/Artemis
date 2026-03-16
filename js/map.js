function normalizeLayerRecord(record) {
  const payload = record && record.fields ? record.fields : record;
  return {
    layer_id: payload.layer_id,
    name: payload.name || payload.layer_id,
    color_hex: payload.color_hex || '#3b82f6',
  };
}

function initMap(features, layers) {
  const map = new maplibregl.Map({
    container: 'map',
    style: 'https://demotiles.maplibre.org/style.json',
    center: [60.6, 56.8],
    zoom: 11,
  });

  map.addControl(new maplibregl.NavigationControl(), 'top-right');

  map.on('load', () => {
    const useClustering = (features.features || []).length > 500;

    map.addSource('features', {
      type: 'geojson',
      data: features,
      cluster: useClustering,
      clusterRadius: 40,
      clusterMaxZoom: 13,
    });

    const normalizedLayers = layers.map(normalizeLayerRecord).filter((layer) => layer.layer_id);

    normalizedLayers.forEach((layer) => {
      map.addLayer({
        id: layer.layer_id,
        type: 'circle',
        source: 'features',
        filter: ['==', ['get', 'layer_id'], layer.layer_id],
        paint: {
          'circle-radius': 6,
          'circle-color': layer.color_hex,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1,
        },
      });
    });

    if (useClustering) {
      map.addLayer({
        id: 'clusters',
        type: 'circle',
        source: 'features',
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': '#334155',
          'circle-radius': ['step', ['get', 'point_count'], 14, 20, 18, 100, 24],
        },
      });

      map.addLayer({
        id: 'cluster-count',
        type: 'symbol',
        source: 'features',
        filter: ['has', 'point_count'],
        layout: {
          'text-field': ['get', 'point_count_abbreviated'],
          'text-size': 12,
        },
        paint: {
          'text-color': '#ffffff',
        },
      });
    }
  });

  window.artemisMap = map;
  return map;
}

window.initMap = initMap;
