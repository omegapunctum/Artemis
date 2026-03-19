from fastapi import Depends, FastAPI

from app.auth.routes import router as auth_router
from app.auth.schemas import UserResponse
from app.auth.service import User, get_current_user, init_db

init_db()

app = FastAPI(title="ARTEMIS Auth API")
app.include_router(auth_router)


@app.get("/")
def healthcheck():
    return {"status": "ok"}


@app.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email}
