"""pg_store.py — S3.1: Postgres state persistence for the MWM Sales Machine.

Kills "deploy amnesia": in-memory state (lead_data, conversation histories,
dedup sets) survives Railway deploys and restarts.

Gracefully no-ops when DATABASE_URL is not set — the app runs unchanged
without Postgres, so this module can never take production down.
"""
import os
import json
import threading

DATABASE_URL = os.getenv("DATABASE_URL", "")
_enabled = bool(DATABASE_URL)
_lock = threading.Lock()


def enabled():
    return _enabled


def _conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


def init_schema():
    """Create the app_state KV table if missing. Returns True on success."""
    if not _enabled:
        return False
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS app_state (
                       key        TEXT PRIMARY KEY,
                       value      JSONB NOT NULL,
                       updated_at TIMESTAMPTZ DEFAULT now()
                   )"""
            )
        return True
    except Exception as e:
        print(f"[PG] init_schema failed: {e}")
        return False


def save_state(key, value):
    """Upsert a JSON-serializable value under key. Never raises."""
    if not _enabled:
        return False
    try:
        payload = json.dumps(value, default=str)
        with _lock:
            with _conn() as c, c.cursor() as cur:
                cur.execute(
                    """INSERT INTO app_state (key, value, updated_at)
                       VALUES (%s, %s::jsonb, now())
                       ON CONFLICT (key)
                       DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
                    (key, payload),
                )
        return True
    except Exception as e:
        print(f"[PG] save_state({key}) failed: {e}")
        return False


def load_state(key, default=None):
    """Fetch a value by key; returns default on miss or any error. Never raises."""
    if not _enabled:
        return default
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT value FROM app_state WHERE key = %s", (key,))
            row = cur.fetchone()
            return row[0] if row else default
    except Exception as e:
        print(f"[PG] load_state({key}) failed: {e}")
        return default
