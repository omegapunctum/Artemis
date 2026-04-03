import os
import unittest

from fastapi import HTTPException
from pathlib import Path
from pydantic import ValidationError
from unittest.mock import patch

DB_PATH = Path('artemis_auth.db')
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ.setdefault('MODERATOR_EMAILS', 'moderator@example.com,moderator2@example.com')
os.environ.setdefault('AIRTABLE_TOKEN', 'test-token')
os.environ.setdefault('AIRTABLE_BASE', 'base123')
os.environ.setdefault('AIRTABLE_TABLE', 'Features')

from app.auth.service import SessionLocal, User, init_db as init_auth_db  # noqa: E402
from app.drafts.schemas import DraftCreate, DraftResponse, DraftUpdate  # noqa: E402
from app.drafts.service import Draft, create_draft, get_user_draft, init_db as init_drafts_db  # noqa: E402
from app.moderation.service import (  # noqa: E402
    PUBLISH_STATUS_FAILED,
    PUBLISH_STATUS_PUBLISHED,
    approve_draft,
    build_airtable_fields,
    find_existing_airtable_feature,
    is_moderator,
    list_review_drafts,
    reject_draft,
    submit_draft_for_review,
)

init_auth_db()
init_drafts_db()


class ModerationFlowTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()
        cleanup = SessionLocal()
        try:
            cleanup.query(Draft).delete()
            cleanup.query(User).delete()
            cleanup.commit()
        finally:
            cleanup.close()

    def make_user(self, email: str, is_admin: bool = False) -> User:
        user = User(email=email, password_hash='hash', is_admin=is_admin)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def test_submit_queue_approve_flow(self):
        user = self.make_user('user@example.com')
        moderator = self.make_user('moderator@example.com')

        draft = create_draft(
            self.db,
            user,
            'Test point',
            'UGC draft',
            {'type': 'Point', 'coordinates': [37.6173, 55.7558]},
        )
        self.assertEqual(draft.status, 'draft')

        draft = submit_draft_for_review(self.db, get_user_draft(self.db, draft.id, user))
        self.assertEqual(draft.status, 'pending')
        self.assertTrue(is_moderator(moderator))

        queue = list_review_drafts(self.db)
        self.assertEqual([item.id for item in queue], [draft.id])

        with patch('app.moderation.service.find_existing_airtable_feature', return_value=None), patch(
            'app.moderation.service.create_airtable_feature'
        ) as create_airtable_mock:
            create_airtable_mock.return_value = {'id': 'rec123'}
            draft = approve_draft(self.db, draft)

        self.assertEqual(draft.status, 'approved')
        self.assertEqual(draft.publish_status, PUBLISH_STATUS_PUBLISHED)
        self.assertEqual(draft.airtable_record_id, 'rec123')
        payload = build_airtable_fields(draft)
        self.assertEqual(payload['name_ru'], 'Test point')
        self.assertEqual(payload['source_url'], 'https://ugc.local/source')
        self.assertEqual(payload['source_license'], 'CC BY')
        self.assertEqual(payload['longitude'], 37.6173)
        self.assertEqual(payload['latitude'], 55.7558)
        self.assertEqual(payload['external_id'], f'draft:{draft.id}')

        with patch('app.moderation.service.create_airtable_feature') as create_airtable_mock:
            approved_again = approve_draft(self.db, draft)

        self.assertEqual(approved_again.id, draft.id)
        self.assertEqual(approved_again.airtable_record_id, 'rec123')
        create_airtable_mock.assert_not_called()

    def test_approve_uses_existing_airtable_record_without_duplicate_publish(self):
        user = self.make_user('existing@example.com')
        draft = create_draft(self.db, user, 'Existing', 'Desc', None)
        draft = submit_draft_for_review(self.db, draft)
        result_context = {}

        with patch('app.moderation.service.find_existing_airtable_feature', return_value={'id': 'rec-existing'}), patch(
            'app.moderation.service.create_airtable_feature'
        ) as create_airtable_mock:
            approved = approve_draft(self.db, draft, result_context=result_context)

        self.assertEqual(approved.status, 'approved')
        self.assertEqual(approved.publish_status, PUBLISH_STATUS_PUBLISHED)
        self.assertEqual(approved.airtable_record_id, 'rec-existing')
        self.assertEqual(result_context['result'], 'published_skipped_duplicate')
        create_airtable_mock.assert_not_called()

    def test_reapprove_already_published_returns_stable_result(self):
        user = self.make_user('stable@example.com')
        draft = create_draft(self.db, user, 'Stable', 'Desc', None)
        draft = submit_draft_for_review(self.db, draft)

        with patch('app.moderation.service.find_existing_airtable_feature', return_value={'id': 'rec-stable'}):
            approved = approve_draft(self.db, draft)

        self.assertEqual(approved.publish_status, PUBLISH_STATUS_PUBLISHED)
        result_context = {}
        approved_again = approve_draft(self.db, approved, result_context=result_context)

        self.assertEqual(approved_again.id, approved.id)
        self.assertEqual(result_context['result'], 'approved_already_published')

    def test_failed_publish_marks_draft_failed_without_approving(self):
        user = self.make_user('failed@example.com')
        draft = create_draft(self.db, user, 'Failure', 'Desc', None)
        draft = submit_draft_for_review(self.db, draft)

        with patch('app.moderation.service.find_existing_airtable_feature', return_value=None), patch(
            'app.moderation.service.create_airtable_feature', side_effect=HTTPException(status_code=502, detail='boom')
        ):
            with self.assertRaises(Exception):
                approve_draft(self.db, draft)

        refreshed = self.db.query(Draft).filter(Draft.id == draft.id).first()
        self.assertEqual(refreshed.status, 'pending')
        self.assertEqual(refreshed.publish_status, PUBLISH_STATUS_FAILED)
        self.assertIsNone(refreshed.airtable_record_id)

    def test_reject_requires_pending_status(self):
        user = self.make_user('user2@example.com')
        moderator = self.make_user('moderator2@example.com')
        self.assertTrue(is_moderator(moderator))

        draft = create_draft(self.db, user, 'Draft', 'Desc', None)
        with self.assertRaises(Exception):
            reject_draft(self.db, draft)

        draft = submit_draft_for_review(self.db, draft)
        draft = reject_draft(self.db, draft)
        self.assertEqual(draft.status, 'rejected')

    def test_build_airtable_fields_without_point_coordinates(self):
        user = self.make_user('admin@example.com', is_admin=True)
        self.assertTrue(is_moderator(user))

        draft = Draft(
            user_id=user.id,
            title='Area feature',
            description='Polygon draft',
            geometry={'type': 'Polygon', 'coordinates': []},
            image_url='/uploads/example.png',
            status='pending',
        )
        payload = build_airtable_fields(draft)
        self.assertIsNone(payload['longitude'])
        self.assertIsNone(payload['latitude'])
        self.assertIsNone(payload['image_url'])
        self.assertEqual(payload['layer_id'], 'ugc')
        self.assertEqual(payload['external_id'], 'draft:None')

    def test_normalized_id_same_payload_same_hash_slight_change_new_hash(self):
        user = self.make_user('hash@example.com')
        payload = {
            'name_ru': 'Same title',
            'source_url': 'https://example.com/source',
            'longitude': 37.6173,
            'latitude': 55.7558,
        }
        draft_a = Draft(user_id=user.id, title='Same title', description='A', payload=payload)
        draft_b = Draft(user_id=user.id, title='Same title', description='B', payload=payload)
        draft_c = Draft(user_id=user.id, title='Same title changed', description='C', payload={**payload, 'name_ru': 'Same title changed'})

        id_a = build_airtable_fields(draft_a)['normalized_id']
        id_b = build_airtable_fields(draft_b)['normalized_id']
        id_c = build_airtable_fields(draft_c)['normalized_id']

        self.assertEqual(id_a, id_b)
        self.assertNotEqual(id_a, id_c)

    def test_find_existing_uses_normalized_id_before_external_id(self):
        user = self.make_user('dedupe@example.com')
        draft = create_draft(
            self.db,
            user,
            'Dedup title',
            'desc',
            {'type': 'Point', 'coordinates': [37.6173, 55.7558]},
            payload={
                'name_ru': 'Dedup title',
                'source_url': 'https://example.com/source',
                'longitude': 37.6173,
                'latitude': 55.7558,
            },
        )
        fields = build_airtable_fields(draft)

        with patch('app.moderation.service._get_airtable_config', return_value=('token', 'base', 'Features')), patch(
            'app.moderation.service._find_airtable_record_by_formula',
            return_value={'id': 'rec-normalized', 'fields': {}},
        ) as find_formula:
            record = find_existing_airtable_feature(draft, fields=fields)

        self.assertIsNotNone(record)
        self.assertEqual(record['id'], 'rec-normalized')
        self.assertEqual(find_formula.call_count, 1)
        self.assertIn('{normalized_id}', find_formula.call_args_list[0].args[2])

    def test_draft_response_schema_includes_status(self):
        payload = DraftResponse.model_validate(
            {
                'id': 1,
                'title': 'Title',
                'description': 'Desc',
                'geometry': None,
                'image_url': None,
                'status': 'draft',
                'publish_status': 'pending',
                'airtable_record_id': None,
                'published_at': None,
                'created_at': '2026-03-22T00:00:00',
                'updated_at': '2026-03-22T00:00:00',
            }
        )
        self.assertEqual(payload.status, 'draft')


class DraftValidationEdgeCasesTests(unittest.TestCase):
    def setUp(self):
        self.valid_create = {
            "name_ru": "Тест",
            "date_start": "2026-01-01",
            "source_url": "https://example.com/source",
            "layer_type": "biography",
            "coordinates_confidence": "exact",
            "source_license": "CC BY-SA",
        }

    def assert_create_invalid(self, payload):
        with self.assertRaises(ValidationError):
            DraftCreate.model_validate(payload)

    def assert_update_invalid(self, payload):
        with self.assertRaises(ValidationError):
            DraftUpdate.model_validate(payload)

    def test_required_fields_create_validation(self):
        self.assert_create_invalid({"date_start": "2026-01-01", "source_url": "https://example.com/source"})
        self.assert_create_invalid({"name_ru": "", "date_start": "2026-01-01", "source_url": "https://example.com/source"})
        self.assert_create_invalid({"name_ru": "Тест", "source_url": "https://example.com/source"})
        self.assert_create_invalid({"name_ru": "Тест", "date_start": "2026/01/01", "source_url": "https://example.com/source"})
        self.assert_create_invalid({"name_ru": "Тест", "date_start": "2026-01-01"})
        self.assert_create_invalid({"name_ru": "Тест", "date_start": "2026-01-01", "source_url": "not-url"})
        self.assert_create_invalid({"name_ru": "Тест", "date_start": "2026-01-01", "source_url": "javascript:alert(1)"})
        self.assert_create_invalid({"name_ru": "Тест", "date_start": "2026-01-01", "source_url": "ftp://example.com/source"})
        valid_http = DraftCreate.model_validate({**self.valid_create, "source_url": "http://example.com/source"})
        self.assertEqual(str(valid_http.source_url), "http://example.com/source")

    def test_coordinates_validation(self):
        self.assert_create_invalid({**self.valid_create, "latitude": 55.7})
        self.assert_create_invalid({**self.valid_create, "longitude": 37.6})
        self.assert_create_invalid({**self.valid_create, "latitude": 95.0, "longitude": 37.6})
        self.assert_create_invalid({**self.valid_create, "latitude": 55.7, "longitude": 200.0})
        valid = DraftCreate.model_validate({**self.valid_create, "latitude": 55.7, "longitude": 37.6})
        self.assertEqual(valid.latitude, 55.7)
        self.assertEqual(valid.longitude, 37.6)

    def test_enum_validation(self):
        self.assert_create_invalid({**self.valid_create, "layer_type": "wrong"})
        self.assert_create_invalid({**self.valid_create, "coordinates_confidence": "EXACT"})
        self.assert_create_invalid({**self.valid_create, "source_license": "MIT"})
        self.assert_create_invalid({**self.valid_create, "layer_type": "BIOGRAPHY"})
        valid = DraftCreate.model_validate(
            {**self.valid_create, "layer_type": "architecture", "coordinates_confidence": "approximate", "source_license": "PD"}
        )
        self.assertEqual(valid.layer_type, "architecture")

    def test_system_fields_are_forbidden(self):
        for field_name in ("etl_status", "status", "published_from_draft_id", "created_at", "updated_at"):
            self.assert_create_invalid({**self.valid_create, field_name: "forbidden"})

    def test_update_flow_validation(self):
        self.assert_update_invalid({"created_at": "2026-01-01T00:00:00"})
        self.assert_update_invalid({"status": "review"})
        self.assert_update_invalid({"source_license": "INVALID"})
        self.assert_update_invalid({"image_url": "javascript:alert(1)"})
        self.assert_update_invalid({"image_url": "ftp://example.com/image.png"})
        self.assert_update_invalid({"latitude": 55.7})
        self.assert_update_invalid({"latitude": 95.0, "longitude": 37.6})
        valid = DraftUpdate.model_validate({"description": "ok", "latitude": 55.7, "longitude": 37.6, "source_license": "PD"})
        self.assertEqual(valid.description, "ok")


if __name__ == '__main__':
    unittest.main()
