import unittest

from scripts.export_airtable import (
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
            "coordinates_source": "UNESCO / Wikipedia",
            "layer_id": "roman_empire",
            "coordinates_confidence": "exact",
            "layer_type": "biography",
            "name_ru": "Запись",
            "date_start": "1348",
        }
        base.update(overrides)
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

    def test_coordinates_source_is_non_fatal(self):
        mapped = self._build_mapped()
        warnings = []
        errors = []
        is_valid = validate_feature(mapped, {"roman_empire"}, warnings, errors)
        self.assertTrue(is_valid)
        self.assertFalse([e for e in errors if e.get("severity") == "critical"])

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


if __name__ == "__main__":
    unittest.main()
