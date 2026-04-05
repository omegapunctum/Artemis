# Project_Phases_05_04_26_v3_6.md
status: canonical
version: v3.6
source: reconstructed
last_updated: 2026-04-05

## Purpose
Определяет фазность проекта и критерии перехода между фазами.

## Scope
Текущая фаза, входные/выходные условия, gate-критерии и зависимые deliverables.

## Contract
Контракт фазового управления: что должно быть выполнено до перехода к следующей фазе.

## Phase snapshot (synced with current repo)

### Phase A — Stabilization & Hardening (completed)
**Status:** ✅ Completed

**Closed deliverables:**
- Runtime hardening и canonical backend runtime (`app/*`).
- ETL/data-contract stabilization.
- CI gating и dependency pinning.
- Upload lifecycle cleanup.
- UI/UX hardening + PWA edge handling.
- Import/export и moderation contract stabilization.

### Phase B — Post-hardening consolidation (completed)
**Status:** ✅ Completed

**Closed deliverables:**
- Reference docs layer restored in repo.
- System audit snapshot обновлён под фактический код.
- Courses/LIVE behavioral unit-level coverage введено.
- Reject reason flow синхронизирован UI↔backend.
- Legacy `/drafts/*` fallback удалён; canonical `/api/drafts/*` закреплён.

### Phase C — Governance & Coverage maturity (current)
**Status:** ▶️ In progress

**Current goals:**
1. Довести planning/reference docs до fully-synced состояния (снять remaining stub/content gaps).
2. Расширить behavioral coverage на критичные UGC/moderation сценарии без e2e-усложнения.
3. Зафиксировать устойчивый process обновления docs сразу после code-level fixes.
4. Стабилизировать canonical public data path карты через published `data/*` без миграции frontend map на `/api/map/feed`.
5. Укрепить release/data integrity контур: batch publish model, publish guard от empty/invalid `data/features.geojson`, и явный publish gate.

**Entry criteria (met):**
- Нет открытых CRITICAL контрактных рассинхронов по текущему audit snapshot.
- Canonical runtime и canonical API path зафиксированы.
- Canonical public map path (`data/*`) зафиксирован, а `/api/map/feed` ограничен auxiliary/runtime ролью.

**Exit criteria:**
- Reference + planning docs отражают фактическое состояние без drift.
- Поведенческие тесты покрывают основные regression-зоны UGC/moderation/Courses/LIVE.
- Для активных medium-рисков есть явный owner и порядок закрытия.
- Governance lifecycle данных выполняется как `AI/manual intake -> review #1 -> review #2 -> batch release -> overwrite publish в data/*`.
- Final publish выполняется только release operator / CI workflow после moderation/governance gate.

### Phase D — Next product iteration (next)
**Status:** ⏳ Planned

**Scope placeholder:**
- Только после закрытия governance/coverage долгов Phase C.
- Новые feature-работы допускаются при сохранении цикла `audit → patch → verification`.
- Любые runtime/internal слои (включая `/api/map/feed`) не должны конкурировать с canonical public path через `data/*`.

## Notes
Документ отражает фазность после завершения cleanup-цикла. Обновлять после каждого milestone с явной фиксацией closed/open deliverables.
