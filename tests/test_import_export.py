import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.import_features import export_validated, import_records, read_csv_records, read_geojson_records, write_validated_outputs


def _layer_ids():
    return {"roman_empire"}


class ImportExportTests(unittest.TestCase):
    def test_import_csv_splits_validated_and_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "input.csv"
            rows = [
                {
                    "id": "recValid",
                    "layer_id": "roman_empire",
                    "layer_type": "biography",
                    "name_ru": "Valid",
                    "date_start": "1900",
                    "date_end": "1910",
                    "longitude": "30.5",
                    "latitude": "50.4",
                    "coordinates_confidence": "exact",
                    "coordinates_source": "Wikipedia",
                    "source_url": "https://example.com/source",
                    "source_license": "CC BY",
                    "validated": "true",
                },
                {
                    "id": "recInvalid",
                    "layer_id": "roman_empire",
                    "layer_type": "biography",
                    "name_ru": "Invalid",
                    "date_start": "1900",
                    "longitude": "300.0",
                    "latitude": "50.4",
                    "coordinates_confidence": "exact",
                    "coordinates_source": "Wikipedia",
                    "source_url": "https://example.com/source",
                    "source_license": "CC BY",
                    "validated": "true",
                },
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            parsed = read_csv_records(csv_path)
            validated, rejected, warnings, errors = import_records(parsed, _layer_ids())
            self.assertEqual(len(validated), 1)
            self.assertEqual(validated[0]["id"], "recValid")
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected[0]["id"], "recInvalid")
            self.assertTrue(any(reason in {"invalid_coordinates", "validation_failed"} for reason in rejected[0]["reasons"]))
            self.assertIsInstance(warnings, list)
            self.assertIsInstance(errors, list)

    def test_import_geojson_and_export_csv_geojson(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            geojson_in = tmp_path / "input.geojson"
            payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "recGeo",
                        "geometry": {"type": "Point", "coordinates": [30.5, 50.4]},
                        "properties": {
                            "id": "recGeo",
                            "layer_id": "roman_empire",
                            "layer_type": "biography",
                            "name_ru": "Geo",
                            "date_start": "1901",
                            "date_end": "1902",
                            "coordinates_confidence": "exact",
                            "coordinates_source": "Wikipedia",
                            "source_url": "https://example.com/source",
                            "source_license": "CC BY",
                            "validated": True,
                        },
                    }
                ],
            }
            geojson_in.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            parsed = read_geojson_records(geojson_in)
            validated, rejected, warnings, errors = import_records(parsed, _layer_ids())
            self.assertEqual(len(validated), 1)
            self.assertEqual(len(rejected), 0)

            data_dir = tmp_path / "data"
            outputs = write_validated_outputs(data_dir, validated, rejected, warnings, errors)
            self.assertTrue(outputs["features_geojson"].exists())
            self.assertTrue(outputs["features_json"].exists())
            self.assertTrue(outputs["rejected"].exists())

            export_dir = tmp_path / "export"
            export_paths = export_validated(outputs["features_geojson"], export_dir)
            self.assertTrue(export_paths["geojson"].exists())
            self.assertTrue(export_paths["csv"].exists())

            csv_content = export_paths["csv"].read_text(encoding="utf-8")
            self.assertIn("id", csv_content)
            self.assertIn("recGeo", csv_content)

            exported_geojson = json.loads(export_paths["geojson"].read_text(encoding="utf-8"))
            self.assertEqual(exported_geojson.get("type"), "FeatureCollection")
            self.assertEqual(len(exported_geojson.get("features", [])), 1)


if __name__ == "__main__":
    unittest.main()
