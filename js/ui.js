function normalizeLayerRecord(record) {
  const payload = record && record.fields ? record.fields : record;
  return {
    layer_id: payload.layer_id,
    name: payload.name || payload.layer_id,
    color_hex: payload.color_hex || '#3b82f6',
  };
}

function buildLayerLegend(layers) {
  const container = document.getElementById('legend');
  if (!container) {
    return;
  }

  container.innerHTML = '';

  layers.map(normalizeLayerRecord).forEach((layer) => {
    if (!layer.layer_id) return;

    const row = document.createElement('label');
    row.className = 'legend-row';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = true;
    checkbox.addEventListener('change', () => {
      const map = window.artemisMap;
      if (!map || !map.getLayer(layer.layer_id)) return;
      map.setLayoutProperty(layer.layer_id, 'visibility', checkbox.checked ? 'visible' : 'none');
    });

    const color = document.createElement('span');
    color.className = 'legend-color';
    color.style.backgroundColor = layer.color_hex;

    const title = document.createElement('span');
    title.textContent = layer.name;

    row.append(checkbox, color, title);
    container.appendChild(row);
  });
}

window.buildLayerLegend = buildLayerLegend;
