import unittest

from scripts.export_airtable import (
    aggregate_issues,
    build_geojson_features,
    build_validation_report,
    get_canonical_publish_id,
    get_dedupe_key,
    get_origin_key,
    map_layers,
    map_record,
    normalize_coordinates_confidence,
    validate_feature,
)


class ExportAirtableIdempotencyTests(unittest.TestCase):
    def _build_mapped(self, **overrides):
        base = {
            "id": "recFeature2",
            "validated": True,
            "source_url": "https://example.com/source",
            "longitude": 10.0,
            "latitude": 10.0,
            "_invalid_coordinates": False,
            "source_license": "CC BY",
            "coordinates_source": "expert estimate",
            "layer_id": "roman_empire",
            "coordinates_confidence": "exact",
            "layer_type": "biography",
            "name_ru": "Запись",
            "date_start": "1348",
        }
        base.update(overrides)
        if "_raw_date_start_present" not in base:
            base["_raw_date_start_present"] = bool(base.get("date_start"))
        return base

    def test_coordinates_confidence_legacy_normalization(self):
        self.assertEqual(normalize_coordinates_confidence("EXACT"), "exact")
        self.assertEqual(normalize_coordinates_confidence("APPROXIMATE±5km"), "approximate")
        self.assertEqual(normalize_coordinates_confidence("CONDITIONAL"), "conditional")

    def test_origin_key_priority(self):
        mapped = {
            "external_id": "draft:100",
            "airtable_record_id": "recAAA",
            "source_draft_id": "draft:100",
        }
        self.assertEqual(get_origin_key(mapped), "draft:100")

    def test_origin_key_fallback_to_airtable_record_id(self):
        mapped = {"external_id": None, "airtable_record_id": "recBBB", "source_draft_id": None}
        self.assertEqual(get_origin_key(mapped), "recBBB")

    def test_dedupe_key_fallback_without_origin(self):
        mapped = {"name_ru": "Test", "latitude": 1.0, "longitude": 2.0}
        self.assertEqual(get_dedupe_key(mapped), ("Test", 1.0, 2.0))

    def test_canonical_publish_id_prefers_normalized_id(self):
        mapped = {
            "normalized_id": "norm-1",
            "airtable_record_id": "recAAA",
            "external_id": "draft:100",
            "source_draft_id": "draft:100",
        }
        self.assertEqual(get_canonical_publish_id(mapped), "norm-1")

    def test_map_layer_linked_record_to_public_layer_id(self):
        linked_map, _ = map_layers(
            [
                {
                    "id": "recLayer1",
                    "fields": {
                        "layer_id": "roman_empire",
                        "name_ru": "Римская империя",
                        "color_hex": "#112233",
                        "is_enabled": True,
                    },
                }
            ]
        )
        mapped = map_record(
            {"id": "recFeature1", "fields": {"layer_id": ["recLayer1"]}},
            [],
            linked_map,
        )
        self.assertEqual(mapped["layer_id"], "roman_empire")

    def test_coordinates_source_invalid_is_rejected(self):
        mapped = self._build_mapped(coordinates_source="Unknown source")
        warnings = []
        errors = []
        is_valid = validate_feature(mapped, {"roman_empire"}, warnings, errors)
        self.assertFalse(is_valid)
        self.assertTrue(any(e.get("reason") == "invalid_coordinates_source" for e in errors))

    def test_coordinates_source_allowed_is_not_rejected(self):
        mapped = self._build_mapped(coordinates_source="expert estimate")
        warnings = []
        errors = []
        is_valid = validate_feature(mapped, {"roman_empire"}, warnings, errors)
        self.assertTrue(is_valid)
        self.assertFalse(any(e.get("reason") == "invalid_coordinates_source" for e in errors))

    def test_missing_id_rejected(self):
        warnings = []
        errors = []
        self.assertFalse(validate_feature(self._build_mapped(id=""), {"roman_empire"}, warnings, errors))
        self.assertTrue(any(e.get("reason") == "missing_id" for e in errors))

    def test_missing_layer_id_rejected(self):
        warnings = []
        errors = []
        self.assertFalse(validate_feature(self._build_mapped(layer_id=None), {"roman_empire"}, warnings, errors))
        self.assertTrue(any(e.get("reason") == "missing_layer_id" for e in errors))

    def test_missing_name_ru_rejected(self):
        warnings = []
        errors = []
        self.assertFalse(validate_feature(self._build_mapped(name_ru=None), {"roman_empire"}, warnings, errors))
        self.assertTrue(any(e.get("reason") == "missing_name_ru" for e in errors))

    def test_missing_date_start_rejected(self):
        warnings = []
        errors = []
        self.assertFalse(validate_feature(self._build_mapped(date_start=None), {"roman_empire"}, warnings, errors))
        self.assertTrue(any(e.get("reason") == "missing_date_start" for e in errors))

    def test_missing_source_url_rejected(self):
        warnings = []
        errors = []
        self.assertFalse(validate_feature(self._build_mapped(source_url=None), {"roman_empire"}, warnings, errors))
        self.assertTrue(any(e.get("reason") == "missing_source_url" for e in errors))

    def test_invalid_enum_rejected(self):
        warnings = []
        errors = []
        self.assertFalse(
            validate_feature(
                self._build_mapped(layer_type="unknown_enum_value"),
                {"roman_empire"},
                warnings,
                errors,
            )
        )
        self.assertTrue(any(e.get("reason") == "invalid_layer_type" for e in errors))

    def test_broken_linked_record_rejected(self):
        linked_map, _ = map_layers(
            [{"id": "recLayer1", "fields": {"layer_id": "roman_empire", "name_ru": "Layer", "color_hex": "#112233", "is_enabled": True}}]
        )
        warnings = []
        mapped = map_record({"id": "recFeatureX", "fields": {"layer_id": ["recLayer1", "recLayer2"]}}, warnings, linked_map)
        errors = []
        self.assertFalse(validate_feature(self._build_mapped(**mapped), {"roman_empire"}, warnings, errors))
        self.assertTrue(any(e.get("reason") == "invalid_layer_link_format" for e in errors))

    def test_string_layer_fallback_is_supported(self):
        mapped = map_record({"id": "recFeatureY", "fields": {"layer_id": "roman_empire"}}, [], {})
        self.assertEqual(mapped["layer_id"], "roman_empire")
        self.assertFalse(mapped["_invalid_layer_link"])

    def test_geometry_with_missing_coordinate_rejected(self):
        warnings = []
        errors = []
        self.assertFalse(validate_feature(self._build_mapped(latitude=None), {"roman_empire"}, warnings, errors))
        self.assertTrue(any(e.get("reason") == "missing_geometry_coordinate" for e in errors))


class ExportAirtablePipelineTests(unittest.TestCase):
    def _feature_record(self, *, record_id: str, validated: bool = True, coordinates_source: str = "UNESCO / Wikipedia"):
        return {
            "id": record_id,
            "fields": {
                "layer_id": ["recLayer1"],
                "layer_type_enum": "biography",
                "name_ru": f"Запись {record_id}",
                "date_start": "1348",
                "longitude": 10.0,
                "latitude": 10.0,
                "validated": validated,
                "source_license_enum": "CC BY",
                "coordinates_confidence_enum": "exact",
                "source_url": "https://example.com/source",
                "coordinates_source": coordinates_source,
            },
        }

    def _run_pipeline(self, records):
        warnings = []
        errors = []
        linked_layers, layers = map_layers(
            [{"id": "recLayer1", "fields": {"layer_id": "roman_empire", "name_ru": "Рим", "color_hex": "#112233", "is_enabled": True}}]
        )
        mapped = [map_record(record, warnings, linked_layers) for record in records]
        valid_layer_ids = {layer["layer_id"] for layer in layers}

        valid_features = []
        rejected = []
        for item in mapped:
            if item.get("validated") is not True:
                rejected.append({"id": item.get("id"), "reasons": ["not_validated"]})
                continue
            record_errors_start = len(errors)
            if not validate_feature(item, valid_layer_ids, warnings, errors):
                reasons = [
                    issue.get("reason")
                    for issue in errors[record_errors_start:]
                    if issue.get("severity") == "critical" and issue.get("id") == (item.get("id") or "<missing>")
                ]
                rejected.append({"id": item.get("id"), "reasons": reasons or ["validation_failed"]})
                continue
            valid_features.append(item)

        geojson = build_geojson_features(valid_features, warnings, errors)
        validation_report = build_validation_report(
            total_records=len(records),
            valid_records=len(valid_features),
            skipped_records=len(records) - len(valid_features),
            warnings=warnings,
            errors=errors,
        )
        export_meta = {
            "records_total_source": len(records),
            "records_exported": len(valid_features),
            "records_geojson": len(geojson["features"]),
            "errors": len(errors),
            "warnings": len(warnings),
            "error_stats": aggregate_issues(errors),
            "warning_stats": aggregate_issues(warnings),
        }
        return geojson, rejected, validation_report, export_meta

    def test_happy_path_validated_record_is_in_geojson(self):
        geojson, rejected, report, meta = self._run_pipeline([self._feature_record(record_id="recA")])
        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertEqual(len(geojson["features"]), 1)
        self.assertEqual(geojson["features"][0]["id"], "recA")
        self.assertEqual(rejected, [])
        self.assertEqual(report["valid_records"], 1)
        self.assertEqual(meta["records_geojson"], 1)

    def test_mixed_path_has_validated_and_rejected(self):
        geojson, rejected, report, meta = self._run_pipeline(
            [
                self._feature_record(record_id="recA"),
                self._feature_record(record_id="recB", coordinates_source="broken-source"),
            ]
        )
        self.assertEqual(len(geojson["features"]), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["id"], "recB")
        self.assertIn("invalid_coordinates_source", rejected[0]["reasons"])
        self.assertEqual(report["valid_records"], 1)
        self.assertEqual(report["skipped_records"], 1)
        self.assertEqual(meta["records_exported"], 1)
        self.assertEqual(meta["records_total_source"], 2)

    def test_empty_valid_path_keeps_empty_geojson_and_consistent_meta(self):
        geojson, rejected, report, meta = self._run_pipeline(
            [self._feature_record(record_id="recA", coordinates_source="broken-source")]
        )
        self.assertEqual(geojson["features"], [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["valid_records"], 0)
        self.assertEqual(report["skipped_records"], 1)
        self.assertEqual(meta["records_total_source"], 1)
        self.assertEqual(meta["records_exported"], 0)
        self.assertEqual(meta["records_geojson"], 0)
        self.assertEqual(meta["error_stats"].get("invalid_coordinates_source"), 1)


if __name__ == "__main__":
    unittest.main()
