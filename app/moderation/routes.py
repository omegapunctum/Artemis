import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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
from app.observability import internal_error_response, log_event
from app.security.rate_limit import rate_limit

router = APIRouter(tags=["moderation"])


@router.post("/drafts/{draft_id}/submit", response_model=DraftResponse)
def submit_draft_endpoint(
    draft_id: int,
    request: Request,
    _: None = Depends(rate_limit(10, 60, prefix="moderation-submit", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    try:
        draft = get_user_draft(db, draft_id, current_user)
        submitted = submit_draft_for_review(db, draft)
        log_event(logging.INFO, 'draft.submit_review', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=submitted.id)
        return submitted
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'draft.submit_review.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)


@router.get("/moderation/queue", response_model=list[DraftResponse])
def moderation_queue(
    request: Request,
    _: None = Depends(rate_limit(30, 60, prefix="moderation-queue", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    try:
        require_moderator(current_user)
        drafts = list_review_drafts(db)
        log_event(logging.INFO, 'moderation.queue.opened', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, queued_items=len(drafts))
        return drafts
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'moderation.queue.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)


@router.post("/moderation/{draft_id}/approve", response_model=DraftResponse)
def approve_draft_endpoint(
    draft_id: int,
    request: Request,
    response: Response,
    _: None = Depends(rate_limit(20, 60, prefix="moderation-approve", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    try:
        require_moderator(current_user)
        draft = get_draft_for_moderation(db, draft_id)
        result_context: dict[str, str] = {}
        approved = approve_draft(db, draft, request=request, moderator=current_user, result_context=result_context)
        if result_context.get("result"):
            response.headers["X-Moderation-Result"] = result_context["result"]
        return approved
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'moderation.approve.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)


@router.post("/moderation/{draft_id}/reject", response_model=DraftResponse)
def reject_draft_endpoint(
    draft_id: int,
    request: Request,
    _: None = Depends(rate_limit(20, 60, prefix="moderation-reject", include_path=True)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request.state.user_id = current_user.id
    try:
        require_moderator(current_user)
        draft = get_draft_for_moderation(db, draft_id)
        rejected = reject_draft(db, draft)
        log_event(logging.INFO, 'moderation.reject', route=request.url.path, request_id=request.state.request_id, user_id=current_user.id, draft_id=rejected.id)
        return rejected
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'moderation.reject.error', path=request.url.path, request_id=request.state.request_id, user_id=current_user.id, error=str(exc))
        return internal_error_response(request)
