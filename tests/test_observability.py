import unittest
from types import SimpleNamespace

from app.observability import get_request_id, health_payload, metrics


class ObservabilityTests(unittest.TestCase):
    def test_get_request_id_uses_header_when_present(self):
        request = SimpleNamespace(headers={'x-request-id': 'req-123'})
        self.assertEqual(get_request_id(request), 'req-123')

    def test_get_request_id_generates_uuid_when_missing(self):
        request = SimpleNamespace(headers={})
        self.assertTrue(get_request_id(request))

    def test_health_payload_exposes_counts_and_uptime(self):
        before = metrics.snapshot()['counts']['total_requests']
        metrics.increment('total_requests')
        payload = health_payload()
        self.assertIn('ok', payload)
        self.assertIn('uptime', payload)
        self.assertIn('counts', payload)
        self.assertGreaterEqual(payload['counts']['total_requests'], before + 1)


if __name__ == '__main__':
    unittest.main()
