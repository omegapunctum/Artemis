import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.service import User, get_current_user, get_db
from app.drafts.schemas import DraftCreate, DraftResponse, DraftUpdate
from app.drafts.service import Draft, create_draft, delete_draft, get_user_draft, list_drafts, update_draft
from app.observability import internal_error_response, log_event
from app.security.rate_limit import rate_limit
from app.uploads.service import cleanup_unreferenced_upload_urls, collect_draft_upload_urls

router = APIRouter(prefix="/drafts", tags=["drafts"])


def normalize_status_for_ui(status_value: str | None) -> str:
    normalized = str(status_value or "draft").lower()
    if normalized == "review":
        return "pending"
    if normalized in {"draft", "pending", "approved", "rejected"}:
        return normalized
    return "draft"


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_coordinates(payload: dict[str, Any], geometry: dict[str, Any] | None) -> tuple[float | None, float | None]:
    lon = _to_float(payload.get("longitude"))
    lat = _to_float(payload.get("latitude"))

    coords = payload.get("coords")
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        lon = _to_float(coords[0]) if lon is None else lon
        lat = _to_float(coords[1]) if lat is None else lat

    if (lon is None or lat is None) and isinstance(geometry, dict) and geometry.get("type") == "Point":
        raw_coords = geometry.get("coordinates")
        if isinstance(raw_coords, (list, tuple)) and len(raw_coords) >= 2:
            lon = _to_float(raw_coords[0]) if lon is None else lon
            lat = _to_float(raw_coords[1]) if lat is None else lat

    return lon, lat


def build_point_geometry(payload: dict[str, Any], fallback_geometry: dict[str, Any] | None) -> dict[str, Any] | None:
    if isinstance(fallback_geometry, dict):
        return fallback_geometry
    lon, lat = extract_coordinates(payload, fallback_geometry)
    if lon is None or lat is None:
        return fallback_geometry
    return {"type": "Point", "coordinates": [lon, lat]}


def _serialize_draft_payload(changes: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in changes.items():
        if value is None:
            serialized[key] = None
        elif key in {"source_url", "image_url"}:
            serialized[key] = str(value)
        else:
            serialized[key] = value

    lon, lat = extract_coordinates(serialized, serialized.get("geometry"))
    if lon is not None and lat is not None:
        serialized["longitude"] = lon
        serialized["latitude"] = lat
        serialized["coords"] = [lon, lat]
    return serialized


def serialize_draft_for_ui(draft: Draft) -> dict[str, Any]:
    payload = dict(draft.payload or {})
    geometry = draft.geometry if isinstance(draft.geometry, dict) else None
    lon, lat = extract_coordinates(payload, geometry)

    if lon is not None and lat is not None:
        payload["longitude"] = lon
        payload["latitude"] = lat
        payload["coords"] = [lon, lat]

    image_url = payload.get("image_url") if payload.get("image_url") is not None else draft.image_url
    name_ru = payload.get("name_ru") or draft.title
    description = payload.get("description") if "description" in payload else draft.description

    return {
        "id": draft.id,
        "title": draft.title,
        "description": description,
        "geometry": geometry,
        "image_url": image_url,
        "payload": payload,
        "status": normalize_status_for_ui(draft.status),
        "publish_status": draft.publish_status,
        "airtable_record_id": draft.airtable_record_id,
        "published_at": draft.published_at,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "name_ru": name_ru,
        "name_en": payload.get("name_en"),
        "layer_id": payload.get("layer_id"),
        "layer_type": payload.get("layer_type"),
        "date_start": payload.get("date_start"),
        "date_end": payload.get("date_end"),
        "longitude": lon,
        "latitude": lat,
        "coords": [lon, lat] if lon is not None and lat is not None else None,
        "coordinates_confidence": payload.get("coordinates_confidence"),
        "title_short": payload.get("title_short"),
        "source_url": payload.get("source_url"),
        "tags": payload.get("tags"),
    }


@router.get("/my", response_model=list[DraftResponse])
def get_my_drafts(
    request: Request,
    _: None = Depends(rate_limit(60, 60, prefix="draft-list-my", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_drafts(request=request, _=None, db=db, current_user=current_user)


@router.get("", response_model=list[DraftResponse])
def get_drafts(
    request: Request,
    _: None = Depends(rate_limit(60, 60, prefix="draft-list", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    try:
        return [serialize_draft_for_ui(item) for item in list_drafts(db, current_user)]
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'draft.list.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)


@router.post("", response_model=DraftResponse, status_code=status.HTTP_201_CREATED)
def create_draft_endpoint(
    payload: DraftCreate,
    request: Request,
    _: None = Depends(rate_limit(10, 60, prefix="draft-create", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    try:
        draft_payload = _serialize_draft_payload(payload.model_dump())
        geometry = build_point_geometry(draft_payload, payload.geometry)
        draft = create_draft(
            db,
            current_user,
            payload.name_ru,
            payload.description or "",
            geometry,
            payload.image_url.unicode_string() if payload.image_url else None,
            payload=draft_payload,
        )
        log_event(logging.INFO, 'draft.create', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=draft.id)
        return serialize_draft_for_ui(draft)
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'draft.create.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)


@router.put("/{draft_id}", response_model=DraftResponse)
def update_draft_endpoint(
    draft_id: int,
    payload: DraftUpdate,
    request: Request,
    _: None = Depends(rate_limit(20, 60, prefix="draft-update", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    try:
        draft = get_user_draft(db, draft_id, current_user)
        previous_upload_urls = collect_draft_upload_urls(draft)
        payload_changes = _serialize_draft_payload(payload.model_dump(exclude_unset=True))
        requested_status = payload_changes.pop("status", None)

        merged_payload = {**(draft.payload or {}), **payload_changes}
        storage_changes: dict[str, Any] = {"payload": merged_payload}
        if "name_ru" in payload_changes:
            storage_changes["title"] = payload_changes["name_ru"]
        if "description" in payload_changes:
            storage_changes["description"] = payload_changes["description"]
        if "image_url" in payload_changes:
            storage_changes["image_url"] = payload_changes["image_url"]

        geometry_candidate = build_point_geometry(merged_payload, payload_changes.get("geometry") or draft.geometry)
        if geometry_candidate is not None:
            storage_changes["geometry"] = geometry_candidate

        allow_system_fields = False
        if requested_status == "pending":
            if draft.status not in {"draft", "rejected", "pending", "review"}:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft cannot be submitted in current status")
            storage_changes["status"] = "pending"
            storage_changes["publish_status"] = "pending"
            allow_system_fields = True

        updated = update_draft(db, draft, changes=storage_changes, allow_system_fields=allow_system_fields)
        updated_upload_urls = collect_draft_upload_urls(updated)
        cleanup_unreferenced_upload_urls(db, previous_upload_urls - updated_upload_urls)
        log_event(logging.INFO, 'draft.update', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=updated.id)
        return serialize_draft_for_ui(updated)
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'draft.update.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft_endpoint(
    draft_id: int,
    request: Request,
    _: None = Depends(rate_limit(30, 60, prefix="draft-delete", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    try:
        draft = get_user_draft(db, draft_id, current_user)
        upload_urls = collect_draft_upload_urls(draft)
        delete_draft(db, draft)
        cleanup_unreferenced_upload_urls(db, upload_urls)
        log_event(logging.INFO, 'draft.delete', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=draft_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'draft.delete.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)
