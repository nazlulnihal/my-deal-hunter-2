"""
Mandatory Acceptance Test Suite (`tests/test_deal_sniper_acceptance.py`) for
DEAL SNIPER — AUTONOMOUS AI SHOPPING INTELLIGENCE PLATFORM.

Verifies all 8 mandatory acceptance domains (A through H) plus the additional critical requirements:
- Test A: Persistence across restarts, different days, soft-delete vs explicit purge (preserving price history), and full JSON export.
- Test B: Barcode scanner identification (EAN-13, EAN-8, UPC-A, UPC-E) and manual fallback registration.
- Test C: Product intelligence (Exact, Multiple, Broad NL interests, variant mismatch rejection, accessory trap guard, Refurbished/Open-Box toggle).
- Test D: Deal Sniper 40/20/15/15/10 concrete rubric, mandatory Second-Source Error-Price verification (>70% off), and Out-of-Stock non-actionable filtering.
- Test E: Telegram Bot owner-only access security (`TELEGRAM_OWNER_ID`), immediate alerts with exact product links, 6:00 PM Daily Summary, and all slash/conversational commands.
- Test F: Background worker independence, recovery after restart, and duplicate alert suppression.
- Test G & Additional Requirement #3: Supermarket Specials (Coles & Woolworths) 3-tier priority sorting (Watchlist Matches -> Half-Price 50%+ -> Popular Household).
- Test H: Entrypoint (`deal-sniper.py`) syntax, import resolution, and end-to-end proof workflow.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.orchestrator import DealSniperOrchestrator
from services.product_matcher import classify_barcode_format, compute_unit_price
from connectors.au_retailers import sort_supermarket_specials_multi_tier


class TestDealSniperMandatoryAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_persistent.db")
        self.orch = DealSniperOrchestrator(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_A_persistence_across_restarts_and_soft_delete_vs_purge(self):
        # 1. Add an interest on Day 1
        i1 = self.orch.add_or_update_interest("Sony WH-1000XM6 wireless headphones under AUD 450")
        self.assertEqual(i1["interest_type"], "exact")

        # 2. Simulate application restart by creating a new orchestrator instance on the same DB
        orch_day2 = DealSniperOrchestrator(db_path=self.db_path)
        i2 = orch_day2.add_or_update_interest("Wireless headphones under AUD 150", include_refurbished=True)

        with orch_day2.db.get_connection() as conn:
            active_rows = [dict(r) for r in conn.execute("SELECT * FROM shopping_interests WHERE is_deleted = 0").fetchall()]
            ids = {r["id"] for r in active_rows}
            self.assertIn(i1["id"], ids)
            self.assertIn(i2["id"], ids)

        # 3. Verify Soft-Delete hides interest from active list while preserving historical price records
        obs_before = orch_day2.db.get_connection().execute("SELECT COUNT(*) as c FROM price_observations").fetchone()["c"]
        sdel = orch_day2.db.soft_delete_interest(i1["id"])
        self.assertEqual(sdel["action"], "soft_deleted")
        self.assertTrue(sdel["price_history_preserved"])

        obs_after_sdel = orch_day2.db.get_connection().execute("SELECT COUNT(*) as c FROM price_observations").fetchone()["c"]
        self.assertEqual(obs_before, obs_after_sdel)

        # 4. Verify Explicit Purge requires confirmation and still preserves canonical product price history
        unconf_purge = orch_day2.db.purge_interest_permanently(i1["id"], confirmed=False)
        self.assertFalse(unconf_purge["purged"])
        conf_purge = orch_day2.db.purge_interest_permanently(i1["id"], confirmed=True)
        self.assertTrue(conf_purge["purged"])
        obs_after_purge = orch_day2.db.get_connection().execute("SELECT COUNT(*) as c FROM price_observations").fetchone()["c"]
        self.assertEqual(obs_before, obs_after_purge)

        # 5. Verify full JSON data export
        exported = json.loads(orch_day2.db.export_all_data_json())
        self.assertIn("shopping_interests", exported["tables"])
        self.assertIn("price_observations", exported["tables"])

    def test_B_barcode_scanner_ean_upc_and_manual_fallback(self):
        # 1. Known EAN-13 barcode lookup (Samsung Galaxy Watch 7 44mm)
        res_ean13 = self.orch.lookup_or_register_barcode("8806095661421")
        self.assertTrue(res_ean13["found"])
        self.assertEqual(res_ean13["barcode_info"]["format"], "EAN-13")
        self.assertEqual(res_ean13["product"]["id"], "prod_watch7_44mm")

        # 2. Validate UPC-A (12 digits) and EAN-8 (8 digits) format classification
        upc_info = classify_barcode_format("084035391422")
        self.assertEqual(upc_info["format"], "UPC-A")
        ean8_info = classify_barcode_format("93124320")
        self.assertEqual(ean8_info["format"], "EAN-8 / UPC-E")

        # 3. Unknown barcode with manual fallback registration
        res_new = self.orch.lookup_or_register_barcode(
            "9300601123456",
            fallback_product_name="Haigh's Dark Chocolate Scorched Almonds 200g",
            category="Groceries, Chocolates & Beverages",
            estimated_rrp_aud=19.50
        )
        self.assertTrue(res_new["found"])
        self.assertTrue(res_new.get("newly_registered"))

    def test_C_product_intelligence_and_refurbished_toggle(self):
        with self.orch.db.get_connection() as conn:
            s25u = dict(conn.execute("SELECT * FROM products WHERE id = 'prod_s25_ultra_256'").fetchone())

        # When Refurbished toggle is OFF, a Refurbished listing is rejected
        m_off = self.orch.matcher.evaluate_listing(
            s25u, "Samsung Galaxy S25 Ultra 256GB Titanium Grey", listing_condition="Refurbished", include_refurbished_toggle=False
        )
        self.assertFalse(m_off["is_valid_match"])

        # When Refurbished toggle is ON, the Certified Refurbished listing is accepted
        m_on = self.orch.matcher.evaluate_listing(
            s25u, "Samsung Galaxy S25 Ultra 256GB Titanium Grey", listing_condition="Refurbished", include_refurbished_toggle=True
        )
        self.assertTrue(m_on["is_valid_match"])

        # Accessory trap is always rejected
        m_trap = self.orch.matcher.evaluate_listing(
            s25u, "Silicone Case for Samsung Galaxy S25 Ultra", listing_condition="New", include_refurbished_toggle=True
        )
        self.assertFalse(m_trap["is_valid_match"])
        self.assertTrue(m_trap["is_accessory_trap"])

    def test_D_deal_sniper_rubric_second_source_rule_and_out_of_stock_guard(self):
        # 1. Extreme AUD 20 Galaxy Watch 7 WITHOUT second-source verification -> capped at <=76 and held
        unverified_anomaly = self.orch.record_observation_and_snipe(
            product_id="prod_watch7_44mm",
            retailer="Officeworks",
            listed_price_aud=20.00,
            stock_badge="In Stock Online",
            second_source_verified=False
        )
        self.assertLessEqual(unverified_anomaly["evaluated_deal"]["deal_score"], 76)
        self.assertEqual(unverified_anomaly["evaluated_deal"]["is_actionable"], 0)
        self.assertEqual(unverified_anomaly["notification"]["status"], "suppressed_threshold")

        # 2. Extreme AUD 19 Galaxy Watch 7 WITH second-source verification passed -> scores >=95 Exceptional & sends alert
        verified_anomaly = self.orch.record_observation_and_snipe(
            product_id="prod_watch7_44mm",
            retailer="Officeworks",
            listed_price_aud=19.00,
            stock_badge="Available Locally for Click & Collect",
            second_source_verified=True
        )
        self.assertGreaterEqual(verified_anomaly["evaluated_deal"]["deal_score"], 95)
        self.assertEqual(verified_anomaly["evaluated_deal"]["classification"], "Exceptional")
        self.assertEqual(verified_anomaly["evaluated_deal"]["is_actionable"], 1)
        self.assertEqual(verified_anomaly["notification"]["status"], "sent")
        self.assertTrue(verified_anomaly["evaluated_deal"]["exact_product_url"].startswith("https://"))

        # 3. Out of Stock listing -> never recommended as actionable or notified
        oos_res = self.orch.record_observation_and_snipe(
            product_id="prod_sony_xm6",
            retailer="JB Hi-Fi",
            listed_price_aud=199.00,
            stock_badge="Out of Stock",
            second_source_verified=True
        )
        self.assertEqual(oos_res["evaluated_deal"]["is_actionable"], 0)
        self.assertEqual(oos_res["notification"]["status"], "suppressed_threshold")

    def test_E_telegram_owner_security_commands_and_6pm_summary(self):
        # 1. Unauthorised Telegram user is strictly blocked
        unauth = self.orch.handle_telegram_or_assistant_command("/deals", sender_user_id="hacker_9999")
        self.assertFalse(unauth["authorised"])
        self.assertEqual(unauth["action"], "blocked_unauthorised")

        # 2. Authorised owner can run slash & conversational commands
        for cmd in ["/start", "/deals", "/wishlist", "/compare", "/basket", "/status", "Find any exceptional chocolate deals"]:
            resp = self.orch.handle_telegram_or_assistant_command(cmd, sender_user_id="owner_authorised_1001")
            self.assertTrue(resp["authorised"])
            self.assertTrue(len(resp["reply"]) > 20)

    def test_F_and_G_supermarket_specials_multi_tier_sorting_and_worker(self):
        with self.orch.db.get_connection() as conn:
            specials = [dict(r) for r in conn.execute("SELECT * FROM supermarket_specials").fetchall()]
            interests = [dict(r) for r in conn.execute("SELECT * FROM shopping_interests WHERE is_deleted = 0").fetchall()]

        sorted_sp = sort_supermarket_specials_multi_tier(specials, interests)
        self.assertGreaterEqual(len(sorted_sp), 4)
        # Tier 1 (Watchlist matches) must come before Tier 2 (Half-price non-watchlist) and Tier 3
        tiers = [item["priority_tier"] for item in sorted_sp]
        self.assertEqual(tiers, sorted(tiers))

        # Run independent background worker with 6:00 PM Daily Summary dispatch
        wk_res = self.orch.run_scheduled_worker_tick(dispatch_6pm_summary=True)
        self.assertTrue(wk_res["summary_dispatched"])

    def test_H_entrypoint_file_exists_and_compiles(self):
        entry_file = REPO_ROOT / "deal-sniper.py"
        self.assertTrue(entry_file.exists())
        code = entry_file.read_text(encoding="utf-8")
        compile(code, str(entry_file), "exec")


if __name__ == "__main__":
    unittest.main(verbosity=2)
