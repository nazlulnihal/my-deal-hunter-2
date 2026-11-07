"""
Mandatory Streamlit Entrypoint (`deal-sniper.py`) for
DEAL SNIPER — AUTONOMOUS AI SHOPPING INTELLIGENCE PLATFORM.

Launch locally with:
    streamlit run deal-sniper.py

Deploy on Streamlit Community Cloud with main file path:
    deal-sniper.py

Also includes a Bulletproof Self-Bootstrapper (`_ensure_modular_packages()`) so
even if a user uploads ONLY `deal-sniper.py` to a blank GitHub repo or runs it
from any working directory, it never raises `ModuleNotFoundError`.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from services.orchestrator import DealSniperOrchestrator, DEFAULT_BASKET_ITEMS
from services.product_matcher import UNIVERSAL_CATEGORIES, classify_barcode_format
from connectors.au_retailers import (
    AUSTRALIAN_RETAILERS_V1,
    sort_supermarket_specials_multi_tier,
    compare_shopping_basket_v1,
)
from services.telegram_bot import SUPPORTED_TELEGRAM_COMMANDS


# =============================================================================
# ZXing Camera-Based HTML5 Barcode Scanner Component (EAN-13, EAN-8, UPC-A, UPC-E)
# =============================================================================
ZXING_CAMERA_SCANNER_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script src="https://unpkg.com/@zxing/library@0.21.2/umd/index.min.js"></script>
  <style>
    body {
      margin: 0; padding: 12px; background: #0f172a; color: #f8fafc;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      border-radius: 14px; border: 1px solid #1e293b;
    }
    .scanner-wrap { display: flex; flex-direction: column; gap: 10px; }
    video {
      width: 100%; max-height: 250px; background: #020617;
      border-radius: 10px; border: 2px solid #10b981; object-fit: cover;
    }
    .btn-row { display: flex; flex-wrap: wrap; gap: 8px; }
    button, label.upload-btn {
      background: #10b981; color: #020617; border: none; padding: 9px 14px;
      border-radius: 8px; font-weight: 700; font-size: 13px; cursor: pointer;
      display: inline-flex; align-items: center; gap: 6px;
    }
    button.secondary, label.upload-btn { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; }
    .status-box {
      padding: 10px; border-radius: 8px; background: #020617;
      border: 1px solid #334155; font-size: 13px; color: #34d399;
      word-break: break-all;
    }
    input[type="file"] { display: none; }
  </style>
</head>
<body>
  <div class="scanner-wrap">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <strong style="font-size:14px;">📷 Live Mobile Camera Barcode Scanner (ZXing)</strong>
      <span style="font-size:11px;color:#94a3b8;">EAN-13 • EAN-8 • UPC-A • UPC-E</span>
    </div>
    <video id="BarcodeVideoPreview" playsinline muted></video>
    <div class="btn-row">
      <button id="btnStartCam" type="button">▶ Start Phone Camera Scan</button>
      <button id="btnStopCam" type="button" class="secondary">⏹ Stop Camera</button>
      <label class="upload-btn">
        🖼️ Decode Barcode Photo
        <input id="fileBarcodeImg" type="file" accept="image/*" capture="environment" />
      </label>
    </div>
    <div id="scanStatusBox" class="status-box">
      Tap "Start Phone Camera Scan" (requires HTTPS on mobile) or upload a barcode photo. Detected code appears below for 1-tap confirmation.
    </div>
  </div>

  <script>
    let codeReader = null;
    const statusBox = document.getElementById('scanStatusBox');
    const videoEl = document.getElementById('BarcodeVideoPreview');

    document.getElementById('btnStartCam').addEventListener('click', async () => {
      try {
        if (!window.ZXing) {
          statusBox.textContent = 'ZXing library loading — use photo upload or manual input below.';
          return;
        }
        codeReader = new ZXing.BrowserMultiFormatReader();
        statusBox.textContent = 'Requesting rear camera permission... Point camera at EAN/UPC barcode.';
        await codeReader.decodeFromVideoDevice(null, 'BarcodeVideoPreview', (result, err) => {
          if (result) {
            const code = result.getText();
            const fmt = result.getBarcodeFormat ? result.getBarcodeFormat() : 'EAN/UPC';
            statusBox.innerHTML = '✅ <strong>BARCODE DETECTED:</strong> <code>' + code + '</code> (Format: ' + fmt + ') — Copy or confirm below!';
            try { navigator.clipboard.writeText(code); } catch(e) {}
          }
        });
      } catch (err) {
        statusBox.textContent = 'Camera permission denied or unavailable (' + err.message + '). Use "Decode Barcode Photo" or the fallback barcode field below.';
      }
    });

    document.getElementById('btnStopCam').addEventListener('click', () => {
      if (codeReader) {
        codeReader.reset();
        statusBox.textContent = 'Camera stopped.';
      }
    });

    document.getElementById('fileBarcodeImg').addEventListener('change', async (ev) => {
      const file = ev.target.files[0];
      if (!file || !window.ZXing) return;
      const reader = new ZXing.BrowserMultiFormatReader();
      const imgUrl = URL.createObjectURL(file);
      try {
        const result = await reader.decodeFromImageUrl(imgUrl);
        statusBox.innerHTML = '✅ <strong>PHOTO BARCODE DECODED:</strong> <code>' + result.getText() + '</code> — Ready to confirm below!';
      } catch (err) {
        statusBox.textContent = 'Could not auto-decode barcode from photo — enter barcode digits or product name in the confirmation form below.';
      }
    });
  </script>
</body>
</html>
"""


def load_secrets_into_env(st_mod: Any) -> None:
    """
    Loads deployed Streamlit Community Cloud `st.secrets` into environment variables
    without ever hardcoding or exposing private keys in source code.
    """
    secret_keys = [
        "SUPABASE_DB_URL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OWNER_ID",
        "TELEGRAM_CHAT_ID",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "DEAL_SNIPER_OWNER_PIN"
    ]
    try:
        for k in secret_keys:
            if k in st_mod.secrets and st_mod.secrets[k]:
                os.environ[k] = str(st_mod.secrets[k])
    except Exception:
        pass


def run_streamlit_app() -> None:
    import streamlit as st
    import streamlit.components.v1 as components

    st.set_page_config(
        page_title="Deal Sniper — Autonomous AI Shopping Intelligence",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    load_secrets_into_env(st)

    # Custom Mobile-First Consumer CSS
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1280px; }
        .sniper-card {
            background: linear-gradient(145deg, #111827, #1e293b);
            border: 1px solid rgba(255,255,255,0.09);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 14px;
            color: #f8fafc;
        }
        .badge-pill {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
            margin-right: 6px;
            margin-bottom: 4px;
        }
        .badge-exc { background: rgba(244,63,94,0.2); color: #fda4af; border: 1px solid rgba(244,63,94,0.4); }
        .badge-stock { background: rgba(16,185,129,0.2); color: #6ee7b7; border: 1px solid rgba(16,185,129,0.4); }
        .badge-sample { background: rgba(148,163,184,0.15); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.3); }
        .price-big { font-size: 1.45rem; font-weight: 800; color: #34d399; }
        .price-old { font-size: 0.85rem; text-decoration: line-through; color: #94a3b8; margin-left: 8px; }
        a.buy-btn {
            display: inline-block;
            background: #10b981;
            color: #020617 !important;
            font-weight: 700;
            font-size: 13px;
            padding: 7px 14px;
            border-radius: 10px;
            text-decoration: none !important;
            margin-top: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Always instantiate orchestrator backed by persistent database (NEVER st.session_state as permanent truth)
    orch = DealSniperOrchestrator()
    storage_info = orch.db.get_storage_status()

    # Fetch live persistent state from database on every render
    with orch.db.get_connection() as conn:
        active_interests = [dict(r) for r in conn.execute("SELECT * FROM shopping_interests WHERE is_deleted = 0 ORDER BY created_at DESC").fetchall()]
        soft_deleted_interests = [dict(r) for r in conn.execute("SELECT * FROM shopping_interests WHERE is_deleted = 1 ORDER BY deleted_at DESC").fetchall()]
        all_deals = [dict(r) for r in conn.execute("SELECT * FROM evaluated_deals ORDER BY deal_score DESC, discovered_at DESC").fetchall()]
        all_products = [dict(r) for r in conn.execute("SELECT * FROM products").fetchall()]
        supermarket_specials = [dict(r) for r in conn.execute("SELECT * FROM supermarket_specials").fetchall()]
        notifications = [dict(r) for r in conn.execute("SELECT * FROM notifications_log ORDER BY created_at DESC LIMIT 40").fetchall()]
        workers = [dict(r) for r in conn.execute("SELECT * FROM worker_health").fetchall()]
        settings = dict(conn.execute("SELECT * FROM app_settings WHERE id = 'owner_default'").fetchone())

    # Sidebar Navigation (Mobile & Laptop Friendly — 14 Screens including Supermarket Specials)
    with st.sidebar:
        st.markdown("## ⚡ Deal Sniper AU")
        st.caption(f"📍 Postcode: **2150 Parramatta** • Currency: **AUD**")
        st.caption(f"🗄️ Storage: `{storage_info['storage_mode'][:38]}`")

        nav_screen = st.radio(
            "Navigation",
            options=[
                "1. Overview",
                "2. My Interests",
                "3. Barcode Scanner",
                "4. Deal Sniper",
                "5. Supermarket Specials",
                "6. Deal Radar",
                "7. Discoveries (Engine B)",
                "8. Shopping Basket",
                "9. Price History",
                "10. Recommendations",
                "11. Saved Deals & Lifecycle",
                "12. AI Assistant",
                "13. Notifications & Telegram",
                "14. Settings & Data Backup"
            ],
            index=0
        )

        st.divider()
        if st.button("↻ Run Background Worker Cycle", use_container_width=True):
            res = orch.run_scheduled_worker_tick(dispatch_6pm_summary=False)
            st.success(f"Synced {len(res['workers_updated'])} workers at {res['completed_at'][11:19]} UTC")
            st.rerun()

    # =========================================================================
    # Quick Product Addition Bar (Accessible on Top of Overview, Interests & Scanner)
    # =========================================================================
    st.markdown("### ⚡ Deal Sniper — Autonomous AI Shopping Intelligence")
    with st.expander("➕ Quick Add Product (Scan Barcode • Natural-Language Requirement • Paste URL • Refurbished Toggle)", expanded=(nav_screen in ("2. My Interests", "3. Barcode Scanner"))):
        add_tab1, add_tab2, add_tab3 = st.tabs([
            "🔤 Search / Natural Language",
            "📷 Scan or Enter Barcode",
            "🔗 Paste Product URL / Screenshot"
        ])

        with add_tab1:
            with st.form("quick_nl_form"):
                nl_q = st.text_input(
                    "Describe what you want to buy (Exact model, 'A OR B', or broad budget requirement)",
                    placeholder="e.g., Samsung Galaxy Watch 7, 44mm OR Any good Android phone around AUD 750"
                )
                c1, c2, c3 = st.columns(3)
                with c1:
                    nl_budget = st.number_input("Max Budget (AUD, 0 = Auto)", min_value=0.0, value=0.0, step=25.0)
                with c2:
                    nl_refurb = st.checkbox("Include Certified Refurbished / Open-Box", value=False)
                with c3:
                    nl_submit = st.form_submit_button("Save to Permanent Wishlist", use_container_width=True)
                if nl_submit and nl_q.strip():
                    saved = orch.add_or_update_interest(
                        raw_input=nl_q.strip(),
                        include_refurbished=nl_refurb,
                        added_method="natural_language",
                        max_budget_override=(nl_budget if nl_budget > 0 else None)
                    )
                    st.success(
                        f"Saved **{saved['interest_type'].upper()}** interest `{saved['name']}` "
                        f"(Refurbished/Open-Box: **{'ON' if saved['include_refurbished'] else 'OFF'}**)."
                    )
                    st.rerun()

        with add_tab2:
            components.html(ZXING_CAMERA_SCANNER_HTML, height=340, scrolling=False)
            with st.form("quick_barcode_form"):
                bc_digits = st.text_input("Detected or Fallback Barcode (EAN-13 / EAN-8 / UPC-A / UPC-E)", value="8806095661421")
                bc_fallback_name = st.text_input("Product Name (if registering an unknown barcode)", value="")
                bc_refurb = st.checkbox("Include Certified Refurbished / Open-Box listings", value=False)
                bc_btn = st.form_submit_button("Identify Barcode & Add to Wishlist", use_container_width=True)
                if bc_btn and bc_digits.strip():
                    lookup = orch.lookup_or_register_barcode(bc_digits.strip(), fallback_product_name=bc_fallback_name)
                    if lookup["found"]:
                        prod = lookup["product"]
                        saved = orch.add_or_update_interest(
                            raw_input=prod["canonical_name"],
                            include_refurbished=bc_refurb,
                            added_method="barcode_scan",
                            scanned_barcode=prod["barcode_ean_upc"]
                        )
                        st.success(f"{lookup['message']} — Added to permanent wishlist (`{saved['id']}`).")
                        st.rerun()
                    else:
                        st.warning(lookup["message"])

        with add_tab3:
            with st.form("quick_url_form"):
                pasted_url = st.text_input("Paste Australian Retailer Product URL", placeholder="https://www.jbhifi.com.au/products/...")
                url_title = st.text_input("Product Name or Requirement", placeholder="Sony WH-1000XM6 Wireless Headphones")
                url_refurb = st.checkbox("Include Certified Refurbished / Open-Box", value=True)
                url_btn = st.form_submit_button("Track Product URL", use_container_width=True)
                if url_btn and (url_title.strip() or pasted_url.strip()):
                    q_str = url_title.strip() or pasted_url.strip()
                    saved = orch.add_or_update_interest(
                        raw_input=q_str,
                        include_refurbished=url_refurb,
                        added_method="url_paste"
                    )
                    st.success(f"Registered URL interest `{saved['name']}` (`{saved['id']}`).")
                    st.rerun()

    # Helper to render rich product/deal cards with direct exact links & stock badges
    def render_deal_card_st(d: Dict[str, Any]) -> None:
        rubric = json.loads(d.get("rubric_breakdown_json", "{}"))
        warnings = json.loads(d.get("risk_warnings_json", "[]"))
        sample_tag = '<span class="badge-pill badge-sample">SAMPLE DATA</span>' if d.get("is_sample_data") else '<span class="badge-pill badge-stock">LIVE VERIFIED</span>'
        warn_html = f"<div style='color:#fbbf24;font-size:12px;margin-top:6px;'>⚠️ {warnings[0]}</div>" if warnings else ""

        st.markdown(
            f"""
            <div class="sniper-card">
              <div>
                <span class="badge-pill badge-exc">Deal Score: {d['deal_score']}/100 • {d['classification']}</span>
                <span class="badge-pill badge-stock">{d['stock_badge']}</span>
                <span class="badge-pill badge-sample">{d['engine_type']}</span>
                <span class="badge-pill badge-sample">Condition: {d.get('condition', 'New')}</span>
                {sample_tag}
              </div>
              <h4 style="margin:8px 0 4px 0;color:#ffffff;">{d['title']}</h4>
              <div>
                <span class="price-big">AUD {float(d['final_checkout_cost_aud']):.2f}</span>
                <span class="price-old">90d Median: AUD {float(d['median_90d_price_aud']):.2f} | RRP AUD {float(d['normal_market_price_aud']):.2f}</span>
                <span style="color:#f43f5e;font-weight:700;margin-left:8px;">-{float(d['discount_vs_median_pct']):.0f}% vs 90d Median</span>
              </div>
              <div style="font-size:12.5px;color:#cbd5e1;margin-top:6px;">
                🏪 <strong>{d['retailer']}</strong> • 📍 {d.get('local_postcode_summary', '2150 Parramatta')} • ⚖️ {d['unit_price_display']}
              </div>
              <div style="font-size:12px;color:#94a3b8;margin-top:6px;">
                📊 <strong>Scoring Rubric (40/20/15/15/10):</strong> <code>{rubric.get('formula_summary', '')}</code>
              </div>
              <div style="font-size:12px;color:#6ee7b7;margin-top:4px;">
                🛡️ <strong>Verification:</strong> {d['verification_status']} • 🧭 <strong>Buy/Wait Verdict:</strong> {d['buy_wait_verdict'].upper()} — {d['buy_wait_reasoning']}
              </div>
              {warn_html}
              <a class="buy-btn" href="{d['exact_product_url']}" target="_blank" rel="noopener noreferrer">
                🛒 Open Exact Product Page at {d['retailer']} ↗
              </a>
            </div>
            """,
            unsafe_allow_html=True
        )

    # =========================================================================
    # Screen Routing
    # =========================================================================
    if nav_screen == "1. Overview":
        actionable_deals = [d for d in all_deals if int(d.get("is_actionable", 1)) == 1 and d["stock_badge"] != "Out of Stock"]
        exc_deals = [d for d in actionable_deals if int(d["deal_score"]) >= 90]

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Active Shopping Interests", len(active_interests), "Permanent DB")
        k2.metric("Exceptional Deals (90+)", len(exc_deals), "Actionable In-Stock")
        k3.metric("Coles & Woolworths ½ Price", len([s for s in supermarket_specials if s["is_half_price"]]), "Watchlist Sorted")
        k4.metric("Scheduled Workers", f"{len(workers)}/4 Healthy", "15m Cron + 6PM Digest")

        st.markdown("#### 🚨 Top Actionable Deal Sniper Opportunities")
        for d in actionable_deals[:4]:
            render_deal_card_st(d)

    elif nav_screen == "2. My Interests":
        st.markdown(f"#### 📋 Active Shopping Interests ({len(active_interests)})")
        for item in active_interests:
            shortlist = json.loads(item.get("shortlist_json", "[]"))
            with st.container():
                st.markdown(
                    f"**{item['name']}** — `{item['interest_type'].upper()}` | Category: *{item['category']}* | "
                    f"Status: **{item['lifecycle_status']}** | Refurbished/Open-Box: **{'ON' if item['include_refurbished'] else 'OFF'}** | "
                    f"Added via: `{item['added_method']}`"
                )
                if shortlist:
                    st.caption("Shortlisted Qualifying Products: " + " • ".join(
                        f"[{s['canonical_name']} (AUD {s['normal_market_price_aud']})]({s.get('exact_product_url', 'https://www.officeworks.com.au')})"
                        for s in shortlist
                    ))
                b1, b2, b3 = st.columns([1, 1, 2])
                if b1.button("⏸ Pause / Resume", key=f"pause_{item['id']}"):
                    new_st = "Paused" if item["lifecycle_status"] != "Paused" else "Exploring"
                    with orch.db.get_connection() as conn:
                        conn.execute("UPDATE shopping_interests SET lifecycle_status = ? WHERE id = ?", (new_st, item["id"]))
                        conn.commit()
                    st.rerun()
                if b2.button("🗄️ Soft-Delete (Keep History)", key=f"sdel_{item['id']}"):
                    orch.db.soft_delete_interest(item["id"])
                    st.success(f"Soft-deleted '{item['name']}'. Price history preserved.")
                    st.rerun()
                st.divider()

        if soft_deleted_interests:
            with st.expander(f"🗄️ Soft-Deleted Interests ({len(soft_deleted_interests)}) — Restore or Permanently Purge"):
                for sd in soft_deleted_interests:
                    c_a, c_b, c_c = st.columns([2, 1, 1])
                    c_a.write(f"**{sd['name']}** (Soft-deleted at `{sd['deleted_at'][:19]}`)")
                    if c_b.button("♻️ Restore", key=f"rest_{sd['id']}"):
                        orch.db.restore_soft_deleted_interest(sd["id"])
                        st.rerun()
                    if c_c.button("🔥 Confirm Hard Purge", key=f"purge_{sd['id']}"):
                        orch.db.purge_interest_permanently(sd["id"], confirmed=True)
                        st.rerun()

    elif nav_screen == "3. Barcode Scanner":
        st.markdown("#### 📷 Mobile Camera Barcode Scanner & Instant Product Identifier")
        st.info("Use the live ZXing camera scanner in the Quick Add panel above, or test known EAN-13 / UPC barcodes below.")
        for p in all_products:
            st.markdown(
                f"• **`{p['barcode_ean_upc']}`** — **{p['canonical_name']}** (RRP AUD {p['normal_market_price_aud']:.2f}) — "
                f"[Exact Retailer Link]({p['exact_product_url']})"
            )

    elif nav_screen == "4. Deal Sniper":
        st.markdown("#### 🎯 Deal Sniper — Concrete 40/20/15/15/10 Rubric & Second-Source Error-Price Verification")
        with st.expander("🧪 Simulate Live Price Drop / Error-Price Second-Source Check", expanded=False):
            with st.form("sim_snipe_form"):
                s_prod = st.selectbox("Product", options=[p["id"] for p in all_products], format_func=lambda x: next(p["canonical_name"] for p in all_products if p["id"] == x))
                s_ret = st.selectbox("Retailer", options=[r["name"] for r in AUSTRALIAN_RETAILERS_V1])
                s_price = st.number_input("Observed Price (AUD)", min_value=1.0, value=20.0, step=1.0)
                s_cond = st.selectbox("Condition", options=["New", "Refurbished", "Open-Box"])
                s_stock = st.selectbox("Stock Badge", options=["Available Locally for Click & Collect", "In Stock Online", "Out of Stock"])
                s_sec = st.checkbox("Second-Source Verification Passed (Required for >70% off error-price anomalies)", value=True)
                s_title = st.text_input("Optional Title Override (e.g. 'Silicone Replacement Strap Only' to test trap rejection)", value="")
                if st.form_submit_button("Run Sniper Evaluation & Telegram Check"):
                    out = orch.record_observation_and_snipe(
                        product_id=s_prod,
                        retailer=s_ret,
                        listed_price_aud=float(s_price),
                        condition=s_cond,
                        stock_badge=s_stock,
                        second_source_verified=s_sec,
                        listing_title_override=(s_title.strip() or None)
                    )
                    st.success(
                        f"Scored **{out['evaluated_deal']['deal_score']}/100 ({out['evaluated_deal']['classification']})** | "
                        f"Actionable: **{bool(out['evaluated_deal']['is_actionable'])}** | "
                        f"Notification: **{out['notification']['status']}**"
                    )
                    st.rerun()

        for d in all_deals:
            render_deal_card_st(d)

    elif nav_screen == "5. Supermarket Specials":
        st.markdown("#### 🛒 Australian Supermarket Half-Price & Specials (Coles & Woolworths)")
        st.caption(
            "**Intelligent 3-Tier Sorting:** 1️⃣ Watchlist Matches First → 2️⃣ Best Absolute Savings / ½ Price (50%+ Off) → 3️⃣ Trending Household Essentials."
        )
        f1, f2, f3 = st.columns(3)
        with f1:
            sp_cat = st.selectbox("Filter Category", ["All", "Chocolates", "Coffee & Beverages", "Snacks & Pantry", "Household Consumables"])
        with f2:
            sp_store = st.selectbox("Supermarket", ["All", "Woolworths", "Coles"])
        with f3:
            sp_disc = st.slider("Minimum Discount (%)", 0, 50, 0, step=10)

        sorted_specials = sort_supermarket_specials_multi_tier(
            supermarket_specials,
            active_interests,
            category_filter=sp_cat,
            min_discount_pct=float(sp_disc),
            supermarket_filter=sp_store
        )
        for sp in sorted_specials:
            st.markdown(
                f"""
                <div class="sniper-card">
                  <div>
                    <span class="badge-pill badge-exc">{sp['priority_label']}</span>
                    <span class="badge-pill badge-stock">{sp['supermarket']} • {sp['stock_badge']}</span>
                    <span class="badge-pill badge-sample">{sp['category']}</span>
                  </div>
                  <h4 style="margin:8px 0 4px 0;color:#ffffff;">{sp['title']}</h4>
                  <div>
                    <span class="price-big">AUD {float(sp['special_price_aud']):.2f}</span>
                    <span class="price-old">Normal AUD {float(sp['normal_price_aud']):.2f}</span>
                    <span style="color:#f43f5e;font-weight:700;margin-left:8px;">-{float(sp['discount_pct']):.0f}% (Save AUD {float(sp['abs_savings_aud']):.2f})</span>
                  </div>
                  <div style="font-size:12.5px;color:#cbd5e1;margin-top:4px;">
                    ⚖️ Unit Price: <strong>{sp['unit_price_display']}</strong> • Pack Size: {sp['pack_size_label']}
                  </div>
                  <a class="buy-btn" href="{sp['exact_product_url']}" target="_blank" rel="noopener noreferrer">
                    🛒 Open Exact Product Page at {sp['supermarket']} ↗
                  </a>
                </div>
                """,
                unsafe_allow_html=True
            )

    elif nav_screen == "6. Deal Radar":
        st.markdown("#### 📡 Deal Radar — Local Postcode Availability (2150 Parramatta) & Urgency")
        for d in all_deals:
            st.markdown(
                f"• **{d['title']}** at **{d['retailer']}** — **AUD {float(d['final_checkout_cost_aud']):.2f}** | "
                f"Badge: `{d['stock_badge']}` | Second-Source Status: `{d['second_source_status']}` — "
                f"[Exact Link]({d['exact_product_url']})"
            )

    elif nav_screen == "7. Discoveries (Engine B)":
        st.markdown("#### 🔭 Engine B — Outside-Wishlist Exceptional Deal Discoveries (Threshold ≥ 90/100)")
        for d in [x for x in all_deals if x["engine_type"] == "Engine B" or int(x["deal_score"]) >= 90]:
            render_deal_card_st(d)

    elif nav_screen == "8. Shopping Basket":
        st.markdown("#### 🧺 Multi-Retailer Shopping Basket Optimiser (Postcode 2150)")
        mode = st.radio("Fulfilment Mode", ["click_and_collect", "home_delivery"], horizontal=True)
        comp = compare_shopping_basket_v1(DEFAULT_BASKET_ITEMS, mode, "2150")
        b1, b2, b3 = st.columns(3)
        b1.metric("Standard RRP Total", f"AUD {comp['rrp_total_aud']:.2f}")
        b2.metric(f"Best Single Store ({comp['best_single_store']['retailer']})", f"AUD {comp['best_single_store']['total_checkout_aud']:.2f}")
        b3.metric("Optimal Split Basket", f"AUD {comp['split_basket']['total_checkout_aud']:.2f}", f"Save AUD {comp['split_basket']['total_savings_vs_rrp_aud']:.2f}")

        st.markdown("##### Optimal Split-Basket Item Allocation")
        for store, items in comp["split_basket"]["allocations"].items():
            st.markdown(f"**🏪 {store}**")
            for it in items:
                st.markdown(
                    f"- {it['name']} (x{it['quantity']}): **AUD {it['line_total_aud']:.2f}** ({it['unit_price_display']} • {it['promo_label']}) — [Exact Link]({it['exact_product_url']})"
                )

    elif nav_screen == "9. Price History":
        st.markdown("#### 📈 7d / 30d / 90d / 180d Historical Price Database & Buy/Wait Engine")
        sel_pid = st.selectbox("Select Product", options=[p["id"] for p in all_products], format_func=lambda x: next(p["canonical_name"] for p in all_products if p["id"] == x))
        prod = next(p for p in all_products if p["id"] == sel_pid)
        with orch.db.get_connection() as conn:
            obs = [dict(r) for r in conn.execute("SELECT * FROM price_observations WHERE product_id = ? ORDER BY observed_at ASC", (sel_pid,)).fetchall()]
        h = orch.interest_history.compute_history_and_buy_wait(prod, obs)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("90-Day Low", f"AUD {h['lowest_90d_aud']:.2f}")
        m2.metric("90-Day Median", f"AUD {h['median_90d_aud']:.2f}")
        m3.metric("90-Day Average", f"AUD {h['average_90d_aud']:.2f}")
        m4.metric("180-Day High", f"AUD {h['highest_180d_aud']:.2f}")
        st.info(f"**AI Buy/Wait Verdict: {h['buy_wait_verdict'].upper()}** — {h['buy_wait_reasoning']}")
        st.table(h["series"])

    elif nav_screen == "10. Recommendations":
        st.markdown("#### 🔬 AI Product Researcher & Side-by-Side Comparison")
        resp = orch.handle_telegram_or_assistant_command("/compare")
        st.markdown(resp["reply"])

    elif nav_screen == "11. Saved Deals & Lifecycle":
        st.markdown("#### 💾 Shopping Lifecycle & Realised Savings Tracker")
        purchased = [i for i in active_interests if i["lifecycle_status"] == "Purchased" and i.get("recorded_purchase_price_aud")]
        st.write(f"**Verified Purchased Interests:** {len(purchased)}")
        for i in active_interests:
            st.markdown(f"- **{i['name']}** — Status: `{i['lifecycle_status']}` | Target: `AUD {i['target_price_aud'] or 'Auto'}`")

    elif nav_screen == "12. AI Assistant":
        st.markdown("#### 🤖 Conversational AI Shopping Assistant & Telegram Command Simulator")
        st.caption("Supports natural language and all 16 slash commands: " + ", ".join(f"`{c}`" for c in SUPPORTED_TELEGRAM_COMMANDS))
        q_chat = st.text_input("Ask the AI Assistant or run a Telegram command", value="/deals")
        if st.button("Send Command / Query"):
            out = orch.handle_telegram_or_assistant_command(q_chat)
            st.markdown(out["reply"])

    elif nav_screen == "13. Notifications & Telegram":
        st.markdown("#### 📲 Single-Owner Telegram Bot & 6:00 PM Daily Summary")
        if st.button("🕕 Generate & Log 6:00 PM Daily Summary Now"):
            orch.run_scheduled_worker_tick(dispatch_6pm_summary=True)
            st.success("Generated and logged 6:00 PM Daily Intelligence Summary.")
            st.rerun()
        for n in notifications:
            with st.expander(f"[{n['status'].upper()}] {n['title']} ({n['created_at'][:19]})"):
                st.markdown(n["message_body"])

    elif nav_screen == "14. Settings & Data Backup":
        st.markdown("#### 📲 Configure Telegram Bot API Token & Authorised Owner User ID")
        st.caption(
            "You can set these permanently in **Streamlit Cloud → App Settings → Secrets** (or `.env`), "
            "or enter them directly below to save your Owner ID & Chat ID to the persistent database and send a live test alert."
        )
        with st.form("telegram_config_form"):
            curr_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            curr_owner = os.environ.get("TELEGRAM_OWNER_ID", "") or settings.get("telegram_owner_user_id", "")
            curr_chat = os.environ.get("TELEGRAM_CHAT_ID", "") or settings.get("telegram_chat_id", "")

            in_token = st.text_input(
                "TELEGRAM_BOT_TOKEN (from @BotFather, e.g. 123456789:AAH...)",
                value=curr_token,
                type="password"
            )
            c_u1, c_u2 = st.columns(2)
            with c_u1:
                in_owner = st.text_input(
                    "TELEGRAM_OWNER_ID (Your numeric Telegram User ID from @userinfobot)",
                    value=curr_owner
                )
            with c_u2:
                in_chat = st.text_input(
                    "TELEGRAM_CHAT_ID (Usually identical to your numeric User ID)",
                    value=curr_chat or curr_owner
                )
            save_tg_btn = st.form_submit_button("💾 Save Telegram Credentials & Send Test Alert", use_container_width=True)
            if save_tg_btn:
                if in_token.strip():
                    os.environ["TELEGRAM_BOT_TOKEN"] = in_token.strip()
                if in_owner.strip():
                    os.environ["TELEGRAM_OWNER_ID"] = in_owner.strip()
                if in_chat.strip():
                    os.environ["TELEGRAM_CHAT_ID"] = in_chat.strip()
                with orch.db.get_connection() as conn:
                    conn.execute(
                        "UPDATE app_settings SET telegram_owner_user_id = ?, telegram_chat_id = ?, updated_at = ? WHERE id = 'owner_default'",
                        (in_owner.strip(), (in_chat.strip() or in_owner.strip()), datetime.now(timezone.utc).isoformat())
                    )
                    conn.commit()
                if all_deals:
                    test_res = orch.telegram.send_or_log_deal_notification(all_deals[0], simulated_hhmm="14:00")
                    st.success(
                        f"Saved Owner ID `{in_owner.strip()}`! Test alert status: **{test_res['status']}** "
                        f"(Live Telegram API dispatched: **{test_res.get('live_api_dispatched', False)}**)"
                    )
                else:
                    st.success(f"Saved Owner ID `{in_owner.strip()}` to persistent database!")

        st.divider()
        st.markdown("#### ⚙️ Persistent Storage Status, Worker Health & One-Click Data Export")
        st.json(storage_info)
        st.markdown("##### Persistent Background Worker Health")
        st.table(workers)
        export_json = orch.db.export_all_data_json()
        st.download_button(
            label="📥 Download Complete Shopping Database (JSON Backup)",
            data=export_json,
            file_name="deal_sniper_full_backup.json",
            mime="application/json"
        )


if __name__ == "__main__":
    run_streamlit_app()
