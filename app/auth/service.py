from uuid import uuid4

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import Column, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .utils import (
    REFRESH_COOKIE_NAME,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

DATABASE_URL = "sqlite:///./artemis_auth.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
active_refresh_tokens: dict[str, str] = {}


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def register_user(db: Session, email: str, password: str) -> str:
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return create_access_token(user.id)


def login_user(db: Session, email: str, password: str) -> tuple[str, str]:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    active_refresh_tokens[decode_token(refresh_token, "refresh")["jti"]] = user.id
    return access_token, refresh_token


def rotate_refresh_token(refresh_token: str, db: Session) -> tuple[str, str]:
    payload = decode_token(refresh_token, "refresh")
    if active_refresh_tokens.get(payload["jti"]) != payload["user_id"]:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user:
        active_refresh_tokens.pop(payload["jti"], None)
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    active_refresh_tokens.pop(payload["jti"], None)
    new_refresh_token = create_refresh_token(user.id)
    active_refresh_tokens[decode_token(new_refresh_token, "refresh")["jti"]] = user.id
    return create_access_token(user.id), new_refresh_token


def logout_user(refresh_token: str | None) -> None:
    if refresh_token:
        try:
            payload = decode_token(refresh_token, "refresh")
            active_refresh_tokens.pop(payload["jti"], None)
        except ValueError:
            pass


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_token(token, "access")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc

    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    return user


def get_refresh_token(refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME)) -> str:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    return refresh_token
