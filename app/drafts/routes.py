import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.service import User, get_current_user, get_db
from app.drafts.schemas import DraftCreate, DraftResponse, DraftUpdate
from app.drafts.service import create_draft, delete_draft, get_user_draft, list_drafts, update_draft
from app.observability import log_event
from app.security.rate_limit import rate_limit

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("", response_model=list[DraftResponse])
def get_drafts(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    return list_drafts(db, current_user)


@router.post("", response_model=DraftResponse, status_code=status.HTTP_201_CREATED)
def create_draft_endpoint(
    payload: DraftCreate,
    request: Request,
    _: None = Depends(rate_limit(10, 60, prefix="draft-create", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    draft = create_draft(db, current_user, payload.title, payload.description, payload.geometry)
    log_event(logging.INFO, 'draft.create', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=draft.id)
    return draft


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
    draft = get_user_draft(db, draft_id, current_user)
    updated = update_draft(db, draft, changes=payload.model_dump(exclude_unset=True))
    log_event(logging.INFO, 'draft.update', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=updated.id)
    return updated


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft_endpoint(
    draft_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    draft = get_user_draft(db, draft_id, current_user)
    delete_draft(db, draft)
    log_event(logging.INFO, 'draft.delete', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=draft_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
