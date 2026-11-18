import unittest
import os
import sys
import pandas as pd
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from main import app
from auth.database import Base, get_db
from auth.models import StockHistory, PortfolioItem
from ml.diversification import (
    calculate_hhi,
    classify_hhi,
    calculate_effective_constituents,
    compute_correlation_matrix,
    compute_covariance_matrix,
    compute_sector_correlation_matrix,
    generate_diversification_insights,
    compute_portfolio_diversification,
)

TEST_DB_FILE = "./test_temp_div.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestDiversificationMath(unittest.TestCase):
    def test_hhi_calculation(self):
        # 1. Single asset: HHI = 1.0
        self.assertEqual(calculate_hhi([1.0]), 1.0)
        self.assertEqual(calculate_hhi([500.0]), 1.0)

        # 2. Two equal assets: 0.5^2 + 0.5^2 = 0.50
        self.assertEqual(calculate_hhi([0.5, 0.5]), 0.50)
        self.assertEqual(calculate_hhi([100.0, 100.0]), 0.50)

        # 3. Five equal assets: 5 * (0.2)^2 = 0.20
        self.assertAlmostEqual(calculate_hhi([0.2, 0.2, 0.2, 0.2, 0.2]), 0.20, places=4)

        # 4. Ten equal assets: 10 * (0.1)^2 = 0.10
        self.assertAlmostEqual(calculate_hhi([0.1] * 10), 0.10, places=4)

        # 5. Empty or zero weights
        self.assertEqual(calculate_hhi([]), 0.0)
        self.assertEqual(calculate_hhi([0.0, 0.0]), 0.0)

    def test_classify_hhi(self):
        status, color, desc = classify_hhi(0.10)
        self.assertEqual(status, "DIVERSIFIED")

        status, color, desc = classify_hhi(0.18)
        self.assertEqual(status, "MODERATE")

        status, color, desc = classify_hhi(0.45)
        self.assertEqual(status, "CONCENTRATED")

    def test_effective_constituents(self):
        # 1 asset -> 1.0
        self.assertEqual(calculate_effective_constituents([1.0]), 1.0)
        # 2 equal assets -> 2.0
        self.assertEqual(calculate_effective_constituents([0.5, 0.5]), 2.0)
        # 5 equal assets -> 5.0
        self.assertAlmostEqual(calculate_effective_constituents([0.2] * 5), 5.0, places=1)
        # Empty -> 0.0
        self.assertEqual(calculate_effective_constituents([]), 0.0)

    def test_correlation_matrix_computation(self):
        # Create synthetic returns
        np.random.seed(42)
        days = 30
        series_a = np.random.normal(0.001, 0.02, days)
        series_b = series_a * 0.9 + np.random.normal(0.0, 0.005, days)  # Highly correlated
        series_c = -series_a * 0.8 + np.random.normal(0.0, 0.005, days) # Negatively correlated

        df = pd.DataFrame({
            "ASSET_A": series_a,
            "ASSET_B": series_b,
            "ASSET_C": series_c
        })

        corr = compute_correlation_matrix(df)
        self.assertEqual(corr["tickers"], ["ASSET_A", "ASSET_B", "ASSET_C"])
        matrix = corr["matrix"]

        # Diagonals must be 1.0
        self.assertEqual(matrix[0][0], 1.0)
        self.assertEqual(matrix[1][1], 1.0)
        self.assertEqual(matrix[2][2], 1.0)

        # Symmetry: corr(A, B) == corr(B, A)
        self.assertEqual(matrix[0][1], matrix[1][0])
        self.assertGreater(matrix[0][1], 0.70)  # High correlation
        self.assertLess(matrix[0][2], 0.0)     # Negative correlation

    def test_sector_correlation_matrix(self):
        df = pd.DataFrame({
            "EQTY": [0.01, -0.02, 0.03, 0.01],
            "KCB":  [0.01, -0.01, 0.02, 0.02],
            "SCOM": [-0.01, 0.02, 0.00, -0.01]
        })
        ticker_map = {
            "EQTY": "Banking",
            "KCB": "Banking",
            "SCOM": "Telecommunications"
        }
        res = compute_sector_correlation_matrix(df, ticker_map)
        self.assertIn("Banking", res["sectors"])
        self.assertIn("Telecommunications", res["sectors"])
        self.assertEqual(len(res["matrix"]), 2)
        self.assertEqual(res["matrix"][0][0], 1.0)
        self.assertEqual(res["matrix"][1][1], 1.0)


class TestDiversificationApi(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all(bind=engine)
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Register and login user
        self.client.post("/api/auth/register", json={
            "email": "divuser@example.com",
            "password": "mypassword123",
            "name": "Diversification User"
        })
        login_res = self.client.post("/api/auth/login", json={
            "email": "divuser@example.com",
            "password": "mypassword123"
        })
        self.token = login_res.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        try:
            if os.path.exists(TEST_DB_FILE):
                os.remove(TEST_DB_FILE)
        except Exception:
            pass

    def test_empty_portfolio_no_holdings(self):
        # Empty portfolio should return clean empty state without fake holdings
        res = self.client.get("/api/portfolio/diversification", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["has_holdings"])
        self.assertEqual(data["total_portfolio_value"], 0.0)
        self.assertEqual(len(data["sector_allocations"]), 0)
        self.assertEqual(data["status"], "NO_HOLDINGS")
        self.assertIn("risk_insights", data)

    def test_portfolio_with_holdings_diversification(self):
        # Add holdings in Banking (EQTY, KCB) and Telecom (SCOM)
        self.client.post("/api/portfolio", json={"ticker": "EQTY", "buy_price": 50.0, "quantity": 100}, headers=self.headers)
        self.client.post("/api/portfolio", json={"ticker": "KCB",  "buy_price": 40.0, "quantity": 100}, headers=self.headers)
        self.client.post("/api/portfolio", json={"ticker": "SCOM", "buy_price": 20.0, "quantity": 250}, headers=self.headers)

        res = self.client.get("/api/portfolio/diversification", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["is_fallback"])
        self.assertEqual(len(data["asset_allocations"]), 3)

        # Sectors should contain Banking and Telecommunications
        sectors = [s["sector"] for s in data["sector_allocations"]]
        self.assertIn("Banking", sectors)
        self.assertIn("Telecommunications", sectors)

        # Asset correlation should have all 3 tickers
        self.assertIn("EQTY", data["asset_correlation"]["tickers"])
        self.assertIn("KCB", data["asset_correlation"]["tickers"])
        self.assertIn("SCOM", data["asset_correlation"]["tickers"])
        self.assertEqual(len(data["asset_correlation"]["matrix"]), 3)

        # Sector correlation should exist
        self.assertIn("sector_correlation", data)
        self.assertIn("risk_insights", data)
        self.assertGreater(len(data["risk_insights"]), 0)


if __name__ == "__main__":
    unittest.main()