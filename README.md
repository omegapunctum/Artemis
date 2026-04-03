# ARTEMIS

**ARTEMIS** is an interactive geo-historical map built with **MapLibre + GeoJSON**.  
It visualizes historical events, movements, and entities in space and time.

---

## Overview

ARTEMIS combines:
- curated historical data (Airtable → ETL → GeoJSON)
- interactive map visualization (MapLibre)
- user-generated content (UGC)
- moderation and publishing pipeline
- progressive web app (PWA)

The system is designed to be **simple, modular, and scalable**.

---

## Architecture

### Data Pipeline
- Source: Airtable (curated data)
- ETL: `scripts/export_airtable.py`
- Output:
  - `/data/features.json`
  - `/data/features.geojson`
  - `/data/layers.json`

### Frontend
Vanilla JavaScript (no frameworks):

- `data.js` — data loading
- `map.js` — MapLibre integration
- `ui.js` — filters, list, state
- `auth.js` — authentication (in-memory tokens)
- `ui.ugc.js` — user drafts
- `ui.moderation.js` — moderation panel
- `pwa.js` — PWA logic

### Backend (canonical)
- FastAPI app entrypoint: **`app.main:app`**
- Canonical API base path: **`/api`**
- Auth API (JWT + refresh cookie)
- Drafts API (CRUD)
- Upload API (images)
- Moderation API (review + publish)
- Airtable integration (publish pipeline)
- Upload lifecycle cleanup: orphan `/uploads/*` files are cleaned safely when drafts are updated/deleted and by periodic orphan scan.

### CI/CD
- GitHub Actions
- ETL validation
- Data export

---

## Key Principles

- **No localStorage / sessionStorage**
- Access token stored **in memory only**
- Refresh token stored in **httpOnly cookie**
- **GeoJSON is the single source of truth** for the map
- No direct Airtable access from frontend
- Minimal, clean code (no overengineering)

---

## API Contract (MVP)

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/me`
- `GET /api/health`

---

## Development

### Requirements
- Python 3.11+
- FastAPI backend
- Dependencies are pinned in `requirements.txt` for reproducible local/CI/prod environments.

Install dependencies:
```bash
pip install -r requirements.txt
```

### Run backend
```bash
uvicorn app.main:app --reload --port 8001
```

### Run frontend
```bash
python -m http.server 8000
```

By default frontend tries `window.ARTEMIS_API_BASE`/meta override, then `/api`.
