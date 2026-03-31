from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Session

from app.auth.service import Base, User, engine




EDITABLE_STATUSES = {"draft", "rejected"}

class Draft(Base):
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    geometry = Column(JSON, nullable=True)
    image_url = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="draft")
    publish_status = Column(String, nullable=False, default="pending")
    airtable_record_id = Column(String, nullable=True, unique=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(drafts)"))}
        if "image_url" not in columns:
            connection.execute(text("ALTER TABLE drafts ADD COLUMN image_url VARCHAR"))
        if "status" not in columns:
            connection.execute(text("ALTER TABLE drafts ADD COLUMN status VARCHAR DEFAULT 'draft'"))
        if "publish_status" not in columns:
            connection.execute(text("ALTER TABLE drafts ADD COLUMN publish_status VARCHAR DEFAULT 'pending'"))
        if "airtable_record_id" not in columns:
            connection.execute(text("ALTER TABLE drafts ADD COLUMN airtable_record_id VARCHAR"))
        if "published_at" not in columns:
            connection.execute(text("ALTER TABLE drafts ADD COLUMN published_at DATETIME"))
        if "payload" not in columns:
            connection.execute(text("ALTER TABLE drafts ADD COLUMN payload JSON"))


def list_drafts(db: Session, user: User) -> list[Draft]:
    return db.query(Draft).filter(Draft.user_id == user.id).order_by(Draft.updated_at.desc()).all()


def create_draft(
    db: Session,
    user: User,
    title: str,
    description: str,
    geometry: dict | None,
    image_url: str | None = None,
    payload: dict | None = None,
) -> Draft:
    draft = Draft(
        user_id=user.id,
        title=title,
        description=description,
        geometry=geometry,
        image_url=image_url,
        payload=payload or {},
        status="draft",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def get_user_draft(db: Session, draft_id: int, user: User) -> Draft:
    draft = db.query(Draft).filter(Draft.id == draft_id, Draft.user_id == user.id).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return draft


def update_draft(
    db: Session,
    draft: Draft,
    *,
    changes: dict,
    allow_system_fields: bool = False,
) -> Draft:
    # Русский комментарий: после публикации черновик должен быть read-only.
    if draft.publish_status == "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Published draft is read-only")

    # Русский комментарий: обычный пользователь не может вручную менять служебные статусы.
    if not allow_system_fields:
        blocked_fields = {"status", "publish_status", "airtable_record_id", "published_at", "user_id", "id", "created_at", "updated_at"}
        forbidden_fields = sorted(field for field in blocked_fields if field in changes)
        if forbidden_fields:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"forbidden fields in payload: {', '.join(forbidden_fields)}",
            )

        if draft.status not in EDITABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft is not editable in current status")

    for field, value in changes.items():
        setattr(draft, field, value)
    db.commit()
    db.refresh(draft)
    return draft


def delete_draft(db: Session, draft: Draft) -> None:
    db.delete(draft)
    db.commit()
