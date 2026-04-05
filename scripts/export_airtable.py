#!/usr/bin/env python3
"""
Экспорт таблицы Airtable (обычно Features) в локальные JSON/GeoJSON файлы.

Пример запуска:
  AIRTABLE_TOKEN=pat_xxx AIRTABLE_BASE=appHmf8ubeUF9 AIRTABLE_TABLE=Features \
  python3 scripts/export_airtable.py --out-dir data

Переменные окружения:
  - AIRTABLE_TOKEN: персональный токен Airtable (Bearer)
  - AIRTABLE_BASE: ID базы Airtable (например appHmf8ubeUF9)
  - AIRTABLE_TABLE: имя таблицы (например Features)

Выходные файлы:
  - data/features.json        : сырые записи Airtable (records)
  - data/features.geojson     : GeoJSON FeatureCollection
  - data/rejected.json        : отклонённые записи с причинами валидации
  - data/layers.json          : агрегированные метаданные слоёв
  - data/export_errors.log    : ошибки в формате JSON Lines
  - data/export_meta.json     : метаданные экспорта (timestamp, counts, source)

Если передан --dry-run или нет обязательных переменных/параметров для API, скрипт
переходит в dry-run режим: не обращается к Airtable и пишет mock-выход в data/_test_*.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import uuid

AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE = os.getenv("AIRTABLE_BASE")
AIRTABLE_TABLE = os.getenv("AIRTABLE_TABLE")

import re
import subprocess
import sys
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Установка зависимости: pip install requests
REQUESTS_AVAILABLE = importlib.util.find_spec("requests") is not None
if REQUESTS_AVAILABLE:
    import requests
else:
    requests = None  # type: ignore[assignment]

DATE_RE = re.compile(r"^-?\d{4}(?:-\d{2}-\d{2})?$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
TRUE_SET = {True, 1, "1", "true", "yes", "y", "да"}
FALSE_SET = {False, 0, "0", "false", "no", "n", "нет"}
ALLOWED_LICENSES = {"CC0", "CC BY", "CC BY-SA", "PD"}
ALLOWED_COORDINATES_CONFIDENCE = {"exact", "approximate", "conditional"}
# IMPORTANT:
# This allowlist MUST be kept in sync with Airtable 'coordinates_source' enum.
# Adding new source values in Airtable requires updating this list.
ALLOWED_COORDINATES_SOURCES = {
    "Wikipedia",
    "Pleiades",
    "GBIF",
    "IUCN",
    "expert estimate",
    "Official Site",
    "Britannica",
    "Vatican",
    "UNESCO",
    "Pompidou Site",
    "PBS",
    "Dezeen",
    "Saylor",
}
ALLOWED_LAYER_TYPES = {"architecture", "route_point", "biogeography", "biography"}
LAYERS_TABLE_NAME = "Layers"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Экспорт данных Features из Airtable")
    parser.add_argument("--base", help="Airtable base id (или AIRTABLE_BASE)")
    parser.add_argument("--table", help="Airtable table name (или AIRTABLE_TABLE)")
    parser.add_argument("--out-dir", default="data", help="Каталог для выходных файлов (по умолчанию: data)")
    parser.add_argument("--dry-run", action="store_true", help="Не ходить в сеть и сгенерировать mock-данные")
    parser.add_argument("--max-records", type=int, default=None, help="Ограничить число записей (для тестирования)")
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Включать записи с is_active=False (по умолчанию такие записи пропускаются)",
    )
    parser.add_argument("--commit", action="store_true", help="После экспорта выполнить git add/commit")
    parser.add_argument("--self-test", action="store_true", help="Запустить минимальную самопроверку и выйти")
    return parser.parse_args()


def log_error(error_log_path: Path, payload: Dict[str, Any]) -> None:
    """Пишем ошибку в JSON Lines файл, не прерывая основной процесс."""
    try:
        error_log_path.parent.mkdir(parents=True, exist_ok=True)
        with error_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"Не удалось записать ошибку в лог: {exc}", file=sys.stderr)


def append_diagnostic(
    issues: List[Dict[str, Any]],
    *,
    record_id: str,
    field: str,
    error: Optional[str] = None,
    warning: Optional[str] = None,
    value: Any = None,
    severity: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """Добавляет diagnostics payload в унифицированном формате, сохраняя legacy ключи."""
    normalized_id = record_id or "<missing>"
    payload: Dict[str, Any] = {
        "id": normalized_id,
        "record_id": normalized_id,
        "field": field,
    }
    if error is not None:
        payload["error"] = error
    if warning is not None:
        payload["warning"] = warning
    if value is not None:
        payload["value"] = value

    derived_reason = reason or error or warning
    if derived_reason is not None:
        payload["reason"] = derived_reason
    resolved_severity = severity or ("critical" if error is not None else "warning" if warning is not None else None)
    if resolved_severity is not None:
        payload["severity"] = resolved_severity
    issues.append(payload)


def to_date_or_none(value: Any, record_id: str, field: str, errors: List[Dict[str, Any]]) -> Optional[str]:
    if value in (None, ""):
        return None
    value_str = str(value).strip()
    if DATE_RE.match(value_str):
        return value_str
    append_diagnostic(errors, record_id=record_id, field=field, error=f"invalid date: {value}", value=value)
    return None


def to_float_or_none(value: Any, record_id: str, field: str, errors: List[Dict[str, Any]]) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        append_diagnostic(errors, record_id=record_id, field=field, error=f"invalid float: {value}", value=value)
        return None


def parse_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int_or_none(value: Any, record_id: str, field: str, errors: List[Dict[str, Any]]) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        append_diagnostic(errors, record_id=record_id, field=field, error=f"invalid int: {value}", value=value)
        return None


def to_bool_or_none(value: Any, record_id: str, field: str, errors: List[Dict[str, Any]]) -> Optional[bool]:
    if value in (None, ""):
        return None
    normalized = value.strip().lower() if isinstance(value, str) else value
    if normalized in TRUE_SET:
        return True
    if normalized in FALSE_SET:
        return False
    append_diagnostic(errors, record_id=record_id, field=field, error=f"invalid bool: {value}", value=value)
    return None


def parse_bool(value: Any) -> Optional[bool]:
    if value in (None, ""):
        return None
    normalized = value.strip().lower() if isinstance(value, str) else value
    if normalized in TRUE_SET:
        return True
    if normalized in FALSE_SET:
        return False
    return None


def is_valid_iso_date(value: Any) -> bool:
    if value is None:
        return True
    value_str = str(value).strip()
    if not DATE_RE.fullmatch(value_str):
        return False
    try:
        if len(value_str) == 4 or (value_str.startswith("-") and len(value_str) == 5):
            return True
        dt.date.fromisoformat(value_str)
    except ValueError:
        return False
    return True


def is_valid_license(value: Optional[str]) -> bool:
    return value in ALLOWED_LICENSES


def is_valid_layer_type(value: Optional[str]) -> bool:
    return value in ALLOWED_LAYER_TYPES


def is_valid_color_hex(value: Optional[str]) -> bool:
    return value is not None and HEX_COLOR_RE.fullmatch(value.strip()) is not None


def is_valid_url(value: Optional[str]) -> bool:
    if value is None:
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_uuid_v4(value: Any) -> bool:
    """Target-contract helper: Airtable governance expects UUID v4 for Features.id.

    Runtime ETL currently keeps compatibility with legacy non-empty ids
    (see get_etl_error / validate_feature), so this helper is intentionally
    not a hard gate in active export path yet.
    """
    candidate = safe_str(value)
    if not candidate:
        return False
    try:
        parsed = uuid.UUID(candidate)
    except (ValueError, TypeError, AttributeError):
        return False
    return parsed.version == 4 and parsed.variant == uuid.RFC_4122


def normalize_coordinates_source(value: Any) -> Optional[str]:
    if isinstance(value, list):
        raw = safe_str(value[0]) if value else None
    else:
        raw = safe_str(value)
    if raw is None:
        return None

    normalized = " ".join(raw.split())
    # Keep ETL allowlist/aliases in sync with curated Airtable Features.coordinates_source enum.
    aliases = {
        "unesco / wikipedia": "Wikipedia",
        "unesco/wikipedia": "Wikipedia",
        "official site": "Official Site",
        "britannica": "Britannica",
        "vatican": "Vatican",
        "unesco": "UNESCO",
        "pompidou site": "Pompidou Site",
        "pbs": "PBS",
        "dezeen": "Dezeen",
        "saylor": "Saylor",
    }
    return aliases.get(normalized.lower(), normalized)


def normalize_single_select(value: Any) -> Optional[str]:
    raw = safe_str(value)
    if raw is None:
        return None
    return raw.strip()


def normalize_source_license(value: Any) -> Optional[str]:
    normalized = normalize_single_select(value)
    if normalized is None:
        return None
    upper = normalized.upper().replace("_", " ").replace("-", " ")
    compact = " ".join(upper.split())
    aliases = {
        "CC0": "CC0",
        "CC 0": "CC0",
        "CC BY": "CC BY",
        "CCBY": "CC BY",
        "CC BY SA": "CC BY-SA",
        "CC BY-SA": "CC BY-SA",
        "PD": "PD",
        "PUBLIC DOMAIN": "PD",
    }
    return aliases.get(compact)


def normalize_coordinates_confidence(value: Any) -> Optional[str]:
    raw = normalize_single_select(value)
    if raw is None:
        return None
    normalized = " ".join(raw.strip().lower().split())
    if normalized == "exact":
        return "exact"
    if normalized == "conditional":
        return "conditional"
    if normalized.startswith("approx"):
        return "approximate"
    if normalized in {"estimated", "estimate", "unknown"}:
        return "conditional"
    return None


def normalize_layer_type(value: Any) -> Optional[str]:
    normalized = normalize_single_select(value)
    if normalized is None:
        return None
    aliases = {
        "architecture": "architecture",
        "route_point": "route_point",
        "route point": "route_point",
        "biogeography": "biogeography",
        "biography": "biography",
    }
    return aliases.get(normalized.strip().lower())


def validate_coordinate_range(
    value: Optional[float],
    minimum: float,
    maximum: float,
    record_id: str,
    field: str,
    errors: List[Dict[str, Any]],
) -> Optional[float]:
    """Проверяем диапазон координаты, иначе логируем ошибку и возвращаем None."""
    if value is None:
        return None
    if minimum <= value <= maximum:
        return value
    append_diagnostic(
        errors,
        record_id=record_id,
        field=field,
        error=f"out of range [{minimum}, {maximum}]",
        warning="invalid coordinates",
        value=value,
        severity="critical",
        reason="invalid_coordinates",
    )
    return None


def to_tags(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        tags = [str(v).strip().lower() for v in value if str(v).strip()]
        return tags
    if isinstance(value, str):
        return [chunk.strip().lower() for chunk in value.split(",") if chunk.strip()]
    return []


def safe_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def normalize_linked_record_id(value: Any) -> Optional[str]:
    """Нормализация linked record из Airtable (обычно ['rec...'])."""
    if isinstance(value, list):
        if not value:
            return None
        return safe_str(value[0])
    return safe_str(value)


def add_issue(issues: List[Dict[str, Any]], severity: str, record_id: str, reason: str, field: Optional[str] = None) -> None:
    normalized_id = record_id or "<missing>"
    payload: Dict[str, Any] = {
        "id": normalized_id,
        "record_id": normalized_id,
        "reason": reason,
        "severity": severity,
    }
    if field:
        payload["field"] = field
    if severity == "critical":
        payload["error"] = reason
    elif severity == "warning":
        payload["warning"] = reason
    issues.append(payload)


def map_record(
    record: Dict[str, Any],
    errors: List[Dict[str, Any]],
    linked_layer_to_public_id: Dict[str, str],
) -> Dict[str, Any]:
    """Преобразование записи Airtable в нормализованную структуру properties."""
    record_id = record.get("id", "")
    fields = record.get("fields", {}) or {}

    longitude_parse_error = False
    latitude_parse_error = False

    longitude = to_float_or_none(fields.get("longitude_num"), record_id, "longitude_num", errors)
    if fields.get("longitude_num") not in (None, "") and longitude is None:
        longitude_parse_error = True
    if longitude in (None, ""):
        legacy_longitude = fields.get("longitude")
        if legacy_longitude not in (None, ""):
            append_diagnostic(
                errors,
                record_id=record_id,
                field="longitude",
                warning="using legacy fallback field",
                value=legacy_longitude,
            )
        longitude = to_float_or_none(legacy_longitude, record_id, "longitude", errors)
        if legacy_longitude not in (None, "") and longitude is None:
            longitude_parse_error = True

    latitude = to_float_or_none(fields.get("latitude_num"), record_id, "latitude_num", errors)
    if fields.get("latitude_num") not in (None, "") and latitude is None:
        latitude_parse_error = True
    if latitude in (None, ""):
        legacy_latitude = fields.get("latitude")
        if legacy_latitude not in (None, ""):
            append_diagnostic(
                errors,
                record_id=record_id,
                field="latitude",
                warning="using legacy fallback field",
                value=legacy_latitude,
            )
        latitude = to_float_or_none(legacy_latitude, record_id, "latitude", errors)
        if legacy_latitude not in (None, "") and latitude is None:
            latitude_parse_error = True

    validated_raw = fields.get("validated")
    if validated_raw in (None, ""):
        validated_raw = fields.get("validated_bool")
    validated = parse_bool(validated_raw)
    if validated is None and validated_raw not in (None, ""):
        append_diagnostic(errors, record_id=record_id, field="validated", error="invalid bool", value=validated_raw)

    is_active_raw = fields.get("is_active")
    if is_active_raw in (None, ""):
        is_active_raw = fields.get("is_active_bool")
    is_active = parse_bool(is_active_raw)
    if is_active is None and is_active_raw not in (None, ""):
        append_diagnostic(errors, record_id=record_id, field="is_active", error="invalid bool", value=is_active_raw)

    source_license = normalize_source_license(fields.get("source_license_enum"))
    if source_license is None:
        source_license = normalize_source_license(fields.get("source_license"))
        if source_license is not None:
            append_diagnostic(
                errors,
                record_id=record_id,
                field="source_license",
                warning="using legacy fallback field",
                value=source_license,
            )

    coordinates_confidence = normalize_coordinates_confidence(fields.get("coordinates_confidence_enum"))
    if coordinates_confidence is None:
        coordinates_confidence = normalize_coordinates_confidence(fields.get("coordinates_confidence"))
        if coordinates_confidence is not None:
            append_diagnostic(
                errors,
                record_id=record_id,
                field="coordinates_confidence",
                warning="using legacy fallback field",
                value=coordinates_confidence,
            )

    validated_longitude = validate_coordinate_range(longitude, -180.0, 180.0, record_id, "longitude", errors)
    validated_latitude = validate_coordinate_range(latitude, -90.0, 90.0, record_id, "latitude", errors)
    longitude_range_error = longitude is not None and validated_longitude is None
    latitude_range_error = latitude is not None and validated_latitude is None
    longitude = validated_longitude
    latitude = validated_latitude
    source_url = safe_str(fields.get("source_url"))
        
    external_id = safe_str(fields.get("external_id"))
    source_draft_id = safe_str(fields.get("source_draft_id"))
    if source_draft_id is None and external_id and external_id.startswith("draft:"):
        source_draft_id = external_id

    layer_id_field = fields.get("layer_id")
    raw_layer_id: Optional[str] = None
    layer_id_used_legacy_fallback = False
    invalid_layer_link = False
    if isinstance(layer_id_field, list):
        if len(layer_id_field) == 1:
            raw_layer_id = safe_str(layer_id_field[0])
        elif len(layer_id_field) > 1:
            invalid_layer_link = True
    elif layer_id_field in (None, ""):
        raw_layer_id = None
    elif isinstance(layer_id_field, str):
        raw_layer_id = safe_str(layer_id_field)
        layer_id_used_legacy_fallback = raw_layer_id is not None
    else:
        invalid_layer_link = True

    if layer_id_used_legacy_fallback:
        append_diagnostic(
            errors,
            record_id=record_id,
            field="layer_id",
            warning="using legacy string fallback",
            value=raw_layer_id,
        )

    mapped_layer_id = raw_layer_id
    unknown_layer_link = False
    if isinstance(layer_id_field, list) or (raw_layer_id and raw_layer_id.startswith("rec")):
        mapped_layer_id = linked_layer_to_public_id.get(raw_layer_id or "")
        if raw_layer_id and not mapped_layer_id:
            unknown_layer_link = True

    raw_date_start = fields.get("date_start")
    raw_date_end = fields.get("date_end")
    raw_date_start_present = raw_date_start not in (None, "")
    raw_date_end_present = raw_date_end not in (None, "")
    parsed_date_start = to_date_or_none(raw_date_start, record_id, "date_start", errors)
    parsed_date_end = to_date_or_none(raw_date_end, record_id, "date_end", errors)

    mapped = {
        "id": record_id,
        "airtable_record_id": record_id,
        "normalized_id": safe_str(fields.get("normalized_id")),
        "external_id": external_id,
        "source_draft_id": source_draft_id,
        "layer_id": mapped_layer_id,
        "_raw_layer_link_id": raw_layer_id,
        "_unknown_layer_link": unknown_layer_link,
        "_invalid_layer_link": invalid_layer_link,
        "layer_type": normalize_layer_type(fields.get("layer_type_enum") or fields.get("layer_type")),
        "name_ru": safe_str(fields.get("name_ru")),
        "name_en": safe_str(fields.get("name_en")),
        "date_start": parsed_date_start,
        "date_construction_end": to_date_or_none(
            fields.get("date_construction_end"), record_id, "date_construction_end", errors
        ),
        "date_end": parsed_date_end,
        "_raw_date_start_present": raw_date_start_present,
        "_invalid_date_start": raw_date_start_present and parsed_date_start is None,
        "_raw_date_end_present": raw_date_end_present,
        "_invalid_date_end": raw_date_end_present and parsed_date_end is None,
        "longitude": longitude,
        "latitude": latitude,
        "_invalid_coordinates": longitude_parse_error or latitude_parse_error or longitude_range_error or latitude_range_error,
        "influence_radius_km": to_int_or_none(
            fields.get("influence_radius_km"), record_id, "influence_radius_km", errors
        ),
        "title_short": safe_str(fields.get("title_short")),
        "description": safe_str(fields.get("description")),
        "image_url": safe_str(fields.get("image_url")),
        "source_url": source_url,
        "source_license": source_license,
        "coordinates_confidence": coordinates_confidence,
        "coordinates_source": normalize_coordinates_source(fields.get("coordinates_source")),
        "sequence_order": to_int_or_none(fields.get("sequence_order"), record_id, "sequence_order", errors),
        "tags": to_tags(fields.get("tags")),
        "validated": validated,
        "is_active": is_active,
        # Доп. поля для слоёв (если в таблице присутствуют)
        "layer_name_ru": safe_str(fields.get("layer_name_ru") or fields.get("layer_name")),
        "layer_color_hex": safe_str(fields.get("layer_color_hex") or fields.get("color_hex")),
        "layer_icon": safe_str(fields.get("layer_icon") or fields.get("icon")),
    }
    return mapped


def get_origin_key(mapped: Dict[str, Any]) -> Optional[str]:
    # Source reference identity (non-canonical for publish dedupe).
    for field in ("external_id", "source_draft_id", "airtable_record_id"):
        value = mapped.get(field)
        if value:
            return str(value)
    return None


def get_canonical_publish_id(mapped: Dict[str, Any]) -> Optional[str]:
    # Canonical publish identity contract:
    # 1) normalized_id (primary)
    # 2) airtable_record_id (backward-compat fallback for old rows)
    # 3) source references (external/source draft ids)
    for field in ("normalized_id", "airtable_record_id", "external_id", "source_draft_id"):
        value = mapped.get(field)
        if value:
            return str(value)
    return None


def get_dedupe_key(mapped: Dict[str, Any]) -> Tuple[Any, ...]:
    return (mapped.get("name_ru") or "", mapped.get("latitude"), mapped.get("longitude"))


def airtable_get_with_retry(
    session: requests.Session,
    url: str,
    headers: Dict[str, str],
    params: Dict[str, Any],
    max_retries_429: int = 5,
) -> requests.Response:
    """GET с обработкой 429 (экспоненциальный бэкофф) и сетевых ошибок."""
    backoff = 30
    attempts_429 = 0

    while True:
        try:
            resp = session.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as exc:
            raise RuntimeError(f"Сетевая ошибка при запросе к Airtable: {exc}") from exc

        if resp.status_code == 429:
            attempts_429 += 1
            if attempts_429 > max_retries_429:
                raise RuntimeError("Превышено число ретраев после 429 (rate limit)")
            print(f"Получен 429, ждём {backoff}s и повторяем ({attempts_429}/{max_retries_429})...")
            time.sleep(backoff)
            backoff *= 2
            continue

        return resp


def fetch_airtable_records(
    token: str,
    base: str,
    table: str,
    max_records: Optional[int],
) -> List[Dict[str, Any]]:
    """Чтение всех страниц Airtable по offset (pageSize=100)."""
    url = f"https://api.airtable.com/v0/{base}/{table}"
    headers = {"Authorization": f"Bearer {token}"}
    records: List[Dict[str, Any]] = []
    offset: Optional[str] = None
    page_no = 0

    with requests.Session() as session:
        while True:
            params: Dict[str, Any] = {"pageSize": 100}
            if offset:
                params["offset"] = offset

            resp = airtable_get_with_retry(session, url, headers, params)
            if resp.status_code in (401, 403):
                raise PermissionError("Ошибка авторизации Airtable (401/403). Проверьте AIRTABLE_TOKEN и права доступа.")
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")

            try:
                payload = resp.json()
            except ValueError as exc:
                raise RuntimeError(f"Некорректный JSON в ответе Airtable: {exc}") from exc

            page_records = payload.get("records", [])
            page_no += 1
            records.extend(page_records)
            print(f"Страница {page_no}: +{len(page_records)} записей (всего: {len(records)})")

            if max_records is not None and len(records) >= max_records:
                return records[:max_records]

            offset = payload.get("offset")
            if not offset:
                break

            # Соблюдение лимита Airtable: до 5 req/s
            time.sleep(0.25)

    return records


def generate_mock_records() -> List[Dict[str, Any]]:
    """Dry-run для CI: не требует secrets и не ходит в Airtable."""
    return [
        {
            "id": "recTEST",
            "fields": {
                "layer_id": "test_layer",
                "layer_type_enum": "biography",
                "name_ru": "Тестовая запись",
                "date_start": "1348",
                "longitude": 37.6173,
                "latitude": 55.7558,
                "influence_radius_km": 12,
                "layer_color_hex": "#ABCDEF",
                "tags": "test",
                "validated": True,
                "source_license": "CC BY",
                "coordinates_confidence_enum": "exact",
                "source_url": "https://example.com/source",
                "coordinates_source": "Wikipedia",
                "sequence_order": 1,
            },
        }
    ]


def generate_mock_layers_records() -> List[Dict[str, Any]]:
    return [
        {
            "id": "recLayerTEST",
            "fields": {
                "layer_id": "test_layer",
                "name_ru": "Тестовый слой",
                "name_en": "Test layer",
                "color_hex": "#ABCDEF",
                "icon": "test",
                "is_enabled": True,
            },
        }
    ]
    
    
def build_geojson_features(mapped_records: Iterable[Dict[str, Any]], warnings: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> Dict[str, Any]:
    features = []
    for m in mapped_records:
        record_id = m.get("id") or "<missing>"
        if parse_bool(m.get("validated")) is not True:
            add_issue(errors, "critical", record_id, "not_validated", "validated")
            continue
        etl_error = get_etl_error(m)
        if etl_error is not None:
            add_issue(errors, "critical", record_id, etl_error, "etl_error")
            continue
        lon = m.get("longitude")
        lat = m.get("latitude")
        if lat is None or lon is None:
            add_issue(errors, "critical", record_id, "missing_geometry", "geometry")
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            add_issue(errors, "critical", record_id, "invalid_coordinates", "geometry")
            continue
        geometry = {"type": "Point", "coordinates": [lon, lat]}
                
        features.append(
            {
                "type": "Feature",
                "id": m.get("id"),
                "geometry": geometry,
                "properties": {
                    "id": m.get("id"),
                    "normalized_id": m.get("normalized_id"),
                    "canonical_publish_id": get_canonical_publish_id(m),
                    "airtable_record_id": m.get("airtable_record_id"),
                    "external_id": m.get("external_id"),
                    "source_draft_id": m.get("source_draft_id"),
                    "origin_key": get_origin_key(m),
                    "layer_id": m.get("layer_id"),
                    "layer_type": m.get("layer_type"),
                    "name_ru": m.get("name_ru"),
                    "name_en": m.get("name_en"),
                    "date_start": m.get("date_start"),
                    "date_construction_end": m.get("date_construction_end"),
                    "date_end": m.get("date_end"),
                    "longitude": m.get("longitude"),
                    "latitude": m.get("latitude"),
                    "influence_radius_km": m.get("influence_radius_km"),
                    "title_short": m.get("title_short"),
                    "description": m.get("description"),
                    "image_url": m.get("image_url"),
                    "source_url": m.get("source_url"),
                    "source_license": m.get("source_license"),
                    "coordinates_confidence": m.get("coordinates_confidence"),
                    "coordinates_source": m.get("coordinates_source"),
                    "sequence_order": m.get("sequence_order"),
                    "tags": m.get("tags"),
                    "validated": m.get("validated"),
                    "date_valid": m.get("date_valid"),
                    "has_geometry": geometry is not None,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def get_etl_error(mapped: Dict[str, Any]) -> Optional[str]:
    existing_error = safe_str(mapped.get("etl_error"))
    if existing_error:
        return existing_error
    record_id = safe_str(mapped.get("id"))
    if not record_id:
        return "missing_id"
    # Compatibility mode: legacy non-empty ids are still tolerated at runtime.
    # Target UUID v4 contract is tracked via is_uuid_v4() helper/self-checks.
    if "name_ru" in mapped and not safe_str(mapped.get("name_ru")):
        return "missing_name_ru"
    if "layer_type" in mapped and mapped.get("layer_type") not in ALLOWED_LAYER_TYPES:
        return "invalid_layer_type"
    source_url = safe_str(mapped.get("source_url"))
    if not source_url:
        return "missing_source_url"
    parsed_source_url = urlparse(source_url.strip())
    if parsed_source_url.scheme not in ("http", "https") or parsed_source_url.netloc == "":
        return "invalid_source_url"
    image_url = safe_str(mapped.get("image_url"))
    if image_url and not is_valid_url(image_url):
        return "invalid_image_url"
    if not is_valid_license(mapped.get("source_license")):
        return "invalid_license"
    if mapped.get("_invalid_coordinates"):
        return "invalid_coordinates"
    latitude = parse_float(mapped.get("latitude"))
    longitude = parse_float(mapped.get("longitude"))
    if latitude is None or longitude is None:
        return "missing_geometry"
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return "invalid_coordinates"
    if "_raw_date_start_present" in mapped:
        if not mapped.get("_raw_date_start_present"):
            return "missing_date_start"
        if mapped.get("_invalid_date_start") or not is_valid_iso_date(mapped.get("date_start")):
            return "invalid_date_start"
    elif mapped.get("date_start") not in (None, "") and not is_valid_iso_date(mapped.get("date_start")):
        return "invalid_date_start"

    if "_raw_date_end_present" in mapped:
        if mapped.get("_raw_date_end_present") and (
            mapped.get("_invalid_date_end") or not is_valid_iso_date(mapped.get("date_end"))
        ):
            return "invalid_date_end"
    elif mapped.get("date_end") not in (None, "") and not is_valid_iso_date(mapped.get("date_end")):
        return "invalid_date_end"
    if mapped.get("_invalid_layer_link"):
        return "invalid_layer_link_format"
    layer_id = mapped.get("layer_id")
    if not layer_id:
        return "unknown_layer_link" if mapped.get("_unknown_layer_link") else "missing_layer_id"
    if mapped.get("_unknown_layer_link"):
        return "unknown_layer_link"
    return None


def normalize_hex_color(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if HEX_COLOR_RE.match(cleaned):
        return cleaned
    return None


def map_layers(layer_records: Iterable[Dict[str, Any]]) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    linked_layer_to_public_id: Dict[str, str] = {}
    layers: List[Dict[str, Any]] = []

    for record in layer_records:
        record_id = record.get("id")
        fields = record.get("fields", {}) or {}
        layer_id = safe_str(fields.get("layer_id"))
        if record_id and layer_id:
            linked_layer_to_public_id[record_id] = layer_id
        layers.append(
            {
                "layer_id": layer_id,
                "name_ru": safe_str(fields.get("name_ru")),
                "name_en": safe_str(fields.get("name_en")),
                "color_hex": normalize_hex_color(safe_str(fields.get("color_hex"))),
                "icon": safe_str(fields.get("icon")),
                "is_enabled": parse_bool(fields.get("is_enabled")),
            }
        )
    return linked_layer_to_public_id, layers


def validate_feature(mapped: Dict[str, Any], layer_ids: set[str], warnings: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> bool:
    record_id = mapped.get("id") or "<missing>"
    valid = True

    def critical(field: str, reason: str) -> None:
        nonlocal valid
        valid = False
        add_issue(errors, "critical", record_id, reason, field)

    def warning(field: str, reason: str) -> None:
        add_issue(warnings, "warning", record_id, reason, field)

    if not mapped.get("id"):
        critical("id", "missing_id")
    if not mapped.get("name_ru"):
        critical("name_ru", "missing_name_ru")
    has_start = bool(mapped.get("_raw_date_start_present"))
    if not has_start:
        critical("date_start", "missing_date_start")
    elif mapped.get("_invalid_date_start") or not is_valid_iso_date(mapped.get("date_start")):
        critical("date_start", "invalid_date_start")
    if mapped.get("_raw_date_end_present") and (
        mapped.get("_invalid_date_end") or not is_valid_iso_date(mapped.get("date_end"))
    ):
        critical("date_end", "invalid_date_end")
    validated_value = parse_bool(mapped.get("validated"))
    if validated_value is not True:
        critical("validated", "not_validated")
    source_url = mapped.get("source_url")
    if not source_url:
        critical("source_url", "missing_source_url")
    else:
        parsed_source_url = urlparse(source_url.strip())
        if parsed_source_url.scheme not in ("http", "https") or parsed_source_url.netloc == "":
            critical("source_url", "invalid_source_url")
    if mapped.get("layer_type") not in ALLOWED_LAYER_TYPES:
        critical("layer_type", "invalid_layer_type")
    if mapped.get("_invalid_coordinates"):
        critical("geometry", "invalid_coordinates")
    raw_latitude = mapped.get("latitude")
    raw_longitude = mapped.get("longitude")
    latitude = parse_float(raw_latitude)
    longitude = parse_float(raw_longitude)
    if raw_latitude not in (None, "") and latitude is None:
        mapped["_invalid_coordinates"] = True
    if raw_longitude not in (None, "") and longitude is None:
        mapped["_invalid_coordinates"] = True
    mapped["latitude"] = latitude
    mapped["longitude"] = longitude
    if (latitude is None) ^ (longitude is None):
        critical("geometry", "missing_geometry_coordinate")
    elif latitude is not None and longitude is not None and not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        critical("geometry", "invalid_coordinates")
    date_valid = (
        not mapped.get("_invalid_date_start")
        and not mapped.get("_invalid_date_end")
        and is_valid_iso_date(mapped.get("date_start"))
        and is_valid_iso_date(mapped.get("date_end"))
    )
    mapped["date_valid"] = date_valid
    if not is_valid_license(mapped.get("source_license")):
        critical("source_license", "invalid_license")
    if mapped.get("coordinates_confidence") not in ALLOWED_COORDINATES_CONFIDENCE:
        critical("coordinates_confidence", "invalid_coordinates_confidence")
    if mapped.get("coordinates_source") and mapped.get("coordinates_source") not in ALLOWED_COORDINATES_SOURCES:
        critical("coordinates_source", "invalid_coordinates_source")
    if mapped.get("image_url") and not is_valid_url(mapped.get("image_url")):
        critical("image_url", "invalid_image_url")
    title_short = mapped.get("title_short")
    if title_short is not None and len(title_short) > 120:
        critical("title_short", "title_short_too_long")
    description = mapped.get("description")
    if description is not None and len(description) > 2000:
        critical("description", "description_too_long")
    layer_id = mapped.get("layer_id")
    if mapped.get("_invalid_layer_link"):
        critical("layer_id", "invalid_layer_link_format")
    elif not layer_id:
        critical("layer_id", "unknown_layer_link" if mapped.get("_unknown_layer_link") else "missing_layer_id")
    elif layer_id not in layer_ids:
        critical("layer_id", "unknown_layer_link")
    return valid


def validate_layer(layer: Dict[str, Any], warnings: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> bool:
    layer_id = layer.get("layer_id") or "<missing>"
    valid = True
    if not layer.get("layer_id"):
        add_issue(errors, "critical", layer_id, "missing layer_id", "layer_id")
        valid = False
    if not layer.get("name_ru"):
        add_issue(errors, "critical", layer_id, "missing layer name_ru", "name_ru")
        valid = False
    if not is_valid_color_hex(layer.get("color_hex")):
        add_issue(errors, "critical", layer_id, "invalid color_hex", "color_hex")
        valid = False
    if not isinstance(layer.get("is_enabled"), bool):
        add_issue(errors, "critical", layer_id, "is_enabled must be boolean", "is_enabled")
        valid = False
    return valid


def build_validation_report(
    total_records: int,
    valid_records: int,
    skipped_records: int,
    warnings: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "total_records": total_records,
        "valid_records": valid_records,
        "skipped_records": skipped_records,
        "warnings_count": len(warnings),
        "errors_count": len(errors),
        "warnings": warnings,
        "errors": errors,
    }


def aggregate_issues(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    stats: Dict[str, int] = {}
    for issue in issues:
        reason = issue.get("reason") or issue.get("error") or issue.get("warning")
        if not reason:
            continue
        stats[reason] = stats.get(reason, 0) + 1
    return stats


def write_json(path: Path, data: Any) -> None:
    """Безопасная сериализация JSON в файл."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def maybe_commit(paths: List[Path], records_count: int) -> None:
    message = f"Export Airtable: {dt.date.today().isoformat()} {records_count} records"
    existing = [str(p) for p in paths if p.exists()]
    if not existing:
        return
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", *existing],
            check=True,
            capture_output=True,
            text=True,
        )
        if not status.stdout.strip():
            print("Флаг --commit указан, но изменений в экспортных файлах нет — commit пропущен.")
            return
        subprocess.run(["git", "add", *existing], check=True)
        subprocess.run(["git", "commit", "-m", message], check=True)
        print(f"Создан git commit: {message}")
    except Exception as exc:  # noqa: BLE001
        print(f"Флаг --commit указан, но git commit не выполнен: {exc}", file=sys.stderr)


def run_self_test() -> int:
    errors: List[Dict[str, Any]] = []
    sample = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "fields": {
            "layer_id": "history",
            "layer_type_enum": "architecture",
            "name_ru": "Тест",
            "date_start": "-0753",
            "longitude_num": 37.6173,
            "latitude_num": 55.7558,
            "influence_radius_km": "12",
            "layer_color_hex": "#ABCDEF",
            "tags": "A, b ,C",
            "validated": True,
            "source_license_enum": "CC BY",
            "coordinates_confidence_enum": "exact",
            "source_url": "https://example.com/source",
            "coordinates_source": "Wikipedia",
        },
    }
    m = map_record(sample, errors, {"history": "history"})
    assert m["date_start"] == "-0753"
    assert m["tags"] == ["a", "b", "c"]
    assert m["validated"] is True
    assert m["influence_radius_km"] == 12
    assert m["longitude"] == 37.6173
    assert m["latitude"] == 55.7558
    assert normalize_hex_color(m["layer_color_hex"]) == "#abcdef"
    assert not any(e.get("error") for e in errors if "error" in e)
    assert is_valid_iso_date(m["date_start"])
    assert is_valid_license(m["source_license"])
    assert normalize_source_license("cc by-sa") == "CC BY-SA"
    assert normalize_source_license("unsupported-license") is None
    assert normalize_layer_type("Route Point") == "route_point"
    assert normalize_layer_type("unsupported-layer") is None
    assert normalize_coordinates_confidence("EXACT") == "exact"
    assert normalize_coordinates_confidence("approximate±3km") == "approximate"
    assert normalize_coordinates_confidence("unknown") == "conditional"
    m_limit_ok = dict(m)
    m_limit_ok["title_short"] = "t" * 120
    m_limit_ok["description"] = "d" * 2000
    assert validate_feature(m_limit_ok, {"history"}, [], [])
    m_limit_fail = dict(m)
    m_limit_fail["title_short"] = "t" * 121
    m_limit_fail["description"] = "d" * 2001
    limit_errors: List[Dict[str, Any]] = []
    assert not validate_feature(m_limit_fail, {"history"}, [], limit_errors)
    assert any(issue.get("reason") == "title_short_too_long" for issue in limit_errors)
    assert any(issue.get("reason") == "description_too_long" for issue in limit_errors)
    assert get_etl_error(
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "source_url": "https://example.com",
            "source_license": "CC BY",
            "latitude": 55.0,
            "longitude": 37.0,
            "layer_id": "history",
        }
    ) is None
    assert get_etl_error(
        {
            "id": "recLEGACY",
            "source_url": "https://example.com",
            "source_license": "CC BY",
            "latitude": 55.0,
            "longitude": 37.0,
            "layer_id": "history",
        }
    ) is None
    assert is_uuid_v4("550e8400-e29b-41d4-a716-446655440000")
    assert not is_uuid_v4("recLEGACY")
    assert (
        get_etl_error(
            {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "source_url": "https://example.com",
                "source_license": "bad",
                "latitude": 55.0,
                "longitude": 37.0,
                "layer_id": "history",
            }
        )
        == "invalid_license"
    )
    assert get_etl_error({"id": "550e8400-e29b-41d4-a716-446655440000", "source_url": "javascript:alert(1)"}) == "invalid_source_url"
    assert (
        get_etl_error(
            {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "source_url": "https://example.com",
                "source_license": "CC BY",
                "latitude": None,
                "longitude": 37.0,
                "layer_id": "history",
            }
        )
        == "missing_geometry"
    )
    assert (
        get_etl_error(
            {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "source_url": "https://example.com",
                "source_license": "CC BY",
                "latitude": 95.0,
                "longitude": 37.0,
                "layer_id": "history",
            }
        )
        == "invalid_coordinates"
    )
    assert get_etl_error({"id": "550e8400-e29b-41d4-a716-446655440000", "source_url": "https://example.com", "source_license": "CC BY", "latitude": 55.0, "longitude": 37.0, "layer_id": None}) == "missing_layer_id"
    assert get_etl_error({"id": "550e8400-e29b-41d4-a716-446655440000", "source_url": "https://example.com", "source_license": "CC BY", "latitude": 55.0, "longitude": 37.0, "layer_id": "history", "_unknown_layer_link": True}) == "unknown_layer_link"
    assert get_etl_error({"id": "", "source_url": "https://example.com"}) == "missing_id"
    name_ru_fixture = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name_ru": "Корректное имя",
        "source_url": "https://example.com",
        "source_license": "CC BY",
        "latitude": 55.0,
        "longitude": 37.0,
        "layer_id": "history",
        "layer_type": "architecture",
        "_raw_date_start_present": True,
        "date_start": "2020",
    }
    assert get_etl_error(name_ru_fixture) is None
    assert get_etl_error({**name_ru_fixture, "image_url": ""}) is None
    assert get_etl_error({**name_ru_fixture, "image_url": "https://example.com/image.jpg"}) is None
    assert get_etl_error({**name_ru_fixture, "image_url": "javascript:alert(1)"}) == "invalid_image_url"
    assert get_etl_error({**name_ru_fixture, "layer_type": "bad_layer"}) == "invalid_layer_type"
    assert get_etl_error({**name_ru_fixture, "name_ru": "   "}) == "missing_name_ru"
    assert get_etl_error({**name_ru_fixture, "name_ru": None}) == "missing_name_ru"
    bad_start = map_record(
        {"id": "550e8400-e29b-41d4-a716-446655440001", "fields": {**sample["fields"], "date_start": "2024-13-01"}},
        [],
        {"history": "history"},
    )
    assert not validate_feature(bad_start, {"history"}, [], [])
    bad_end = map_record(
        {"id": "550e8400-e29b-41d4-a716-446655440002", "fields": {**sample["fields"], "date_end": "2024-99-01"}},
        [],
        {"history": "history"},
    )
    assert not validate_feature(bad_end, {"history"}, [], [])
    missing_start = map_record(
        {"id": "550e8400-e29b-41d4-a716-446655440003", "fields": {k: v for k, v in sample["fields"].items() if k != "date_start"}},
        [],
        {"history": "history"},
    )
    missing_start_errors: List[Dict[str, Any]] = []
    assert not validate_feature(missing_start, {"history"}, [], missing_start_errors)
    start_reasons = [issue.get("reason") for issue in missing_start_errors if issue.get("field") == "date_start"]
    assert start_reasons.count("missing_date_start") == 1
    assert "invalid_date_start" not in start_reasons
    assert get_etl_error(missing_start) == "missing_date_start"

    no_end = map_record(
        {"id": "550e8400-e29b-41d4-a716-446655440004", "fields": {**sample["fields"], "date_end": ""}},
        [],
        {"history": "history"},
    )
    assert validate_feature(no_end, {"history"}, [], [])
    assert get_etl_error(no_end) is None
    assert get_etl_error(bad_start) == "invalid_date_start"
    assert get_etl_error(bad_end) == "invalid_date_end"
    print("Self-test OK")
    return 0


def sort_mapped_records(mapped_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Детерминированная сортировка для стабильных diff/commit."""
    def key(item: Dict[str, Any]) -> Tuple[Any, ...]:
        layer = item.get("layer_id")
        date_start = item.get("date_start")
        return (
            layer is None,
            layer or "",
            date_start is None,
            date_start or "",
            item.get("id") or "",
        )

    return sorted(mapped_records, key=key)
    
def main() -> int:
    started_at = time.time()
    args = parse_args()

    if args.self_test:
        return run_self_test()

    token = os.getenv("AIRTABLE_TOKEN")
    base = args.base or os.getenv("AIRTABLE_BASE")
    table = args.table or os.getenv("AIRTABLE_TABLE")

    dry_run = bool(args.dry_run)
    if not dry_run and (not token or not base or not table):
        dry_run = True
        print("Не заданы AIRTABLE_TOKEN/AIRTABLE_BASE/AIRTABLE_TABLE — включён dry-run.")

    if not dry_run and not REQUESTS_AVAILABLE:
        print("Не найден модуль 'requests'. Установите его: pip install requests", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    # В dry-run пишем в _test_* файлы, чтобы не затирать рабочие данные.
    prefix = "_test_" if dry_run else ""
    raw_path = out_dir / f"{prefix}features.json"
    geojson_path = out_dir / f"{prefix}features.geojson"
    rejected_path = out_dir / f"{prefix}rejected.json"
    layers_path = out_dir / f"{prefix}layers.json"
    validation_report_path = out_dir / f"{prefix}validation_report.json"
    export_meta_path = out_dir / f"{prefix}export_meta.json"
    error_log_path = out_dir / f"{prefix}export_errors.log"

    records: List[Dict[str, Any]]
    layer_records: List[Dict[str, Any]]
    try:
        if dry_run:
            records = generate_mock_records()
            layer_records = generate_mock_layers_records()
            if args.max_records is not None:
                records = records[: args.max_records]
            print("Dry-run: mock data generated")
        else:
            assert token is not None and base is not None and table is not None
            records = fetch_airtable_records(token, base, table, args.max_records)
            layer_records = fetch_airtable_records(token, base, LAYERS_TABLE_NAME, None)
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"Критическая ошибка: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Непредвиденная ошибка: {exc}", file=sys.stderr)
        return 1

    print(f"Загружено Features: {len(records)}")
    print(f"Загружено Layers: {len(layer_records)}")

    warnings: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    candidate_records: List[Dict[str, Any]] = []

    linked_layer_to_public_id, layers = map_layers(layer_records)
    for record in records:
        mapped = map_record(record, warnings, linked_layer_to_public_id)
        candidate_records.append(mapped)

    valid_layers = [layer for layer in layers if validate_layer(layer, warnings, errors)]
    valid_layer_ids = {layer["layer_id"] for layer in valid_layers}

    valid_features: List[Dict[str, Any]] = []
    rejected_features: List[Dict[str, Any]] = []
    seen_dedupe_keys: set[Tuple[Any, ...]] = set()
    for mapped in candidate_records:
        mapped["etl_status"] = "pending"
        mapped["etl_error"] = None

        if parse_bool(mapped.get("validated")) is not True:
            mapped["etl_status"] = "rejected"
            mapped["etl_error"] = "not_validated"
            rejected_features.append(
                {
                    "id": mapped.get("id") or "<missing>",
                    "name_ru": mapped.get("name_ru"),
                    "reasons": ["not_validated"],
                }
            )
            continue

        if not args.include_inactive and mapped.get("is_active") is False:
            mapped["etl_status"] = "rejected"
            mapped["etl_error"] = "inactive"
            rejected_features.append(
                {
                    "id": mapped.get("id") or "<missing>",
                    "name_ru": mapped.get("name_ru"),
                    "reasons": ["inactive"],
                }
            )
            continue

        record_errors_start = len(errors)
        feature_valid = validate_feature(mapped, valid_layer_ids, warnings, errors)
        if not feature_valid:
            critical_reasons = [
                issue.get("reason")
                for issue in errors[record_errors_start:]
                if issue.get("severity") == "critical" and issue.get("id") == (mapped.get("id") or "<missing>")
            ]
            if not critical_reasons:
                critical_reasons = ["validation_failed"]
            mapped["etl_status"] = "rejected"
            mapped["etl_error"] = critical_reasons[0]
            rejected_features.append(
                {
                    "id": mapped.get("id") or "<missing>",
                    "name_ru": mapped.get("name_ru"),
                    "reasons": critical_reasons,
                }
            )
            continue

        etl_error = get_etl_error(mapped)
        if etl_error is not None:
            mapped["etl_status"] = "rejected"
            mapped["etl_error"] = etl_error
            rejected_features.append(
                {
                    "id": mapped.get("id") or "<missing>",
                    "name_ru": mapped.get("name_ru"),
                    "reasons": [etl_error],
                }
            )
            continue

        longitude = mapped.get("longitude")
        latitude = mapped.get("latitude")
        if longitude is None or latitude is None:
            mapped["etl_status"] = "rejected"
            mapped["etl_error"] = "missing_geometry"
            rejected_features.append(
                {
                    "id": mapped.get("id") or "<missing>",
                    "name_ru": mapped.get("name_ru"),
                    "reasons": ["missing_geometry"],
                }
            )
            continue

        dedupe_key = get_dedupe_key(mapped)
        if dedupe_key in seen_dedupe_keys:
            mapped["etl_status"] = "rejected"
            mapped["etl_error"] = "duplicate"
            rejected_features.append(
                {
                    "id": mapped.get("id") or "<missing>",
                    "name_ru": mapped.get("name_ru"),
                    "reasons": ["duplicate"],
                }
            )
            continue
        seen_dedupe_keys.add(dedupe_key)
        mapped["etl_status"] = "ok"
        mapped["etl_error"] = None
        valid_features.append(mapped)

    valid_features = sort_mapped_records(valid_features)

    geojson = build_geojson_features(valid_features, warnings, errors)
    validation_report = build_validation_report(
        total_records=len(records),
        valid_records=len(valid_features),
        skipped_records=len(records) - len(valid_features),
        warnings=warnings,
        errors=errors,
    )
    error_stats = aggregate_issues(errors)
    warning_stats = aggregate_issues(warnings)

    export_meta = {
        "timestamp": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "dry-run" if dry_run else "airtable",
        "records_total_source": len(records),
        "records_exported": len(valid_features),
        "records_geojson": len(geojson["features"]),
        "errors": len(errors),
        "warnings": len(warnings),
        "error_stats": error_stats,
        "warning_stats": warning_stats,
        "duration_seconds": round(time.time() - started_at, 3),
    }

    try:
        write_json(raw_path, records)
        write_json(geojson_path, geojson)
        write_json(rejected_path, rejected_features)
        write_json(layers_path, valid_layers)
        write_json(validation_report_path, validation_report)
        write_json(export_meta_path, export_meta)

        # Перезаписываем лог ошибок на каждый запуск
        if error_log_path.exists():
            error_log_path.unlink()
        error_log_path.parent.mkdir(parents=True, exist_ok=True)
        error_log_path.touch()
        for err in [*warnings, *errors]:
            log_error(error_log_path, err)
    except Exception as exc:  # noqa: BLE001
        print(f"Критическая ошибка сериализации/записи: {exc}", file=sys.stderr)
        return 1

    # Финальный вывод — в формате, согласованном с мастер-промптом
    print(f"OK: {len(valid_features)} | Errors: {len(errors)} | Rejected: {len(rejected_features)}")
    print(f"LAYERS: {len(valid_layers)}")
    if rejected_features:
        preview = rejected_features[:3]
        print(f"REJECT_PREVIEW: {json.dumps(preview, ensure_ascii=False)}")
    if len(valid_features) == 0:
        print("WARNING: valid features = 0")

    if args.commit:
        maybe_commit(
            [raw_path, geojson_path, rejected_path, layers_path, validation_report_path, export_meta_path, error_log_path],
            len(valid_features),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

# --- Пример запуска ---
# AIRTABLE_TOKEN=pat_xxx AIRTABLE_BASE=appHmf8ubeUF9 AIRTABLE_TABLE=Features python3 scripts/export_airtable.py
# python3 scripts/export_airtable.py --dry-run --out-dir data --max-records 20
#
# --- Чеклист после запуска ---
# 1) Созданы data/features.json, data/features.geojson, data/layers.json, data/export_meta.json (или data/_test_* в dry-run).
# 2) В data/*export_errors.log есть JSON Lines с ключами record_id/field/error/value.
# 3) features.geojson имеет influence_radius_km и has_geometry в properties.
# 4) В выводе есть строка: Успешно: N | Ошибок: M | Source total: T.
#
# --- Как тестировать ---
# 1) Dry-run:
#    python scripts/export_airtable.py --dry-run --out-dir data --max-records 5
#    Проверить: data/_test_features.geojson, data/_test_export_meta.json, data/_test_export_errors.log
# 2) С реальным Airtable (если есть env):
#    AIRTABLE_TOKEN=... AIRTABLE_BASE=... python scripts/export_airtable.py --out-dir data --max-records 50
#    Проверить: data/features.geojson, data/export_meta.json и вывод "Успешно: ..."
# 3) Проверить, что features.geojson.features[*].properties содержит поля:
#    - influence_radius_km
#    - has_geometry
# 4) Проверить флаг --include-inactive:
#    а) по умолчанию: записи с is_active=False пропускаются
#    б) с --include-inactive: экспортируются все записи
