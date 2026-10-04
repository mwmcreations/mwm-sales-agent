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

PATCH #151 (4 Oct 2026) — reconnect-and-retry, and one connection per flush.
  Three "server closed the connection unexpectedly" alerts in two days
  (2 Oct 13:23, 2 Oct 16:48, 3 Oct 15:46). Railway's Postgres logged nothing
  at any of them — no restart, no FATAL — and the app's own pg_store, which
  already retried once after 0.5 s, recovered every time it was hit. So the
  drop is a transient on Railway's private network (postgres.railway.internal,
  IPv6), not the database. What made it visible here is that leads_db opened
  a NEW connection for every lead it wrote — 340 TCP+TLS handshakes every
  five-minute sweep, each one a chance to catch the blip — and retried none
  of them: a failed write was put back on the dirty set for the next flush
  (never lost, Patch #103) but alerted #dev as if the database had gone.
  Now: (1) connect-level failures (OperationalError / InterfaceError) are
  retried in place, three attempts with a short backoff, before anything is
  reported; (2) a flush writes every dirty lead over ONE connection, so a
  sweep is one handshake, not 340; (3) `conn_stats()` counts connects,
  retries, recoveries and give-ups for /health; (4) `find_rows()` reads the
  table directly so a lead's row can be checked from an admin route instead
  of inferred from the in-memory count.
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

# PATCH #151 — connection-level failures are retried this many times, with
# these pauses between attempts, before a write is reported and requeued.
CONN_ATTEMPTS = 3
CONN_BACKOFF_S = (0.5, 1.5)

_report_error = lambda ctx, exc, detail="": print(f"[LEADS_DB] {ctx}: {exc} {detail}")


def set_error_reporter(fn):
    global _report_error
    _report_error = fn


def enabled():
    return _enabled


def db_host():
    """Hostname of DATABASE_URL and nothing else — never the credentials."""
    if not DATABASE_URL:
        return ""
    try:
        from urllib.parse import urlsplit
        return urlsplit(DATABASE_URL).hostname or ""
    except Exception:
        return ""


# ── connection stats + reconnect-and-retry (PATCH #151) ──────────────────────

_conn_stats = {
    "connects": 0,        # connections opened
    "retries": 0,         # connection-level failures that were retried
    "recovered": 0,       # operations that succeeded on a retry
    "gave_up": 0,         # operations that failed every attempt
    "batches": 0,         # flushes written over one connection
    "last_error": "",
    "last_error_at": "",
    "last_recovered_at": "",
}


def conn_stats():
    """Read at /health. `retries` climbing with `recovered` climbing alongside
    is the network blinking and the retry doing its job; `gave_up` climbing is
    Postgres actually unreachable (and the requeue stats will climb with it)."""
    return dict(_conn_stats)


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _conn():
    import psycopg2
    _conn_stats["connects"] += 1
    return psycopg2.connect(DATABASE_URL, connect_timeout=10,
                            keepalives=1, keepalives_idle=30,
                            keepalives_interval=10, keepalives_count=3)


def _is_conn_error(exc):
    """True for the errors a reconnect can fix: the socket dropped, the
    server closed the connection, DNS did not resolve. SQL and value errors
    are not retried — the same statement would fail the same way."""
    try:
        import psycopg2
        return isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError))
    except Exception:
        return False


def _note_retry(op, attempt, exc):
    _conn_stats["retries"] += 1
    _conn_stats["last_error"] = str(exc).strip().splitlines()[0][:200] if str(exc) else repr(exc)[:200]
    _conn_stats["last_error_at"] = _now_iso()
    wait = CONN_BACKOFF_S[min(attempt - 1, len(CONN_BACKOFF_S) - 1)]
    print(f"[LEADS_DB] {op} connection error (attempt {attempt}/{CONN_ATTEMPTS}) "
          f"— retrying in {wait}s: {_conn_stats['last_error']}")
    return wait


def _note_recovered(op, attempt):
    _conn_stats["recovered"] += 1
    _conn_stats["last_recovered_at"] = _now_iso()
    print(f"[LEADS_DB] {op} recovered on attempt {attempt}")


def _with_reconnect(op, fn):
    """Run fn() — which opens its own connection — and retry it on a
    connection-level failure, CONN_ATTEMPTS times with CONN_BACKOFF_S between.
    Any other exception, and the last connection error, propagate to the
    caller's existing except/report path. Returns fn()'s result."""
    last = None
    for attempt in range(1, CONN_ATTEMPTS + 1):
        try:
            result = fn()
            if attempt > 1:
                _note_recovered(op, attempt)
            return result
        except Exception as e:
            if not _is_conn_error(e):
                raise
            last = e
            if attempt < CONN_ATTEMPTS:
                time.sleep(_note_retry(op, attempt, e))
    _conn_stats["gave_up"] += 1
    raise last


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


_UPSERT_SQL = """INSERT INTO leads (lead_key, phone, channel, name, email, business,
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
                       data = EXCLUDED.data, updated_at = now()"""


def _upsert_params(lead_key, rec):
    cols = _promote(lead_key, rec)
    return dict(cols, lead_key=lead_key, data=json.dumps(rec, default=str))


def _close_quietly(c):
    try:
        c.close()
    except Exception:
        pass


def upsert_many(items):
    """PATCH #151 — write many leads over ONE connection, committing after
    each so a drop mid-batch loses at most the statement in flight (which is
    then retried on the reconnect: the upsert is idempotent). A lead whose
    record cannot be written for a non-connection reason (bad value, JSON)
    is reported and skipped so it cannot hold the rest of the batch hostage.
    Returns (written_keys, failed_keys). Never raises."""
    if not _enabled or not items:
        return [], [k for k, _ in (items or [])]
    pending = list(items)
    written, failed = [], []
    attempt = 1          # consecutive connection failures without progress
    while pending:
        c = None
        try:
            with _lock:
                c = _conn()
                if attempt > 1:
                    _note_recovered("upsert_many", attempt)
                    attempt = 1
                cur = c.cursor()
                while pending:
                    k, rec = pending[0]
                    try:
                        cur.execute(_UPSERT_SQL, _upsert_params(k, rec))
                        c.commit()
                    except Exception as e:
                        if _is_conn_error(e):
                            raise
                        try:
                            c.rollback()
                        except Exception:
                            pass
                        _report_error("leads_db.upsert_lead", e, f"lead={k}")
                        failed.append(k)
                        pending.pop(0)
                        continue
                    written.append(k)
                    pending.pop(0)
        except Exception as e:
            if _is_conn_error(e) and attempt < CONN_ATTEMPTS:
                wait = _note_retry("upsert_many", attempt, e)
                attempt += 1
                _close_quietly(c)
                c = None
                time.sleep(wait)
                continue
            if _is_conn_error(e):
                _conn_stats["gave_up"] += 1
            first = pending[0][0] if pending else ""
            more = f" (+{len(pending) - 1} more in this batch)" if len(pending) > 1 else ""
            _report_error("leads_db.upsert_lead", e,
                          f"lead={first}{more} after {attempt} attempt(s)")
            failed.extend(k for k, _ in pending)
            pending = []
        finally:
            if c is not None:
                _close_quietly(c)
    if written:
        _conn_stats["batches"] += 1
    return written, failed


def upsert_lead(lead_key, rec):
    """Write one lead (full record) to the table. Never raises."""
    if not _enabled:
        return False
    written, _ = upsert_many([(lead_key, rec)])
    return bool(written)


def delete_lead(lead_key):
    if not _enabled:
        return False

    def _do():
        with _lock:
            c = _conn()
            try:
                with c, c.cursor() as cur:
                    cur.execute("DELETE FROM leads WHERE lead_key = %s", (lead_key,))
            finally:
                _close_quietly(c)
        return True

    try:
        return _with_reconnect("delete_lead", _do)
    except Exception as e:
        _report_error("leads_db.delete_lead", e, f"lead={lead_key}")
        return False


def load_all():
    """Return {lead_key: record_dict} for every lead. Empty dict on failure."""
    if not _enabled:
        return {}

    def _do():
        c = _conn()
        try:
            with c, c.cursor() as cur:
                cur.execute("SELECT lead_key, data FROM leads")
                return {row[0]: row[1] for row in cur.fetchall()}
        finally:
            _close_quietly(c)

    try:
        return _with_reconnect("load_all", _do)
    except Exception as e:
        _report_error("leads_db.load_all", e)
        return {}


def count():
    if not _enabled:
        return -1

    def _do():
        c = _conn()
        try:
            with c, c.cursor() as cur:
                cur.execute("SELECT count(*) FROM leads")
                return cur.fetchone()[0]
        finally:
            _close_quietly(c)

    try:
        return _with_reconnect("count", _do)
    except Exception as e:
        _report_error("leads_db.count", e)
        return -1


def find_rows(terms, limit=5):
    """PATCH #151 — read-only: the rows behind a lead, straight from the
    table. `terms` are lead keys, phone numbers (any formatting) or emails.
    Returns {term: [row, ...]} with the promoted columns plus how big the
    JSON record is — enough to say "the row is there and current" without
    inferring it from a count. Never raises; a failure is {term: None}."""
    out = {}
    if not _enabled:
        return {str(t): None for t in (terms or [])}
    for term in (terms or []):
        term = str(term or "").strip()
        if not term:
            continue
        digits = _digits(term)
        email = term.lower() if "@" in term else ""

        def _do(term=term, digits=digits, email=email):
            c = _conn()
            try:
                with c, c.cursor() as cur:
                    cur.execute(
                        """SELECT lead_key, name, business, status, channel, booked,
                                  last_message_time, updated_at, created_at,
                                  length(data::text)
                             FROM leads
                            WHERE lead_key = %(key)s
                               OR (%(digits)s <> '' AND phone = %(digits)s)
                               OR (%(email)s <> '' AND lower(email) = %(email)s)
                            ORDER BY updated_at DESC
                            LIMIT %(limit)s""",
                        {"key": term, "digits": digits, "email": email, "limit": int(limit)},
                    )
                    rows = []
                    for r in cur.fetchall():
                        rows.append({
                            "lead_key": r[0], "name": r[1] or "", "business": r[2] or "",
                            "status": r[3] or "", "channel": r[4] or "",
                            "booked": bool(r[5]) if r[5] is not None else None,
                            "last_message_time": r[6].isoformat() if r[6] else "",
                            "updated_at": r[7].isoformat() if r[7] else "",
                            "created_at": r[8].isoformat() if r[8] else "",
                            "data_bytes": int(r[9] or 0),
                        })
                    return rows
            finally:
                _close_quietly(c)

        try:
            out[term] = _with_reconnect("find_rows", _do)
        except Exception as e:
            _report_error("leads_db.find_rows", e, f"term={term}")
            out[term] = None
    return out


# ── write-through tracked dicts ──────────────────────────────────────────────

_requeue_stats = {"upsert": 0, "delete": 0}


def requeue_stats():
    """PATCH #103 — how many writes have been retried instead of lost.
    Read this at /health; a number that climbs and never settles means
    Postgres is unreachable and leads are queued in memory, not saved."""
    return dict(_requeue_stats)


def _requeued(kind, key, n_keys=1):
    """A write failed and was put back on the queue. Loud on the first one,
    then counted — a per-record alert storm during an outage helps nobody.
    PATCH #151: a batch that fails as one is counted as one line, n_keys
    records; the alert fires when the total crosses 1, 10 and 100."""
    before = _requeue_stats.get(kind, 0)
    n = before + max(1, int(n_keys))
    _requeue_stats[kind] = n
    more = f" (+{n_keys - 1} more)" if n_keys > 1 else ""
    print(f"[LEADS_DB] {kind} REQUEUED (not lost) key={key}{more} total={n}")
    if any(before < t <= n for t in (1, 10, 100)):
        _report_error(
            f"leads_db.{kind}_requeued",
            f"{n} {kind} write(s) have been retried, not lost",
            f"latest={key}{more} — records are queued in memory and will drain when "
            f"Postgres returns. If this number keeps climbing, Postgres is down.",
        )


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
    items = []
    for k in keys:
        rec = dict.get(lead_data, k)
        if not isinstance(rec, dict):
            continue
        try:
            snapshot = dict(rec)  # may race with a concurrent mutation
        except RuntimeError:
            _mark_dirty(k)        # try again next flush cycle
            continue
        items.append((k, snapshot))
    # PATCH #151 — one connection for the whole batch (a full sweep used to
    # open one per lead: 340 handshakes every five minutes, each a chance to
    # catch a network blip), with reconnect-and-retry inside.
    written_keys, failed_keys = upsert_many(items)
    written = len(written_keys)
    if failed_keys:
        # PATCH #103 — a failed write used to be DISCARDED here. The dirty
        # set is cleared at the top of flush(), so when Postgres blipped the
        # record was simply gone: no retry, no queue, no second chance. That
        # is how a real lead was lost on 2026-08-17 12:21 when the server
        # closed the connection mid-flush.
        # Re-queueing is the same move the RuntimeError branch above already
        # makes, and it turns the existing dirty set into the retry queue:
        # the next cycle (FLUSH_INTERVAL) tries again, and keeps trying until
        # Postgres comes back. The set is keyed by lead_key, so a backlog is
        # bounded by the number of leads — it cannot grow without limit.
        for k in failed_keys:
            _mark_dirty(k)
        _requeued("upsert", failed_keys[0], n_keys=len(failed_keys))
    for k in deleted:
        if not delete_lead(k):
            # same bug, same fix: a failed delete was dropped and the row
            # would have been resurrected by the next full sweep.
            with _dirty_lock:
                _deleted.add(k)
            _requeued("delete", k)
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
