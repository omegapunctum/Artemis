from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Session

from app.auth.service import Base, User, engine


class Draft(Base):
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    geometry = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def list_drafts(db: Session, user: User) -> list[Draft]:
    return db.query(Draft).filter(Draft.user_id == user.id).order_by(Draft.updated_at.desc()).all()


def create_draft(db: Session, user: User, title: str, description: str, geometry: dict | None) -> Draft:
    draft = Draft(user_id=user.id, title=title, description=description, geometry=geometry)
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
) -> Draft:
    for field, value in changes.items():
        setattr(draft, field, value)
    db.commit()
    db.refresh(draft)
    return draft


def delete_draft(db: Session, draft: Draft) -> None:
    db.delete(draft)
    db.commit()
