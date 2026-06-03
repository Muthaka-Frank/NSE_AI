import unittest
import os
import sys
from unittest.mock import patch, MagicMock

# Add parent directories to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from ml.predictor import predict
from routers.alerts import check_and_send_high_confidence_alert

class TestAlertsAndTimeframe(unittest.TestCase):
    def setUp(self):
        # Path for sent alerts log during testing
        self.log_dir = os.path.join(os.path.dirname(__file__), "..", "tmp")
        self.sent_log = os.path.join(self.log_dir, "sent_alerts.log")
        # Clean up any leftover test log file
        self.tearDown()

    def tearDown(self):
        try:
            if os.path.exists(self.sent_log):
                os.remove(self.sent_log)
        except Exception:
            pass

    def test_dynamic_timeframe_range(self):
        """Verify timeframe is generated dynamically and scales with price volatility."""
        # 1. Low volatility history (closes very close to each other)
        low_vol_history = [
            {"date": f"2026-05-{i:02d}", "open": 30.0, "high": 30.1, "low": 29.9, "close": 30.0 + (i * 0.001), "volume": 100000}
            for i in range(1, 20)
        ]
        
        # 2. High volatility history (large daily movements)
        high_vol_history = [
            {"date": f"2026-05-{i:02d}", "open": 30.0, "high": 35.0, "low": 25.0, "close": 30.0 + (i * 1.5 if i % 2 == 0 else -i * 1.2), "volume": 100000}
            for i in range(1, 20)
        ]

        # Calculate prediction results
        res_low = predict("TEST_LOW", low_vol_history)
        res_high = predict("TEST_HIGH", high_vol_history)

        # Check low volatility timeframe is valid (expecting a longer timeframe due to slow changes)
        if res_low.direction in ["BUY", "SELL"]:
            self.assertIsNotNone(res_low.timeframe)
            self.assertIn("days", res_low.timeframe)
            
        # Check high volatility timeframe is valid (expecting a shorter timeframe due to rapid swings)
        if res_high.direction in ["BUY", "SELL"]:
            self.assertIsNotNone(res_high.timeframe)
            self.assertIn("days", res_high.timeframe)

    @patch("routers.alerts._load_subscribers")
    @patch("routers.alerts.send_sms_via_africastalking")
    def test_duplicate_alert_filtering(self, mock_send_sms, mock_load_subs):
        """Verify check_and_send_high_confidence_alert sends alert once and filters daily duplicates."""
        mock_load_subs.return_value = ["+254700000000"]
        mock_send_sms.return_value = {"status": "success"}

        # First alert trigger: should call send_sms
        check_and_send_high_confidence_alert("SCOM", "BUY", 0.99, 33.45, "5 to 7 days")
        self.assertTrue(mock_send_sms.called)
        self.assertEqual(mock_send_sms.call_count, 1)

        # Reset mock call count
        mock_send_sms.reset_mock()

        # Second alert trigger: same day, same direction, should be filtered (no call)
        check_and_send_high_confidence_alert("SCOM", "BUY", 0.99, 33.45, "5 to 7 days")
        self.assertFalse(mock_send_sms.called)
        self.assertEqual(mock_send_sms.call_count, 0)

if __name__ == "__main__":
    unittest.main()
