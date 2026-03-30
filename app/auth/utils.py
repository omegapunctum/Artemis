import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# Русский комментарий: секрет вшитым значением не используем — только env или временный ключ для dev.
_SECRET_FROM_ENV = os.getenv("AUTH_SECRET_KEY")
if _SECRET_FROM_ENV:
    SECRET_KEY = _SECRET_FROM_ENV
else:
    SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning("AUTH_SECRET_KEY is not set. Generated ephemeral key for current process only.")

ALGORITHM = os.getenv("AUTH_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "refresh_token")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = (os.getenv("APP_ENV") or os.getenv("ENV") or "development").strip().lower()
COOKIE_HTTPONLY = _env_bool("COOKIE_HTTPONLY", True)
COOKIE_SECURE = _env_bool("COOKIE_SECURE", APP_ENV == "production")
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None
COOKIE_PATH = os.getenv("COOKIE_PATH", "/")
REFRESH_COOKIE_MAX_AGE = int(os.getenv("REFRESH_COOKIE_MAX_AGE", str(REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60)))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _create_token(user_id: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "type": token_type,
        "exp": now + expires_delta,
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _create_token(user_id, "access", timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, "refresh", timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc

    if payload.get("type") != expected_type or not payload.get("user_id") or not payload.get("jti"):
        raise ValueError("Invalid token")
    return payload
