from uuid import uuid4

from app.auth.service import SessionLocal, User, init_db
from app.auth.utils import hash_password
from app.drafts.service import Draft, create_draft, init_db as init_drafts_db
from app.uploads import service as uploads_service


def _create_user(db) -> User:
    user = User(email=f"uploads-core-{uuid4().hex}@example.com", password_hash=hash_password("password123"), is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_collect_draft_upload_urls_reads_storage_and_payload():
    init_db()
    init_drafts_db()
    db = SessionLocal()
    db.query(Draft).delete()
    db.query(User).delete()
    db.commit()

    user = _create_user(db)
    draft = create_draft(
        db,
        user,
        "Draft title",
        "Draft description",
        None,
        image_url=f"/uploads/{user.id}/storage.png",
        payload={"name_ru": "Draft title", "image_url": f"/uploads/{user.id}/payload.png"},
    )

    urls = uploads_service.collect_draft_upload_urls(draft)
    assert urls == {f"/uploads/{user.id}/storage.png", f"/uploads/{user.id}/payload.png"}
    db.close()
