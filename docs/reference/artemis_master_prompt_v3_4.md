# artemis_master_prompt_v3_4.md
status: canonical
version: v3.4
source: repository-state
last_updated: 2026-04-05

## Purpose
Определяет master-level operational contract проекта ARTEMIS: как должны согласовываться архитектура, API, data-contract, тесты и governance-документы.

## Scope
Документ распространяется на весь lifecycle изменений в репозитории: `audit -> patch -> verification -> docs sync`.

## Contract

### 1) System architecture invariants
- Canonical backend runtime: `app/*` (`app.main:app`).
- Canonical API surface: `/api/*`.
- Frontend должен использовать только documented canonical endpoints (без undocumented fallback путей).
- Canonical public map source: `data/*` (включая `data/features.geojson` и related `data/*`).
- Frontend map читает canonical данные только из `data/*`.
- `/api/map/feed` не является canonical map source и допускается только как auxiliary/runtime/internal layer.
- ETL/publish/data-contract слой остаётся основным public data path для карты.

### 2) Behavior invariants
- **No silent fallback:** запрещены скрытые fallback-механизмы, маскирующие ошибки конфигурации.
- **No undocumented behavior:** пользовательские и интеграционные сценарии должны быть прозрачно отражены в коде/документации.
- **API as source of truth:** контракт UI↔backend должен фиксироваться через canonical API и сериализацию.
- Любые runtime-интеграции с `/api/map/feed` не должны вводить competing architecture относительно canonical map path через `data/*`.

### 3) Governance invariants
- `docs/reference/*` является обязательным governance-слоем.
- Load-bearing документы (audit/phases/priorities/structure/master prompt/operating instruction) должны синхронизироваться с кодом после каждого значимого patch.
- Закрытые дефекты не должны оставаться в active backlog.

### 4) Quality & verification invariants
- Для критичных пользовательских flows требуется поведенческое покрытие (unit/integration/behavioral tests), а не только string/static presence checks.
- Любой patch считается завершённым только при green verification и отсутствии contract drift между кодом и docs.

## Current phase alignment
- Текущая рабочая фаза: **Phase C — Governance & Coverage maturity**.
- Приоритеты верхнего уровня:
  - P1: semantic docs completion,
  - P2: behavioral coverage expansion,
  - P3: process hardening against future doc drift.

## Change control policy
- Runtime/API изменения без синхронного обновления релевантных governance/docs считаются incomplete.
- Docs-only исправления допустимы как отдельный тип patch, если они устраняют governance drift.
