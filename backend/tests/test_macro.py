"""
Unit Tests for Macro Benchmark Indicator & CBK 91-Day T-Bill vs Dividend Yield Engine
"""

import unittest
from fastapi.testclient import TestClient
from main import app
from ml.macro import (
    get_cbk_benchmarks,
    compute_stock_macro_profile,
    compute_market_yield_comparison,
    compute_portfolio_macro_yield,
    WHT_TBILL_RATE,
    WHT_EQUITY_RESIDENT,
)


class TestMacroBenchmarkEngine(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_cbk_benchmarks_structure_and_tax(self):
        """Verify CBK benchmark rates, 15% WHT net yield, and real risk-free rates."""
        bm = get_cbk_benchmarks()
        self.assertIn("tbill_91d", bm)
        self.assertIn("net_tbill_91d", bm)
        self.assertIn("cbr_rate", bm)
        self.assertIn("inflation_rate", bm)

        # 91d T-Bill should be in double digits in Kenya
        self.assertGreaterEqual(bm["tbill_91d"], 10.0)
        
        # Verify 15% Withholding Tax deduction
        expected_net = round(bm["tbill_91d"] * (1.0 - WHT_TBILL_RATE), 2)
        self.assertAlmostEqual(bm["net_tbill_91d"], expected_net, places=2)

        # Real risk-free rate = Nominal - Inflation
        expected_real = round(bm["tbill_91d"] - bm["inflation_rate"], 2)
        self.assertAlmostEqual(bm["real_risk_free_rate"], expected_real, places=2)

    def test_stock_macro_profile_high_yield(self):
        """Verify macro evaluation for dividend payer (e.g. BAT: KES 50 DPS @ KES 520)."""
        prof = compute_stock_macro_profile("BAT", current_price=520.0, dividend_per_share=50.0)
        self.assertEqual(prof["ticker"], "BAT")
        self.assertAlmostEqual(prof["gross_dividend_yield"], 9.62, places=1)

        # Verify 5% equity resident tax deduction
        expected_net_yield = round(9.62 * (1.0 - WHT_EQUITY_RESIDENT), 2)
        self.assertAlmostEqual(prof["net_dividend_yield"], expected_net_yield, delta=0.1)

        # Tax shield advantage = 10% rate differential (15% T-bill vs 5% stock dividend)
        self.assertGreater(prof["tax_shield_advantage_pct"], 0.0)

        # Growth hurdle: required appreciation to beat 91-day T-bill
        self.assertAlmostEqual(
            prof["required_growth_hurdle"],
            round(prof["tbill_91d_rate"] - prof["gross_dividend_yield"], 2),
            places=2
        )
        self.assertIn(prof["verdict_category"], ["BALANCED_YIELD", "EXCEPTIONAL_YIELD"])

    def test_stock_macro_profile_zero_dividend(self):
        """Verify zero-dividend counter (e.g. KPLC) requires full T-bill return in capital appreciation."""
        prof = compute_stock_macro_profile("KPLC", current_price=15.50, dividend_per_share=0.0)
        self.assertEqual(prof["gross_dividend_yield"], 0.0)
        self.assertEqual(prof["net_dividend_yield"], 0.0)
        self.assertEqual(prof["verdict_category"], "ZERO_DIVIDEND")
        
        # 100% of return required from price growth
        self.assertEqual(prof["required_growth_hurdle"], prof["tbill_91d_rate"])

    def test_market_yield_comparison(self):
        """Verify market ranking sorts descending by dividend yield."""
        sample_stocks = [
            {"ticker": "SCOM", "name": "Safaricom PLC", "price": 30.90, "dividend_per_share": 1.20},
            {"ticker": "BAT",  "name": "BAT Kenya",     "price": 520.00, "dividend_per_share": 50.00},
            {"ticker": "KPLC", "name": "Kenya Power",   "price": 15.50, "dividend_per_share": 0.00},
        ]
        result = compute_market_yield_comparison(sample_stocks)
        self.assertIn("benchmarks", result)
        self.assertIn("market_stats", result)
        self.assertEqual(len(result["stocks"]), 3)

        # First stock should have the highest dividend yield (BAT > SCOM > KPLC)
        self.assertEqual(result["stocks"][0]["ticker"], "BAT")
        self.assertEqual(result["stocks"][-1]["ticker"], "KPLC")
        self.assertGreater(result["market_stats"]["average_market_dividend_yield"], 0.0)

    def test_portfolio_macro_empty(self):
        """Verify empty portfolio returns clean empty-state payload without crashing."""
        result = compute_portfolio_macro_yield([])
        self.assertFalse(result["has_holdings"])
        self.assertEqual(result["total_portfolio_value"], 0.0)
        self.assertEqual(result["portfolio_dividend_yield"], 0.0)
        self.assertEqual(result["macro_status"], "NO_HOLDINGS")

    def test_portfolio_macro_with_holdings(self):
        """Verify portfolio weighted dividend yield and T-bill opportunity cost."""
        holdings = [
            {"ticker": "BAT", "quantity": 100, "buy_price": 500.0, "current_price": 500.0, "dividend_per_share": 50.0},
            {"ticker": "SCOM", "quantity": 1000, "buy_price": 30.0, "current_price": 30.0, "dividend_per_share": 1.20},
        ]
        # Total value: (100 * 500) + (1000 * 30) = 50,000 + 30,000 = KES 80,000
        # Expected annual dividends: (100 * 50) + (1000 * 1.20) = 5,000 + 1,200 = KES 6,200
        # Weighted yield: 6,200 / 80,000 = 7.75%
        res = compute_portfolio_macro_yield(holdings)
        self.assertTrue(res["has_holdings"])
        self.assertEqual(res["total_portfolio_value"], 80000.0)
        self.assertEqual(res["expected_annual_dividends"], 6200.0)
        self.assertAlmostEqual(res["portfolio_dividend_yield"], 7.75, places=2)
        self.assertGreater(res["equivalent_tbill_gross_return"], 0.0)
        self.assertEqual(len(res["holding_breakdown"]), 2)

    def test_api_macro_endpoints(self):
        """Verify HTTP endpoints /api/macro/benchmarks, /yield-comparison, and /stock/{ticker}."""
        res_bm = self.client.get("/api/macro/benchmarks")
        self.assertEqual(res_bm.status_code, 200)
        self.assertIn("tbill_91d", res_bm.json())

        res_yc = self.client.get("/api/macro/yield-comparison")
        self.assertEqual(res_yc.status_code, 200)
        data_yc = res_yc.json()
        self.assertIn("stocks", data_yc)
        self.assertGreater(len(data_yc["stocks"]), 0)

        res_st = self.client.get("/api/macro/stock/SCOM")
        self.assertEqual(res_st.status_code, 200)
        data_st = res_st.json()
        self.assertEqual(data_st["ticker"], "SCOM")
        self.assertIn("gross_dividend_yield", data_st)
        self.assertIn("required_growth_hurdle", data_st)


if __name__ == "__main__":
    unittest.main()
