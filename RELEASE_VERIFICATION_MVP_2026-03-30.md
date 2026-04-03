# ARTEMIS — MVP Release Verification (2026-03-30)

## Canonical backend entrypoint
- Production backend runtime: `uvicorn app.main:app`
- Canonical API base path: `/api/*`
- Transitional shim was present during migration (compatibility import, no own routes).
- Transitional removal plan completed after deployment/runtime configs migrated.

## Legacy consolidation result

### Keep
- `app/` backend modules (`auth`, `drafts`, `moderation`, `uploads`, `security`, `observability`)
- `app/main.py` as single backend assembly/runtime path

### Merge
- No runtime merge needed: `api/` implementation was fully legacy and not used by tests/frontend contract.

### Deprecate/remove
- Removed legacy duplicate backend implementation files:
  - `api/auth.py`
  - `api/database.py`
  - `api/models.py`
  - `api/schemas.py`
  - `api/routes/*`
- Kept only compatibility shim during migration with explicit legacy cleanup marker.

## Smoke checks (manual + automated)

1. Auth contract
   - `POST /api/auth/register`
   - `POST /api/auth/login`
   - `POST /api/auth/refresh`
   - `POST /api/auth/logout`
   - `GET /api/me`
   - `GET /api/health`
2. Drafts owner-only CRUD + submit
3. Moderation queue/approve/reject permissions
4. Publish idempotency (repeat approve has stable result, no duplicates)
5. Upload endpoint contract (`/api/uploads`, `/api/uploads/image`)
6. ETL contract sanity (enum/date/url/coords/dedupe/source_url/raw+validated split)
7. Service worker private/auth API bypass cache

## Known risks
1. Transitional compatibility shim can hide stale infra config until cleanup is completed.
2. End-to-end browser smoke (offline/auth UI edge scenarios) remains manual.
3. Airtable publish behavior in real network depends on valid external env config.

## Release verdict
**READY FOR MVP RELEASE (with transitional shim)**

Rationale:
- One canonical backend runtime path is fixed.
- Duplicate backend branch removed.
- Core auth/moderation/publish/etl/sw contracts covered by tests and targeted checks.
