# Priorities_05_04_26_v3_6.md
status: canonical
version: v3.6
source: repository-state
last_updated: 2026-04-05

## Purpose
Фиксирует реальный backlog и порядок выполнения задач после завершённого cleanup-cycle.

## Scope
Актуальные приоритеты по governance, coverage и стабильности контуров без повторной постановки уже закрытых дефектов.

## Contract
- Закрытые задачи не должны оставаться в active high-priority списке.
- Backlog должен соответствовать текущей фазе C (`Governance & Coverage maturity`).
- Приоритеты формируются от фактического состояния кода/тестов/документов в репозитории.

## Closed and removed from active backlog
Следующие задачи считаются закрытыми и **не являются активными приоритетами**:
- ✅ Reference docs layer restoration.
- ✅ SYSTEM_CONTRACT_AUDIT sync with current code.
- ✅ Courses/LIVE behavioral baseline tests.
- ✅ Reject reason contract fix (UI↔backend).
- ✅ Legacy `/drafts/*` fallback removal in UGC client.

## Active priorities (Phase C aligned)

### P1 — Canonical data path integrity (`/data/features.geojson`)
- Гарантировать непустой и валидный public dataset в `data/features.geojson` как source of truth для public map.
- Поддерживать строгий data-contract для связанных public артефактов `data/*`.

### P2 — Release guard / publish integrity
- Ввести и поддерживать publish-guards против empty/invalid public dataset перед релизом.
- Закрепить publish unit как batch release c overwrite текущего `data/features.geojson`.

### P3 — Governance lifecycle enforcement
- Зафиксировать и операционализировать lifecycle: `AI-assisted/manual intake/import -> review #1 -> review #2 -> batch publish`.
- Подтвердить, что AI-generated данные не становятся source of truth без human review.

### P4 — Frontend canonical source discipline
- Сохранить для frontend map canonical path чтения только из `data/*`.
- Не допускать зависимости frontend map от runtime API как primary source.

### P5 — Auxiliary/runtime clarity for `/api/map/feed`
- Устранить архитектурную неоднозначность: `/api/map/feed` фиксируется только как auxiliary/runtime/internal слой.
- Исключить формирование competing architecture относительно canonical public path через `data/*`.

### P6 — Remaining runtime residue (tracked)
- Закрыть оставшиеся runtime дефекты и инфраструктурные шероховатости (например, auth refresh `405`, icon `404`) без расширения архитектурного scope.

## Execution order
1. Закрыть P1 (integrity canonical public dataset в `data/*`).
2. Выполнить P2 (release guard + publish integrity).
3. Закрепить P3 (double-review governance lifecycle).
4. Поддерживать P4–P5 как архитектурную дисциплину.
5. Выполнять P6 без конкуренции с P1–P5.

## Out-of-priority (explicit)
Не возвращать в urgent/high:
- координатные CRITICAL mismatch,
- pending/review CRITICAL mismatch,
- payload flatten CRITICAL mismatch,
- legacy `/drafts/*` fallback workaround,
- migration frontend map на `/api/map/feed` как primary/canonical source.
