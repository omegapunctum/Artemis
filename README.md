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

### Backend
- FastAPI
- Auth API (JWT + refresh cookie)
- Drafts API (CRUD)
- Upload API (images)
- Moderation API (review + publish)
- Airtable integration (publish pipeline)

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

## Features

### Core Map
- Interactive map (MapLibre)
- Clustering
- Filters and layers
- Popup with metadata
- Object list

### User-Generated Content (UGC)
- Create/edit drafts
- Attach images
- Geometry support (optional)
- Private until published

### Moderation
- Review queue
- Approve / reject drafts
- Publish to Airtable
- Automatic inclusion via ETL

### Authentication
- JWT access token (short-lived)
- Refresh token (cookie-based)
- No persistent client storage

### PWA
- Installable app
- Offline support (cached data)
- Service Worker
- Basic offline UX

---

## Data Model (Simplified)

### Feature
- id
- layer_id
- name
- description
- coordinates (GeoJSON)
- image_url
- source_url
- source_license

### Draft
- id
- user_id
- title
- description
- geometry (optional)
- image_url
- status (draft / review / approved / rejected)

---

## Development

### Requirements
- Node.js (optional, for tooling)
- Python (for ETL)
- FastAPI backend

### Run Frontend
Serve static files:
```bash
python -m http.server

---

### Project structure

```text
.
├── index.html
├── css/
│   └── style.css
├── js/
│   ├── data.js
│   ├── map.js
│   ├── ui.js
│   ├── auth.js
│   ├── ui.ugc.js
│   ├── ui.moderation.js
│   └── pwa.js
├── scripts/
│   └── export_airtable.py
├── data/
│   ├── features.json
│   ├── features.geojson
│   └── layers.json
├── .github/
│   └── workflows/
│       └── export-airtable.yml
├── manifest.json
├── sw.js
└── README.md