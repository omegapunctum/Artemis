from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import require_moderator_or_admin
from ..database import get_db
from ..models import Draft, User
from ..schemas import DraftOut

router = APIRouter(tags=["moderation"])


@router.get("/pending", response_model=list[DraftOut])
def get_pending_drafts(
    db: Session = Depends(get_db),
    _: User = Depends(require_moderator_or_admin),
):
    return db.query(Draft).filter(Draft.status == "pending").all()


@router.post("/{draft_id}/approve", response_model=DraftOut)
def approve_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_moderator_or_admin),
):
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    draft.status = "approved"
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/{draft_id}/reject", response_model=DraftOut)
def reject_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_moderator_or_admin),
):
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    draft.status = "rejected"
    db.commit()
    db.refresh(draft)
    return draft
