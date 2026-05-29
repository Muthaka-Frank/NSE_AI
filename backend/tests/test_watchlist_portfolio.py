import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

# Add parent directories to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from main import app
from auth.database import Base, get_db
from auth.models import User, WatchlistItem, PortfolioItem

# Use a local temporary SQLite file
TEST_DB_FILE = "./test_temp_wp.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

class TestWatchlistPortfolio(unittest.TestCase):
    def setUp(self):
        # Create all tables in memory
        Base.metadata.create_all(bind=engine)
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        
        # Create a test user and obtain a login token
        self.reg_payload = {
            "email": "watchlistuser@example.com",
            "password": "securepassword",
            "name": "Watchlist User"
        }
        self.client.post("/api/auth/register", json=self.reg_payload)
        
        login_res = self.client.post("/api/auth/login", json={
            "email": "watchlistuser@example.com",
            "password": "securepassword"
        })
        self.token = login_res.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        # Clean up dependency overrides
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        # Remove the file if exists
        try:
            if os.path.exists(TEST_DB_FILE):
                os.remove(TEST_DB_FILE)
        except Exception:
            pass

    def test_watchlist_crud(self):
        # 1. Watchlist should be empty initially
        get_res = self.client.get("/api/watchlist", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(len(get_res.json()), 0)

        # 2. Add stock SCOM to watchlist
        add_res = self.client.post("/api/watchlist", json={"ticker": "SCOM"}, headers=self.headers)
        self.assertEqual(add_res.status_code, 200)
        self.assertIn("added to watchlist", add_res.json()["message"])

        # 3. Try to add same stock SCOM again (should fail with 400)
        dup_res = self.client.post("/api/watchlist", json={"ticker": "SCOM"}, headers=self.headers)
        self.assertEqual(dup_res.status_code, 400)

        # 4. Watchlist should now have 1 item
        get_res = self.client.get("/api/watchlist", headers=self.headers)
        self.assertEqual(len(get_res.json()), 1)
        self.assertEqual(get_res.json()[0]["ticker"], "SCOM")

        # 5. Remove stock SCOM from watchlist
        del_res = self.client.delete("/api/watchlist/SCOM", headers=self.headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertIn("removed from watchlist", del_res.json()["message"])

        # 6. Watchlist should be empty again
        get_res = self.client.get("/api/watchlist", headers=self.headers)
        self.assertEqual(len(get_res.json()), 0)

    def test_portfolio_tracking(self):
        # 1. Portfolio should be empty initially
        get_res = self.client.get("/api/portfolio", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        data = get_res.json()
        self.assertEqual(len(data["holdings"]), 0)
        self.assertEqual(data["summary"]["total_cost"], 0.0)

        # 2. Record purchase of 500 shares of EQTY at KES 50.00
        buy_res = self.client.post("/api/portfolio", json={
            "ticker": "EQTY",
            "buy_price": 50.00,
            "quantity": 500
        }, headers=self.headers)
        self.assertEqual(buy_res.status_code, 200)
        self.assertIn("Successfully purchased", buy_res.json()["message"])
        holding_id = buy_res.json()["id"]

        # 3. Portfolio should now show holdings and summaries
        get_res = self.client.get("/api/portfolio", headers=self.headers)
        data = get_res.json()
        self.assertEqual(len(data["holdings"]), 1)
        holding = data["holdings"][0]
        self.assertEqual(holding["ticker"], "EQTY")
        self.assertEqual(holding["quantity"], 500)
        self.assertEqual(holding["buy_price"], 50.00)
        self.assertEqual(holding["total_cost"], 25000.00)

        # 4. Remove holding
        del_res = self.client.delete(f"/api/portfolio/{holding_id}", headers=self.headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertIn("Holding successfully deleted", del_res.json()["message"])

        # 5. Portfolio summary should reset to 0
        get_res = self.client.get("/api/portfolio", headers=self.headers)
        self.assertEqual(len(get_res.json()["holdings"]), 0)

if __name__ == "__main__":
    unittest.main()
