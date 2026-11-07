# Deal Sniper — Autonomous AI Shopping Intelligence Platform (`deal-sniper.py`)

A production-quality, mobile-first Australian shopping intelligence and extreme-bargain sniping platform engineered specifically for **GitHub + Streamlit Community Cloud (`deal-sniper.py`) + Supabase PostgreSQL + Single-Owner Telegram Bot + GitHub Actions Scheduled Workers**.

---

## 1. Why Your Previous Streamlit Deployment Failed (`ModuleNotFoundError`) & How It Is Fixed

Your previous error on Streamlit Community Cloud occurred because:
1. Streamlit Cloud ran `/mount/src/my-deal-hunter/streamlit_app.py`, which tried to execute `from app.orchestrator import ...` when either the `app/` package folder was not committed to the root of your `my-deal-hunter` GitHub repository or the zipfile was nested inside a subfolder.
2. **How this repository fixes it permanently**:
   - The mandatory entrypoint is **`deal-sniper.py`** at the exact root of the repository (`streamlit run deal-sniper.py`), and a compatibility shim (`streamlit_app.py`) is also included so either entrypoint setting works out of the box.
   - All modular packages (`services/`, `connectors/`, `workers/`, `database/`, `tests/`, `.streamlit/`, `.github/workflows/`) sit cleanly at the repository root.

---

## 2. Key Architectural Decisions & Engineering Resolutions

### A. Resolving "Never Forget Anything" vs "Explicit Deletion Controls" (Soft-Delete vs Purge)
- **Default Delete = Soft-Delete (`is_deleted = 1`)**: Clicking Delete on an interest in the UI or via Telegram marks `is_deleted = 1` and `lifecycle_status = 'Archived'`. The interest is hidden from active monitoring, can be restored with one click, and **100% of historical price observations (`price_observations`) remain permanently preserved**.
- **Explicit Hard Purge (`purge_interest_permanently(confirmed=True)`)**: Available inside the Soft-Deleted Interests drawer with a mandatory confirmation step, removing the interest row while still keeping canonical product price history intact.

### B. Telegram Architecture: Webhook vs Polling on Free Infrastructure
- **Chosen Architecture**: **Hybrid Stateless Webhook (Supabase Edge Function / Cloudflare Worker Free Tier) + Scheduled GitHub Action Worker (`workers/monitor_worker.py`)**.
- **Why**:
  1. Running `getUpdates` polling inside `deal-sniper.py` on Streamlit Community Cloud is an anti-pattern: every Streamlit rerun or extra mobile tab spawns competing polling loops (`HTTP 409 Conflict`) and stops whenever Streamlit Cloud sleeps.
  2. Polling *only* inside a 15-minute GitHub Action delays interactive `/deals` or `/scan` replies by up to 15 minutes.
  3. Pairing a stateless webhook on Supabase Edge Functions / Cloudflare Workers (100,000 free requests/day, `<50ms` latency) connected to the same Supabase PostgreSQL database with our 15-minute GitHub Action worker (`.github/workflows/deal_sniper_scheduler.yml`) for outbound deal sniping and the **6:00 PM (18:00 AEST/AEDT) Daily Summary** delivers instant interactive Telegram control with $0 recurring cost.

### C. Concrete 100-Point Deal Scoring Rubric & Error-Price Second-Source Rule (`services/deal_scorer.py`)
Every deal is scored from **0 to 100** using an explicit, auditable formula:
- **40% (0–40 pts)**: Discount vs 90-Day Observed Median Price (full 40 pts at `>= 50%` below the 90-day median).
- **20% (0–20 pts)**: Cross-Retailer Price Gap vs Next Cheapest Competitor (full 20 pts at `>= 25%` cheaper than the next store).
- **15% (0–15 pts)**: Data Confidence & Verification Stage (`checkout_verified` = 100%, `retailer_listed` = 90%, `search_result` = 72%).
- **15% (0–15 pts)**: Seller & Retailer Trust (Tier-1 Australian retailers like Officeworks, JB Hi-Fi, Woolworths, Coles score 94–98; third-party marketplace listings are penalised).
- **10% (0–10 pts)**: Live Stock & Postcode Availability (`Available Locally for Click & Collect` = 10 pts, `In Stock Online` = 9 pts, `Out of Stock` = 0 pts and strictly marked `is_actionable = 0`).
- **Mandatory Error-Price Second-Source Rule**: Any listing discounted `>= 70%` below the 90-day median (such as an `AUD 20` Samsung Galaxy Watch 7 at Officeworks) is flagged as an `is_error_price_anomaly` and **capped at 76/100 (held from unsolicited alerts)** until `second_source_verified = True` confirms the exact GTIN/MPN hardware variant and checkout stock status.

---

## 3. Repository Structure

```text
.
├── deal-sniper.py                        # Mandatory Streamlit entrypoint (`streamlit run deal-sniper.py`)
├── streamlit_app.py                      # Compatibility shim delegating to deal-sniper.py
├── requirements.txt                      # Pinned Streamlit Community Cloud dependencies
├── .env.example                          # Local environment variables template
├── .streamlit/
│   ├── config.toml                       # Mobile-first dark theme & server configuration
│   └── secrets.toml.example              # Streamlit Community Cloud Secrets template
├── database/
│   ├── schema.sql                        # Complete Supabase PostgreSQL / SQLite WAL schema
│   └── migrations/
│       └── 001_initial_schema.sql        # Initial schema migration
├── services/
│   ├── db_manager.py                     # Supabase PostgreSQL + SQLite WAL manager & Soft-Delete/Purge
│   ├── product_matcher.py                # EAN-13/EAN-8/UPC-A/UPC-E barcode validator, Refurbished toggle & unit pricing
│   ├── deal_scorer.py                    # 40/20/15/15/10 Deal Scoring Rubric + Second-Source Error-Price check
│   ├── interest_and_history.py           # Exact/Multiple/Broad NL parser + 7d/30d/90d/180d history & Buy/Wait engine
│   ├── telegram_bot.py                   # Single-owner Telegram security, 16 commands, inline buttons & 6PM Summary
│   └── orchestrator.py                   # Central application orchestrator
├── connectors/
│   └── au_retailers.py                   # 18 Australian retailers, Supermarket Specials 3-Tier sorter & Basket Optimiser
├── workers/
│   └── monitor_worker.py                 # Standalone headless background worker
├── tests/
│   └── test_deal_sniper_acceptance.py    # Automated acceptance test suite (A through H)
└── .github/
    └── workflows/
        └── deal_sniper_scheduler.yml     # 15-min background cron + 6:00 PM Daily Summary workflow
```

---

## 4. Step-by-Step Deployment to GitHub & Streamlit Community Cloud

1. **Unzip at Repository Root**:
   Extract all files from `deal-sniper-github-repo.zip` directly into the root of your GitHub repository (`my-deal-hunter`) and push to `main`.
2. **Configure Supabase PostgreSQL**:
   Create a free project at Supabase, open the SQL Editor, paste `database/schema.sql` (or let `services/db_manager.py` auto-initialise on first run), and copy your Transaction Pooler URI (`SUPABASE_DB_URL`).
3. **Deploy on Streamlit Community Cloud**:
   - Select your repository and set **Main file path** to `deal-sniper.py`.
   - Open **App Settings → Secrets** and paste the contents of `.streamlit/secrets.toml.example` filled with your `SUPABASE_DB_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_ID`, and `TELEGRAM_CHAT_ID`.
4. **Enable Free Background Monitoring**:
   Add the same secrets under your GitHub repository **Settings → Secrets and variables → Actions** so `.github/workflows/deal_sniper_scheduler.yml` runs every 15 minutes and dispatches your **6:00 PM Daily Summary**.
