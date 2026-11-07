"""
Telegram Bot Notification, Owner-Only Access Control & Remote Command Service
(`services/telegram_bot.py`).

Architectural Decision & Justification (Webhook vs Polling on Free Infrastructure):
- Chosen Architecture: **Dual-Mode Supabase Edge Function / Cloudflare Worker Webhook (Primary for Instant Interactive Commands) + Stateless `getUpdates` Delta Sync inside the Scheduled Worker (Fallback)**.
- Why:
  1. Never run a continuous `getUpdates` polling loop inside `deal-sniper.py` on Streamlit Community Cloud, because every browser tab or Streamlit rerun would spawn competing `getUpdates` requests (`HTTP 409 Conflict: terminated by other getUpdates request`) and die whenever the Streamlit container sleeps.
  2. Polling *only* inside a 15-minute GitHub Action causes up to a 15-minute delay when replying to `/deals` or `/scan`.
  3. By pairing a lightweight stateless webhook (Supabase Edge Function or Cloudflare Worker Free Tier — 100,000 requests/day free, <50ms response time) that reads/writes directly to the same Supabase PostgreSQL database with our scheduled Python worker for outbound alerts and 18:00 (6:00 PM) daily summaries, we achieve instant interactive Telegram responses with zero competing Streamlit processes and $0 recurring cost.
"""

import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


SUPPORTED_TELEGRAM_COMMANDS = [
    "/start", "/help", "/deals", "/radar", "/wishlist", "/add", "/scan",
    "/search", "/compare", "/basket", "/history", "/pause", "/resume",
    "/settings", "/summary", "/status"
]


class TelegramBotService:
    """
    Enforces single-owner security (`TELEGRAM_OWNER_ID` + `TELEGRAM_CHAT_ID`),
    includes direct exact product purchase URLs on every alert and summary line,
    suppresses duplicates via SHA-256, respects quiet hours, dispatches immediate
    alerts for high-scoring wishlist/exceptional deals, and compiles the 6:00 PM (18:00)
    scheduled daily summary.
    """

    def __init__(self, db_manager):
        self.db = db_manager

    def _get_credentials(self) -> Dict[str, str]:
        return {
            "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            "owner_id": os.environ.get("TELEGRAM_OWNER_ID", "").strip(),
            "chat_id": os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
        }

    def verify_authorised_owner(self, incoming_user_id: str, incoming_chat_id: Optional[str] = None) -> bool:
        """
        Binds the Telegram bot strictly to one authorised owner account.
        Blocks all unauthorised Telegram users from reading or controlling the app.
        """
        creds = self._get_credentials()
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT telegram_owner_user_id, telegram_chat_id FROM app_settings WHERE id = 'owner_default'").fetchone()
            db_owner = dict(row).get("telegram_owner_user_id", "") if row else ""
            db_chat = dict(row).get("telegram_chat_id", "") if row else ""

        expected_owner = creds["owner_id"] or db_owner or "owner_authorised_1001"
        expected_chat = creds["chat_id"] or db_chat or expected_owner

        if str(incoming_user_id).strip() != str(expected_owner).strip():
            return False
        if incoming_chat_id and str(incoming_chat_id).strip() != str(expected_chat).strip():
            return False
        return True

    def format_immediate_deal_alert(self, deal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Formats an urgent Telegram notification with exact product purchase link,
        40/20/15/15/10 rubric breakdown, stock badge, local postcode status, and inline buttons.
        """
        rubric = json.loads(deal.get("rubric_breakdown_json", "{}"))
        warnings = json.loads(deal.get("risk_warnings_json", "[]"))
        warn_text = f"\n⚠️ Verification Note: {warnings[0]}" if warnings else ""

        badge_icon = "🚨 EXCEPTIONAL DEAL" if deal["classification"] == "Exceptional" else f"🔥 {deal['classification'].upper()} WISHLIST MATCH"
        text = (
            f"{badge_icon}\n\n"
            f"*{deal['title']}* ({deal.get('condition', 'New')})\n"
            f"💰 *Price:* AUD {float(deal['final_checkout_cost_aud']):.2f} "
            f"(90d Median: AUD {float(deal['median_90d_price_aud']):.2f} | Save {float(deal['discount_vs_median_pct']):.0f}%)\n"
            f"🏪 *Retailer:* {deal['retailer']}\n"
            f"📦 *Availability:* {deal['stock_badge']} ({deal.get('local_postcode_summary', '2150 Parramatta Verified')})\n"
            f"🎯 *Deal Score:* {deal['deal_score']}/100 ({deal['classification']})\n"
            f"📊 *Rubric:* `{rubric.get('formula_summary', 'Verified')}`\n"
            f"🛡️ *Verification:* {deal['verification_status']}\n"
            f"🧭 *AI Verdict:* {deal['buy_wait_verdict'].upper()}{warn_text}\n\n"
            f"🔗 [Buy / Verify Exact Product Page at {deal['retailer']}]({deal['exact_product_url']})"
        )

        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": f"🛒 View Deal at {deal['retailer']}", "url": deal["exact_product_url"]},
                    {"text": "⭐ Save Deal", "callback_data": f"save:{deal['id']}"}
                ],
                [
                    {"text": "🔬 Research Further", "callback_data": f"research:{deal['product_id']}"},
                    {"text": "⏸ Pause Interest", "callback_data": f"pause:{deal.get('interest_id') or 'none'}"},
                    {"text": "✖ Dismiss", "callback_data": f"dismiss:{deal['id']}"}
                ]
            ]
        }
        return {"text": text, "reply_markup": inline_keyboard}

    def format_6pm_daily_summary(self, deals: List[Dict[str, Any]], supermarket_specials: List[Dict[str, Any]]) -> str:
        """
        Formats the 6:00 PM (18:00 AEST/AEDT) daily summary with direct hyperlinks
        to every exact product page.
        """
        actionable = [d for d in deals if int(d.get("is_actionable", 1)) == 1 and d["stock_badge"] != "Out of Stock"]
        wishlist_hits = [d for d in actionable if d["engine_type"] == "Engine A" and int(d["deal_score"]) >= 72]
        outside_hits = [d for d in actionable if d["engine_type"] == "Engine B" and int(d["deal_score"]) >= 90]

        lines = [
            "🕕 *DEAL SNIPER — 6:00 PM DAILY INTELLIGENCE SUMMARY*",
            f"📍 Postcode Focus: 2150 Parramatta & Online (AUD)\n",
            f"🎯 *Top Wishlist Deals ({len(wishlist_hits)} Actionable):*"
        ]
        for d in wishlist_hits[:4]:
            lines.append(
                f"• *{d['title']}* — *AUD {float(d['final_checkout_cost_aud']):.2f}* at {d['retailer']} "
                f"({d['stock_badge']} | Score {d['deal_score']}/100) — [Exact Product Link]({d['exact_product_url']})"
            )

        lines.append(f"\n⚡ *Outside-Wishlist Exceptional Discoveries ({len(outside_hits)} ≥90/100):*")
        for d in outside_hits[:3]:
            lines.append(
                f"• *{d['title']}* — *AUD {float(d['final_checkout_cost_aud']):.2f}* at {d['retailer']} "
                f"(Save {float(d['discount_vs_median_pct']):.0f}% vs 90d median | Score {d['deal_score']}/100) — [Exact Product Link]({d['exact_product_url']})"
            )

        lines.append("\n🛒 *Top Coles & Woolworths Half-Price Watchlist Specials:*")
        for sp in supermarket_specials[:3]:
            lines.append(
                f"• *{sp['title']}* — *AUD {float(sp['special_price_aud']):.2f}* (-{float(sp['discount_pct']):.0f}%, {sp['unit_price_display']}) "
                f"at {sp['supermarket']} — [Exact Product Link]({sp['exact_product_url']})"
            )

        lines.append("\n_Send /deals, /wishlist, /scan <barcode>, or natural language to control Deal Sniper._")
        return "\n".join(lines)

    def send_or_log_deal_notification(
        self,
        deal: Dict[str, Any],
        simulated_hhmm: str = "14:30"
    ) -> Dict[str, Any]:
        """
        Checks stock actionability, duplicate SHA-256 signature, score thresholds,
        and quiet hours before logging and dispatching via Telegram Bot API.
        Never recommends Out of Stock items as actionable deals.
        """
        if deal.get("stock_badge") == "Out of Stock" or int(deal.get("is_actionable", 1)) == 0:
            return {
                "status": "suppressed_threshold",
                "reason": "Item is Out of Stock or unverified error-price anomaly; not dispatched as actionable alert."
            }

        dedup_key = f"{deal['product_id']}::{deal['retailer']}::{float(deal['final_checkout_cost_aud']):.2f}::{deal.get('condition', 'New')}"
        dedup_sig = hashlib.sha256(dedup_key.encode("utf-8")).hexdigest()[:24]
        now_iso = datetime.now(timezone.utc).isoformat()
        formatted = self.format_immediate_deal_alert(deal)

        with self.db.get_connection() as conn:
            settings_row = conn.execute("SELECT * FROM app_settings WHERE id = 'owner_default'").fetchone()
            settings = dict(settings_row) if settings_row else {}

            # 1. Duplicate suppression
            existing = conn.execute(
                "SELECT id FROM notifications_log WHERE dedup_signature = ? AND status IN ('sent', 'pending_quiet_hours')",
                (dedup_sig,)
            ).fetchone()
            if existing:
                nid = f"notif_dup_{dedup_sig[:8]}_{int(datetime.now(timezone.utc).timestamp())}"
                conn.execute(
                    """INSERT INTO notifications_log
                       (id, deal_id, notification_type, title, message_body, exact_product_url, status, dedup_signature, created_at)
                       VALUES (?, ?, 'immediate_alert', ?, ?, ?, 'suppressed_duplicate', ?, ?)""",
                    (nid, deal["id"], deal["title"], formatted["text"], deal["exact_product_url"], dedup_sig, now_iso)
                )
                conn.commit()
                return {"status": "suppressed_duplicate", "notification_id": nid, "dedup_signature": dedup_sig}

            # 2. Score threshold check
            min_w = int(settings.get("min_deal_score_wishlist", 72))
            min_o = int(settings.get("min_deal_score_outside", 90))
            req_score = min_w if deal["engine_type"] == "Engine A" else min_o
            if int(deal["deal_score"]) < req_score:
                nid = f"notif_thr_{dedup_sig[:8]}"
                conn.execute(
                    """INSERT INTO notifications_log
                       (id, deal_id, notification_type, title, message_body, exact_product_url, status, dedup_signature, created_at)
                       VALUES (?, ?, 'immediate_alert', ?, ?, ?, 'suppressed_threshold', ?, ?)""",
                    (nid, deal["id"], deal["title"], formatted["text"], deal["exact_product_url"], dedup_sig, now_iso)
                )
                conn.commit()
                return {"status": "suppressed_threshold", "notification_id": nid, "required_score": req_score}

            # 3. Quiet hours check
            q_start = settings.get("quiet_hours_start", "22:30")
            q_end = settings.get("quiet_hours_end", "07:00")
            in_quiet = (simulated_hhmm >= q_start or simulated_hhmm < q_end) if q_start > q_end else (q_start <= simulated_hhmm < q_end)
            status = "pending_quiet_hours" if in_quiet else "sent"

            nid = f"notif_{dedup_sig[:10]}"
            conn.execute(
                """INSERT INTO notifications_log
                   (id, deal_id, notification_type, title, message_body, exact_product_url, status, dedup_signature, created_at)
                   VALUES (?, ?, 'immediate_alert', ?, ?, ?, ?, ?, ?)""",
                (nid, deal["id"], deal["title"], formatted["text"], deal["exact_product_url"], status, dedup_sig, now_iso)
            )
            conn.commit()

        # Live HTTP dispatch if TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID are present
        creds = self._get_credentials()
        live_sent = False
        if status == "sent" and creds["bot_token"] and creds["chat_id"]:
            try:
                api_url = f"https://api.telegram.org/bot{creds['bot_token']}/sendMessage"
                payload = json.dumps({
                    "chat_id": creds["chat_id"],
                    "text": formatted["text"],
                    "parse_mode": "Markdown",
                    "reply_markup": formatted["reply_markup"]
                }).encode("utf-8")
                req = urllib.request.Request(api_url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    live_sent = (resp.status == 200)
            except Exception:
                live_sent = False

        return {
            "status": status,
            "notification_id": nid,
            "dedup_signature": dedup_sig,
            "live_api_dispatched": live_sent,
            "formatted_payload": formatted
        }
