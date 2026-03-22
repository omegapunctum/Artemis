from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.service import User, get_current_user, get_db
from app.drafts.service import get_user_draft
from app.uploads.service import save_draft_image

router = APIRouter(prefix="/uploads", tags=["uploads"])


class UploadImageResponse(BaseModel):
    url: str


@router.post("/image", response_model=UploadImageResponse, status_code=status.HTTP_201_CREATED)
def upload_image(
    draft_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not draft_id.isdigit():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="draft_id must be a number")

    draft = get_user_draft(db, int(draft_id), current_user)
    image_url = save_draft_image(db, draft, current_user, file)
    return {"url": image_url}
