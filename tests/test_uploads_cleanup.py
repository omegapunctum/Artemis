import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from app.auth.service import SessionLocal, User, init_db
from app.auth.utils import hash_password
from app.drafts.service import Draft, create_draft, delete_draft, init_db as init_drafts_db, update_draft
from app.uploads import service as uploads_service


def _create_user(db) -> User:
    user = User(email=f"uploads-{uuid4().hex}@example.com", password_hash=hash_password("password123"), is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _build_upload(filename: str, content: bytes, content_type: str = "image/png") -> UploadFile:
    path = Path(filename)
    path.write_bytes(content)
    fh = path.open("rb")
    return UploadFile(filename=path.name, file=fh, headers={"content-type": content_type})


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


def test_replace_upload_removes_old_orphan(monkeypatch, tmp_path):
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

    old_file = user_directory / "old.png"
    old_file.write_bytes(b"old")
    draft = create_draft(
        db,
        user,
        "Draft image replace",
        "Draft description",
        None,
        image_url=f"/uploads/{user.id}/old.png",
        payload={"name_ru": "Draft image replace"},
    )

    upload = _build_upload(tmp_path / "new.png", b"new")
    try:
        new_url = uploads_service.save_draft_image(db, draft, user, upload)
    finally:
        upload.file.close()

    assert new_url.startswith(f"/uploads/{user.id}/")
    assert not old_file.exists()
    new_file = tmp_path / new_url.removeprefix("/uploads/")
    assert new_file.exists()
    db.close()


def test_delete_draft_cleanup_removes_unreferenced_upload(monkeypatch, tmp_path):
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

    bound = user_directory / "bound.png"
    bound.write_bytes(b"bound")

    draft = create_draft(
        db,
        user,
        "Draft delete cleanup",
        "Draft description",
        None,
        image_url=f"/uploads/{user.id}/bound.png",
        payload={"name_ru": "Draft delete cleanup"},
    )

    tracked = uploads_service.collect_draft_upload_urls(draft)
    delete_draft(db, draft)
    removed_count = uploads_service.cleanup_unreferenced_upload_urls(db, tracked)

    assert removed_count == 1
    assert not bound.exists()
    db.close()


def test_safety_shared_upload_not_deleted_if_still_referenced(monkeypatch, tmp_path):
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

    shared = user_directory / "shared.png"
    shared.write_bytes(b"shared")
    shared_url = f"/uploads/{user.id}/shared.png"

    draft_a = create_draft(db, user, "A", "desc", None, image_url=shared_url, payload={"name_ru": "A"})
    create_draft(db, user, "B", "desc", None, image_url=shared_url, payload={"name_ru": "B"})

    update_draft(db, draft_a, changes={"image_url": None, "payload": {"name_ru": "A"}})
    removed_count = uploads_service.cleanup_unreferenced_upload_urls(db, {shared_url})

    assert removed_count == 0
    assert shared.exists()
    db.close()
