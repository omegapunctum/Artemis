import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

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

    def test_draft_title_min_length_is_three(self):
        with self.assertRaises(Exception):
            DraftCreate(title='ab', description='desc', geometry=None)
        payload = DraftUpdate(title='abc')
        self.assertEqual(payload.title, 'abc')


if __name__ == '__main__':
    unittest.main()
