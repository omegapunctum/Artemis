import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.service import User, get_current_user, get_db
from app.drafts.schemas import DraftResponse
from app.drafts.service import get_user_draft
from app.moderation.service import (
    approve_draft,
    get_draft_for_moderation,
    list_review_drafts,
    reject_draft,
    require_moderator,
    submit_draft_for_review,
)
from app.observability import log_event

router = APIRouter(tags=["moderation"])


@router.post("/drafts/{draft_id}/submit", response_model=DraftResponse)
def submit_draft_endpoint(
    draft_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    draft = get_user_draft(db, draft_id, current_user)
    submitted = submit_draft_for_review(db, draft)
    log_event(logging.INFO, 'draft.submit_review', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=submitted.id)
    return submitted


@router.get("/moderation/queue", response_model=list[DraftResponse])
def moderation_queue(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    require_moderator(current_user)
    drafts = list_review_drafts(db)
    log_event(logging.INFO, 'moderation.queue.opened', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, queued_items=len(drafts))
    return drafts


@router.post("/moderation/{draft_id}/approve", response_model=DraftResponse)
def approve_draft_endpoint(
    draft_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    require_moderator(current_user)
    draft = get_draft_for_moderation(db, draft_id)
    approved = approve_draft(db, draft, request=request, moderator=current_user)
    return approved


@router.post("/moderation/{draft_id}/reject", response_model=DraftResponse)
def reject_draft_endpoint(
    draft_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    require_moderator(current_user)
    draft = get_draft_for_moderation(db, draft_id)
    rejected = reject_draft(db, draft)
    log_event(logging.INFO, 'moderation.reject', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=rejected.id)
    return rejected
