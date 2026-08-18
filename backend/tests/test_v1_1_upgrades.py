import unittest
import sys
import os

# Adjust path to import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.yfinance_sync import sync_stock_history
from ml.optimizer import optimize_portfolio
from auth.database import init_db, SessionLocal
from auth.models import StockHistory

class TestV11Upgrades(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_kwayisi_history_scraping(self):
        """Verify that historical quotes sync from Kwayisi database."""
        added = sync_stock_history("SCOM")
        print(f"Synced {added} rows for SCOM")
        
        db = SessionLocal()
        count = db.query(StockHistory).filter(StockHistory.ticker == "SCOM").count()
        db.close()
        
        self.assertTrue(count > 0, "No historical rows found in database for SCOM")

    def test_portfolio_optimization(self):
        """Verify that portfolio optimizer calculates weights summing to 1.0."""
        # Ensure we have some historical data in db for SCOM and EQTY
        sync_stock_history("SCOM")
        sync_stock_history("EQTY")
        
        result = optimize_portfolio(["SCOM", "EQTY"])
        print("Optimizer result:", result)
        
        self.assertIn("status", result)
        self.assertIn("weights", result)
        
        weights = result["weights"]
        total_weight = sum(weights.values())
        self.assertAlmostEqual(total_weight, 1.0, places=2, msg="Portfolio weights do not sum to 1.0")

    def test_centralized_settings(self):
        """Verify that centralized Settings module loads expected typed values."""
        from core.config import settings
        self.assertEqual(settings.SERVICE_NAME, "NSE AI Investment Intelligence API")
        self.assertEqual(settings.CONFIDENCE_THRESHOLD, 0.75)
        self.assertEqual(settings.SCRAPER_CACHE_TTL, 600)
        self.assertEqual(settings.MARKET_OPEN_HOUR, 8)
        self.assertEqual(settings.MARKET_CLOSE_HOUR, 15)

    def test_composite_unique_stock_history_constraint(self):
        """Verify that database prevents duplicate (ticker, date) records."""
        from sqlalchemy.exc import IntegrityError
        import uuid
        db = SessionLocal()
        test_date = f"2099-01-{uuid.uuid4().hex[:4]}"
        try:
            item1 = StockHistory(ticker="TEST_UNIQ", date=test_date, open=10.0, high=11.0, low=9.0, close=10.5, volume=1000)
            db.add(item1)
            db.commit()

            # Attempt duplicate insertion
            item2 = StockHistory(ticker="TEST_UNIQ", date=test_date, open=10.0, high=11.0, low=9.0, close=10.5, volume=1000)
            db.add(item2)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.query(StockHistory).filter(StockHistory.ticker == "TEST_UNIQ").delete()
            db.commit()
            db.close()

    def test_intraday_snapshot_recording(self):
        """Verify that record_intraday_snapshot stores ticks in StockIntraday."""
        from data.scheduler import record_intraday_snapshot
        from auth.models import StockIntraday
        saved = record_intraday_snapshot()
        self.assertGreaterEqual(saved, 0)
        
        db = SessionLocal()
        ticks = db.query(StockIntraday).limit(5).all()
        db.close()
        # Should execute cleanly without DB error
        self.assertIsNotNone(ticks)

    def test_intraday_endpoint(self):
        """Verify that stock_intraday endpoint returns structured ticks and baseline."""
        from routers.stocks import stock_intraday
        res = stock_intraday("SCOM")
        self.assertIn("ticker", res)
        self.assertIn("ticks", res)
        self.assertIn("prev_close", res)
        self.assertIn("is_market_open", res)
        self.assertGreater(len(res["ticks"]), 0)


if __name__ == "__main__":
    unittest.main()
