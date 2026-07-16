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

if __name__ == "__main__":
    unittest.main()
