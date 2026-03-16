const fs = require('fs');
const path = require('path');
const axios = require('axios');

const AIRTABLE_TOKEN = process.env.AIRTABLE_TOKEN;
const AIRTABLE_BASE = process.env.AIRTABLE_BASE;
const API_BASE_URL = `https://api.airtable.com/v0/${AIRTABLE_BASE}`;

if (!AIRTABLE_TOKEN || !AIRTABLE_BASE) {
  console.error('Missing AIRTABLE_TOKEN or AIRTABLE_BASE environment variables');
  process.exit(1);
}

async function fetchTable(tableName) {
  const records = [];
  let offset;

  do {
    const response = await axios.get(`${API_BASE_URL}/${encodeURIComponent(tableName)}`, {
      headers: {
        Authorization: `Bearer ${AIRTABLE_TOKEN}`,
      },
      params: {
        pageSize: 100,
        ...(offset ? { offset } : {}),
      },
      timeout: 30000,
    });

    records.push(...response.data.records);
    offset = response.data.offset;
  } while (offset);

  return records;
}

function toGeoJSON(featuresRecords) {
  const features = featuresRecords
    .map((record) => {
      const fields = record.fields || {};
      const latitude = Number(fields.latitude);
      const longitude = Number(fields.longitude);

      if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
        return null;
      }

      return {
        type: 'Feature',
        geometry: {
          type: 'Point',
          coordinates: [longitude, latitude],
        },
        properties: {
          ...fields,
        },
      };
    })
    .filter(Boolean);

  return {
    type: 'FeatureCollection',
    features,
  };
}

function ensureDataDirectory() {
  const dataDir = path.resolve('data');
  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }
}

function writeJson(filePath, payload) {
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
}

async function main() {
  const [featuresRecords, layersRecords] = await Promise.all([
    fetchTable('Features'),
    fetchTable('Layers'),
  ]);

  const featuresGeoJSON = toGeoJSON(featuresRecords);

  ensureDataDirectory();
  writeJson('data/features.json', featuresRecords);
  writeJson('data/features.geojson', featuresGeoJSON);
  writeJson('data/layers.json', layersRecords);

  console.log(
    `Export completed: ${featuresRecords.length} features records, ${layersRecords.length} layers records.`
  );
}

main().catch((error) => {
  console.error('Airtable export failed:', error.message);
  process.exit(1);
});
