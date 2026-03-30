from pathlib import Path
import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
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
    log_event,
    internal_error_response,
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

allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

for router in (auth_router, drafts_router, uploads_router, moderation_router):
    app.include_router(router, prefix="/api")

app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


@app.get("/api/health")
def health(request: Request):
    try:
        return health_payload()
    except Exception as exc:
        log_event(logging.ERROR, 'health.error', path=request.url.path, request_id=getattr(request.state, 'request_id', None), error=str(exc))
        return internal_error_response(request)


@app.get("/api/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email, "is_admin": bool(current_user.is_admin)}
