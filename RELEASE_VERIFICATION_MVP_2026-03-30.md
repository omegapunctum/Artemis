# ARTEMIS — MVP Release Verification (2026-03-30)

## Scope
Final smoke verification pass against MVP readiness criteria:
- security/data-loss criticals
- publish idempotency
- private API cache policy
- UGC XSS resilience
- ETL stability
- core user flows

## Smoke test matrix

| test | expected | actual | status |
|---|---|---|---|
| A1 App bootstrap (index/js/css/map/data fetch) | UI shell loads, map bootstraps, data files reachable | `/index.html`, `/css/style.css`, `/js/map.js`, `/data/layers.json`, `/data/features.geojson`, `/sw.js` return 200 via static server. Runtime bootstrap path in `index.html` intact. | PASS |
| A2 Map/layers/features render path | layer renders, popup works, missing geometry safe | Map code filters invalid/missing geometry (`buildMapFeatureCollection`, `hasPointGeometry`), popup built via safe DOM. But `data/features.geojson` currently contains 0 features. | PARTIAL |
| A3 Public data contract | `features.json`, `features.geojson`, `rejected.json` exist and valid | All files exist and parse. `features.geojson` valid `FeatureCollection`, but empty (`features=0`). | PARTIAL |
| B4 ETL run | `export_airtable.py` stable, deterministic outputs | Script executes in dry-run without crash, generates `_test_*` outputs and clear stdout. | PASS |
| B5 Validation rules | invalid fields rejected consistently; date invalid -> `date_valid=false` | Rule coverage confirmed by validation code (`invalid_source_url`, invalid coords/source/license/image, date validity flag) and test suite pass. | PASS |
| C6 Auth flow | register/login/logout/refresh stable; no infinite refresh loop | API smoke: register/login/me/refresh/logout all pass; request-id present; login spam reaches 429. Frontend `fetchWithAuth` implements single retry on 401. | PASS |
| C7 Draft CRUD + isolation | create/edit/delete/list + no чужих drafts | API smoke confirms create/list/update/submit; cross-user update returns 404. Delete endpoint covered by route/unit stack, not manually exercised in smoke command. | PARTIAL |
| C8 UGC validation | client blocks invalid payloads | Client validation rules present for required/length/url/coords pair/ranges/whitelists before submit (`validateDraftPayload`). | PASS |
| C9 XSS checks (drafts/moderation/popup/cards) | payload rendered as text, no JS execution | Safe text/link helpers and popup/list render via `textContent` + safe URL normalization. No browser-executed payload run in this pass (static/code verification only). | PARTIAL |
| D10 Moderation flow | queue/approve/reject stable | queue/reject API smoke pass for moderator; approve path functionally covered by unit tests (including failure handling). | PASS |
| D11 Publish idempotency | no duplicate publish on repeated approve | Unit tests validate duplicate-skip and stable re-approve result (`published_skipped_duplicate`, `approved_already_published`). | PASS |
| E12 Service worker lifecycle | register + activate cleanup + versioned cache names | `sw.js` uses versioned cache names and deletes stale caches on activate. | PASS |
| E13 Cache rules private API | private endpoints and mutating methods uncached | `sw.js`: non-GET bypass; `/auth`, `/me`, `/drafts`, `/moderation`, `/uploads` matched as private and forced network-only. | PASS |
| E14 Offline mode boundaries | public shell/data offline only, no stale private | `sw.js` navigation/data cache logic supports offline public shell + `/data/*`; private/auth requests bypass cache. | PASS |
| F15 Request ID/logging | request_id in responses/errors, structured logs | Observability middleware/tests + live response headers include `X-Request-ID`; health payload exposes metrics. | PASS |
| F16 Rate limits | predictable 429 on spam, normal flow unaffected | Login spam reproducibly reaches 429 after threshold; normal authenticated flow succeeds prior to spam test. | PASS |
| F17 Upload cleanup | uploads ok + orphan cleanup + no false deletes | Cleanup call exists in upload route; not executed end-to-end due file upload fixture not run in this pass. | PARTIAL |
| F18 Error UI | compact user-visible failures, no UI crash | Error banner/status handling present in bootstrap + UGC actions; no browser-driven UI fault injection executed. | PARTIAL |
| G19 Perf sanity | no redundant requests/map recreation, smooth base UX | Data in-flight caching and map `setData` update path prevent full map recreation; no browser perf profiling run. | PARTIAL |

## Defects found

### Critical
- None found in executed checks.

### Major
- `data/features.geojson` is currently an empty FeatureCollection (`features=0`) while `features.json` contains substantial dataset. This creates an MVP risk of an “empty map” user experience despite successful app bootstrap.

### Minor
- End-to-end browser execution checks (interactive XSS payloads, offline PWA behavior in real browser, visual Error UI states, upload cleanup with real files) were not fully executed in this pass.

## Residual MVP risks
1. Empty public GeoJSON leads to perceived “no data” release.
2. Some security/usability checks are code-verified but not browser-proven in this run (XSS rendering contexts, offline shell behavior across reloads).
3. Upload cleanup behavior is validated by code path, not by integration fixture with real upload lifecycle.

## Verdict
**READY WITH KNOWN RISKS**

Rationale:
- Core backend auth/drafts/moderation/rate-limit/observability checks pass.
- Publish idempotency is explicitly tested and passing in unit tests.
- Private API cache bypass rules are correctly implemented.
- But empty `features.geojson` is a major release-quality risk for public map MVP behavior.

## Minimal patch plan
1. Re-run ETL against production Airtable source with valid env (`AIRTABLE_TOKEN`, `AIRTABLE_BASE`, `AIRTABLE_TABLE`) and verify non-zero features exported to `data/features.geojson`.
2. Add CI gate: fail if `data/features.geojson.features.length == 0` when `data/features.json` has non-zero valid records.
3. Run one browser smoke (manual or Playwright):
   - load map + popup
   - one XSS payload in draft preview/popup
   - offline reload of public shell
   - ensure private API remains network-only offline.
