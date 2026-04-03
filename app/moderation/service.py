import json
import hashlib
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
from app.url_validation import is_safe_url

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
DEFAULT_COORDINATES_SOURCE = "expert estimate"
DEFAULT_SOURCE_URL = "https://ugc.local/source"
DEFAULT_SOURCE_LICENSE = "CC BY"
AIRTABLE_EXTERNAL_ID_FIELD = os.getenv("AIRTABLE_EXTERNAL_ID_FIELD", "external_id")
AIRTABLE_NORMALIZED_ID_FIELD = "normalized_id"
AIRTABLE_SOURCE_DRAFT_ID_FIELD = "source_draft_id"
PUBLISH_STATUS_PENDING = "pending"
PUBLISH_STATUS_PUBLISHED = "published"
PUBLISH_STATUS_FAILED = "failed"

logger = logging.getLogger(__name__)
_publish_locks: dict[int, threading.Lock] = {}
_publish_locks_guard = threading.Lock()


def normalize_coordinates_source(value: Any) -> str:
    raw = str(value).strip() if value is not None else ""
    if not raw:
        return DEFAULT_COORDINATES_SOURCE

    aliases = {
        "ugc": "expert estimate",
    }
    return aliases.get(raw.lower(), raw)


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
    return db.query(Draft).filter(Draft.status.in_(["pending", "review"])).order_by(Draft.updated_at.asc()).all()


def get_draft_for_moderation(db: Session, draft_id: int) -> Draft:
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return draft


def submit_draft_for_review(db: Session, draft: Draft) -> Draft:
    if draft.status == "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved draft cannot be resubmitted")
    if draft.status in {"pending", "review"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft already in review")
    return update_draft(db, draft, allow_system_fields=True, changes={"status": "pending", "publish_status": PUBLISH_STATUS_PENDING})


def approve_draft(
    db: Session,
    draft: Draft,
    request: Request | None = None,
    moderator: User | None = None,
    result_context: dict[str, str] | None = None,
) -> Draft:
    logger.info("APPROVE: draft_id=%s", draft.id)
    with _draft_publish_lock(draft.id):
        db.refresh(draft)

        if draft.airtable_record_id and draft.publish_status == PUBLISH_STATUS_PUBLISHED:
            if draft.status != "approved":
                published = update_draft(
                    db,
                    draft,
                    allow_system_fields=True,
                    changes={
                        "status": "approved",
                        "published_at": draft.published_at or datetime.utcnow(),
                    },
                )
                logger.info("UPDATE: existing feature refreshed for draft_id=%s", published.id)
                _set_approve_result(result_context, "approved_already_published")
                metrics.increment('publishes_success')
                log_event(logging.INFO, 'moderation.approve', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
                log_event(logging.INFO, 'moderation.publish.success', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
                return published
            logger.info("SKIP: duplicate publish for draft_id=%s", draft.id)
            _set_approve_result(result_context, "approved_already_published")
            return draft

        if draft.status not in {"pending", "review", "approved"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only drafts in pending or approved can be published")

        airtable_fields = build_airtable_fields(draft)
        existing_record = find_existing_airtable_feature(draft, fields=airtable_fields)
        if existing_record:
            published = _mark_draft_as_published(db, draft, existing_record)
            logger.info("SKIP: duplicate publish for draft_id=%s", published.id)
            _set_approve_result(result_context, "published_skipped_duplicate")
            metrics.increment('publishes_success')
            log_event(logging.INFO, 'moderation.publish.skipped_duplicate', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
            log_event(logging.INFO, 'moderation.approve', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
            log_event(logging.INFO, 'moderation.publish.success', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
            return published

        draft = update_draft(db, draft, allow_system_fields=True, changes={"publish_status": PUBLISH_STATUS_PENDING})
        try:
            created_record = create_airtable_feature(draft, fields=airtable_fields)
        except HTTPException as exc:
            logger.warning("Failed to publish draft %s to Airtable: %s", draft.id, exc.detail)
            metrics.increment('publishes_fail')
            log_event(logging.ERROR, 'moderation.publish.fail', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=draft.id, status_code=exc.status_code)
            if draft.publish_status != PUBLISH_STATUS_FAILED:
                draft = update_draft(db, draft, allow_system_fields=True, changes={"publish_status": PUBLISH_STATUS_FAILED})
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.exception("Unexpected publish failure for draft %s", draft.id)
            metrics.increment('publishes_fail')
            log_event(logging.ERROR, 'moderation.publish.fail', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=draft.id)
            if draft.publish_status != PUBLISH_STATUS_FAILED:
                update_draft(db, draft, allow_system_fields=True, changes={"publish_status": PUBLISH_STATUS_FAILED})
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Airtable publish failed") from exc

        published = _mark_draft_as_published(db, draft, created_record)
        logger.info("PUBLISH: created feature for draft_id=%s", published.id)
        _set_approve_result(result_context, "published_created")
        metrics.increment('publishes_success')
        log_event(logging.INFO, 'moderation.approve', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
        log_event(logging.INFO, 'moderation.publish.success', route=request.url.path if request else None, request_id=getattr(getattr(request, 'state', None), 'request_id', None), user_id=getattr(moderator, 'id', None), draft_id=published.id)
        return published


def reject_draft(db: Session, draft: Draft) -> Draft:
    if draft.status == "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved draft cannot be rejected")
    if draft.status == "rejected":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft already rejected")
    if draft.status not in {"pending", "review"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only drafts in pending can be rejected")
    return update_draft(db, draft, allow_system_fields=True, changes={"status": "rejected"})


def create_airtable_feature(draft: Draft, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    token, base_id, table_name = _get_airtable_config()
    url = _build_airtable_table_url(base_id, table_name)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"fields": fields or build_airtable_fields(draft)}

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


def find_existing_airtable_feature(draft: Draft, fields: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if draft.airtable_record_id:
        return {"id": draft.airtable_record_id, "fields": build_airtable_fields(draft)}

    token, base_id, table_name = _get_airtable_config()
    resolved_fields = fields or build_airtable_fields(draft)
    external_id = get_draft_external_id(draft)
    normalized_id = resolved_fields.get(AIRTABLE_NORMALIZED_ID_FIELD)
    url = _build_airtable_table_url(base_id, table_name)

    # Canonical publish identity contract:
    # 1) normalized_id is the primary identity for publish idempotency.
    # 2) external/source ids are source references and backward-compatible fallbacks.
    if normalized_id:
        normalized_formula = f"{{{AIRTABLE_NORMALIZED_ID_FIELD}}}='{_escape_airtable_formula_value(str(normalized_id))}'"
        by_normalized_id = _find_airtable_record_by_formula(url, token, normalized_formula)
        if by_normalized_id:
            return by_normalized_id

    external_formula = f"{{{AIRTABLE_EXTERNAL_ID_FIELD}}}='{_escape_airtable_formula_value(external_id)}'"
    by_external_id = _find_airtable_record_by_formula(url, token, external_formula)
    if by_external_id:
        return by_external_id

    return None


def _find_airtable_record_by_formula(url: str, token: str, formula: str) -> dict[str, Any] | None:
    if not formula:
        return None

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
    draft_payload = draft.payload or {}
    longitude = _to_float_or_none(draft_payload.get("longitude"))
    latitude = _to_float_or_none(draft_payload.get("latitude"))
    geometry = draft.geometry or {}
    if (longitude is None or latitude is None) and geometry.get("type") == "Point":
        coordinates = geometry.get("coordinates") or []
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            longitude = longitude if longitude is not None else _to_float_or_none(coordinates[0])
            latitude = latitude if latitude is not None else _to_float_or_none(coordinates[1])

    raw_image_url = draft_payload.get("image_url") if "image_url" in draft_payload else draft.image_url
    image_url = raw_image_url if is_safe_url(raw_image_url) else None
    raw_source_url = draft_payload.get("source_url")
    source_url = raw_source_url if is_safe_url(raw_source_url) else DEFAULT_SOURCE_URL
    normalized_id = build_normalized_id(source_url, draft_payload.get("name_ru") or draft.title, latitude, longitude)

    fields: dict[str, Any] = {
        AIRTABLE_EXTERNAL_ID_FIELD: get_draft_external_id(draft),
        AIRTABLE_SOURCE_DRAFT_ID_FIELD: get_draft_external_id(draft),
        AIRTABLE_NORMALIZED_ID_FIELD: normalized_id,
        "name_ru": draft_payload.get("name_ru") or draft.title,
        "description": draft_payload.get("description") if "description" in draft_payload else draft.description,
        "image_url": image_url,
        "source_url": source_url,
        "source_license": draft_payload.get("source_license") or DEFAULT_SOURCE_LICENSE,
        "layer_id": DEFAULT_LAYER_ID,
        "layer_type": draft_payload.get("layer_type") or DEFAULT_LAYER_TYPE,
        "coordinates_confidence": draft_payload.get("coordinates_confidence") or DEFAULT_COORDINATES_CONFIDENCE,
        "coordinates_source": normalize_coordinates_source(draft_payload.get("coordinates_source")),
        "name_en": draft_payload.get("name_en"),
        "date_start": draft_payload.get("date_start"),
        "date_end": None,
        "influence_radius_km": draft_payload.get("influence_radius_km"),
        "sequence_order": draft_payload.get("sequence_order"),
        "title_short": draft_payload.get("title_short") or draft.title,
        "tags": draft_payload.get("tags"),
        "is_active": True,
        "latitude": latitude,
        "longitude": longitude,
    }
    return fields


def build_normalized_id(source_url: str | None, title: str | None, latitude: float | None, longitude: float | None) -> str:
    raw = f"{source_url or ''}|{title or ''}|{latitude if latitude is not None else ''}|{longitude if longitude is not None else ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
        allow_system_fields=True,
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


def _set_approve_result(result_context: dict[str, str] | None, result: str) -> None:
    if result_context is not None:
        result_context["result"] = result
