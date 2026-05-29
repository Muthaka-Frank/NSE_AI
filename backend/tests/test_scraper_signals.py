import unittest
import sys
import os

# Add parent directories to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from data.nse_scraper import get_price, get_all_prices
from ml.sentiment import analyse
from ml.predictor import predict

class TestScraperAndSignals(unittest.TestCase):
    def test_scraper_all_prices(self):
        """Verify that get_all_prices returns active listings and expected key metrics."""
        prices = get_all_prices()
        self.assertIsNotNone(prices)
        self.assertGreater(len(prices), 0)
        
        # SCOM should be one of the elements
        self.assertIn("SCOM", prices)
        scom = prices["SCOM"]
        self.assertIn("price", scom)
        self.assertIn("change", scom)
        self.assertIn("change_pct", scom)
        self.assertIn("volume", scom)
        
        # Verify ticker translations worked
        self.assertIn("STND", prices)
        stnd = prices["STND"]
        self.assertIn("price", stnd)

    def test_keyword_sentiment_fallback(self):
        """Verify that sentiment classification operates cleanly and handles keywords and negations."""
        # Positive sentiment
        res_pos = analyse("Standard Chartered Bank posts strong record revenue and profit growth.")
        self.assertEqual(res_pos.label, "POSITIVE")
        self.assertGreater(res_pos.score, 0.5)

        # Negative sentiment
        res_neg = analyse("Safaricom shares plunge as earnings decline and warning issued.")
        self.assertEqual(res_neg.label, "NEGATIVE")
        
        # Negated positive should result in negative
        res_negated = analyse("Equity Bank did not report positive revenue.")
        self.assertEqual(res_negated.label, "NEGATIVE")

    def test_indicator_signals_predictor(self):
        """Verify that predictor signal engine processes history and calculates BUY/SELL targets."""
        # Construct mock history Walk around KES 30.00
        mock_history = [
            {"date": f"2026-05-{i:02d}", "open": 30.0, "high": 30.5, "low": 29.5, "close": 30.0 + (i * 0.1), "volume": 1000000}
            for i in range(1, 20)
        ]
        
        pred = predict("SCOM", mock_history)
        self.assertEqual(pred.ticker, "SCOM")
        self.assertIn(pred.direction, ["BUY", "SELL", "HOLD", "NO_SIGNAL"])
        if pred.direction in ["BUY", "SELL"]:
            self.assertIsNotNone(pred.price_target)
            self.assertGreater(pred.price_target, 0)
            self.assertIn(pred.risk_level, ["LOW", "MEDIUM", "HIGH"])

if __name__ == "__main__":
    unittest.main()
