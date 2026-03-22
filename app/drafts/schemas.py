from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DraftCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    geometry: dict[str, Any] | None = None

    @field_validator("geometry")
    @classmethod
    def validate_geometry(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        _validate_geojson(value)
        return value


class DraftUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    geometry: dict[str, Any] | None = None

    @field_validator("geometry")
    @classmethod
    def validate_geometry(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        _validate_geojson(value)
        return value


class DraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    geometry: dict[str, Any] | None
    image_url: str | None
    created_at: datetime
    updated_at: datetime


GeoJson = dict[str, Any]


def _validate_geojson(value: GeoJson) -> None:
    geojson_type = value.get("type")
    if not geojson_type or not isinstance(geojson_type, str):
        raise ValueError("geometry must be valid GeoJSON")

    if geojson_type in {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
        if "coordinates" not in value:
            raise ValueError("geometry must be valid GeoJSON")
        return

    if geojson_type == "GeometryCollection":
        geometries = value.get("geometries")
        if not isinstance(geometries, list):
            raise ValueError("geometry must be valid GeoJSON")
        for geometry in geometries:
            if not isinstance(geometry, dict):
                raise ValueError("geometry must be valid GeoJSON")
            _validate_geojson(geometry)
        return

    if geojson_type == "Feature":
        geometry = value.get("geometry")
        if geometry is not None and not isinstance(geometry, dict):
            raise ValueError("geometry must be valid GeoJSON")
        if isinstance(geometry, dict):
            _validate_geojson(geometry)
        return

    if geojson_type == "FeatureCollection":
        features = value.get("features")
        if not isinstance(features, list):
            raise ValueError("geometry must be valid GeoJSON")
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise ValueError("geometry must be valid GeoJSON")
            _validate_geojson(feature)
        return

    raise ValueError("geometry must be valid GeoJSON")
