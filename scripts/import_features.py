#!/usr/bin/env python3
"""Локальный import/export датасетов (CSV/GeoJSON) в ETL-совместимый data/*.

Скрипт не пишет в Airtable: он подготавливает локальные data/features.* и rejected.json,
используя ту же validation-логику, что и основной ETL (`scripts/export_airtable.py`).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from scripts.export_airtable import (
    build_geojson_features,
    is_valid_iso_date,
    normalize_coordinates_confidence,
    normalize_coordinates_source,
    normalize_layer_type,
    normalize_source_license,
    parse_bool,
    parse_float,
    to_tags,
    validate_feature,
    write_json,
)

CSV_FIELDS = [
    "id",
    "normalized_id",
    "external_id",
    "source_draft_id",
    "layer_id",
    "layer_type",
    "name_ru",
    "name_en",
    "date_start",
    "date_construction_end",
    "date_end",
    "longitude",
    "latitude",
    "influence_radius_km",
    "title_short",
    "description",
    "image_url",
    "source_url",
    "source_license",
    "coordinates_confidence",
    "coordinates_source",
    "sequence_order",
    "tags",
    "validated",
    "is_active",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import/export features datasets (CSV/GeoJSON)")
    sub = parser.add_subparsers(dest="command", required=True)

    import_cmd = sub.add_parser("import", help="Импорт CSV/GeoJSON в data/* через ETL validation")
    import_cmd.add_argument("--input", required=True, help="Путь к CSV или GeoJSON")
    import_cmd.add_argument("--format", choices=["csv", "geojson", "auto"], default="auto")
    import_cmd.add_argument("--layers", default="data/layers.json", help="Путь к layers.json")
    import_cmd.add_argument("--out-dir", default="data", help="Каталог для результата")

    export_cmd = sub.add_parser("export", help="Экспорт validated data в GeoJSON/CSV")
    export_cmd.add_argument("--geojson-in", default="data/features.geojson", help="Путь к validated features.geojson")
    export_cmd.add_argument("--raw-json-in", default="data/features.json", help="Путь к raw features.json")
    export_cmd.add_argument("--out-dir", default="data/export", help="Каталог экспорта")
    export_cmd.add_argument("--include-raw", action="store_true", help="Экспортировать также raw dataset (если есть)")

    return parser.parse_args()


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_date(value: Any) -> str | None:
    text = _safe_text(value)
    if text is None:
        return None
    return text if is_valid_iso_date(text) else None


def _normalize_row(record: Dict[str, Any], fallback_id: str) -> Dict[str, Any]:
    mapped: Dict[str, Any] = {
        "id": _safe_text(record.get("id")) or fallback_id,
        "airtable_record_id": _safe_text(record.get("airtable_record_id")) or _safe_text(record.get("id")) or fallback_id,
        "normalized_id": _safe_text(record.get("normalized_id")),
        "external_id": _safe_text(record.get("external_id")),
        "source_draft_id": _safe_text(record.get("source_draft_id")),
        "layer_id": _safe_text(record.get("layer_id")),
        "_raw_layer_link_id": _safe_text(record.get("layer_id")),
        "_unknown_layer_link": False,
        "_invalid_layer_link": False,
        "layer_type": normalize_layer_type(record.get("layer_type")),
        "name_ru": _safe_text(record.get("name_ru")),
        "name_en": _safe_text(record.get("name_en")),
        "date_start": _normalize_date(record.get("date_start")),
        "date_construction_end": _normalize_date(record.get("date_construction_end")),
        "date_end": _normalize_date(record.get("date_end")),
        "longitude": parse_float(record.get("longitude")),
        "latitude": parse_float(record.get("latitude")),
        "_invalid_coordinates": False,
        "influence_radius_km": _parse_int(record.get("influence_radius_km")),
        "title_short": _safe_text(record.get("title_short")),
        "description": _safe_text(record.get("description")),
        "image_url": _safe_text(record.get("image_url")),
        "source_url": _safe_text(record.get("source_url")),
        "source_license": normalize_source_license(record.get("source_license")),
        "coordinates_confidence": normalize_coordinates_confidence(record.get("coordinates_confidence")),
        "coordinates_source": normalize_coordinates_source(record.get("coordinates_source")),
        "sequence_order": _parse_int(record.get("sequence_order")),
        "tags": to_tags(record.get("tags")),
        "validated": parse_bool(record.get("validated")),
        "is_active": parse_bool(record.get("is_active")),
        "_raw_date_start_present": record.get("date_start") not in (None, ""),
        "_invalid_date_start": record.get("date_start") not in (None, "") and _normalize_date(record.get("date_start")) is None,
        "_raw_date_end_present": record.get("date_end") not in (None, ""),
        "_invalid_date_end": record.get("date_end") not in (None, "") and _normalize_date(record.get("date_end")) is None,
    }
    lon = mapped.get("longitude")
    lat = mapped.get("latitude")
    mapped["_invalid_coordinates"] = (
        (record.get("longitude") not in (None, "") and lon is None)
        or (record.get("latitude") not in (None, "") and lat is None)
        or (lon is not None and not (-180 <= lon <= 180))
        or (lat is not None and not (-90 <= lat <= 90))
    )
    return mapped


def load_layer_ids(layers_path: Path) -> set[str]:
    payload = json.loads(layers_path.read_text(encoding="utf-8"))
    return {
        str(layer.get("layer_id") or "").strip()
        for layer in (payload if isinstance(payload, list) else [])
        if str(layer.get("layer_id") or "").strip()
    }


def read_csv_records(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader)


def read_geojson_records(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON input must be FeatureCollection")
    rows: List[Dict[str, Any]] = []
    for index, feature in enumerate(payload.get("features", [])):
        props = feature.get("properties", {}) if isinstance(feature, dict) else {}
        geometry = feature.get("geometry") if isinstance(feature, dict) else {}
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        row = dict(props or {})
        if isinstance(coords, list) and len(coords) >= 2:
            row.setdefault("longitude", coords[0])
            row.setdefault("latitude", coords[1])
        row.setdefault("id", feature.get("id") if isinstance(feature, dict) else f"geojson-{index + 1}")
        rows.append(row)
    return rows


def import_records(records: Iterable[Dict[str, Any]], layer_ids: set[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    warnings: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    validated: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for index, raw in enumerate(records):
        mapped = _normalize_row(raw, fallback_id=f"import-{index + 1}")
        before_errors = len(errors)
        is_valid = validate_feature(mapped, layer_ids, warnings, errors)
        if is_valid:
            validated.append(mapped)
            continue
        reason_rows = errors[before_errors:]
        reasons = [str(row.get("reason") or row.get("error") or "validation_failed") for row in reason_rows] or ["validation_failed"]
        rejected.append({"id": mapped.get("id"), "reasons": reasons, "record": mapped})

    return validated, rejected, warnings, errors


def write_validated_outputs(out_dir: Path, validated: List[Dict[str, Any]], rejected: List[Dict[str, Any]], warnings: List[Dict[str, Any]], errors: List[Dict[str, Any]]) -> Dict[str, Path]:
    geojson = build_geojson_features(validated, warnings, errors)
    features_json_path = out_dir / "features.json"
    features_geojson_path = out_dir / "features.geojson"
    rejected_path = out_dir / "rejected.json"
    write_json(features_json_path, validated)
    write_json(features_geojson_path, geojson)
    write_json(rejected_path, rejected)
    return {
        "features_json": features_json_path,
        "features_geojson": features_geojson_path,
        "rejected": rejected_path,
    }


def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def export_validated(geojson_path: Path, out_dir: Path) -> Dict[str, Path]:
    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("features.geojson must be FeatureCollection")
    features = payload.get("features", [])
    validated_rows: List[Dict[str, Any]] = []
    for feature in features:
        props = feature.get("properties", {}) if isinstance(feature, dict) else {}
        row = {field: props.get(field) for field in CSV_FIELDS}
        if row.get("longitude") is None or row.get("latitude") is None:
            coords = (feature.get("geometry") or {}).get("coordinates") if isinstance(feature, dict) else None
            if isinstance(coords, list) and len(coords) >= 2:
                row["longitude"] = coords[0]
                row["latitude"] = coords[1]
        validated_rows.append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    geojson_out = out_dir / "validated_features.geojson"
    csv_out = out_dir / "validated_features.csv"
    write_json(geojson_out, payload)
    write_csv(csv_out, validated_rows, CSV_FIELDS)
    return {"geojson": geojson_out, "csv": csv_out}


def export_raw(raw_json_path: Path, out_dir: Path) -> Dict[str, Path]:
    if not raw_json_path.exists():
        return {}
    rows = json.loads(raw_json_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("raw features.json must be array")
    raw_json_out = out_dir / "raw_features.json"
    raw_csv_out = out_dir / "raw_features.csv"
    write_json(raw_json_out, rows)
    write_csv(raw_csv_out, rows, CSV_FIELDS)
    return {"raw_json": raw_json_out, "raw_csv": raw_csv_out}


def run_import(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    layers_path = Path(args.layers)

    selected_format = args.format
    if selected_format == "auto":
        selected_format = "geojson" if input_path.suffix.lower() in {".geojson", ".json"} else "csv"

    layer_ids = load_layer_ids(layers_path)
    if selected_format == "csv":
        source_records = read_csv_records(input_path)
    else:
        source_records = read_geojson_records(input_path)

    validated, rejected, warnings, errors = import_records(source_records, layer_ids)
    outputs = write_validated_outputs(out_dir, validated, rejected, warnings, errors)
    print(
        f"Import done: total={len(source_records)} validated={len(validated)} rejected={len(rejected)} "
        f"(warnings={len(warnings)}, errors={len(errors)})."
    )
    print("Written:", ", ".join(str(path) for path in outputs.values()))
    return 0


def run_export(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    outputs = export_validated(Path(args.geojson_in), out_dir)
    if args.include_raw:
        outputs.update(export_raw(Path(args.raw_json_in), out_dir))
    print("Export done:", ", ".join(f"{name}={path}" for name, path in outputs.items()))
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "import":
        return run_import(args)
    if args.command == "export":
        return run_export(args)
    raise RuntimeError("Unsupported command")


if __name__ == "__main__":
    raise SystemExit(main())
