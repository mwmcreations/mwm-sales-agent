"""leads_db.py — S4.1: relational leads table, the single source of truth.

Replaces the 4-store lead-state split (in-memory dict / Leads Sheet /
Re-engagement Sheet / Slack Canvas) with one authoritative Postgres table.
The Sheets and Canvas remain human-facing VIEWS synced FROM this store;
the in-memory `lead_data` dict becomes a write-through cache of it.

Design:
  - `leads` table: promoted columns (phone, name, email, status, ...) for
    SQL queryability + a lossless JSONB `data` column holding the full
    record exactly as the app uses it. Restore = SELECT lead_key, data.
  - `LeadData` / `LeadRecord` dict subclasses: every mutation (including
    nested `lead_data[key]["field"] = x`) marks the key dirty.
  - A flusher loop upserts dirty leads every FLUSH_INTERVAL seconds and
    full-sweeps everything every SWEEP_INTERVAL as a safety net for
    deeply-nested mutations the trackers can't see.
  - Gracefully no-ops without DATABASE_URL — app runs unchanged.

Never raises into the caller. All failures go to the error reporter the
app injects via set_error_reporter().
"""
import os
import json
import threading
import time
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "")
_enabled = bool(DATABASE_URL)
_lock = threading.Lock()
_dirty = set()
_dirty_lock = threading.Lock()
_deleted = set()

FLUSH_INTERVAL = 15    # seconds between dirty-key flushes
SWEEP_INTERVAL = 300   # seconds between full-table sweeps

_report_error = lambda ctx, exc, detail="": print(f"[LEADS_DB] {ctx}: {exc} {detail}")


def set_error_reporter(fn):
    global _report_error
    _report_error = fn


def enabled():
    return _enabled


def _conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


def init_schema():
    """Create the leads table + indexes. Returns True on success."""
    if not _enabled:
        return False
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS leads (
                       lead_key   TEXT PRIMARY KEY,
                       phone      TEXT,
                       channel    TEXT,
                       name       TEXT,
                       email      TEXT,
                       business   TEXT,
                       status     TEXT,
                       temperature TEXT,
                       lead_score INTEGER,
                       booked     BOOLEAN,
                       cold_fired BOOLEAN,
                       event_id   TEXT,
                       last_message_time TIMESTAMPTZ,
                       data       JSONB NOT NULL DEFAULT '{}',
                       created_at TIMESTAMPTZ DEFAULT now(),
                       updated_at TIMESTAMPTZ DEFAULT now()
                   )"""
            )
            # S7 migration (paired with Victory Ocoee multi-tenant prep):
            # product  — which MWM product this lead/client bought (e.g. 'Studio Package')
            # tenant_id — multi-tenant partition key, DEFAULT 'MWM'
            cur.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS product TEXT")
            cur.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS tenant_id TEXT DEFAULT 'MWM'")
            cur.execute("CREATE INDEX IF NOT EXISTS leads_tenant_idx ON leads (tenant_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS leads_phone_idx  ON leads (phone)")
            cur.execute("CREATE INDEX IF NOT EXISTS leads_email_idx  ON leads (lower(email))")
            cur.execute("CREATE INDEX IF NOT EXISTS leads_status_idx ON leads (status)")
        return True
    except Exception as e:
        _report_error("leads_db.init_schema", e)
        return False


# ── column promotion ─────────────────────────────────────────────────────────

def _digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _promote(lead_key, rec):
    """Extract queryable columns from a lead record dict."""
    def _s(k):
        v = rec.get(k)
        return str(v) if v not in (None, "") else None

    phone = _digits(lead_key) or _digits(rec.get("phone", "")) or None
    channel = "instagram" if (lead_key.startswith("instagram:") or lead_key.startswith("@")) \
              else str(rec.get("channel") or "whatsapp")
    lmt = rec.get("last_message_time")
    if isinstance(lmt, datetime):
        lmt_val = lmt.isoformat()
    elif isinstance(lmt, str) and lmt:
        lmt_val = lmt
    else:
        lmt_val = None
    score = rec.get("lead_score")
    try:
        score = int(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    return {
        "phone": phone,
        "channel": channel,
        "name": _s("name"),
        "email": _s("email"),
        "business": _s("business"),
        "status": _s("status") or _s("whatsapp_status"),
        "temperature": _s("temperature"),
        "lead_score": score,
        "booked": bool(rec.get("booked")) if "booked" in rec else None,
        "cold_fired": bool(rec.get("cold_fired")) if "cold_fired" in rec else None,
        "event_id": _s("event_id"),
        "last_message_time": lmt_val,
        "product": _s("product"),
        "tenant_id": _s("tenant_id") or "MWM",
    }


def upsert_lead(lead_key, rec):
    """Write one lead (full record) to the table. Never raises."""
    if not _enabled:
        return False
    try:
        cols = _promote(lead_key, rec)
        payload = json.dumps(rec, default=str)
        with _lock, _conn() as c, c.cursor() as cur:
            cur.execute(
                """INSERT INTO leads (lead_key, phone, channel, name, email, business,
                                      status, temperature, lead_score, booked, cold_fired,
                                      event_id, last_message_time, product, tenant_id,
                                      data, updated_at)
                   VALUES (%(lead_key)s, %(phone)s, %(channel)s, %(name)s, %(email)s,
                           %(business)s, %(status)s, %(temperature)s, %(lead_score)s,
                           %(booked)s, %(cold_fired)s, %(event_id)s,
                           %(last_message_time)s, %(product)s, %(tenant_id)s,
                           %(data)s::jsonb, now())
                   ON CONFLICT (lead_key) DO UPDATE SET
                       phone = EXCLUDED.phone, channel = EXCLUDED.channel,
                       name = EXCLUDED.name, email = EXCLUDED.email,
                       business = EXCLUDED.business, status = EXCLUDED.status,
                       temperature = EXCLUDED.temperature, lead_score = EXCLUDED.lead_score,
                       booked = EXCLUDED.booked, cold_fired = EXCLUDED.cold_fired,
                       event_id = EXCLUDED.event_id,
                       last_message_time = EXCLUDED.last_message_time,
                       product = EXCLUDED.product, tenant_id = EXCLUDED.tenant_id,
                       data = EXCLUDED.data, updated_at = now()""",
                dict(cols, lead_key=lead_key, data=payload),
            )
        return True
    except Exception as e:
        _report_error("leads_db.upsert_lead", e, f"lead={lead_key}")
        return False


def delete_lead(lead_key):
    if not _enabled:
        return False
    try:
        with _lock, _conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM leads WHERE lead_key = %s", (lead_key,))
        return True
    except Exception as e:
        _report_error("leads_db.delete_lead", e, f"lead={lead_key}")
        return False


def load_all():
    """Return {lead_key: record_dict} for every lead. Empty dict on failure."""
    if not _enabled:
        return {}
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT lead_key, data FROM leads")
            return {row[0]: row[1] for row in cur.fetchall()}
    except Exception as e:
        _report_error("leads_db.load_all", e)
        return {}


def count():
    if not _enabled:
        return -1
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT count(*) FROM leads")
            return cur.fetchone()[0]
    except Exception as e:
        _report_error("leads_db.count", e)
        return -1


# ── write-through tracked dicts ──────────────────────────────────────────────

def _mark_dirty(key):
    with _dirty_lock:
        _dirty.add(key)


class LeadRecord(dict):
    """Inner per-lead dict: mutations mark the owning lead dirty."""
    __slots__ = ("_lead_key",)

    def __init__(self, lead_key, *a, **kw):
        super().__init__(*a, **kw)
        self._lead_key = lead_key

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        _mark_dirty(self._lead_key)

    def __delitem__(self, k):
        super().__delitem__(k)
        _mark_dirty(self._lead_key)

    def update(self, *a, **kw):
        super().update(*a, **kw)
        _mark_dirty(self._lead_key)

    def setdefault(self, k, default=None):
        had = k in self
        v = super().setdefault(k, default)
        if not had:
            _mark_dirty(self._lead_key)
        return v

    def pop(self, k, *a):
        v = super().pop(k, *a)
        _mark_dirty(self._lead_key)
        return v


class LeadData(dict):
    """Outer lead_data dict: values are coerced to LeadRecord, mutations tracked."""

    @staticmethod
    def _wrap(key, value):
        if isinstance(value, dict) and not isinstance(value, LeadRecord):
            return LeadRecord(key, value)
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, self._wrap(key, value))
        _mark_dirty(key)

    def __delitem__(self, key):
        super().__delitem__(key)
        with _dirty_lock:
            _dirty.discard(key)
            _deleted.add(key)

    def update(self, *a, **kw):
        for d in a:
            items = d.items() if isinstance(d, dict) else d
            for k, v in items:
                self[k] = v
        for k, v in kw.items():
            self[k] = v

    def setdefault(self, key, default=None):
        if key in self:
            return super().__getitem__(key)
        self[key] = default
        return super().__getitem__(key)

    def pop(self, key, *a):
        try:
            v = super().pop(key)
            with _dirty_lock:
                _dirty.discard(key)
                _deleted.add(key)
            return v
        except KeyError:
            if a:
                return a[0]
            raise


# ── boot restore + flusher ───────────────────────────────────────────────────

# Fields the app stores as datetime objects. JSON round-trips turn them into
# ISO strings; code like `(now - last_message_time)` then raises TypeError.
# (This also silently broke cold-lead detection for pg_store-restored leads
# since Sprint 3a — fixed here for both restore paths.)
_DATETIME_FIELDS = ("last_message_time", "first_contact_time", "created_time",
                    "booking_time", "start_time", "end_time")


def revive_datetimes(rec, tz=None):
    """Parse ISO-string datetime fields back into (tz-aware) datetime objects.
    Mutates rec in place; unparseable values are left untouched. Never raises."""
    for f in _DATETIME_FIELDS:
        v = rec.get(f)
        if isinstance(v, str) and v:
            try:
                dt = datetime.fromisoformat(v)
                if dt.tzinfo is None and tz is not None:
                    dt = tz.localize(dt) if hasattr(tz, "localize") else dt.replace(tzinfo=tz)
                rec[f] = dt
            except (ValueError, TypeError):
                pass
    return rec


def restore_into(lead_data, legacy_snapshot=None):
    """Hydrate lead_data (a LeadData) from the leads table.
    If the table is empty and a legacy pg_store snapshot exists, run the
    one-time migration from that snapshot. Returns (restored, migrated)."""
    if not _enabled:
        return (0, 0)
    rows = load_all()
    migrated = 0
    if not rows and legacy_snapshot:
        for k, v in legacy_snapshot.items():
            if isinstance(v, dict) and upsert_lead(k, v):
                migrated += 1
        rows = load_all()
    try:
        import pytz
        _tz = pytz.timezone(os.getenv("APP_TIMEZONE", "America/New_York"))
    except Exception:
        _tz = None
    restored = 0
    for k, v in rows.items():
        if k not in lead_data and isinstance(v, dict):
            dict.__setitem__(lead_data, k, LeadRecord(k, revive_datetimes(v, _tz)))
            restored += 1
    with _dirty_lock:
        _dirty.clear()
    return (restored, migrated)


def flush(lead_data, full=False):
    """Upsert dirty (or all, if full=True) leads. Returns count written."""
    if not _enabled:
        return 0
    if full:
        keys = list(lead_data.keys())
        with _dirty_lock:
            _dirty.clear()
            deleted = list(_deleted)
            _deleted.clear()
    else:
        with _dirty_lock:
            keys = list(_dirty)
            _dirty.clear()
            deleted = list(_deleted)
            _deleted.clear()
    written = 0
    for k in keys:
        rec = dict.get(lead_data, k)
        if not isinstance(rec, dict):
            continue
        try:
            snapshot = dict(rec)  # may race with a concurrent mutation
        except RuntimeError:
            _mark_dirty(k)        # try again next flush cycle
            continue
        if upsert_lead(k, snapshot):
            written += 1
    for k in deleted:
        delete_lead(k)
    return written


def start_flusher(lead_data, heartbeat=None):
    """Background loop: dirty flush every FLUSH_INTERVAL, full sweep every
    SWEEP_INTERVAL. Registers 'leads_flush' heartbeat when provided."""
    if not _enabled:
        return None

    def _loop():
        last_sweep = time.time()
        while True:
            try:
                if heartbeat:
                    heartbeat("leads_flush")
                full = (time.time() - last_sweep) >= SWEEP_INTERVAL
                flush(lead_data, full=full)
                if full:
                    last_sweep = time.time()
            except Exception as e:
                _report_error("leads_db.flusher", e)
            time.sleep(FLUSH_INTERVAL)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t
