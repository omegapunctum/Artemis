import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.service import User, get_current_user, get_db
from app.drafts.schemas import DraftCreate, DraftResponse, DraftUpdate
from app.drafts.service import create_draft, delete_draft, get_user_draft, list_drafts, update_draft
from app.observability import internal_error_response, log_event
from app.security.rate_limit import rate_limit

router = APIRouter(prefix="/drafts", tags=["drafts"])


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
        draft = create_draft(db, current_user, payload.title, payload.description, payload.geometry)
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
        updated = update_draft(db, draft, changes=payload.model_dump(exclude_unset=True))
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
