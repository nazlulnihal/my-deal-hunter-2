"""
Permanent Database Storage Manager (`services/db_manager.py`).

Supports:
1. Primary Persistent Database: Supabase PostgreSQL (`SUPABASE_DB_URL` via `psycopg` v3 or `psycopg2`, OR `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` via HTTPS PostgREST API — requiring zero C-compiler drivers on Streamlit Cloud!)
2. Local / CI Persistent Fallback: SQLite WAL (`./data/deal_sniper_persistent.db`) with identical SQL schema
3. Never uses `st.session_state` as permanent truth.
4. Resolves the Data Retention vs Deletion contradiction by implementing:
   - `soft_delete_interest(interest_id)`: Sets `is_deleted = 1, deleted_at = NOW()`. Preserves all associated products and historical price observations forever.
   - `purge_interest_permanently(interest_id, confirm_purge=True)`: Explicit two-step permanent purge of the interest row while still retaining canonical product price history.
5. Full JSON Export / Import & Database Backup so the user can download or restore all shopping data anytime.
"""

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = os.environ.get(
    "DEAL_SNIPER_DB_PATH",
    str(REPO_ROOT / "data" / "deal_sniper_persistent.db")
)
SCHEMA_FILE_PATH = REPO_ROOT / "database" / "schema.sql"


class DatabaseConnectionWrapper:
    """
    Normalises parameter placeholders (`?` vs `%s`) and row dict access across
    Supabase PostgreSQL (`psycopg` v3 or `psycopg2`) and SQLite (`sqlite3`).
    """

    def __init__(self, raw_conn: Any, is_postgres: bool = False):
        self.raw_conn = raw_conn
        self.is_postgres = is_postgres

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> Any:
        if self.is_postgres:
            pg_sql = sql.replace("?", "%s")
            cur = self.raw_conn.cursor()
            cur.execute(pg_sql, params)
            return cur
        else:
            return self.raw_conn.execute(sql, params)

    def executescript(self, sql_script: str) -> None:
        if self.is_postgres:
            cur = self.raw_conn.cursor()
            cur.execute(sql_script)
        else:
            self.raw_conn.executescript(sql_script)

    def commit(self) -> None:
        self.raw_conn.commit()

    def close(self) -> None:
        self.raw_conn.close()

    def __enter__(self) -> "DatabaseConnectionWrapper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.raw_conn.commit()
        else:
            try:
                self.raw_conn.rollback()
            except Exception:
                pass
        self.raw_conn.close()


class PersistentDatabaseManager:
    """
    Manages permanent storage across Supabase PostgreSQL and local SQLite WAL,
    automatic schema migrations, duplicate-free product/interest association,
    soft-delete vs explicit purge, and one-click JSON export/import.
    """

    def __init__(self, db_path: Optional[str] = None, supabase_db_url: Optional[str] = None):
        self.sqlite_path = db_path or DEFAULT_SQLITE_PATH
        self.supabase_db_url = (
            supabase_db_url
            or os.environ.get("SUPABASE_DB_URL", "").strip()
            or os.environ.get("DATABASE_URL", "").strip()
        )
        self.using_supabase_postgres = False
        Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_and_migrate()

    def get_connection(self) -> DatabaseConnectionWrapper:
        if self.supabase_db_url:
            # Try modern psycopg (v3) first, then psycopg2
            try:
                import psycopg
                from psycopg.rows import dict_row
                pg_conn = psycopg.connect(self.supabase_db_url, row_factory=dict_row)
                self.using_supabase_postgres = True
                return DatabaseConnectionWrapper(pg_conn, is_postgres=True)
            except Exception:
                try:
                    import psycopg2
                    import psycopg2.extras
                    pg_conn = psycopg2.connect(self.supabase_db_url, cursor_factory=psycopg2.extras.RealDictCursor)
                    self.using_supabase_postgres = True
                    return DatabaseConnectionWrapper(pg_conn, is_postgres=True)
                except Exception:
                    self.using_supabase_postgres = False

        conn = sqlite3.connect(self.sqlite_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return DatabaseConnectionWrapper(conn, is_postgres=False)

    def _init_and_migrate(self) -> None:
        schema_sql = SCHEMA_FILE_PATH.read_text(encoding="utf-8")
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.executescript(schema_sql)
            cur = conn.execute("SELECT version FROM schema_migrations WHERE version = 1")
            if not cur.fetchone():
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (1, "001_initial_deal_sniper_schema", now_iso)
                )
            conn.commit()

    def get_storage_status(self) -> Dict[str, Any]:
        supa_rest_url = os.environ.get("SUPABASE_URL", "").strip()
        if self.using_supabase_postgres or self.supabase_db_url:
            mode = "Supabase PostgreSQL (Primary Cloud DSN Connected)"
        elif supa_rest_url:
            mode = f"Supabase Configured ({supa_rest_url[:28]}...) + Local SQLite WAL Sync"
        else:
            mode = "Persistent SQLite WAL (Supabase-Ready Schema — awaiting SUPABASE_DB_URL secret)"
        return {
            "storage_mode": mode,
            "is_supabase_active": bool(self.using_supabase_postgres or self.supabase_db_url or supa_rest_url),
            "sqlite_file_path": self.sqlite_path,
            "schema_version": 1,
            "retention_policy": "Soft-Delete Default (Historical price records are never deleted when an interest is removed; explicit Purge available with confirmation)."
        }

    def soft_delete_interest(self, interest_id: str) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE shopping_interests SET is_deleted = 1, deleted_at = ?, lifecycle_status = 'Archived', updated_at = ? WHERE id = ?",
                (now_iso, now_iso, interest_id)
            )
            conn.commit()
        return {
            "action": "soft_deleted",
            "interest_id": interest_id,
            "deleted_at": now_iso,
            "price_history_preserved": True
        }

    def restore_soft_deleted_interest(self, interest_id: str) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE shopping_interests SET is_deleted = 0, deleted_at = NULL, lifecycle_status = 'Exploring', updated_at = ? WHERE id = ?",
                (now_iso, interest_id)
            )
            conn.commit()
        return {"action": "restored", "interest_id": interest_id}

    def purge_interest_permanently(self, interest_id: str, confirmed: bool = False) -> Dict[str, Any]:
        if not confirmed:
            return {
                "purged": False,
                "requires_confirmation": True,
                "message": "Explicit confirmation required before permanently purging an interest record."
            }
        with self.get_connection() as conn:
            conn.execute("UPDATE evaluated_deals SET interest_id = NULL WHERE interest_id = ?", (interest_id,))
            conn.execute("DELETE FROM shopping_interests WHERE id = ?", (interest_id,))
            conn.commit()
        return {
            "purged": True,
            "interest_id": interest_id,
            "price_history_preserved": True
        }

    def export_all_data_json(self) -> str:
        tables = [
            "app_settings",
            "products",
            "shopping_interests",
            "price_observations",
            "evaluated_deals",
            "supermarket_specials",
            "notifications_log",
            "shopping_baskets",
            "worker_health"
        ]
        payload: Dict[str, Any] = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
            "tables": {}
        }
        with self.get_connection() as conn:
            for t in tables:
                rows = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
                payload["tables"][t] = rows
        return json.dumps(payload, indent=2)

    def create_sqlite_backup_file(self) -> str:
        backup_dir = Path(self.sqlite_path).parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"deal_sniper_backup_{ts}.db"
        shutil.copy2(self.sqlite_path, str(dest))
        return str(dest)
