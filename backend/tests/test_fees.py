import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from main import app
from auth.database import Base, get_db
from auth.models import User, PortfolioItem
from core.fees import (
    BROKERAGE_RATE,
    VAT_RATE_ON_BROKERAGE,
    CMA_LEVY_RATE,
    NSE_LEVY_RATE,
    CDSC_LEVY_RATE,
    ICF_LEVY_RATE,
    TOTAL_SINGLE_WAY_RATE,
    ROUNDTRIP_BREAKEVEN_MULTIPLIER,
    ROUNDTRIP_BREAKEVEN_HURDLE_PCT,
    calculate_breakeven_price,
    calculate_buy_costs,
    calculate_sell_proceeds,
    calculate_trade_pnl,
    calculate_net_dividend,
    get_fee_schedule,
)

TEST_DB_FILE = './test_temp_fees.db'
SQLALCHEMY_DATABASE_URL = f'sqlite:///{TEST_DB_FILE}'
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={'check_same_thread': False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestFeesEngine(unittest.TestCase):
    def test_fee_schedule_rates(self):
        schedule = get_fee_schedule()
        self.assertEqual(schedule['brokerage_pct'], 1.50)
        self.assertAlmostEqual(schedule['vat_on_brokerage_pct'], 0.24, places=2)
        self.assertEqual(schedule['cma_levy_pct'], 0.14)
        self.assertEqual(schedule['nse_levy_pct'], 0.12)
        self.assertEqual(schedule['cdsc_levy_pct'], 0.08)
        self.assertEqual(schedule['icf_levy_pct'], 0.01)
        self.assertAlmostEqual(schedule['total_single_way_pct'], 2.09, places=2)
        self.assertAlmostEqual(schedule['roundtrip_breakeven_hurdle_pct'], 4.27, places=1)
        self.assertEqual(schedule['dividend_wht_resident_pct'], 5.0)
        self.assertEqual(schedule['dividend_wht_non_resident_pct'], 15.0)

    def test_calculate_buy_costs(self):
        # 100 shares at KES 30.00 -> gross consideration = 3,000.00
        buy = calculate_buy_costs(price=30.0, quantity=100)
        self.assertEqual(buy['gross_consideration'], 3000.0)
        self.assertEqual(buy['brokerage'], 45.0)       # 1.5% of 3000
        self.assertEqual(buy['vat'], 7.2)              # 16% of 45.0
        self.assertEqual(buy['cma_levy'], 4.2)         # 0.14% of 3000
        self.assertEqual(buy['nse_levy'], 3.6)         # 0.12% of 3000
        self.assertEqual(buy['cdsc_levy'], 2.4)        # 0.08% of 3000
        self.assertEqual(buy['icf_levy'], 0.3)         # 0.01% of 3000
        self.assertEqual(buy['total_fees'], 62.7)      # 2.09% of 3000
        self.assertEqual(buy['total_outlay'], 3062.7)
        self.assertAlmostEqual(buy['breakeven_price'], 31.28, places=2)

    def test_calculate_sell_proceeds(self):
        # 100 shares at KES 35.00 -> gross consideration = 3,500.00
        sell = calculate_sell_proceeds(price=35.0, quantity=100)
        self.assertEqual(sell['gross_consideration'], 3500.0)
        self.assertEqual(sell['brokerage'], 52.5)      # 1.5% of 3500
        self.assertEqual(sell['vat'], 8.4)             # 16% of 52.5
        self.assertEqual(sell['cma_levy'], 4.9)        # 0.14% of 3500
        self.assertEqual(sell['nse_levy'], 4.2)        # 0.12% of 3500
        self.assertEqual(sell['cdsc_levy'], 2.8)       # 0.08% of 3500
        self.assertEqual(sell['icf_levy'], 0.35)       # 0.01% of 3500
        self.assertEqual(sell['total_fees'], 73.15)
        self.assertEqual(sell['net_proceeds'], 3426.85)

    def test_breakeven_math_roundtrip(self):
        buy_price = 100.0
        qty = 500
        be_price = calculate_breakeven_price(buy_price)
        self.assertEqual(be_price, 104.27)

        buy = calculate_buy_costs(buy_price, qty)
        sell = calculate_sell_proceeds(be_price, qty)
        # Net proceeds should cover total outlay within rounding cents
        net_diff = abs(sell['net_proceeds'] - buy['total_outlay'])
        self.assertLess(net_diff, 1.0)

    def test_calculate_trade_pnl(self):
        pnl = calculate_trade_pnl(buy_price=30.0, current_price=35.0, quantity=100)
        self.assertEqual(pnl['gross_profit_loss'], 500.0)
        self.assertAlmostEqual(pnl['gross_profit_loss_pct'], 16.67, places=2)
        self.assertEqual(pnl['net_profit_loss'], 364.15)
        self.assertAlmostEqual(pnl['net_profit_loss_pct'], 11.89, places=2)
        self.assertEqual(pnl['total_statutory_fees'], 135.85)

    def test_dividend_withholding_tax(self):
        # Resident: 5% WHT
        div_res = calculate_net_dividend(gross_dividend_per_share=2.50, shares=1000, resident=True)
        self.assertEqual(div_res['gross_dividend'], 2500.0)
        self.assertEqual(div_res['wht_amount'], 125.0)
        self.assertEqual(div_res['net_dividend'], 2375.0)

        # Non-Resident: 15% WHT
        div_non_res = calculate_net_dividend(gross_dividend_per_share=2.50, shares=1000, resident=False)
        self.assertEqual(div_non_res['gross_dividend'], 2500.0)
        self.assertEqual(div_non_res['wht_amount'], 375.0)
        self.assertEqual(div_non_res['net_dividend'], 2125.0)


class TestFeesApiIntegration(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all(bind=engine)
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        self.client.post('/api/auth/register', json={
            'email': 'feestest@example.com',
            'password': 'secretpassword',
            'name': 'Fees Tester'
        })
        login_res = self.client.post('/api/auth/login', json={
            'email': 'feestest@example.com',
            'password': 'secretpassword'
        })
        self.token = login_res.json()['access_token']
        self.headers = {'Authorization': f'Bearer {self.token}'}

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        try:
            if os.path.exists(TEST_DB_FILE):
                os.remove(TEST_DB_FILE)
        except Exception:
            pass

    def test_fees_schedule_api(self):
        res = self.client.get('/api/fees/schedule')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('brokerage_pct', data)
        self.assertEqual(data['brokerage_pct'], 1.5)
        self.assertEqual(data['total_single_way_pct'], 2.09)

    def test_fees_calculate_api(self):
        res = self.client.get('/api/fees/calculate?price=50.0&quantity=200')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['gross_consideration'], 10000.0)
        self.assertEqual(data['total_fees'], 209.0)
        self.assertEqual(data['total_outlay'], 10209.0)
        self.assertAlmostEqual(data['breakeven_price'], 52.13, places=2)

    def test_portfolio_with_fees_enrichment(self):
        # Record a purchase: 200 shares of SCOM at KES 25.00
        buy_res = self.client.post('/api/portfolio', json={
            'ticker': 'SCOM',
            'buy_price': 25.00,
            'quantity': 200
        }, headers=self.headers)
        self.assertEqual(buy_res.status_code, 200)

        # Query portfolio
        port_res = self.client.get('/api/portfolio', headers=self.headers)
        self.assertEqual(port_res.status_code, 200)
        data = port_res.json()
        self.assertEqual(len(data['holdings']), 1)
        holding = data['holdings'][0]
        
        # Verify enriched statutory fee & breakeven fields
        self.assertEqual(holding['ticker'], 'SCOM')
        self.assertEqual(holding['total_cost'], 5000.0)
        self.assertEqual(holding['total_outlay'], 5104.5)
        self.assertEqual(holding['buy_fees'], 104.5)
        self.assertIn('breakeven_price', holding)
        self.assertEqual(holding['breakeven_price'], 26.07)
        self.assertIn('net_profit_loss', holding)
        self.assertIn('total_statutory_fees', holding)

        # Verify summary
        summary = data['summary']
        self.assertIn('total_outlay', summary)
        self.assertIn('portfolio_net_profit_loss', summary)
        self.assertIn('total_statutory_fees', summary)
        self.assertIn('fee_schedule', summary)


if __name__ == '__main__':
    unittest.main()
