import unittest
import time
from data.http_client import (
    get_random_headers,
    is_circuit_breaker_active,
    trip_circuit_breaker,
    reset_circuit_breaker,
    get_circuit_breaker_remaining,
    get_stealth_session,
    DESKTOP_USER_AGENTS,
)

class TestHttpClientAntiBlock(unittest.TestCase):
    def setUp(self):
        reset_circuit_breaker()

    def tearDown(self):
        reset_circuit_breaker()

    def test_random_headers(self):
        headers = get_random_headers()
        self.assertIn(headers["User-Agent"], DESKTOP_USER_AGENTS)
        self.assertIn("Accept", headers)
        self.assertIn("Sec-Fetch-Dest", headers)
        self.assertEqual(headers["Referer"], "https://www.google.com/")

    def test_circuit_breaker_trip_and_reset(self):
        self.assertFalse(is_circuit_breaker_active())
        self.assertEqual(get_circuit_breaker_remaining(), 0)

        trip_circuit_breaker("Test block", duration_secs=60)
        self.assertTrue(is_circuit_breaker_active())
        self.assertGreater(get_circuit_breaker_remaining(), 50)

        reset_circuit_breaker()
        self.assertFalse(is_circuit_breaker_active())
        self.assertEqual(get_circuit_breaker_remaining(), 0)

    def test_stealth_session_creation(self):
        session = get_stealth_session()
        self.assertIsNotNone(session)
        # Verify adapter is mounted
        adapter = session.get_adapter("https://afx.kwayisi.org")
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.max_retries.total, 0)

if __name__ == "__main__":
    unittest.main()
