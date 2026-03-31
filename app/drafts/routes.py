import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.service import User, get_current_user, get_db
from app.drafts.schemas import DraftCreate, DraftResponse, DraftUpdate
from app.drafts.service import create_draft, delete_draft, get_user_draft, list_drafts, update_draft
from app.observability import internal_error_response, log_event
from app.security.rate_limit import rate_limit

router = APIRouter(prefix="/drafts", tags=["drafts"])


def _serialize_draft_payload(changes: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in changes.items():
        if value is None:
            serialized[key] = None
        elif key in {"source_url", "image_url"}:
            serialized[key] = str(value)
        else:
            serialized[key] = value
    return serialized


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
        return list_drafts(db, current_user)
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
        draft = create_draft(
            db,
            current_user,
            payload.name_ru,
            payload.description or "",
            payload.geometry,
            payload.image_url.unicode_string() if payload.image_url else None,
            payload=draft_payload,
        )
        log_event(logging.INFO, 'draft.create', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=draft.id)
        return draft
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
        payload_changes = _serialize_draft_payload(payload.model_dump(exclude_unset=True))
        storage_changes = {"payload": {**(draft.payload or {}), **payload_changes}}
        if "name_ru" in payload_changes:
            storage_changes["title"] = payload_changes["name_ru"]
        if "description" in payload_changes:
            storage_changes["description"] = payload_changes["description"]
        if "geometry" in payload_changes:
            storage_changes["geometry"] = payload_changes["geometry"]
        if "image_url" in payload_changes:
            storage_changes["image_url"] = payload_changes["image_url"]
        updated = update_draft(db, draft, changes=storage_changes)
        log_event(logging.INFO, 'draft.update', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=updated.id)
        return updated
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
        delete_draft(db, draft)
        log_event(logging.INFO, 'draft.delete', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=draft_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'draft.delete.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)
