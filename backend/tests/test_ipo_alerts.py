"""
Unit tests for the NSE IPO Detection, Pipeline Tracking, and Multi-Channel Alert System.
"""
import unittest
import os
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from main import app
from auth.database import SessionLocal, init_db, engine, Base
from auth.models import IPOListing, IPOSubscriber
from ml.ipo_detector import (
    seed_ipo_pipeline,
    scan_articles_for_ipo_signals,
    check_and_send_ipo_alert,
    KNOWN_IPO_CANDIDATES
)

client = TestClient(app)


class TestIPOAlerts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.sent_log = os.path.join(os.path.dirname(__file__), "..", "tmp", "sent_ipo_alerts.log")
        self.sms_log = os.path.join(os.path.dirname(__file__), "..", "tmp", "sms_outbox.log")
        self.clean_test_files()

    def tearDown(self):
        self.clean_test_files()
        self.db.close()

    def clean_test_files(self):
        for f in [self.sent_log, self.sms_log]:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass

    def test_pipeline_seeding_and_structure(self):
        """Verify that seed_ipo_pipeline seeds expected Kenyan candidates with complete schema."""
        seed_ipo_pipeline(self.db)
        listings = self.db.query(IPOListing).all()
        self.assertGreaterEqual(len(listings), 3)

        kpc = self.db.query(IPOListing).filter(IPOListing.proposed_ticker == "KPC").first()
        self.assertIsNotNone(kpc)
        self.assertIn("Kenya Pipeline", kpc.company_name)
        self.assertEqual(kpc.offer_price, 16.50)
        self.assertTrue(kpc.cma_approval)
        self.assertEqual(kpc.ai_verdict, "ATTRACTIVE")
        self.assertGreater(kpc.ai_verdict_score, 0.8)

        # Check Credit Bank
        cbl = self.db.query(IPOListing).filter(IPOListing.proposed_ticker == "CBL").first()
        self.assertIsNotNone(cbl)
        self.assertEqual(cbl.status, "OFFER_OPEN")

    def test_nlp_news_article_scanner(self):
        """Verify that scan_articles_for_ipo_signals catches IPO keywords and extracts price."""
        sample_articles = [
            {
                "title": "CMA approves Kenya Pipeline initial public offering on the NSE",
                "summary": "State floats shares with offer price of 16.50 shillings per share to raise KES 15 Billion.",
                "source": "Business Daily",
                "url": "https://example.com/kpc-ipo"
            },
            {
                "title": "Safaricom reports half year net earnings",
                "summary": "M-Pesa revenues jump 19% as active customers surge in Ethiopia.",
                "source": "Standard",
                "url": "https://example.com/scom-earnings"
            },
            {
                "title": "Credit Bank announces offer for subscription ahead of MIMS debut",
                "summary": "The prospectus published today details public share subscription window.",
                "source": "Capital FM",
                "url": "https://example.com/cbl-ipo"
            }
        ]

        detected = scan_articles_for_ipo_signals(sample_articles)
        self.assertEqual(len(detected), 2)
        titles = [d["title"] for d in detected]
        self.assertIn("CMA approves Kenya Pipeline initial public offering on the NSE", titles)
        self.assertIn("Credit Bank announces offer for subscription ahead of MIMS debut", titles)

        # Price extraction check
        kpc_event = next(d for d in detected if "Kenya Pipeline" in d["title"])
        self.assertEqual(kpc_event["estimated_price"], 16.50)

    @patch("ml.ipo_detector.send_sms_via_africastalking")
    def test_ipo_alert_sms_broadcast_and_deduplication(self, mock_send_sms):
        """Verify check_and_send_ipo_alert sends SMS once and suppresses duplicates on the same day."""
        mock_send_sms.return_value = {"status": "success"}

        # Ensure subscriber exists
        test_phone = "+254711999888"
        sub = self.db.query(IPOSubscriber).filter(IPOSubscriber.phone_number == test_phone).first()
        if not sub:
            sub = IPOSubscriber(phone_number=test_phone, sms_enabled=True)
            self.db.add(sub)
            self.db.commit()

        ipo = self.db.query(IPOListing).filter(IPOListing.proposed_ticker == "CBL").first()
        self.assertIsNotNone(ipo)

        # First trigger: Should send SMS
        res1 = check_and_send_ipo_alert(ipo, db=self.db)
        self.assertEqual(res1["status"], "sent")
        self.assertTrue(mock_send_sms.called)
        self.assertEqual(mock_send_sms.call_count, 1)

        # Verify message text contents
        call_args = mock_send_sms.call_args[0]
        sent_message = call_args[0]
        recipients = call_args[1]
        self.assertIn("NSE IPO ALERT", sent_message)
        self.assertIn("Credit Bank Plc", sent_message)
        self.assertIn(test_phone, recipients)

        # Second trigger on same day: should suppress duplicate
        mock_send_sms.reset_mock()
        res2 = check_and_send_ipo_alert(ipo, db=self.db)
        self.assertEqual(res2["status"], "skipped")
        self.assertEqual(res2["reason"], "duplicate_suppressed")
        self.assertFalse(mock_send_sms.called)

    def test_api_endpoints_flow(self):
        """Verify /api/ipo, /api/ipo/active, /api/ipo/{id}, and /api/ipo/subscribe."""
        # 1. GET /api/ipo
        r = client.get("/api/ipo")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("pipeline", data)
        self.assertIn("stats", data)
        self.assertGreaterEqual(data["stats"]["total"], 3)
        self.assertIsNotNone(data["active_alert"])

        first_id = data["pipeline"][0]["id"]

        # 2. GET /api/ipo/{id}
        r_detail = client.get(f"/api/ipo/{first_id}")
        self.assertEqual(r_detail.status_code, 200)
        detail = r_detail.json()
        self.assertEqual(detail["id"], first_id)
        self.assertIn("ai_verdict", detail)
        self.assertIsInstance(detail["highlights"], list)

        # 3. GET /api/ipo/active
        r_act = client.get("/api/ipo/active")
        self.assertEqual(r_act.status_code, 200)
        act_data = r_act.json()
        self.assertTrue(act_data["has_active_alert"])
        self.assertIsNotNone(act_data["alert"])

        # 4. POST /api/ipo/subscribe
        sub_phone = "+254722000111"
        r_sub = client.post("/api/ipo/subscribe", json={"phone_number": sub_phone})
        self.assertEqual(r_sub.status_code, 200)
        sub_res = r_sub.json()
        self.assertIn("Successfully subscribed", sub_res["message"])

        # Verify DB entry
        in_db = self.db.query(IPOSubscriber).filter(IPOSubscriber.phone_number == sub_phone).first()
        self.assertIsNotNone(in_db)

        # 5. POST /api/ipo/simulate-alert
        r_sim = client.post("/api/ipo/simulate-alert", json={"custom_company": "National Oil Corporation IPO", "custom_price": 22.00})
        self.assertEqual(r_sim.status_code, 200)
        sim_data = r_sim.json()
        self.assertEqual(sim_data["status"], "simulation_dispatched")
        self.assertIn("National Oil Corporation IPO", sim_data["message"])


if __name__ == "__main__":
    unittest.main()
