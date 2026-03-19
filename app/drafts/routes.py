from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.auth.service import User, get_current_user, get_db
from app.drafts.schemas import DraftCreate, DraftResponse, DraftUpdate
from app.drafts.service import (
    create_draft,
    delete_draft,
    get_user_draft,
    list_drafts,
    update_draft,
)

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("", response_model=list[DraftResponse])
def get_drafts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_drafts(db, current_user)


@router.post("", response_model=DraftResponse, status_code=status.HTTP_201_CREATED)
def create_draft_endpoint(
    payload: DraftCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return create_draft(db, current_user, payload.title, payload.description, payload.geometry)


@router.put("/{draft_id}", response_model=DraftResponse)
def update_draft_endpoint(
    draft_id: int,
    payload: DraftUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    draft = get_user_draft(db, draft_id, current_user)
    return update_draft(db, draft, changes=payload.model_dump(exclude_unset=True))


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft_endpoint(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    draft = get_user_draft(db, draft_id, current_user)
    delete_draft(db, draft)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
