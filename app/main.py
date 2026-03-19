from fastapi import Depends, FastAPI

from app.auth.routes import router as auth_router
from app.auth.schemas import UserResponse
from app.auth.service import User, get_current_user, init_db as init_auth_db
from app.drafts.routes import router as drafts_router
from app.drafts.service import init_db as init_drafts_db

init_auth_db()
init_drafts_db()

app = FastAPI(title="ARTEMIS API")
app.include_router(auth_router)
app.include_router(drafts_router)


@app.get("/")
def healthcheck():
    return {"status": "ok"}


@app.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email}
