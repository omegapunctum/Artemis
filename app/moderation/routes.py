from fastapi import APIRouter, Depends
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

router = APIRouter(tags=["moderation"])


@router.post("/drafts/{draft_id}/submit", response_model=DraftResponse)
def submit_draft_endpoint(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    draft = get_user_draft(db, draft_id, current_user)
    return submit_draft_for_review(db, draft)


@router.get("/moderation/queue", response_model=list[DraftResponse])
def moderation_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_moderator(current_user)
    return list_review_drafts(db)


@router.post("/moderation/{draft_id}/approve", response_model=DraftResponse)
def approve_draft_endpoint(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_moderator(current_user)
    draft = get_draft_for_moderation(db, draft_id)
    return approve_draft(db, draft)


@router.post("/moderation/{draft_id}/reject", response_model=DraftResponse)
def reject_draft_endpoint(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_moderator(current_user)
    draft = get_draft_for_moderation(db, draft_id)
    return reject_draft(db, draft)
