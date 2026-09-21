import unittest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.liquidity import (
    estimate_corwin_schultz_spread,
    calculate_turnover_velocity,
    classify_liquidity,
    analyze_liquidity
)
from ml.predictor import predict
from data.fetcher import get_historical_data
from routers.stocks import stock_detail, stock_prediction


class TestLiquidityEngine(unittest.TestCase):

    def test_corwin_schultz_estimator_synthetic(self):
        """Verify Corwin-Schultz returns expected spread on known high-low ranges."""
        # 1. Active volatile stock with 2% intraday range
        history_active = [
            {"date": f"2026-08-{i:02d}", "open": 100.0, "high": 101.5, "low": 99.5, "close": 100.5, "volume": 100000}
            for i in range(1, 15)
        ]
        spread_active = estimate_corwin_schultz_spread(history_active)
        self.assertGreaterEqual(spread_active, 0.0)
        self.assertLessEqual(spread_active, 5.0)

        # 2. Frozen/zero-spread stock (High == Low every day)
        history_frozen = [
            {"date": f"2026-08-{i:02d}", "open": 15.0, "high": 15.0, "low": 15.0, "close": 15.0, "volume": 0}
            for i in range(1, 15)
        ]
        spread_frozen = estimate_corwin_schultz_spread(history_frozen)
        # Should be penalized as high hidden friction (>= 5.0%)
        self.assertGreaterEqual(spread_frozen, 5.0)

    def test_turnover_velocity_calculation(self):
        """Verify turnover velocity ratios scale correctly with volume and shares outstanding."""
        # SCOM has ~40B shares outstanding
        history_scom = [
            {"date": f"2026-08-{i:02d}", "open": 30.0, "high": 31.0, "low": 29.5, "close": 30.5, "volume": 5_000_000}
            for i in range(1, 21)
        ]
        m_vel, a_vel, ff_vel, zero_ratio = calculate_turnover_velocity("SCOM", history_scom)
        self.assertGreater(m_vel, 0.0)
        self.assertAlmostEqual(a_vel, m_vel * 12.0, places=1)
        # Free-float velocity should be higher than total shares velocity
        self.assertGreater(ff_vel, m_vel)
        self.assertEqual(zero_ratio, 0.0)

    def test_liquidity_classification(self):
        """Verify traffic light tier classifications."""
        # High liquidity
        rating_h, badge_h, premium_h, _ = classify_liquidity(spread_pct=1.1, monthly_velocity=1.5, zero_vol_ratio=0.0)
        self.assertEqual(rating_h, "HIGH")
        self.assertIn("High", badge_h)

        # Illiquid trap (high zero volume days)
        rating_i, badge_i, premium_i, _ = classify_liquidity(spread_pct=6.5, monthly_velocity=0.02, zero_vol_ratio=0.6)
        self.assertEqual(rating_i, "ILLIQUID")
        self.assertIn("Illiquid", badge_i)

    def test_predictor_liquidity_integration(self):
        """Verify predictor attaches liquidity metrics and triggers illiquidity guardrail."""
        # 1. Liquid stock
        history = get_historical_data("SCOM", "3mo")
        if history:
            res = predict("SCOM", history)
            self.assertIsNotNone(res.spread_pct)
            self.assertIsNotNone(res.turnover_velocity_pct)
            self.assertIsNotNone(res.liquidity_rating)
            self.assertIn("Liquidity Profile", " ".join(res.reasoning))

        # 2. Illiquid stock synthetic
        illiquid_hist = [
            {"date": f"2026-07-{i:02d}", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 0}
            for i in range(1, 15)
        ]
        res_ill = predict("TEST_ILLQ", illiquid_hist)
        self.assertEqual(res_ill.direction, "NO_SIGNAL")
        self.assertEqual(res_ill.liquidity_rating, "ILLIQUID")

    def test_api_stock_detail_liquidity(self):
        """Verify stock_detail endpoint returns structured liquidity object."""
        detail = stock_detail("SCOM")
        self.assertIn("liquidity", detail)
        liq = detail["liquidity"]
        self.assertIsNotNone(liq)
        self.assertIn("spread_pct", liq)
        self.assertIn("turnover_velocity_monthly_pct", liq)
        self.assertIn("rating", liq)
        self.assertIn("free_float_pct", liq)


if __name__ == "__main__":
    unittest.main()
