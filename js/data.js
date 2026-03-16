  // ── КОНФИГУРАЦИЯ ──────────────────────────────────────────
  const DATA_URL = 'data/features.geojson';

  async function loadData() {
    setStatus('Загрузка данных…');
    try {
      const res = await fetch(DATA_URL);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const geo = await res.json();
      state.features = (geo.features || []).map(f => {
        const p = f.properties || {};
        const coords = (f.geometry && f.geometry.coordinates) || [];
        const rawTags = p.tags;
        const tags = Array.isArray(rawTags)
          ? rawTags
          : String(rawTags || '').split(',').map(t => t.trim()).filter(Boolean);

        return {
          id: p.id || '',
          name_ru: p.name || '',
          layer_id: p.layer || '',
          layer_type: p.layer_type || 'architecture',
          date_start: p.start || null,
          date_end: p.end && String(p.end).trim() !== '' ? String(p.end).trim() : null,
          date_construction_end: p.date_construction_end || null,
          radius: p.radius != null && String(p.radius).trim() !== '' ? parseInt(p.radius, 10) : null,
          desc: p.desc || '',
          architect: p.architect || null,
          img: p.img || null,
          src: p.src || '',
          tags: tags.map(t => String(t).toLowerCase()),
          lon: coords[0] != null ? parseFloat(coords[0]) : null,
          lat: coords[1] != null ? parseFloat(coords[1]) : null,
        };
      });

      renderLayers();
      renderCategories();
      initSearch();
      renderAll();
    } catch (e) {
      console.error('Ошибка загрузки GeoJSON:', e);
      setStatus('Ошибка загрузки данных.');
    }
  }


  // ── ЗАПУСК ────────────────────────────────────────────────
  map.on("load", loadData);
