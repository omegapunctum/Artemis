import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.service import User
from app.drafts.service import Draft, update_draft

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover - fallback for limited environments
    requests = None

AIRTABLE_API_URL = "https://api.airtable.com/v0"
DEFAULT_AIRTABLE_TABLE = "Features"
DEFAULT_MODERATOR_EMAILS_ENV = "MODERATOR_EMAILS"
DEFAULT_LAYER_ID = "ugc"
DEFAULT_LAYER_TYPE = "point"
DEFAULT_COORDINATES_CONFIDENCE = "exact"
DEFAULT_COORDINATES_SOURCE = "ugc"
DEFAULT_SOURCE_URL = "UGC"
DEFAULT_SOURCE_LICENSE = "CC BY"


def is_moderator(user: User) -> bool:
    if bool(getattr(user, "is_admin", False)):
        return True

    whitelist = {
        email.strip().lower()
        for email in os.getenv(DEFAULT_MODERATOR_EMAILS_ENV, "").split(",")
        if email.strip()
    }
    return user.email.lower() in whitelist


def require_moderator(user: User) -> User:
    if not is_moderator(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Moderator access required")
    return user


def list_review_drafts(db: Session) -> list[Draft]:
    return db.query(Draft).filter(Draft.status == "review").order_by(Draft.updated_at.asc()).all()


def get_draft_for_moderation(db: Session, draft_id: int) -> Draft:
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return draft


def submit_draft_for_review(db: Session, draft: Draft) -> Draft:
    if draft.status == "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved draft cannot be resubmitted")
    if draft.status == "review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft already in review")
    return update_draft(db, draft, changes={"status": "review"})


def approve_draft(db: Session, draft: Draft) -> Draft:
    if draft.status == "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft already approved")
    if draft.status != "review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only drafts in review can be approved")

    create_airtable_feature(draft)
    return update_draft(db, draft, changes={"status": "approved"})


def reject_draft(db: Session, draft: Draft) -> Draft:
    if draft.status == "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved draft cannot be rejected")
    if draft.status == "rejected":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft already rejected")
    if draft.status != "review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only drafts in review can be rejected")
    return update_draft(db, draft, changes={"status": "rejected"})


def create_airtable_feature(draft: Draft) -> dict[str, Any]:
    token = os.getenv("AIRTABLE_TOKEN")
    base_id = os.getenv("AIRTABLE_BASE") or os.getenv("AIRTABLE_BASE_ID")
    table_name = os.getenv("AIRTABLE_TABLE", DEFAULT_AIRTABLE_TABLE)

    if not token or not base_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Airtable is not configured",
        )

    url = f"{AIRTABLE_API_URL}/{base_id}/{urllib.parse.quote(table_name, safe='')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"fields": build_airtable_fields(draft)}

    if requests is not None:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Airtable request failed: {response.status_code}",
            )
        return response.json()

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Airtable request failed: {exc.code}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Airtable request failed: network error",
        ) from exc


def build_airtable_fields(draft: Draft) -> dict[str, Any]:
    longitude: float | None = None
    latitude: float | None = None
    geometry = draft.geometry or {}
    if geometry.get("type") == "Point":
        coordinates = geometry.get("coordinates") or []
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            longitude = _to_float_or_none(coordinates[0])
            latitude = _to_float_or_none(coordinates[1])

    fields: dict[str, Any] = {
        "name_ru": draft.title,
        "description": draft.description,
        "image_url": draft.image_url,
        "source_url": DEFAULT_SOURCE_URL,
        "source_license": DEFAULT_SOURCE_LICENSE,
        "layer_id": DEFAULT_LAYER_ID,
        "layer_type": DEFAULT_LAYER_TYPE,
        "coordinates_confidence": DEFAULT_COORDINATES_CONFIDENCE,
        "coordinates_source": DEFAULT_COORDINATES_SOURCE,
        "name_en": None,
        "date_start": None,
        "date_end": None,
        "influence_radius_km": None,
        "sequence_order": None,
        "title_short": draft.title,
        "tags": None,
        "is_active": True,
        "latitude": latitude,
        "longitude": longitude,
    }
    return fields


def _to_float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
