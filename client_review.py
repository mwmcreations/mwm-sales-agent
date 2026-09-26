"""client_review.py — PATCH #137: client review pages on MWM hosting.

First use: the Valente Brothers name 86 technique repetitions from the 18 Sep
shoot and star the best take of each (EDDIE's spec, 26 Sep). The page was built
as a Claude artifact, but a guest cannot save into an artifact, so it lives here.

    GET  /r/<token>/                 the page (no sign-in; the token is the lock)
    GET  /r/<token>/p/<key>.jpg      poster
    GET  /r/<token>/c/<key>.mp4      clip (Range answered, iOS needs it)
    GET  /api/<token>/answers        every saved answer, to restore on load
    POST /api/<token>/answer         upsert ONE field of one segment
    POST /r/<token>/setup/<kind>/<key>   write-once media upload (see below)

    GET  /admin/review/<review_id>       our live table (admin)
    GET  /admin/review/<review_id>.json  same, as data
    GET  /admin/review/<review_id>.csv   export

Rules that were paid for elsewhere and are kept on purpose:

  THE SERVER OWNS "ONE BEST TAKE PER TECHNIQUE". The page un-stars locally for
  instant feedback, but a phone and an iPad can disagree; only the server can
  settle it. Scope: same technique for the same reviewer; while a segment is
  unnamed, the scope is its camera clip (unnamed segments only). The answer to
  a POST lists every row the server changed, so the page un-stars the other
  card without a reload.

  THE TECHNIQUE IS STORED AS THE VERBATIM STRING. The curriculum numbers are the
  client's own and two entries share 95; re-keying to an id would corrupt it.

  THE TOKEN IS THE WHOLE ACCESS CONTROL. Only its sha256 lives in the repo; the
  token itself exists in the link. Pages and media are noindex, no-referrer
  (the page loads Google Fonts, and a Referer would carry the token to them).

  MEDIA IS WRITE-ONCE. Uploads are accepted only for segment keys in the review
  and only while that file is missing, so the token cannot be used to replace
  footage. No admin secret is needed to seed a review, and no footage sits in git.

  NOTHING HERE RAISES INTO A REQUEST, and a failure here never stops the sales
  machine booting (same contract as victory_store).
"""
import csv
import hashlib
import io
import json
import os
import re
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEWS_DIR = os.path.join(HERE, "reviews")
KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{20,80}$")
MAX_TECH = 300
MAX_NOTE = 2000
MEDIA_LIMITS = {"poster": (500, 400_000, b"\xff\xd8"), "clip": (5_000, 4_000_000, None)}

DDL = [
    """CREATE TABLE IF NOT EXISTS cr_answer (
           review_id   TEXT NOT NULL,
           token_hash  TEXT NOT NULL,
           segment_key TEXT NOT NULL,
           technique   TEXT,
           is_best     BOOLEAN NOT NULL DEFAULT FALSE,
           note        TEXT NOT NULL DEFAULT '',
           updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
           PRIMARY KEY (review_id, token_hash, segment_key)
       )""",
    """CREATE TABLE IF NOT EXISTS cr_event (
           id          BIGSERIAL PRIMARY KEY,
           at          TIMESTAMPTZ NOT NULL DEFAULT now(),
           review_id   TEXT NOT NULL,
           token_hash  TEXT NOT NULL,
           segment_key TEXT NOT NULL,
           field       TEXT NOT NULL,
           value       TEXT,
           client_ts   DOUBLE PRECISION,
           ua          TEXT
       )""",
    "CREATE INDEX IF NOT EXISTS cr_event_review ON cr_event (review_id, at DESC)",
    """CREATE TABLE IF NOT EXISTS cr_media (
           review_id   TEXT NOT NULL,
           segment_key TEXT NOT NULL,
           kind        TEXT NOT NULL,
           data        BYTEA NOT NULL,
           at          TIMESTAMPTZ NOT NULL DEFAULT now(),
           PRIMARY KEY (review_id, segment_key, kind)
       )""",
]


def sha(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


# ── reviews on disk ──────────────────────────────────────────────────────────
class Review:
    def __init__(self, d, folder):
        self.review_id = d["review_id"]
        self.title = d.get("title", self.review_id)
        self.slack_channel = d.get("slack_channel", "")
        self.reviewers = {r["token_sha256"]: r.get("label", "reviewer") for r in d.get("reviewers", [])}
        with open(os.path.join(folder, "segments.json"), encoding="utf-8") as f:
            segs = json.load(f)
        self.segments = [s for s in segs if KEY_RE.match(str(s.get("key", "")))]
        self.order = [s["key"] for s in self.segments]
        self.clip_of = {s["key"]: s.get("clip", "") for s in self.segments}
        self.seg = {s["key"]: s for s in self.segments}
        self.page_path = os.path.join(folder, "page.html")


def load_reviews(base=REVIEWS_DIR):
    out = {}
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        folder = os.path.join(base, name)
        cfg = os.path.join(folder, "review.json")
        if not os.path.isfile(cfg):
            continue
        try:
            with open(cfg, encoding="utf-8") as f:
                r = Review(json.load(f), folder)
            out[r.review_id] = r
        except Exception as e:
            print("[CR] review %s skipped: %r" % (name, e))
    return out


def find_review(reviews, token):
    """(review, token_hash, label) for a token, or (None, None, None)."""
    if not TOKEN_RE.match(str(token or "")):
        return None, None, None
    h = sha(token)
    for r in reviews.values():
        if h in r.reviewers:
            return r, h, r.reviewers[h]
    return None, None, None


# ── the rules (pure) ─────────────────────────────────────────────────────────
def clean_fields(body):
    """Validate a POST body. Returns (segment_key, fields) or raises ValueError."""
    if not isinstance(body, dict):
        raise ValueError("body must be an object")
    k = str(body.get("segment_key") or "")
    if not KEY_RE.match(k):
        raise ValueError("bad segment_key")
    f = {}
    if "technique" in body:
        t = body["technique"]
        if t is None or t == "":
            f["technique"] = None
        elif isinstance(t, str) and len(t) <= MAX_TECH:
            f["technique"] = t          # verbatim — never trimmed, never re-keyed
        else:
            raise ValueError("bad technique")
    if "is_best" in body:
        if not isinstance(body["is_best"], bool):
            raise ValueError("is_best must be true or false")
        f["is_best"] = body["is_best"]
    if "note" in body:
        n = body["note"]
        if n is None:
            n = ""
        if not isinstance(n, str):
            raise ValueError("bad note")
        f["note"] = n[:MAX_NOTE]
    if not f:
        raise ValueError("nothing to save")
    return k, f


def _blank():
    return {"technique": None, "is_best": False, "note": ""}


def _group(rows, clip_of, key):
    """Keys that share `key`'s best-take scope."""
    r = rows.get(key) or _blank()
    t = r.get("technique")
    if t:
        return [k for k, v in rows.items() if k != key and v.get("technique") == t]
    c = clip_of.get(key, "")
    return [k for k, v in rows.items()
            if k != key and not v.get("technique") and clip_of.get(k, "") == c]


def apply_answer(rows, clip_of, key, fields):
    """Apply one POST to this reviewer's rows (dict key -> row), in place.

    Returns {key: row} for every row that changed, including the target.
    Best-take exclusivity is enforced here: when the target ends up starred —
    because it was starred, or because a starred segment was renamed into a new
    technique — every other star in its scope is cleared.
    """
    before = {k: dict(v) for k, v in rows.items()}
    row = rows.setdefault(key, _blank())
    for name, val in fields.items():
        row[name] = val
    if row.get("is_best"):
        for k in _group(rows, clip_of, key):
            if rows[k].get("is_best"):
                rows[k]["is_best"] = False
    changed = {}
    for k, v in rows.items():
        if before.get(k) != v:
            changed[k] = dict(v)
    if key not in changed:
        changed[key] = dict(row)
    return changed


def progress(review, rows_by_token):
    """Counts for the admin page, per reviewer."""
    out = []
    for h, rows in rows_by_token.items():
        named = [k for k in review.order if (rows.get(k) or {}).get("technique")]
        techs = {}
        for k in named:
            techs.setdefault(rows[k]["technique"], []).append(bool(rows[k].get("is_best")))
        out.append({"token_hash": h[:10], "label": review.reviewers.get(h, "?"),
                    "named": len(named), "of": len(review.order),
                    "best": sum(1 for k in review.order if (rows.get(k) or {}).get("is_best")),
                    "techniques": len(techs),
                    "techniques_without_best": sum(1 for v in techs.values() if not any(v))})
    return out


def to_csv(review, answers):
    """answers: list of dicts with label, segment_key, technique, is_best, note, updated_at."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["reviewer", "segment_key", "clip", "rep", "wall_clock", "duration_s",
                "weapon_seen", "technique", "best", "note", "updated_at"])
    for a in answers:
        s = review.seg.get(a["segment_key"], {})
        w.writerow([a.get("label", ""), a["segment_key"], s.get("clip", ""),
                    "%s of %s" % (s.get("rep_n", ""), s.get("rep_of", "")),
                    s.get("wall_clock", ""), s.get("duration_s", ""), s.get("weapon", ""),
                    a.get("technique") or "", "BEST" if a.get("is_best") else "",
                    (a.get("note") or "").replace("\n", " "), a.get("updated_at", "")])
    return buf.getvalue()


def media_ok(kind, data):
    if kind not in MEDIA_LIMITS or not data:
        return False
    lo, hi, magic = MEDIA_LIMITS[kind]
    if not (lo <= len(data) <= hi):
        return False
    if magic and not data.startswith(magic):
        return False
    if kind == "clip" and b"ftyp" not in data[:64]:
        return False
    return True


# ── storage ──────────────────────────────────────────────────────────────────
def _pg():
    try:
        import pg_store
        return pg_store if pg_store.enabled() else None
    except Exception:
        return None


class _Conn:
    """psycopg2's `with conn` commits but does not close; this does both."""
    def __init__(self, pg):
        self.c = pg._conn()

    def __enter__(self):
        return self.c

    def __exit__(self, et, ev, tb):
        try:
            if et is None:
                self.c.commit()
            else:
                self.c.rollback()
        finally:
            self.c.close()
        return False


def init_schema():
    pg = _pg()
    if not pg:
        return False
    try:
        with _Conn(pg) as c, c.cursor() as cur:
            for stmt in DDL:
                cur.execute(stmt)
        return True
    except Exception as e:
        print("[CR] init_schema failed: %r" % (e,))
        return False


def db_rows(review_id, token_hash, cur):
    cur.execute("""SELECT segment_key, technique, is_best, note FROM cr_answer
                    WHERE review_id=%s AND token_hash=%s""", (review_id, token_hash))
    return {k: {"technique": t, "is_best": bool(b), "note": n or ""} for k, t, b, n in cur.fetchall()}


def db_answer(review, token_hash, key, fields, client_ts=None, ua=""):
    """Transactional upsert + exclusivity. Returns changed rows or None on failure."""
    pg = _pg()
    if not pg:
        return None
    try:
        with _Conn(pg) as c, c.cursor() as cur:
            # one writer per reviewer at a time: phone and iPad cannot interleave
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (review.review_id + ":" + token_hash,))
            rows = db_rows(review.review_id, token_hash, cur)
            changed = apply_answer(rows, review.clip_of, key, fields)
            for k, r in changed.items():
                cur.execute(
                    """INSERT INTO cr_answer (review_id, token_hash, segment_key, technique,
                                              is_best, note, updated_at)
                            VALUES (%s,%s,%s,%s,%s,%s, now())
                       ON CONFLICT (review_id, token_hash, segment_key) DO UPDATE SET
                            technique=EXCLUDED.technique, is_best=EXCLUDED.is_best,
                            note=EXCLUDED.note, updated_at=now()""",
                    (review.review_id, token_hash, k, r["technique"], r["is_best"], r["note"]))
            for name, val in fields.items():
                cur.execute(
                    """INSERT INTO cr_event (review_id, token_hash, segment_key, field, value,
                                             client_ts, ua) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (review.review_id, token_hash, key, name,
                     None if val is None else str(val), client_ts, (ua or "")[:200]))
        return changed
    except Exception as e:
        print("[CR] db_answer failed: %r" % (e,))
        return None


def db_answers_for(review_id, token_hash):
    pg = _pg()
    if not pg:
        return None
    try:
        with _Conn(pg) as c, c.cursor() as cur:
            return db_rows(review_id, token_hash, cur)
    except Exception as e:
        print("[CR] db_answers_for failed: %r" % (e,))
        return None


def db_all(review_id):
    """(answers newest first, last touch per reviewer, rows grouped by token)."""
    pg = _pg()
    if not pg:
        return None
    try:
        with _Conn(pg) as c, c.cursor() as cur:
            cur.execute("""SELECT token_hash, segment_key, technique, is_best, note, updated_at
                             FROM cr_answer WHERE review_id=%s ORDER BY updated_at DESC""",
                        (review_id,))
            ans = [{"token_hash": h, "segment_key": k, "technique": t, "is_best": bool(b),
                    "note": n or "", "updated_at": u.isoformat() if u else ""}
                   for h, k, t, b, n, u in cur.fetchall()]
            cur.execute("""SELECT token_hash, max(at), count(*) FROM cr_event
                            WHERE review_id=%s GROUP BY token_hash""", (review_id,))
            touch = {h: {"last": a.isoformat() if a else "", "events": n} for h, a, n in cur.fetchall()}
        by_tok = {}
        for a in ans:
            by_tok.setdefault(a["token_hash"], {})[a["segment_key"]] = a
        return ans, touch, by_tok
    except Exception as e:
        print("[CR] db_all failed: %r" % (e,))
        return None


def db_media_get(review_id, key, kind):
    pg = _pg()
    if not pg:
        return None
    try:
        with _Conn(pg) as c, c.cursor() as cur:
            cur.execute("SELECT data FROM cr_media WHERE review_id=%s AND segment_key=%s AND kind=%s",
                        (review_id, key, kind))
            r = cur.fetchone()
            return bytes(r[0]) if r else None
    except Exception as e:
        print("[CR] media_get failed: %r" % (e,))
        return None


def db_media_put_once(review_id, key, kind, data):
    """True if stored, False if it already existed, None on failure."""
    pg = _pg()
    if not pg:
        return None
    try:
        import psycopg2
        with _Conn(pg) as c, c.cursor() as cur:
            cur.execute("""INSERT INTO cr_media (review_id, segment_key, kind, data)
                           VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING 1""",
                        (review_id, key, kind, psycopg2.Binary(data)))
            return cur.fetchone() is not None
    except Exception as e:
        print("[CR] media_put failed: %r" % (e,))
        return None


def db_media_count(review_id):
    pg = _pg()
    if not pg:
        return {}
    try:
        with _Conn(pg) as c, c.cursor() as cur:
            cur.execute("SELECT kind, count(*) FROM cr_media WHERE review_id=%s GROUP BY kind", (review_id,))
            return dict(cur.fetchall())
    except Exception:
        return {}


# ── routes ───────────────────────────────────────────────────────────────────
_ADMIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Review · %(title)s</title>
<style>body{font:14px system-ui,sans-serif;margin:16px;color:#111;background:#fafafa}
h1{font-size:18px;margin:0 0 4px}.sub{color:#666;margin-bottom:12px}
table{border-collapse:collapse;width:100%%;background:#fff;margin-bottom:18px}
th,td{border:1px solid #ddd;padding:5px 7px;text-align:left;vertical-align:top;font-size:13px}
th{background:#f0f0f0;position:sticky;top:0}.best{color:#b8860b;font-weight:600}
.k{display:flex;gap:18px;flex-wrap:wrap;margin:8px 0 14px}.k div{background:#fff;border:1px solid #ddd;padding:8px 12px;border-radius:6px}
.k b{font-size:20px;display:block}a{color:#0645ad}.muted{color:#888}</style></head><body>
<h1>%(title)s</h1><div class="sub">Live — refreshes every 15 s · <a id="csv" href="#">CSV export</a> · <span id="at" class="muted"></span></div>
<div class="k" id="kpis"></div><h2 style="font-size:15px">Best takes by technique</h2><table id="bytech"></table>
<h2 style="font-size:15px">All answers, newest change first</h2><table id="all"></table>
<script>
const Q=location.search;document.getElementById('csv').href=location.pathname+'.csv'+Q;
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function go(){
 try{const r=await fetch(location.pathname+'.json'+Q,{cache:'no-store'});const d=await r.json();
 if(!d.ok){document.getElementById('at').textContent=d.error||'error';return;}
 document.getElementById('kpis').innerHTML=d.reviewers.map(p=>'<div><span class="muted">'+esc(p.label)+'</span><b>'+p.named+' / '+p.of+'</b>named · '+p.best+' starred · '+p.techniques_without_best+' of '+p.techniques+' techniques without a best take<br><span class="muted">last touch '+esc(p.last||'—')+'</span></div>').join('')||'<div>No answers yet.</div>';
 let h='<tr><th>technique</th><th>reviewer</th><th>best take</th><th>other takes</th></tr>';
 d.by_technique.forEach(t=>{h+='<tr><td>'+esc(t.technique)+'</td><td>'+esc(t.label)+'</td><td class="best">'+esc(t.best||'(not chosen)')+'</td><td>'+esc(t.others.join(', '))+'</td></tr>';});
 document.getElementById('bytech').innerHTML=h;
 h='<tr><th>updated</th><th>reviewer</th><th>segment</th><th>clip · rep · time</th><th>technique</th><th>best</th><th>note</th></tr>';
 d.answers.forEach(a=>{h+='<tr><td>'+esc(a.updated_at.replace('T',' ').slice(0,19))+'</td><td>'+esc(a.label)+'</td><td>'+esc(a.segment_key)+'</td><td>'+esc(a.where)+'</td><td>'+esc(a.technique||'')+'</td><td class="best">'+(a.is_best?'★':'')+'</td><td>'+esc(a.note)+'</td></tr>';});
 document.getElementById('all').innerHTML=h;document.getElementById('at').textContent='updated '+new Date().toLocaleTimeString();
 }catch(e){document.getElementById('at').textContent='offline — retrying';}}
go();setInterval(go,15000);
</script></body></html>"""


def register(app, admin_ok, report_error=None, notify=None, session_ok=None, reviews=None):
    """Attach the routes.

    admin_ok(secret) -> bool     the app's admin check (?secret=)
    session_ok() -> bool         optional: an MWM sign-in (the VI session)
    notify(channel, text)        optional: a Slack line
    """
    from flask import request, jsonify, make_response, redirect

    R = reviews if reviews is not None else load_reviews()
    media_cache = {}
    ping_lock = threading.Lock()

    def _err(where, exc, ctx=""):
        try:
            (report_error or (lambda w, e, c="": print("[CR]", w, e, c)))(where, exc, ctx)
        except Exception:
            pass

    def _private(resp, cache="no-store"):
        resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = cache
        return resp

    def _nf():
        return _private(make_response("Not found", 404))

    def _admin():
        try:
            if admin_ok(request.values.get("secret", "")):
                return True
        except Exception:
            pass
        try:
            return bool(session_ok and session_ok())
        except Exception:
            return False

    def _maybe_ping(review, token_hash, label):
        if not notify or not review.slack_channel:
            return
        try:
            import pg_store
            rows = db_answers_for(review.review_id, token_hash) or {}
            named = sum(1 for k in review.order if (rows.get(k) or {}).get("technique"))
            base = "cr_ping:%s:%s:" % (review.review_id, token_hash[:12])
            with ping_lock:
                if rows and not pg_store.load_state(base + "first", False):
                    pg_store.save_state(base + "first", True)
                    notify(review.slack_channel,
                           "📝 *%s* — first answer just arrived from %s. Live table: /admin/review/%s"
                           % (review.title, label, review.review_id))
                if named >= len(review.order) and not pg_store.load_state(base + "done", False):
                    pg_store.save_state(base + "done", True)
                    notify(review.slack_channel,
                           "✅ *%s* — %s has named all %d. Live table: /admin/review/%s"
                           % (review.title, label, len(review.order), review.review_id))
        except Exception as e:
            _err("client_review.ping", e)

    @app.route("/r/<token>", methods=["GET"])
    def cr_page_noslash(token):
        rv, _, _ = find_review(R, token)
        if not rv:
            return _nf()
        return _private(redirect("/r/%s/" % token, code=302))

    @app.route("/r/<token>/", methods=["GET"])
    def cr_page(token):
        rv, _, _ = find_review(R, token)
        if not rv:
            return _nf()
        try:
            with open(rv.page_path, encoding="utf-8") as f:
                html = f.read()
            resp = make_response(html, 200)
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            return _private(resp)
        except Exception as e:
            _err("client_review.page", e, rv.review_id)
            return _private(make_response("Temporarily unavailable", 503))

    def _media(token, key, kind, mime):
        rv, _, _ = find_review(R, token)
        if not rv or key not in rv.seg:
            return _nf()
        ck = (rv.review_id, key, kind)
        data = media_cache.get(ck)
        if data is None:
            data = db_media_get(rv.review_id, key, kind)
            if data is None:
                return _nf()
            if kind == "poster" or len(media_cache) < 120:
                media_cache[ck] = data
        total = len(data)
        rng = request.headers.get("Range", "")
        if rng.startswith("bytes="):
            try:
                a, b = rng[6:].split("-", 1)
                start = int(a) if a else max(0, total - int(b))
                end = int(b) if (a and b) else total - 1
                end = min(end, total - 1)
                if start > end:
                    raise ValueError
                resp = make_response(data[start:end + 1], 206)
                resp.headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, total)
            except ValueError:
                resp = make_response(b"", 416)
                resp.headers["Content-Range"] = "bytes */%d" % total
        else:
            resp = make_response(data, 200)
        resp.headers["Content-Type"] = mime
        resp.headers["Accept-Ranges"] = "bytes"
        return _private(resp, cache="private, max-age=86400")

    @app.route("/r/<token>/p/<key>.jpg", methods=["GET"])
    def cr_poster(token, key):
        try:
            return _media(token, key, "poster", "image/jpeg")
        except Exception as e:
            _err("client_review.poster", e, key)
            return _nf()

    @app.route("/r/<token>/c/<key>.mp4", methods=["GET", "HEAD"])
    def cr_clip(token, key):
        try:
            return _media(token, key, "clip", "video/mp4")
        except Exception as e:
            _err("client_review.clip", e, key)
            return _nf()

    @app.route("/r/<token>/setup/<kind>/<key>", methods=["POST"])
    def cr_setup(token, kind, key):
        rv, _, _ = find_review(R, token)
        if not rv or key not in rv.seg or kind not in MEDIA_LIMITS:
            return _nf()
        data = request.get_data(cache=False) or b""
        if not media_ok(kind, data):
            return _private(jsonify({"ok": False, "error": "not a valid %s" % kind})), 400
        res = db_media_put_once(rv.review_id, key, kind, data)
        if res is None:
            return _private(jsonify({"ok": False, "error": "could not store"})), 503
        if res is False:
            return _private(jsonify({"ok": False, "error": "already there — media is write-once"})), 409
        return _private(jsonify({"ok": True, "key": key, "kind": kind, "bytes": len(data)})), 200

    @app.route("/api/<token>/answers", methods=["GET"])
    def cr_answers(token):
        rv, h, _ = find_review(R, token)
        if not rv:
            return _nf()
        rows = db_answers_for(rv.review_id, h)
        if rows is None:
            return _private(jsonify({"ok": False, "error": "storage unavailable"})), 503
        return _private(jsonify({"ok": True, "review_id": rv.review_id, "answers": rows}))

    @app.route("/api/<token>/answer", methods=["POST"])
    def cr_answer(token):
        rv, h, label = find_review(R, token)
        if not rv:
            return _nf()
        try:
            body = request.get_json(force=True, silent=True)
            key, fields = clean_fields(body)
        except ValueError as ve:
            return _private(jsonify({"ok": False, "error": str(ve)})), 400
        if key not in rv.seg:
            return _private(jsonify({"ok": False, "error": "unknown segment"})), 400
        ts = body.get("ts") if isinstance(body.get("ts"), (int, float)) else None
        changed = db_answer(rv, h, key, fields, ts, request.headers.get("User-Agent", ""))
        if changed is None:
            return _private(jsonify({"ok": False, "error": "storage unavailable — kept on your phone, will retry"})), 503
        threading.Thread(target=_maybe_ping, args=(rv, h, label), daemon=True).start()
        return _private(jsonify({"ok": True, "changed": changed}))

    def _admin_data(rv):
        got = db_all(rv.review_id)
        if got is None:
            return None
        ans, touch, by_tok = got
        prog = progress(rv, by_tok)
        for p in prog:
            full = next((h for h in by_tok if h.startswith(p["token_hash"])), "")
            p["last"] = (touch.get(full) or {}).get("last", "")
        rows = []
        for a in ans:
            s = rv.seg.get(a["segment_key"], {})
            rows.append(dict(a, label=rv.reviewers.get(a["token_hash"], "?"),
                             where="%s · rep %s of %s · %s" % (s.get("clip", ""), s.get("rep_n", ""),
                                                               s.get("rep_of", ""), s.get("wall_clock", "")),
                             token_hash=a["token_hash"][:10]))
        bytech = []
        for h, rs in by_tok.items():
            techs = {}
            for k in rv.order:
                r = rs.get(k)
                if r and r.get("technique"):
                    techs.setdefault(r["technique"], []).append((k, r.get("is_best")))
            for t in sorted(techs):
                best = next((k for k, b in techs[t] if b), "")
                bytech.append({"technique": t, "label": rv.reviewers.get(h, "?"), "best": best,
                               "others": [k for k, b in techs[t] if not b]})
        return {"ok": True, "review_id": rv.review_id, "title": rv.title, "reviewers": prog,
                "answers": rows, "by_technique": bytech, "media": db_media_count(rv.review_id)}

    @app.route("/admin/review/<review_id>", methods=["GET"])
    def cr_admin(review_id):
        if not _admin():
            return make_response("Unauthorized — add ?secret=… or sign in at /vi/ first", 401)
        rv = R.get(review_id)
        if not rv:
            return _nf()
        resp = make_response(_ADMIN_PAGE % {"title": rv.title.replace("<", "")}, 200)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return _private(resp)

    @app.route("/admin/review/<review_id>.json", methods=["GET"])
    def cr_admin_json(review_id):
        if not _admin():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        rv = R.get(review_id)
        if not rv:
            return _nf()
        d = _admin_data(rv)
        if d is None:
            return jsonify({"ok": False, "error": "storage unavailable"}), 503
        return _private(jsonify(d))

    @app.route("/admin/review/<review_id>.csv", methods=["GET"])
    def cr_admin_csv(review_id):
        if not _admin():
            return make_response("unauthorized", 401)
        rv = R.get(review_id)
        if not rv:
            return _nf()
        d = _admin_data(rv)
        if d is None:
            return make_response("storage unavailable", 503)
        resp = make_response(to_csv(rv, d["answers"]), 200)
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = 'attachment; filename="%s.csv"' % rv.review_id
        return _private(resp)

    return R


def boot():
    ok = init_schema()
    print("[CR] client review schema %s" % ("ready" if ok else "NOT ready (no database?)"))
    return ok
