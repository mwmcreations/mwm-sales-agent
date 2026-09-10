"""victory_store.py — Phase 2 persistence: people, sign-in links, the log.

victory_auth.py holds the rules and touches nothing. This holds the rows.

Three things here are worth reading before changing anything:

  SINGLE USE IS ENFORCED IN SQL, NOT IN PYTHON. consume_link does
  UPDATE ... WHERE used_at IS NULL ... RETURNING, so two simultaneous requests
  carrying the same link cannot both win: the database decides, once. Checking
  "is it used?" and then marking it used would be two statements and a race,
  and the prize for winning that race is somebody else's session.

  THE SIGNING SECRET PROVISIONS ITSELF. It is generated once and kept in
  app_state, so every worker and every future deploy shares it without anyone
  having to set an environment variable — and without an admin secret being
  reused as a signing key. No database means no secret means no sessions,
  which is the correct way to fail.

  NOTHING HERE RAISES INTO A REQUEST. Same contract as pg_store and
  victory_index: a database problem degrades the door, it does not take the
  sales machine down.
"""
import time
import threading

SESSION_SECRET_KEY = "vi_session_secret"

_secret_cache = None
_secret_lock = threading.Lock()

DDL = [
    """CREATE TABLE IF NOT EXISTS vi_person (
           email       TEXT PRIMARY KEY,
           role        TEXT NOT NULL,
           school      TEXT,
           granted_by  TEXT,
           granted_at  TIMESTAMPTZ,
           first_seen  TIMESTAMPTZ DEFAULT now(),
           last_seen   TIMESTAMPTZ
       )""",
    """CREATE TABLE IF NOT EXISTS vi_magic_link (
           token_hash  TEXT PRIMARY KEY,
           email       TEXT NOT NULL,
           issued_at   DOUBLE PRECISION NOT NULL,
           used_at     TIMESTAMPTZ,
           ip          TEXT,
           created_at  TIMESTAMPTZ DEFAULT now()
       )""",
    "CREATE INDEX IF NOT EXISTS vi_magic_link_email ON vi_magic_link (email)",
    """CREATE TABLE IF NOT EXISTS vi_search_log (
           id        BIGSERIAL PRIMARY KEY,
           at        TIMESTAMPTZ DEFAULT now(),
           email     TEXT,
           role      TEXT,
           q         TEXT,
           event_key TEXT,
           found     INT,
           ms        INT,
           ip        TEXT
       )""",
    "CREATE INDEX IF NOT EXISTS vi_search_log_at ON vi_search_log (at DESC)",
    # The request queue. Phase 3 will render from these rows; the page can
    # already write them, because "I found things and don't know what to do
    # with them" was the first thing a real user said.
    """CREATE TABLE IF NOT EXISTS vi_request (
           id         BIGSERIAL PRIMARY KEY,
           at         TIMESTAMPTZ DEFAULT now(),
           email      TEXT NOT NULL,
           role       TEXT,
           school     TEXT,
           note       TEXT,
           items      JSONB NOT NULL,
           state      TEXT NOT NULL DEFAULT 'asked',
           handled_at TIMESTAMPTZ,
           handled_by TEXT
       )""",
    "CREATE INDEX IF NOT EXISTS vi_request_state ON vi_request (state, at DESC)",
]

# asked -> planned -> rendering -> ready -> approved -> delivered
REQUEST_STATES = ("asked", "planned", "rendering", "ready", "approved",
                  "delivered", "declined")


def _pg():
    """The pg_store module, or None. Import guarded: see Patch #129."""
    try:
        import pg_store
        return pg_store if pg_store.enabled() else None
    except Exception:
        return None


def init_schema():
    pg = _pg()
    if not pg:
        return False
    try:
        with pg._conn() as c, c.cursor() as cur:
            for stmt in DDL:
                cur.execute(stmt)
        return True
    except Exception as e:
        print("[VI-AUTH] init_schema failed: %r" % (e,))
        return False


# ── the signing secret ─────────────────────────────────────────────────────
def session_secret(create=True):
    """The HMAC key for session cookies. '' when there is no database.

    Generated once, then shared by every worker through app_state. Rotating it
    is a supported operation: delete the row and every session ends.
    """
    global _secret_cache
    with _secret_lock:
        if _secret_cache:
            return _secret_cache
    pg = _pg()
    if not pg:
        return ""
    try:
        got = pg.load_state(SESSION_SECRET_KEY, None)
        if isinstance(got, str) and len(got) >= 32:
            with _secret_lock:
                _secret_cache = got
            return got
        if not create:
            return ""
        import secrets as _s
        fresh = _s.token_urlsafe(48)
        pg.save_state(SESSION_SECRET_KEY, fresh)
        # Read it back: if two workers raced, the stored value wins, so every
        # worker ends up signing with the same key rather than each trusting
        # only its own cookies.
        stored = pg.load_state(SESSION_SECRET_KEY, fresh)
        stored = stored if isinstance(stored, str) and len(stored) >= 32 else fresh
        with _secret_lock:
            _secret_cache = stored
        print("[VI-AUTH] session signing secret provisioned")
        return stored
    except Exception as e:
        print("[VI-AUTH] session_secret failed: %r" % (e,))
        return ""


# ── people ─────────────────────────────────────────────────────────────────
def get_person(email):
    """{email, role, school} or None."""
    pg = _pg()
    if not pg or not email:
        return None
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute("SELECT email, role, school FROM vi_person WHERE email = %s",
                        (email,))
            row = cur.fetchone()
        return {"email": row[0], "role": row[1], "school": row[2] or ""} if row else None
    except Exception as e:
        print("[VI-AUTH] get_person failed: %r" % (e,))
        return None


def remember_person(email, role, school=""):
    """Record someone we have just admitted, WITHOUT changing a granted role.

    ON CONFLICT touches only last_seen. A returning visitor must never have
    their role rewritten by the default that applies to a stranger — that is
    how a school quietly becomes an hq.
    """
    pg = _pg()
    if not pg or not email:
        return False
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """INSERT INTO vi_person (email, role, school, last_seen)
                        VALUES (%s,%s,%s, now())
                   ON CONFLICT (email) DO UPDATE SET last_seen = now()""",
                (email, role, school or None))
        return True
    except Exception as e:
        print("[VI-AUTH] remember_person failed: %r" % (e,))
        return False


def grant(email, role, school="", by="michael"):
    """Set someone's role. This is the access decision, and it is Michael's."""
    pg = _pg()
    if not pg or not email:
        return False
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """INSERT INTO vi_person (email, role, school, granted_by, granted_at)
                        VALUES (%s,%s,%s,%s, now())
                   ON CONFLICT (email) DO UPDATE SET
                        role = EXCLUDED.role, school = EXCLUDED.school,
                        granted_by = EXCLUDED.granted_by, granted_at = now()""",
                (email, role, school or None, by))
        return True
    except Exception as e:
        print("[VI-AUTH] grant failed: %r" % (e,))
        return False


def list_people(limit=200):
    pg = _pg()
    if not pg:
        return []
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """SELECT email, role, school, granted_by, granted_at, last_seen
                     FROM vi_person ORDER BY role, email LIMIT %s""", (int(limit),))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        print("[VI-AUTH] list_people failed: %r" % (e,))
        return []


# ── sign-in links ──────────────────────────────────────────────────────────
def create_link(token_hash, email, ip=""):
    pg = _pg()
    if not pg:
        return False
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """INSERT INTO vi_magic_link (token_hash, email, issued_at, ip)
                        VALUES (%s,%s,%s,%s)""",
                (token_hash, email, time.time(), (ip or "")[:64]))
        return True
    except Exception as e:
        print("[VI-AUTH] create_link failed: %r" % (e,))
        return False


def consume_link(token_hash):
    """Claim a link. Returns (email, issued_at) once, then None forever.

    The UPDATE ... WHERE used_at IS NULL ... RETURNING is the whole point: the
    database decides the winner of a race, atomically. Expiry is checked by the
    caller against issued_at, deliberately AFTER the claim — a link presented
    late is still spent, so a leaked expired link cannot be retried.
    """
    pg = _pg()
    if not pg or not token_hash:
        return None
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """UPDATE vi_magic_link SET used_at = now()
                    WHERE token_hash = %s AND used_at IS NULL
                RETURNING email, issued_at""", (token_hash,))
            row = cur.fetchone()
        return (row[0], float(row[1])) if row else None
    except Exception as e:
        print("[VI-AUTH] consume_link failed: %r" % (e,))
        return None


def purge_links(older_than_seconds=86400):
    """Housekeeping: spent and stale links have no reason to be kept."""
    pg = _pg()
    if not pg:
        return 0
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM vi_magic_link WHERE issued_at < %s",
                        (time.time() - older_than_seconds,))
            return cur.rowcount or 0
    except Exception as e:
        print("[VI-AUTH] purge_links failed: %r" % (e,))
        return 0


# ── the log ────────────────────────────────────────────────────────────────
def log_search(email, role, q, event_key, found, ms, ip=""):
    """Who looked for what. The first question anyone asks about a system like
    this is 'who did that?', and the answer should not be a shrug."""
    pg = _pg()
    if not pg:
        return False
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """INSERT INTO vi_search_log (email, role, q, event_key, found, ms, ip)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (email or "", role or "", (q or "")[:500], event_key,
                 int(found or 0), int(ms or 0), (ip or "")[:64]))
        return True
    except Exception as e:
        print("[VI-AUTH] log_search failed: %r" % (e,))
        return False


# ── requests ───────────────────────────────────────────────────────────────
def create_request(email, role, school, note, items):
    """Someone picked some moments and asked for something. Returns the id.

    Never raises: losing the row would be bad, but taking the page down while
    someone is mid-ask would be worse — and the caller reports the failure
    honestly rather than showing a false confirmation.
    """
    import json as _json
    pg = _pg()
    if not pg or not email:
        return None
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """INSERT INTO vi_request (email, role, school, note, items)
                        VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                (email, role or "", school or "", (note or "")[:4000],
                 _json.dumps(items or [])))
            return cur.fetchone()[0]
    except Exception as e:
        print("[VI] create_request failed: %r" % (e,))
        return None


def list_requests(limit=50, state=None):
    pg = _pg()
    if not pg:
        return []
    try:
        with pg._conn() as c, c.cursor() as cur:
            if state:
                cur.execute(
                    """SELECT id, at, email, role, note, items, state
                         FROM vi_request WHERE state = %s
                        ORDER BY at DESC LIMIT %s""", (state, int(limit)))
            else:
                cur.execute(
                    """SELECT id, at, email, role, note, items, state
                         FROM vi_request ORDER BY at DESC LIMIT %s""", (int(limit),))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        print("[VI] list_requests failed: %r" % (e,))
        return []


def recent_searches(limit=50):
    pg = _pg()
    if not pg:
        return []
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """SELECT at, email, role, q, found, ms FROM vi_search_log
                    ORDER BY at DESC LIMIT %s""", (int(limit),))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        print("[VI-AUTH] recent_searches failed: %r" % (e,))
        return []
