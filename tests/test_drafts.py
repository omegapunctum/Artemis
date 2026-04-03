from types import SimpleNamespace
from uuid import uuid4

from app.auth.service import SessionLocal, User, init_db
from app.auth.utils import hash_password
from app.drafts.routes import delete_draft_endpoint, update_draft_endpoint
from app.drafts.schemas import DraftUpdate
from app.drafts.service import Draft, create_draft, init_db as init_drafts_db


def _request(path: str):
    return SimpleNamespace(state=SimpleNamespace(request_id="test-request-id", user_id=None), url=SimpleNamespace(path=path))


def _create_user(db) -> User:
    user = User(email=f"drafts-{uuid4().hex}@example.com", password_hash=hash_password("password123"), is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_update_draft_calls_upload_cleanup_for_replaced_image(monkeypatch):
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
        image_url=f"/uploads/{user.id}/old.png",
        payload={"name_ru": "Draft title", "image_url": f"/uploads/{user.id}/old.png"},
    )

    captured = {}

    def _capture_cleanup(_db, upload_urls):
        captured["urls"] = set(upload_urls)
        return 0

    monkeypatch.setattr("app.drafts.routes.cleanup_unreferenced_upload_urls", _capture_cleanup)
    payload = DraftUpdate.model_validate({"image_url": f"https://example.com/uploads/{user.id}/new.png"})
    update_draft_endpoint(draft.id, payload, _request(f"/api/drafts/{draft.id}"), _=None, db=db, current_user=user)

    assert captured["urls"] == {f"/uploads/{user.id}/old.png"}
    db.close()


def test_delete_draft_calls_upload_cleanup(monkeypatch):
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
        image_url=f"/uploads/{user.id}/to-delete.png",
        payload={"name_ru": "Draft title", "image_url": f"/uploads/{user.id}/to-delete.png"},
    )

    captured = {}

    def _capture_cleanup(_db, upload_urls):
        captured["urls"] = set(upload_urls)
        return 0

    monkeypatch.setattr("app.drafts.routes.cleanup_unreferenced_upload_urls", _capture_cleanup)
    delete_draft_endpoint(draft.id, _request(f"/api/drafts/{draft.id}"), _=None, db=db, current_user=user)

    assert captured["urls"] == {f"/uploads/{user.id}/to-delete.png"}
    db.close()
