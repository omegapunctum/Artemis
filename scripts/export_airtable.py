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

AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE = os.getenv("AIRTABLE_BASE")
AIRTABLE_TABLE = os.getenv("AIRTABLE_TABLE")

import re
import subprocess
import sys
import time
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
ALLOWED_COORDINATES_CONFIDENCE = {"ТОЧНО", "ПРИБЛИЗИТЕЛЬНО±Nкм", "УСЛОВНО"}
ALLOWED_LAYER_TYPES = {"architecture", "route_point", "biogeography", "biography"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Экспорт данных Features из Airtable")
    parser.add_argument("--base", help="Airtable base id (или AIRTABLE_BASE)")
    parser.add_argument("--table", help="Airtable table name (или AIRTABLE_TABLE)")
    parser.add_argument("--out-dir", default="data", help="Каталог для выходных файлов (по умолчанию: data)")
    parser.add_argument("--dry-run", action="store_true", help="Не ходить в сеть и сгенерировать mock-данные")
    parser.add_argument("--max-records", type=int, default=None, help="Ограничить число записей (для тестирования)")
    parser.add_argument(
        "--exclude-without-geometry",
        action="store_true",
        help="Исключить из GeoJSON записи без координат (по умолчанию такие записи остаются)",
    )
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


def to_date_or_none(value: Any, record_id: str, field: str, errors: List[Dict[str, Any]]) -> Optional[str]:
    if value in (None, ""):
        return None
    value_str = str(value).strip()
    if DATE_RE.match(value_str):
        return value_str
    errors.append({"record_id": record_id, "field": field, "error": f"invalid date: {value}", "value": value})
    return None


def to_float_or_none(value: Any, record_id: str, field: str, errors: List[Dict[str, Any]]) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append({"record_id": record_id, "field": field, "error": f"invalid float: {value}", "value": value})
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
        errors.append({"record_id": record_id, "field": field, "error": f"invalid int: {value}", "value": value})
        return None


def to_bool_or_none(value: Any, record_id: str, field: str, errors: List[Dict[str, Any]]) -> Optional[bool]:
    if value in (None, ""):
        return None
    normalized = value.strip().lower() if isinstance(value, str) else value
    if normalized in TRUE_SET:
        return True
    if normalized in FALSE_SET:
        return False
    errors.append({"record_id": record_id, "field": field, "error": f"invalid bool: {value}", "value": value})
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
    errors.append(
        {
            "record_id": record_id,
            "field": field,
            "error": f"out of range [{minimum}, {maximum}]",
            "warning": "invalid coordinates",
            "value": value,
        }
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


def add_issue(issues: List[Dict[str, Any]], severity: str, record_id: str, reason: str, field: Optional[str] = None) -> None:
    payload: Dict[str, Any] = {"id": record_id or "<missing>", "reason": reason, "severity": severity}
    if field:
        payload["field"] = field
    issues.append(payload)


def map_record(record: Dict[str, Any], errors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Преобразование записи Airtable в нормализованную структуру properties."""
    record_id = record.get("id", "")
    fields = record.get("fields", {}) or {}

    longitude = fields.get("longitude_num")
    if longitude in (None, ""):
        legacy_longitude = fields.get("longitude")
        if legacy_longitude not in (None, ""):
            errors.append(
                {"record_id": record_id, "field": "longitude", "warning": "using legacy fallback field", "value": legacy_longitude}
            )
        longitude = parse_float(legacy_longitude)

    latitude = fields.get("latitude_num")
    if latitude in (None, ""):
        legacy_latitude = fields.get("latitude")
        if legacy_latitude not in (None, ""):
            errors.append(
                {"record_id": record_id, "field": "latitude", "warning": "using legacy fallback field", "value": legacy_latitude}
            )
        latitude = parse_float(legacy_latitude)

    is_active = fields.get("is_active_bool")
    if is_active in (None, ""):
        legacy_is_active = fields.get("is_active")
        if legacy_is_active not in (None, ""):
            errors.append(
                {"record_id": record_id, "field": "is_active", "warning": "using legacy fallback field", "value": legacy_is_active}
            )
        is_active = parse_bool(legacy_is_active)

    source_license = safe_str(fields.get("source_license_enum"))
    if source_license is None:
        source_license = safe_str(fields.get("source_license"))
        if source_license is not None:
            errors.append(
                {
                    "record_id": record_id,
                    "field": "source_license",
                    "warning": "using legacy fallback field",
                    "value": source_license,
                }
            )

    coordinates_confidence = safe_str(fields.get("coordinates_confidence_enum"))
    if coordinates_confidence is None:
        coordinates_confidence = safe_str(fields.get("coordinates_confidence"))
        if coordinates_confidence is not None:
            errors.append(
                {
                    "record_id": record_id,
                    "field": "coordinates_confidence",
                    "warning": "using legacy fallback field",
                    "value": coordinates_confidence,
                }
            )

    longitude = validate_coordinate_range(longitude, -180.0, 180.0, record_id, "longitude", errors)
    latitude = validate_coordinate_range(latitude, -90.0, 90.0, record_id, "latitude", errors)
    source_url = safe_str(fields.get("source_url"))
    if source_url is None:
        errors.append({"record_id": record_id, "field": "source_url", "warning": "missing source_url", "value": None})

    mapped = {
        "id": record_id,
        "layer_id": safe_str(fields.get("layer_id")),
        "layer_type": safe_str(fields.get("layer_type")),
        "name_ru": safe_str(fields.get("name_ru")),
        "name_en": safe_str(fields.get("name_en")),
        "date_start": to_date_or_none(fields.get("date_start"), record_id, "date_start", errors),
        "date_construction_end": to_date_or_none(
            fields.get("date_construction_end"), record_id, "date_construction_end", errors
        ),
        "date_end": to_date_or_none(fields.get("date_end"), record_id, "date_end", errors),
        "longitude": longitude,
        "latitude": latitude,
        "influence_radius_km": to_int_or_none(
            fields.get("influence_radius_km"), record_id, "influence_radius_km", errors
        ),
        "title_short": safe_str(fields.get("title_short")),
        "description": safe_str(fields.get("description")),
        "image_url": safe_str(fields.get("image_url")),
        "source_url": source_url,
        "source_license": source_license,
        "coordinates_confidence": coordinates_confidence,
        "coordinates_source": safe_str(fields.get("coordinates_source")),
        "sequence_order": to_int_or_none(fields.get("sequence_order"), record_id, "sequence_order", errors),
        "tags": to_tags(fields.get("tags")),
        "is_active": is_active,
        # Доп. поля для слоёв (если в таблице присутствуют)
        "layer_name_ru": safe_str(fields.get("layer_name_ru") or fields.get("layer_name")),
        "layer_color_hex": safe_str(fields.get("layer_color_hex") or fields.get("color_hex")),
        "layer_icon": safe_str(fields.get("layer_icon") or fields.get("icon")),
    }
    return mapped


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
                "layer_type": "biography",
                "name_ru": "Тестовая запись",
                "date_start": "1348",
                "longitude": 37.6173,
                "latitude": 55.7558,
                "influence_radius_km": 12,
                "layer_color_hex": "#ABCDEF",
                "tags": "test",
                "is_active_bool": True,
                "source_license": "CC BY",
                "coordinates_confidence": "ТОЧНО",
                "source_url": "https://example.com/source",
                "coordinates_source": "Wikipedia",
                "sequence_order": 1,
            },
        }
    ]
    
    
def build_geojson_features(mapped_records: Iterable[Dict[str, Any]], warnings: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> Dict[str, Any]:
    features = []
    for m in mapped_records:
        lon = m.get("longitude")
        lat = m.get("latitude")
        if lat is None or lon is None:
            add_issue(warnings, "warning", m.get("id") or "<missing>", "missing coordinates, skipped in geojson", "geometry")
            continue
        else:
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                add_issue(errors, "critical", m.get("id") or "<missing>", "invalid coordinates, skipped in geojson", "geometry")
                continue
            else:
                geometry = {"type": "Point", "coordinates": [lon, lat]}

        features.append(
            {
                "type": "Feature",
                "id": m.get("id"),
                "geometry": geometry,
                "properties": {
                    "id": m.get("id"),
                    "layer_id": m.get("layer_id"),
                    "layer_type": m.get("layer_type"),
                    "name_ru": m.get("name_ru"),
                    "name_en": m.get("name_en"),
                    "date_start": m.get("date_start"),
                    "date_construction_end": m.get("date_construction_end"),
                    "date_end": m.get("date_end"),
                    "longitude_enum": m.get("longitude"),
                    "latitude_enum": m.get("latitude"),
                    "influence_radius_km": m.get("influence_radius_km"),
                    "title_short": m.get("title_short"),
                    "description": m.get("description"),
                    "image_url": m.get("image_url"),
                    "source_url": m.get("source_url"),
                    "source_license_enum": m.get("source_license"),
                    "coordinates_confidence": m.get("coordinates_confidence"),
                    "coordinates_source": m.get("coordinates_source"),
                    "sequence_order": m.get("sequence_order"),
                    "tags": m.get("tags"),
                    "is_active": m.get("is_active"),
                    "has_geometry": True,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def normalize_hex_color(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if HEX_COLOR_RE.match(cleaned):
        return cleaned
    return None


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
        critical("id", "missing id")
    if not mapped.get("layer_id"):
        critical("layer_id", "missing layer_id")
    elif mapped["layer_id"] not in layer_ids:
        critical("layer_id", "layer_id not found in layers")
    if not is_valid_layer_type(mapped.get("layer_type")):
        critical("layer_type", "invalid layer_type")
    if not mapped.get("name_ru"):
        critical("name_ru", "missing name_ru")
    if not mapped.get("source_url"):
        critical("source_url", "missing source_url")
    if mapped.get("latitude") is not None and not (-90 <= mapped["latitude"] <= 90):
        critical("latitude", "latitude out of range")
    if mapped.get("longitude") is not None and not (-180 <= mapped["longitude"] <= 180):
        critical("longitude", "longitude out of range")
    if not is_valid_iso_date(mapped.get("date_start")):
        critical("date_start", "invalid ISO date")
    if not is_valid_iso_date(mapped.get("date_end")):
        critical("date_end", "invalid ISO date")
    if not is_valid_license(mapped.get("source_license")):
        critical("source_license", "invalid source_license")
    if mapped.get("coordinates_confidence") not in ALLOWED_COORDINATES_CONFIDENCE:
        critical("coordinates_confidence", "invalid coordinates_confidence")
    if not isinstance(mapped.get("is_active"), bool):
        critical("is_active", "is_active must be boolean")
    if mapped.get("title_short") and len(mapped["title_short"]) > 120:
        critical("title_short", "title_short exceeds 120 characters")
    if mapped.get("description") and len(mapped["description"]) > 2000:
        critical("description", "description exceeds 2000 characters")
    tags = mapped.get("tags") or []
    if any(" " in tag for tag in tags):
        critical("tags", "tags must be comma-separated without spaces")
    if mapped.get("latitude") is None and mapped.get("longitude") is None:
        warning("geometry", "coordinates are null")
    elif mapped.get("latitude") is None or mapped.get("longitude") is None:
        critical("geometry", "longitude/latitude must both be present or null")
    if not mapped.get("image_url"):
        warning("image_url", "missing image_url")
    if not mapped.get("description"):
        warning("description", "empty description")
    return valid


def validate_layer(layer: Dict[str, Any], warnings: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> bool:
    layer_id = layer.get("id") or "<missing>"
    valid = True
    if not layer.get("id"):
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


def build_layers(mapped_records: Iterable[Dict[str, Any]], errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_layer: Dict[str, Dict[str, Any]] = {}
    for m in mapped_records:
        lid = m.get("layer_id")
        if not lid:
            continue
        raw_color = m.get("layer_color_hex")
        normalized_color = normalize_hex_color(raw_color)
        if raw_color is None:
            normalized_color = "#999999"
        elif normalized_color is None:
            errors.append(
                {
                    "record_id": m.get("id"),
                    "field": "layer_color_hex",
                    "error": "invalid hex color, set to null",
                    "value": raw_color,
                }
            )
        if lid not in by_layer:
            by_layer[lid] = {
                "id": lid,
                "name_ru": m.get("layer_name_ru") or lid,
                "color_hex": normalized_color,
                "icon": m.get("layer_icon"),
                "is_enabled": True,
            }
    return [by_layer[k] for k in sorted(by_layer.keys())]


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
        "id": "recTEST",
        "fields": {
            "layer_id": "history",
            "layer_type": "timeline",
            "name_ru": "Тест",
            "date_start": "-0753",
            "longitude_num": 37.6173,
            "latitude_num": 55.7558,
            "influence_radius_km": "12",
            "layer_color_hex": "#ABCDEF",
            "tags": "A, b ,C",
            "is_active_bool": True,
            "source_license_enum": "CC BY",
            "coordinates_confidence_enum": "exact",
            "source_url": "https://example.com/source",
        },
    }
    m = map_record(sample, errors)
    assert m["date_start"] == "-0753"
    assert m["tags"] == ["a", "b", "c"]
    assert m["is_active"] is True
    assert m["influence_radius_km"] == 12
    assert m["longitude"] == 37.6173
    assert m["latitude"] == 55.7558
    assert normalize_hex_color(m["layer_color_hex"]) == "#abcdef"
    assert not errors
    assert is_valid_iso_date(m["date_start"])
    assert is_valid_license(m["source_license"])
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
    layers_path = out_dir / f"{prefix}layers.json"
    validation_report_path = out_dir / f"{prefix}validation_report.json"
    export_meta_path = out_dir / f"{prefix}export_meta.json"
    error_log_path = out_dir / f"{prefix}export_errors.log"

    records: List[Dict[str, Any]]
    try:
        if dry_run:
            records = generate_mock_records()
            if args.max_records is not None:
                records = records[: args.max_records]
            print("Dry-run: mock data generated")
        else:
            assert token is not None and base is not None and table is not None
            records = fetch_airtable_records(token, base, table, args.max_records)
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"Критическая ошибка: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Непредвиденная ошибка: {exc}", file=sys.stderr)
        return 1

    warnings: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    candidate_records: List[Dict[str, Any]] = []
    skipped_inactive = 0
    for record in records:
        mapped = map_record(record, warnings)
        if not mapped.get("is_active") and not args.include_inactive:
            skipped_inactive += 1
            continue
        candidate_records.append(mapped)

    layers = build_layers(candidate_records, warnings)
    valid_layers = [layer for layer in layers if validate_layer(layer, warnings, errors)]
    valid_layer_ids = {layer["id"] for layer in valid_layers}

    mapped_records = [m for m in candidate_records if validate_feature(m, valid_layer_ids, warnings, errors)]
    mapped_records = sort_mapped_records(mapped_records)
    if args.exclude_without_geometry:
        mapped_records = [m for m in mapped_records if m.get("longitude") is not None and m.get("latitude") is not None]

    geojson = build_geojson_features(mapped_records, warnings, errors)
    validation_report = build_validation_report(
        total_records=len(records),
        valid_records=len(mapped_records),
        skipped_records=len(records) - len(mapped_records),
        warnings=warnings,
        errors=errors,
    )

    export_meta = {
        "timestamp": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "dry-run" if dry_run else "airtable",
        "records_total_source": len(records),
        "records_exported": len(mapped_records),
        "records_geojson": len(geojson["features"]),
        "errors": len(errors),
        "warnings": len(warnings),
        "skipped_inactive": skipped_inactive,
        "duration_seconds": round(time.time() - started_at, 3),
    }

    try:
        write_json(raw_path, records)
        write_json(geojson_path, geojson)
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
    print(
        f"Прочитано: {len(records)} | Валидно: {len(mapped_records)} | "
        f"Пропущено: {validation_report['skipped_records']} | "
        f"Warnings: {len(warnings)} | Critical: {len(errors)}"
    )

    if args.commit:
        maybe_commit(
            [raw_path, geojson_path, layers_path, validation_report_path, export_meta_path, error_log_path],
            len(mapped_records),
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
