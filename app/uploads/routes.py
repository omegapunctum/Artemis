import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.service import User, get_current_user, get_db
from app.drafts.service import get_user_draft
from app.observability import internal_error_response, log_event
from app.security.rate_limit import rate_limit
from app.uploads.service import cleanup_orphan_uploads, save_draft_image, save_uploaded_file

router = APIRouter(prefix="/uploads", tags=["uploads"])


class UploadImageResponse(BaseModel):
    url: str


class UploadResponse(BaseModel):
    url: str
    width: int | None = None
    height: int | None = None
    license: str


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def upload_file(
    request: Request,
    file: UploadFile = File(...),
    license: str = Form(...),
    _: None = Depends(rate_limit(10, 60, prefix="upload-file", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    try:
        removed = cleanup_orphan_uploads(db)
        if removed:
            log_event(logging.INFO, 'upload.cleanup.orphans_removed', path=request.url.path, request_id=request.state.request_id, removed=removed)

        image_url, normalized_license = save_uploaded_file(current_user, file, license)
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'upload.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)

    return {"url": image_url, "width": None, "height": None, "license": normalized_license}


@router.post("/image", response_model=UploadImageResponse, status_code=status.HTTP_201_CREATED)
def upload_image(
    request: Request,
    draft_id: str = Form(...),
    file: UploadFile = File(...),
    _: None = Depends(rate_limit(10, 60, prefix="upload-image", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    draft = None
    try:
        removed = cleanup_orphan_uploads(db)
        if removed:
            log_event(logging.INFO, 'upload.cleanup.orphans_removed', path=request.url.path, request_id=request.state.request_id, removed=removed)

        if not draft_id.isdigit():
            log_event(logging.WARNING, 'upload.invalid_draft_id', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="draft_id must be a number")

        draft = get_user_draft(db, int(draft_id), current_user)
        image_url = save_draft_image(db, draft, current_user, file, request=request)
    except HTTPException as exc:
        message = 'upload.fail'
        if exc.detail == 'File too large':
            message = 'upload.file_too_large'
        elif exc.detail == 'Unsupported image type':
            message = 'upload.invalid_type'
        log_event(
            logging.WARNING,
            message,
            route=request.url.path,
            request_id=request.state.request_id,
            user_id=current_user.id,
            status_code=exc.status_code,
            draft_id=draft.id if draft else None,
        )
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'upload.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)

    log_event(logging.INFO, 'upload.success', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=draft.id)
    return {"url": image_url}
