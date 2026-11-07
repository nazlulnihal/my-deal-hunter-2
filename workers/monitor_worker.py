"""
Standalone Headless Monitoring Worker (`workers/monitor_worker.py`).

Runs completely independently of the Streamlit UI (invoked via GitHub Actions
`.github/workflows/deal_sniper_scheduler.yml`, cron, or Docker worker) so that
wishlist monitoring, error-price second-source verification, and 6:00 PM (18:00)
Telegram summaries execute even when no browser is open.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.orchestrator import DealSniperOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Deal Sniper Autonomous Background Worker")
    parser.add_argument("--daily-summary", action="store_true", help="Compile and send the 6:00 PM Daily Telegram Summary")
    args = parser.parse_args()

    orch = DealSniperOrchestrator()
    res = orch.run_scheduled_worker_cycle() if hasattr(orch, "run_scheduled_worker_cycle") else orch.run_scheduled_worker_tick(dispatch_6pm_summary=args.daily_summary)
    print(f"[DealSniperWorker] Completed cycle at {res['completed_at']} | Workers updated: {len(res['workers_updated'])} | 6PM Summary: {res['summary_dispatched']}")


if __name__ == "__main__":
    main()
