from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.service import User
from app.drafts.service import Draft, update_draft

MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/jpg": ".jpg",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
UPLOADS_ROOT = Path("uploads")


def save_draft_image(db: Session, draft: Draft, user: User, file: UploadFile, request=None) -> str:
    extension = ALLOWED_CONTENT_TYPES.get(file.content_type)
    if extension is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported image type")

    content = file.file.read(MAX_IMAGE_SIZE_BYTES + 1)
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File too large")
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")

    user_directory = UPLOADS_ROOT / user.id
    user_directory.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid4()}{extension}"
    destination = user_directory / filename
    if destination.exists():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to allocate file name")

    destination.write_bytes(content)

    image_url = f"/uploads/{user.id}/{filename}"
    update_draft(db, draft, changes={"image_url": image_url})
    return image_url
