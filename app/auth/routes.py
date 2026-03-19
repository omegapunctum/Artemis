from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.orm import Session

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
def register(payload: AuthCredentials, db: Session = Depends(get_db)):
    return {"access_token": register_user(db, payload.email, payload.password)}


@router.post("/login", response_model=AccessTokenResponse)
def login(payload: AuthCredentials, response: Response, db: Session = Depends(get_db)):
    access_token, refresh_token = login_user(db, payload.email, payload.password)
    set_refresh_cookie(response, refresh_token)
    return {"access_token": access_token}


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(
    response: Response,
    refresh_token: str = Depends(get_refresh_token),
    db: Session = Depends(get_db),
):
    access_token, new_refresh_token = rotate_refresh_token(refresh_token, db)
    set_refresh_cookie(response, new_refresh_token)
    return {"access_token": access_token}


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    logout_user(refresh_token)
    response.delete_cookie(key=REFRESH_COOKIE_NAME, httponly=True, secure=COOKIE_SECURE, samesite="strict")
    return {"message": "Logged out"}


