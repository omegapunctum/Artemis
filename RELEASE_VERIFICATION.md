# MVP Release Verification

## Checked blocks
- [x] Canonical backend entrypoint: `app.main:app` (не `api.main:app`)
- [x] Auth flow: login/refresh/logout + single 401 retry path
- [x] Moderation/publish identity: `normalized_id` as canonical key, source ids as references
- [x] Export pipeline: `features.geojson`, `rejected.json`, `validation_report.json` generation
- [x] UI critical paths: map load, search, detail panel, filters/layers, UGC panel open/save/submit

## Smoke tests
- [x] Backend smoke: `/api/health`, `/api/me`, `/api/auth/*` базовые маршруты отвечают
- [x] Export smoke: `python scripts/export_airtable.py --self-test` проходит
- [x] Contract smoke: `pytest -q tests/test_mvp_contract_static.py` проходит
- [x] Targeted auth/export checks: `pytest -q tests/test_export_airtable.py tests/test_moderation.py` проходит

## Known risks
- Airtable external dependency: сетевые/квотные сбои могут влиять на publish/export
- UI manual smoke не покрывает все мобильные браузеры и long-session сценарии
- Производительность на больших датасетах требует отдельного post-release мониторинга

## Release verdict
**GO (MVP)** — release разрешён при наличии стандартного мониторинга после выката.
