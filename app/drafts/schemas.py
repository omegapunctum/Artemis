from datetime import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

FORBIDDEN_DRAFT_FIELDS = {
    "etl_status",
    "etl_error",
    "date_valid",
    "dedupe_key",
    "published_from_draft_id",
    "version",
    "created_at",
    "updated_at",
    "status",
    "publish_status",
    "airtable_record_id",
    "published_at",
    "id",
    "user_id",
    "validated",
    "is_active",
}

DATE_START_PATTERN = re.compile(r"^-?\d{4}(?:-\d{2}-\d{2})?$")


class DraftPayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_type: Literal["architecture", "route_point", "biogeography", "biography"] | None = None
    name_en: str | None = None
    coordinates_confidence: Literal["exact", "approximate", "conditional"] | None = None
    coordinates_source: str | None = None
    source_license: Literal["CC0", "CC BY", "CC BY-SA", "PD"] | None = None
    source_url: HttpUrl | None = None
    latitude: float | None = None
    longitude: float | None = None
    title_short: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None
    image_url: HttpUrl | None = None
    sequence_order: int | None = None
    influence_radius_km: float | None = None
    geometry: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_forbidden_fields(cls, payload: Any) -> Any:
        if not isinstance(payload, dict):
            return payload
        forbidden = sorted(FORBIDDEN_DRAFT_FIELDS.intersection(payload.keys()))
        if forbidden:
            raise ValueError(f"forbidden fields in payload: {', '.join(forbidden)}")
        return payload

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if not -90 <= value <= 90:
            raise ValueError("latitude must be between -90 and 90")
        return value

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if not -180 <= value <= 180:
            raise ValueError("longitude must be between -180 and 180")
        return value

    @model_validator(mode="after")
    def validate_coordinates_pair(self) -> "DraftPayloadBase":
        has_latitude = self.latitude is not None
        has_longitude = self.longitude is not None
        if has_latitude != has_longitude:
            raise ValueError("latitude and longitude must be provided together")
        return self


class DraftCreate(DraftPayloadBase):
    name_ru: str = Field(min_length=1)
    date_start: str = Field(min_length=1)
    source_url: HttpUrl

    @field_validator("name_ru")
    @classmethod
    def validate_name_ru(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name_ru must not be empty")
        return value

    @field_validator("date_start")
    @classmethod
    def validate_date_start(cls, value: str) -> str:
        if not DATE_START_PATTERN.fullmatch(value):
            raise ValueError("date_start must be YYYY, YYYY-MM-DD, or -YYYY")
        return value

    @field_validator("geometry")
    @classmethod
    def validate_geometry(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        _validate_geojson(value)
        return value


class DraftUpdate(DraftPayloadBase):
    name_ru: str | None = Field(default=None, min_length=1)
    date_start: str | None = Field(default=None, min_length=1)

    @field_validator("name_ru")
    @classmethod
    def validate_name_ru(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("name_ru must not be empty")
        return value

    @field_validator("date_start")
    @classmethod
    def validate_date_start(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not DATE_START_PATTERN.fullmatch(value):
            raise ValueError("date_start must be YYYY, YYYY-MM-DD, or -YYYY")
        return value

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
    payload: dict[str, Any] | None = None
    status: Literal["draft", "review", "approved", "rejected"]
    publish_status: Literal["pending", "published", "failed"]
    airtable_record_id: str | None
    published_at: datetime | None
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
