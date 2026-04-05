# Project_Structure_04_04_26_v3_5.md
status: canonical
version: v3.5
source: repository-state
last_updated: 2026-04-04

## Purpose
Описывает фактическую рабочую структуру репозитория ARTEMIS как source of truth для audit/patch циклов.

## Scope
Каталоги, canonical runtime-слои, data-contract артефакты, тестовый и governance контуры, а также deployment/PWA поверхности.

## Contract
- Canonical backend runtime расположен в `app/*` (entrypoint: `app.main:app`).
- Frontend runtime расположен в root + `js/*` + `css/*` + `index.html`.
- Canonical public map source расположен в `data/*` (прежде всего `data/features.geojson`), frontend public map читает только published `data/*`.
- ETL/publish/data-contract слой обслуживает canonical public delivery path для карты.
- `/api/map/feed` допускается только как auxiliary/runtime/internal слой и не является canonical map source.
- Frontend map не должен зависеть от runtime API как primary source карты.
- Любые structural изменения должны сохранять audit-traceability и совместимость с текущим CI/test контуром.

## Repository structure (current)

### 1) Runtime surface
- `index.html` — основной app shell.
- `js/*` — модульный frontend слой:
  - `data.js` (load/cache data),
  - `map.js` (MapLibre слой + source updates),
  - `ui.js` (shell/panels/filters/cards/courses/live),
  - `ui.ugc.js` (UGC draft flows),
  - `ui.moderation.js` (moderation workspace),
  - `auth.js`, `uploads.js`, `pwa.js`, `state.js`, `ux.js`, `safe-dom.js`.
- `css/style.css` — единый основной стиль.
- `manifest.json` + `sw.js` — PWA manifest/service worker слой.

### 2) Backend (canonical)
- `app/main.py` — FastAPI app и подключение роутеров.
- `app/auth/*`, `app/drafts/*`, `app/moderation/*`, `app/uploads/*`, `app/security/*` — доменные backend-модули.
- `app/observability.py` — request-id/health/metrics/logging middleware contract.
- `api/__init__.py` — legacy marker package, не runtime entrypoint.

### 3) Data contract layer
- Core map/data artifacts:
  - `data/features.geojson` (canonical validated map source),
  - `data/features.json`,
  - `data/layers.json`,
  - `data/rejected.json`,
  - `data/courses.json`.
- Diagnostics/meta artifacts:
  - `data/export_meta.json`,
  - `data/validation_report.json`,
  - `data/export_errors.log`.
- Public lifecycle (governance-bound):
  - AI-assisted/manual intake/import -> Review #1 -> Review #2 -> release batch -> publish overwrite в public `data/*`.
  - Public map layer читает только опубликованный набор `data/*`.
  - Publish unit = пакетный релиз; итоговый public dataset перезаписывает текущий `data/features.geojson`.
  - Историзация/versioning public dataset на текущем этапе не требуется.

### 4) Scripts / ETL / import-export
- `scripts/export_airtable.py` — основной ETL export и валидационный контур.
- `scripts/import_features.py` — import/export локальных датасетов в ETL-совместимом контракте.
- `scripts/build_geojson.py`, `scripts/audit_airtable.py` — вспомогательные data/audit утилиты.

### 5) Tests and regression layer
- `tests/*` — unit/integration/contract/static test contour.
- Покрытие включает auth/drafts/moderation/uploads/rate-limit/observability/import-export + static/behavioral guards для frontend hooks.
- `pytest.ini` — единая конфигурация запуска тестов.

### 6) CI/CD and automation
- `.github/workflows/etl.yml` — ETL + pytest checks.
- `.github/workflows/export-airtable.yml` — scheduled export pipeline.
- `.github/workflows/pages.yml` — GitHub Pages deploy flow.
- Final publish инициируется отдельным release operator / CI workflow как publish gate после прохождения governance-модерации.

### 7) Governance and docs
- `README.md` — high-level architecture/operations reference.
- `docs/*` — audit/smoke/baseline документы по состоянию системы.
- `docs/reference/*` — canonical governance/reference слой (phases/priorities/operating context).

## Structural invariants
1. Backend changes не должны обходить canonical `app/*` runtime.
2. Frontend публичный map data-flow должен оставаться привязанным к canonical `data/*` path; `/api/map/feed` не формирует competing architecture.
3. Изменения в `data/*`, `scripts/*`, `tests/*`, `workflows/*` должны оставаться согласованными как единый release контур.
4. AI-generated/imported данные не становятся source of truth без human review (двухступенчатый governance gate до publish).
