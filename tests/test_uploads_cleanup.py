import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.auth.service import SessionLocal, User, init_db
from app.auth.utils import hash_password
from app.drafts.service import Draft, create_draft, init_db as init_drafts_db, update_draft
from app.uploads import service as uploads_service


def _create_user(db) -> User:
    user = User(email=f"uploads-{uuid4().hex}@example.com", password_hash=hash_password("password123"), is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_cleanup_orphan_uploads_removes_expired_orphans_and_keeps_active(monkeypatch, tmp_path):
    init_db()
    init_drafts_db()
    db = SessionLocal()
    db.query(Draft).delete()
    db.query(User).delete()
    db.commit()

    monkeypatch.setattr(uploads_service, "UPLOADS_ROOT", tmp_path)
    user = _create_user(db)
    user_directory = tmp_path / user.id
    user_directory.mkdir(parents=True, exist_ok=True)

    orphan = user_directory / "orphan.png"
    orphan.write_bytes(b"orphan")

    active = user_directory / "active.png"
    active.write_bytes(b"active")

    fresh_orphan = user_directory / "fresh.png"
    fresh_orphan.write_bytes(b"fresh")

    old_timestamp = (datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()
    os.utime(orphan, (old_timestamp, old_timestamp))
    os.utime(active, (old_timestamp, old_timestamp))

    draft = create_draft(
        db,
        user,
        "Draft title",
        "Draft description",
        None,
        image_url=f"/uploads/{user.id}/active.png",
        payload={"name_ru": "Draft title"},
    )

    update_draft(
        db,
        draft,
        changes={"payload": {"name_ru": "Draft title", "image_url": f"/uploads/{user.id}/active.png"}},
    )

    removed_count = uploads_service.cleanup_orphan_uploads(db, max_age_hours=24)

    assert removed_count == 1
    assert not orphan.exists()
    assert active.exists()
    assert fresh_orphan.exists()
    db.close()


def test_cleanup_orphan_uploads_keeps_payload_bound_upload(monkeypatch, tmp_path):
    init_db()
    init_drafts_db()
    db = SessionLocal()
    db.query(Draft).delete()
    db.query(User).delete()
    db.commit()

    monkeypatch.setattr(uploads_service, "UPLOADS_ROOT", tmp_path)
    user = _create_user(db)
    user_directory = tmp_path / user.id
    user_directory.mkdir(parents=True, exist_ok=True)

    payload_bound = user_directory / "payload-bound.png"
    payload_bound.write_bytes(b"payload-bound")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()
    os.utime(payload_bound, (old_timestamp, old_timestamp))

    create_draft(
        db,
        user,
        "Draft payload image",
        "Draft description",
        None,
        image_url=None,
        payload={"name_ru": "Draft payload image", "image_url": f"/uploads/{user.id}/payload-bound.png"},
    )

    removed_count = uploads_service.cleanup_orphan_uploads(db, max_age_hours=24)

    assert removed_count == 0
    assert payload_bound.exists()
    db.close()
