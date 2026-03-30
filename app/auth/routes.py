import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.observability import internal_error_response, log_event
from app.security.rate_limit import check_login_block, rate_limit, register_login_failure, reset_login_failures

from .schemas import AccessTokenResponse, AuthCredentials
from .service import (
    REFRESH_COOKIE_NAME,
    get_db,
    get_refresh_token,
    login_user,
    logout_user,
    register_user,
    rotate_refresh_token,
)
from .utils import COOKIE_SECURE, REFRESH_TOKEN_EXPIRE_DAYS

router = APIRouter(prefix="/auth", tags=["auth"])


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


@router.post("/register", response_model=AccessTokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: AuthCredentials,
    request: Request,
    _: None = Depends(rate_limit(3, 5 * 60, prefix="register")),
    db: Session = Depends(get_db),
):
    try:
        access_token = register_user(db, payload.email, payload.password)
        log_event(
            logging.INFO,
            'auth.register.success',
            route=request.url.path,
            request_id=request.state.request_id,
            email=payload.email,
        )
        return {"access_token": access_token}
    except HTTPException:
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'auth.register.error', path=request.url.path, request_id=request.state.request_id, error=str(exc))
        return internal_error_response(request)


@router.post("/login", response_model=AccessTokenResponse)
def login(
    payload: AuthCredentials,
    request: Request,
    response: Response,
    _: None = Depends(rate_limit(5, 60, prefix="login")),
    db: Session = Depends(get_db),
):
    check_login_block(request)
    try:
        access_token, refresh_token = login_user(db, payload.email, payload.password)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            register_login_failure(request, limit=5, window_seconds=60, block_seconds=60)
            log_event(
                logging.WARNING,
                'auth.login.fail',
                route=request.url.path,
                request_id=request.state.request_id,
                email=payload.email,
                status_code=exc.status_code,
            )
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'auth.login.error', path=request.url.path, request_id=request.state.request_id, error=str(exc))
        return internal_error_response(request)

    reset_login_failures(request)
    set_refresh_cookie(response, refresh_token)
    log_event(
        logging.INFO,
        'auth.login.success',
        route=request.url.path,
        request_id=request.state.request_id,
        user_id=request.state.user_id if hasattr(request.state, 'user_id') else None,
        email=payload.email,
    )
    return {"access_token": access_token}


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(
    request: Request,
    response: Response,
    _: None = Depends(rate_limit(10, 60, prefix="refresh")),
    refresh_token: str = Depends(get_refresh_token),
    db: Session = Depends(get_db),
):
    try:
        access_token, new_refresh_token = rotate_refresh_token(refresh_token, db)
    except HTTPException as exc:
        log_event(
            logging.WARNING,
            'auth.refresh.fail',
            route=request.url.path,
            request_id=request.state.request_id,
            status_code=exc.status_code,
        )
        raise
    except Exception as exc:
        log_event(logging.ERROR, 'auth.refresh.error', path=request.url.path, request_id=request.state.request_id, error=str(exc))
        return internal_error_response(request)
    set_refresh_cookie(response, new_refresh_token)
    log_event(logging.INFO, 'auth.refresh.success', route=request.url.path, request_id=request.state.request_id)
    return {"access_token": access_token}


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    logout_user(refresh_token)
    response.delete_cookie(key=REFRESH_COOKIE_NAME, httponly=True, secure=COOKIE_SECURE, samesite="strict")
    log_event(logging.INFO, 'auth.logout', route=request.url.path, request_id=request.state.request_id)
    return {"message": "Logged out"}
