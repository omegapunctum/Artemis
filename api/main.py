from fastapi import FastAPI

from .database import Base, engine
from .routes import auth, drafts, moderation

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ARTEMIS API")

app.include_router(auth.router, prefix="/api/auth")
app.include_router(drafts.router, prefix="/api/drafts")
app.include_router(moderation.router, prefix="/api/moderation")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
