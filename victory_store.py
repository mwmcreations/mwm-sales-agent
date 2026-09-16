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
    # Phase 3 (14 Sep): the machine is the editor. These columns carry what it
    # was asked for, what it did, and where the result lives. ADD COLUMN IF NOT
    # EXISTS keeps the boot idempotent on a table that already has rows.
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS length_s   INT",
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ",
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS result_drive_id TEXT",
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS result_file TEXT",
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS result_bytes BIGINT",
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS result_seconds REAL",
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS summary JSONB",
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS error TEXT",
    "ALTER TABLE vi_request ADD COLUMN IF NOT EXISTS text JSONB",
    """CREATE TABLE IF NOT EXISTS vi_feedback (
           id         BIGSERIAL PRIMARY KEY,
           request_id BIGINT NOT NULL,
           at         TIMESTAMPTZ DEFAULT now(),
           email      TEXT,
           text       TEXT NOT NULL
       )""",
    "CREATE INDEX IF NOT EXISTS vi_feedback_req ON vi_feedback (request_id, at)",
    # Our own thumbnails and previews (15 Sep): Drive's thumbnail redirect did not
    # show on Michael's phone, and there was no way to watch a clip before picking
    # it. The Mac worker makes a poster JPEG and a small MP4 per clip; they live
    # here and the app serves them. ~30 KB + ~1 MB per clip.
    """CREATE TABLE IF NOT EXISTS vi_media (
           clip_id    TEXT PRIMARY KEY,
           poster     BYTEA,
           preview    BYTEA,
           updated_at TIMESTAMPTZ DEFAULT now()
       )""",
]

# asked -> rendering -> ready -> approved -> delivered, or failed / declined.
# 'planned' is kept for rows that predate the machine editor; nothing sets it.
REQUEST_STATES = ("asked", "planned", "rendering", "ready", "approved",
                  "delivered", "declined", "failed")


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
def create_request(email, role, school, note, items, length_s=30, text=None):
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
                """INSERT INTO vi_request (email, role, school, note, items, length_s, text)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (email, role or "", school or "", (note or "")[:4000],
                 _json.dumps(items or []), int(length_s or 30),
                 _json.dumps(text) if text else None))
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
                    "SELECT %s FROM vi_request WHERE state = %%s ORDER BY at DESC LIMIT %%s"
                    % REQUEST_COLS, (state, int(limit)))
            else:
                cur.execute(
                    "SELECT %s FROM vi_request ORDER BY at DESC LIMIT %%s"
                    % REQUEST_COLS, (int(limit),))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        print("[VI] list_requests failed: %r" % (e,))
        return []


REQUEST_COLS = ("id, at, email, role, school, note, items, state, handled_at, handled_by, "
                "length_s, started_at, finished_at, result_drive_id, result_file, "
                "result_bytes, result_seconds, summary, error, text")


def list_requests_for(email, limit=50):
    """One person's own requests, newest first. The page shows nobody else's."""
    pg = _pg()
    if not pg or not email:
        return []
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT %s FROM vi_request WHERE email = %%s ORDER BY at DESC LIMIT %%s"
                % REQUEST_COLS, (email, int(limit)))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        print("[VI] list_requests_for failed: %r" % (e,))
        return []


def get_request(rid):
    pg = _pg()
    if not pg:
        return None
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute("SELECT %s FROM vi_request WHERE id = %%s" % REQUEST_COLS, (int(rid),))
            row = cur.fetchone()
            if not row:
                return None
            return dict(zip([d[0] for d in cur.description], row))
    except Exception as e:
        print("[VI] get_request failed: %r" % (e,))
        return None


def claim_next_request(worker):
    """Hand the oldest 'asked' request to a worker, atomically.

    The claim is the UPDATE itself — FOR UPDATE SKIP LOCKED means two workers
    asking at the same instant get two different rows or one gets nothing.
    Same principle as consume_link: the database decides, once.
    """
    pg = _pg()
    if not pg:
        return None
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """UPDATE vi_request
                      SET state = 'rendering', handled_by = %%s, handled_at = now(),
                          started_at = now(), error = NULL
                    WHERE id = (SELECT id FROM vi_request WHERE state = 'asked'
                                 ORDER BY at LIMIT 1 FOR UPDATE SKIP LOCKED)
                RETURNING %s""" % REQUEST_COLS, (worker or "worker",))
            row = cur.fetchone()
            if not row:
                return None
            return dict(zip([d[0] for d in cur.description], row))
    except Exception as e:
        print("[VI] claim_next_request failed: %r" % (e,))
        return None


def finish_request(rid, state, drive_id=None, file_name=None, size=None,
                   seconds=None, summary=None, error=None):
    """Record the outcome of a render: 'ready' with a result, or 'failed' with why."""
    import json as _json
    pg = _pg()
    if not pg or state not in REQUEST_STATES:
        return False
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """UPDATE vi_request
                      SET state = %s, finished_at = now(),
                          result_drive_id = COALESCE(%s, result_drive_id),
                          result_file = COALESCE(%s, result_file),
                          result_bytes = COALESCE(%s, result_bytes),
                          result_seconds = COALESCE(%s, result_seconds),
                          summary = COALESCE(%s, summary),
                          error = %s
                    WHERE id = %s""",
                (state, drive_id, file_name, size, seconds,
                 _json.dumps(summary) if summary is not None else None,
                 (error or "")[:2000] or None, int(rid)))
            return cur.rowcount == 1
    except Exception as e:
        print("[VI] finish_request failed: %r" % (e,))
        return False


def set_request_state(rid, state, by=""):
    """A person's decision on a finished cut: approved / declined / delivered."""
    pg = _pg()
    if not pg or state not in REQUEST_STATES:
        return False
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """UPDATE vi_request SET state = %s, handled_by = COALESCE(NULLIF(%s,''), handled_by),
                          handled_at = now() WHERE id = %s""", (state, by or "", int(rid)))
            return cur.rowcount == 1
    except Exception as e:
        print("[VI] set_request_state failed: %r" % (e,))
        return False


def requeue_stale(older_than_seconds=1800):
    """A render that has been 'rendering' for half an hour is a render that died.
    Put it back in the queue so the next worker pass picks it up; the summary
    keeps the trace."""
    pg = _pg()
    if not pg:
        return 0
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """UPDATE vi_request SET state = 'asked',
                          error = COALESCE(error, '') || ' [requeued after a stalled render]'
                    WHERE state = 'rendering'
                      AND started_at < now() - (%s * interval '1 second')""",
                (int(older_than_seconds),))
            return cur.rowcount
    except Exception as e:
        print("[VI] requeue_stale failed: %r" % (e,))
        return 0


def queue_counts():
    pg = _pg()
    if not pg:
        return {}
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute("SELECT state, count(*) FROM vi_request GROUP BY state")
            return {r[0]: int(r[1]) for r in cur.fetchall()}
    except Exception as e:
        print("[VI] queue_counts failed: %r" % (e,))
        return {}


def recent_music(email, limit=2):
    """The last tracks this person received, so the next cut rotates away from them."""
    pg = _pg()
    if not pg or not email:
        return []
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """SELECT summary->>'music_id' FROM vi_request
                    WHERE email = %s AND summary ? 'music_id'
                    ORDER BY finished_at DESC NULLS LAST LIMIT %s""", (email, int(limit)))
            return [r[0] for r in cur.fetchall() if r[0]]
    except Exception as e:
        print("[VI] recent_music failed: %r" % (e,))
        return []


def recent_clips(email, cuts=6):
    """Clip ids in this person's last few cuts, most recent first — so the
    next cut reaches for footage they have not seen yet."""
    pg = _pg()
    if not pg or not email:
        return []
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """SELECT summary->'shots' FROM vi_request
                    WHERE email = %s AND summary ? 'shots'
                    ORDER BY finished_at DESC NULLS LAST LIMIT %s""", (email, int(cuts)))
            out = []
            for (shots,) in cur.fetchall():
                for sh in shots or []:
                    cid = sh.get("id") if isinstance(sh, dict) else None
                    if cid and cid not in out:
                        out.append(cid)
            return out
    except Exception as e:
        print("[VI] recent_clips failed: %r" % (e,))
        return []


# ── feedback ───────────────────────────────────────────────────────────────
def add_feedback(rid, email, text):
    pg = _pg()
    if not pg or not text:
        return None
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """INSERT INTO vi_feedback (request_id, email, text)
                        VALUES (%s,%s,%s) RETURNING id""",
                (int(rid), email or "", text[:4000]))
            return cur.fetchone()[0]
    except Exception as e:
        print("[VI] add_feedback failed: %r" % (e,))
        return None


def list_feedback(rids):
    """Feedback for a set of requests, oldest first, keyed by request id."""
    pg = _pg()
    if not pg or not rids:
        return {}
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """SELECT request_id, at, email, text FROM vi_feedback
                    WHERE request_id = ANY(%s) ORDER BY at""", ([int(r) for r in rids],))
            out = {}
            for rid, at, email, text in cur.fetchall():
                out.setdefault(rid, []).append({"at": at, "email": email, "text": text})
            return out
    except Exception as e:
        print("[VI] list_feedback failed: %r" % (e,))
        return {}


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


# ── thumbnails and previews ────────────────────────────────────────────────
def media_have():
    """Clip ids that already have a poster and a preview."""
    pg = _pg()
    if not pg:
        return set()
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute("SELECT clip_id FROM vi_media WHERE poster IS NOT NULL AND preview IS NOT NULL")
            return {r[0] for r in cur.fetchall()}
    except Exception as e:
        print("[VI] media_have failed: %r" % (e,))
        return set()


def media_put(clip_id, poster, preview):
    pg = _pg()
    if not pg or not clip_id:
        return False
    try:
        import psycopg2
        with pg._conn() as c, c.cursor() as cur:
            cur.execute(
                """INSERT INTO vi_media (clip_id, poster, preview, updated_at)
                        VALUES (%s, %s, %s, now())
                   ON CONFLICT (clip_id) DO UPDATE SET
                        poster = COALESCE(EXCLUDED.poster, vi_media.poster),
                        preview = COALESCE(EXCLUDED.preview, vi_media.preview),
                        updated_at = now()""",
                (clip_id, psycopg2.Binary(poster) if poster else None,
                 psycopg2.Binary(preview) if preview else None))
        return True
    except Exception as e:
        print("[VI] media_put failed: %r" % (e,))
        return False


def media_get(clip_id, kind):
    """bytes or None. kind: 'poster' | 'preview'."""
    pg = _pg()
    if not pg or kind not in ("poster", "preview"):
        return None
    try:
        with pg._conn() as c, c.cursor() as cur:
            cur.execute("SELECT %s FROM vi_media WHERE clip_id = %%s" % kind, (clip_id,))
            row = cur.fetchone()
            return bytes(row[0]) if row and row[0] is not None else None
    except Exception as e:
        print("[VI] media_get failed: %r" % (e,))
        return None
