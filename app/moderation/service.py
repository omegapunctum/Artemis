import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.service import User
from app.observability import log_event, metrics
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
AIRTABLE_EXTERNAL_ID_FIELD = os.getenv("AIRTABLE_EXTERNAL_ID_FIELD", "external_id")
PUBLISH_STATUS_PENDING = "pending"
PUBLISH_STATUS_PUBLISHED = "published"
PUBLISH_STATUS_FAILED = "failed"

logger = logging.getLogger(__name__)
_publish_locks: dict[int, threading.Lock] = {}
_publish_locks_guard = threading.Lock()


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
    return update_draft(db, draft, changes={"status": "review", "publish_status": PUBLISH_STATUS_PENDING})


def approve_draft(db: Session, draft: Draft, request: Request | None = None, moderator: User | None = None) -> Draft:
    with _draft_publish_lock(draft.id):
        db.refresh(draft)

        if draft.airtable_record_id and draft.publish_status == PUBLISH_STATUS_PUBLISHED:
            if draft.status != "approved":
                published = update_draft(
                    db,
                    draft,
                    changes={
                        "status": "approved",
                        "published_at": draft.published_at or datetime.utcnow(),
                    },
                )
                metrics.increment('publishes_success')
                log_event(logging.INFO, 'moderation.approve', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
                log_event(logging.INFO, 'moderation.publish.success', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
                return published
            return draft

        if draft.status not in {"review", "approved"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only drafts in review or approved can be published")

        existing_record = find_existing_airtable_feature(draft)
        if existing_record:
            published = _mark_draft_as_published(db, draft, existing_record)
            metrics.increment('publishes_success')
            log_event(logging.INFO, 'moderation.approve', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
            log_event(logging.INFO, 'moderation.publish.success', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
            return published

        draft = update_draft(db, draft, changes={"publish_status": PUBLISH_STATUS_PENDING})
        try:
            created_record = create_airtable_feature(draft)
        except HTTPException as exc:
            logger.warning("Failed to publish draft %s to Airtable: %s", draft.id, exc.detail)
            metrics.increment('publishes_fail')
            log_event(logging.ERROR, 'moderation.publish.fail', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=draft.id, status_code=exc.status_code)
            if draft.publish_status != PUBLISH_STATUS_FAILED:
                draft = update_draft(db, draft, changes={"publish_status": PUBLISH_STATUS_FAILED})
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.exception("Unexpected publish failure for draft %s", draft.id)
            metrics.increment('publishes_fail')
            log_event(logging.ERROR, 'moderation.publish.fail', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=draft.id)
            if draft.publish_status != PUBLISH_STATUS_FAILED:
                update_draft(db, draft, changes={"publish_status": PUBLISH_STATUS_FAILED})
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Airtable publish failed") from exc

        published = _mark_draft_as_published(db, draft, created_record)
        metrics.increment('publishes_success')
        log_event(logging.INFO, 'moderation.approve', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
        log_event(logging.INFO, 'moderation.publish.success', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
        return published


def reject_draft(db: Session, draft: Draft) -> Draft:
    if draft.status == "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved draft cannot be rejected")
    if draft.status == "rejected":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft already rejected")
    if draft.status != "review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only drafts in review can be rejected")
    return update_draft(db, draft, changes={"status": "rejected"})


def create_airtable_feature(draft: Draft) -> dict[str, Any]:
    token, base_id, table_name = _get_airtable_config()
    url = _build_airtable_table_url(base_id, table_name)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"fields": build_airtable_fields(draft)}

    if requests is not None:
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
        except requests.RequestException as exc:  # type: ignore[attr-defined]
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Airtable request failed: network error") from exc
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


def find_existing_airtable_feature(draft: Draft) -> dict[str, Any] | None:
    if draft.airtable_record_id:
        return {"id": draft.airtable_record_id, "fields": build_airtable_fields(draft)}

    token, base_id, table_name = _get_airtable_config()
    external_id = get_draft_external_id(draft)
    formula = f"{{{AIRTABLE_EXTERNAL_ID_FIELD}}}='{_escape_airtable_formula_value(external_id)}'"
    url = _build_airtable_table_url(base_id, table_name)

    if requests is not None:
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"maxRecords": 1, "filterByFormula": formula},
                timeout=30,
            )
        except requests.RequestException as exc:  # type: ignore[attr-defined]
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Airtable request failed: network error") from exc
        if response.status_code >= 400:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Airtable request failed: {response.status_code}")
        records = response.json().get("records") or []
        return records[0] if records else None

    query = urllib.parse.urlencode({"maxRecords": 1, "filterByFormula": formula})
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Airtable request failed: {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Airtable request failed: network error") from exc

    records = payload.get("records") or []
    return records[0] if records else None


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
        AIRTABLE_EXTERNAL_ID_FIELD: get_draft_external_id(draft),
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


def get_draft_external_id(draft: Draft) -> str:
    return f"draft:{draft.id}"


def _mark_draft_as_published(db: Session, draft: Draft, airtable_record: dict[str, Any]) -> Draft:
    record_id = airtable_record.get("id")
    if not record_id:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Airtable publish failed: missing record id")
    published_at = draft.published_at or datetime.utcnow()
    return update_draft(
        db,
        draft,
        changes={
            "status": "approved",
            "publish_status": PUBLISH_STATUS_PUBLISHED,
            "airtable_record_id": record_id,
            "published_at": published_at,
        },
    )


def _get_airtable_config() -> tuple[str, str, str]:
    token = os.getenv("AIRTABLE_TOKEN")
    base_id = os.getenv("AIRTABLE_BASE") or os.getenv("AIRTABLE_BASE_ID")
    table_name = os.getenv("AIRTABLE_TABLE", DEFAULT_AIRTABLE_TABLE)

    if not token or not base_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Airtable is not configured",
        )
    return token, base_id, table_name


def _build_airtable_table_url(base_id: str, table_name: str) -> str:
    return f"{AIRTABLE_API_URL}/{base_id}/{urllib.parse.quote(table_name, safe='')}"


def _escape_airtable_formula_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


@contextmanager
def _draft_publish_lock(draft_id: int):
    with _publish_locks_guard:
        lock = _publish_locks.setdefault(draft_id, threading.Lock())
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _to_float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
