import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.security.rate_limit import (
    check_login_block,
    get_client_ip,
    login_block_store,
    login_failure_store,
    rate_limit,
    rate_limit_store,
    register_login_failure,
    reset_login_failures,
)
from app.drafts.schemas import DraftCreate, DraftUpdate


class RateLimitUnitTests(unittest.TestCase):
    def setUp(self):
        rate_limit_store.clear()
        login_failure_store.clear()
        login_block_store.clear()

    def make_request(self, ip='127.0.0.1', path='/auth/login', headers=None):
        return SimpleNamespace(
            headers=headers or {},
            client=SimpleNamespace(host=ip),
            url=SimpleNamespace(path=path),
        )

    def test_get_client_ip_prefers_forwarded_for(self):
        request = self.make_request(ip='10.0.0.1', headers={'x-forwarded-for': '198.51.100.10, 10.0.0.1'})
        self.assertEqual(get_client_ip(request), '198.51.100.10')

    def test_register_limit_blocks_after_three_requests(self):
        request = self.make_request(path='/auth/register')
        dependency = rate_limit(3, 300, prefix='register')
        with patch('app.security.rate_limit.time', side_effect=[0, 1, 2, 3]):
            dependency(request)
            dependency(request)
            dependency(request)
            with self.assertRaises(HTTPException) as exc:
                dependency(request)
        self.assertEqual(exc.exception.status_code, 429)
        self.assertEqual(exc.exception.detail, 'rate_limit_exceeded')

    def test_draft_limit_isolated_by_path(self):
        create_request = self.make_request(path='/drafts')
        update_request = self.make_request(path='/drafts/1')
        create_dependency = rate_limit(1, 60, prefix='draft', include_path=True)
        update_dependency = rate_limit(1, 60, prefix='draft', include_path=True)
        with patch('app.security.rate_limit.time', side_effect=[10, 11, 12]):
            create_dependency(create_request)
            update_dependency(update_request)
            with self.assertRaises(HTTPException):
                create_dependency(create_request)

    def test_old_timestamps_are_pruned(self):
        request = self.make_request(path='/uploads/image')
        dependency = rate_limit(2, 60, prefix='upload')
        with patch('app.security.rate_limit.time', side_effect=[0, 30, 61, 62]):
            dependency(request)
            dependency(request)
            dependency(request)
            with self.assertRaises(HTTPException):
                dependency(request)

    def test_login_failures_trigger_temporary_block(self):
        request = self.make_request(path='/auth/login')
        with patch('app.security.rate_limit.time', side_effect=[0, 10, 20, 30, 40]):
            for _ in range(5):
                register_login_failure(request, limit=5, window_seconds=60, block_seconds=60)

        with patch('app.security.rate_limit.time', return_value=50):
            with self.assertRaises(HTTPException) as exc:
                check_login_block(request)
        self.assertEqual(exc.exception.status_code, 429)

    def test_login_success_resets_failure_counters(self):
        request = self.make_request(path='/auth/login')
        with patch('app.security.rate_limit.time', side_effect=[0, 10]):
            register_login_failure(request)
            register_login_failure(request)
        reset_login_failures(request)
        self.assertEqual(login_failure_store, {})
        self.assertEqual(login_block_store, {})

    def test_draft_create_requires_name_date_source(self):
        with self.assertRaises(ValidationError):
            DraftCreate(description='desc', date_start='2026-01-01', source_url='https://example.com')
        with self.assertRaises(ValidationError):
            DraftCreate(name_ru='Name', description='desc', source_url='https://example.com')
        with self.assertRaises(ValidationError):
            DraftCreate(name_ru='Name', description='desc', date_start='2026-01-01')

    def test_draft_create_rejects_invalid_enum_values(self):
        with self.assertRaises(ValidationError):
            DraftCreate(
                name_ru='Name',
                date_start='2026-01-01',
                source_url='https://example.com',
                description='desc',
                layer_type='unknown',
            )
        with self.assertRaises(ValidationError):
            DraftCreate(
                name_ru='Name',
                date_start='2026-01-01',
                source_url='https://example.com',
                description='desc',
                coordinates_confidence='somewhere',
            )
        with self.assertRaises(ValidationError):
            DraftCreate(
                name_ru='Name',
                date_start='2026-01-01',
                source_url='https://example.com',
                source_license='GPL',
            )

    def test_draft_create_rejects_invalid_coordinates(self):
        with self.assertRaises(ValidationError):
            DraftCreate(
                name_ru='Name',
                date_start='2026-01-01',
                source_url='https://example.com',
                latitude=100,
                longitude=40,
            )
        with self.assertRaises(ValidationError):
            DraftCreate(
                name_ru='Name',
                date_start='2026-01-01',
                source_url='https://example.com',
                latitude=40,
            )

    def test_draft_payload_blocks_forbidden_system_fields(self):
        create_payload = {
            'name_ru': 'Name',
            'date_start': '2026-01-01',
            'source_url': 'https://example.com',
        }
        for forbidden_field in (
            'etl_status',
            'etl_error',
            'date_valid',
            'dedupe_key',
            'published_from_draft_id',
            'version',
            'created_at',
            'updated_at',
            'validated',
            'is_active',
            'status',
            'publish_status',
            'airtable_record_id',
            'published_at',
            'id',
            'user_id',
        ):
            with self.assertRaises(ValidationError):
                DraftCreate(**create_payload, **{forbidden_field: 'forbidden'})

        for forbidden_field in ('status', 'created_at', 'updated_at'):
            with self.assertRaises(ValidationError):
                DraftUpdate(**{forbidden_field: 'forbidden'})

    def test_draft_create_rejects_invalid_source_url(self):
        with self.assertRaises(ValidationError):
            DraftCreate(name_ru='Name', date_start='2026-01-01', source_url='not-url')

    def test_draft_create_rejects_invalid_date_start(self):
        with self.assertRaises(ValidationError):
            DraftCreate(name_ru='Name', date_start='2026/01/01', source_url='https://example.com')

    def test_draft_create_rejects_too_long_fields(self):
        with self.assertRaises(ValidationError):
            DraftCreate(
                name_ru='Name',
                date_start='2026-01-01',
                source_url='https://example.com',
                title_short='a' * 121,
            )
        with self.assertRaises(ValidationError):
            DraftCreate(
                name_ru='Name',
                date_start='2026-01-01',
                source_url='https://example.com',
                description='a' * 2001,
            )

    def test_valid_draft_payload_passes_validation(self):
        payload = DraftCreate(
            name_ru='Feature',
            date_start='2026-01-01',
            source_url='https://example.com/source',
            description='valid description',
            title_short='Short title',
            layer_type='biography',
            coordinates_confidence='exact',
            source_license='CC BY',
            latitude=55.7558,
            longitude=37.6173,
            geometry={'type': 'Point', 'coordinates': [37.6173, 55.7558]},
        )
        self.assertEqual(payload.name_ru, 'Feature')

    def test_draft_update_rejects_status_escalation(self):
        with self.assertRaises(ValidationError):
            DraftUpdate(status='approved')


if __name__ == '__main__':
    unittest.main()
