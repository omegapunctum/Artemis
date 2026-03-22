from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.auth.routes import router as auth_router
from app.auth.schemas import UserResponse
from app.auth.service import User, get_current_user, init_db as init_auth_db
from app.drafts.routes import router as drafts_router
from app.drafts.service import init_db as init_drafts_db
from app.moderation.routes import router as moderation_router
from app.observability import (
    ObservabilityMiddleware,
    health_payload,
    http_exception_handler,
    setup_logging,
    unhandled_exception_handler,
)
from app.uploads.routes import router as uploads_router

setup_logging()
init_auth_db()
init_drafts_db()

UPLOADS_DIR = "uploads"
Path(UPLOADS_DIR).mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ARTEMIS API")
app.add_middleware(ObservabilityMiddleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.include_router(auth_router)
app.include_router(drafts_router)
app.include_router(uploads_router)
app.include_router(moderation_router)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


@app.get("/")
def healthcheck():
    return {"status": "ok"}


@app.get("/health")
def health():
    return health_payload()


@app.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email, "is_admin": bool(current_user.is_admin)}
