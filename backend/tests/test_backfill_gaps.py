import unittest
import os
import sys
import shutil
import sqlite3

# Adjust path to import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.backfill_gaps import (
    diagnose_gaps,
    insert_history_records,
    forward_fill_gaps,
    get_business_days,
)

class TestBackfillGaps(unittest.TestCase):
    def setUp(self):
        self.test_db = "./test_temp_backfill.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        
        # Create minimal stock_history table
        conn = sqlite3.connect(self.test_db)
        conn.execute("""
            CREATE TABLE stock_history (
                id VARCHAR PRIMARY KEY,
                ticker VARCHAR NOT NULL,
                date VARCHAR NOT NULL,
                open FLOAT NOT NULL,
                high FLOAT NOT NULL,
                low FLOAT NOT NULL,
                close FLOAT NOT NULL,
                volume INTEGER DEFAULT 0,
                UNIQUE (ticker, date)
            );
        """)
        # Insert seed records for SCOM ending on 2026-10-20
        conn.execute("""
            INSERT INTO stock_history VALUES
            ('1', 'SCOM', '2026-10-19', 35.0, 35.5, 34.8, 35.2, 10000),
            ('2', 'SCOM', '2026-10-20', 35.2, 35.6, 35.1, 35.4, 15000);
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_get_business_days(self):
        # 2026-10-21 (Wed) to 2026-10-26 (Mon) should have 4 business days: Wed 21, Thu 22, Fri 23, Mon 26
        days = get_business_days("2026-10-21", "2026-10-26")
        self.assertEqual(days, ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26"])

    def test_diagnose_gaps(self):
        # Diagnose against target 2026-10-23 (Fri)
        diag = diagnose_gaps(db_path=self.test_db, target_end_date="2026-10-23")
        self.assertEqual(diag["status"], "gap_detected")
        self.assertEqual(diag["global_latest_date"], "2026-10-20")
        self.assertEqual(diag["missing_trading_days_count"], 3)  # 21, 22, 23
        self.assertIn("SCOM", diag["affected_tickers"])

    def test_forward_fill_gaps(self):
        diag_before = diagnose_gaps(db_path=self.test_db, target_end_date="2026-10-23")
        self.assertEqual(diag_before["status"], "gap_detected")

        res = forward_fill_gaps(db_path=self.test_db)
        self.assertEqual(res["status"], "completed")

        diag_after = diagnose_gaps(db_path=self.test_db, target_end_date="2026-10-23")
        self.assertEqual(diag_after["status"], "up_to_date")
        self.assertEqual(diag_after["affected_tickers_count"], 0)

        # Check records in DB
        conn = sqlite3.connect(self.test_db)
        cur = conn.cursor()
        cur.execute("SELECT date, close, volume FROM stock_history WHERE ticker = 'SCOM' ORDER BY date ASC;")
        rows = cur.fetchall()
        conn.close()

        dates = [r[0] for r in rows]
        self.assertIn("2026-10-21", dates)
        self.assertIn("2026-10-22", dates)
        self.assertIn("2026-10-23", dates)
        # Verify carried forward price
        for r in rows:
            if r[0] in ["2026-10-21", "2026-10-22", "2026-10-23"]:
                self.assertEqual(r[1], 35.4)  # last close
                self.assertEqual(r[2], 0)     # 0 volume placeholder

if __name__ == "__main__":
    unittest.main()
