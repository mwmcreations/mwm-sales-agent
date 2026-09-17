"""victory_index.py — Victory Intelligence, Phase 1: the content layer as a service.

The demo (START_HERE__VICTORY_DEMO.html) carried 1,873 records and the whole
search engine inside one 45.8 MB HTML file, and it knew exactly one event.
This module is that same engine, moved server-side and made event-agnostic, so
three years of Victory footage can live in it instead of four days.

Two rules govern this file:

  1. THE RANKING IS A PORT, NOT A REWRITE. Every scoring decision below is
     lifted from the demo's JavaScript unchanged — the synonym table, the
     3.4/2.5/2.0/1.15 field weights, the 0.16 multi-term bonus, the 2.9
     priority term, the peak/speech modifiers and the 0.42 honesty floor.
     test_victory_index.py proves parity against the demo's own output. If a
     query ranks differently here than it did in front of the client, that is
     a bug in this file, not an improvement.

  2. NOTHING HERE MAY TAKE PRODUCTION DOWN. Same contract as pg_store: when
     DATABASE_URL is absent every function degrades to a no-op or an in-memory
     corpus, and no exception escapes into a request.

What changed from the demo, deliberately:

  * Convention 2026's sessions and camera-card ranges were HARDCODED in
    build_index.py's SESSIONS list. They are rows now (vi_session /
    vi_card_range), because Michael's scope is the whole archive.
  * Records carry event_key, so 'candlelight' can mean the 2026 convention or
    a 2024 belt ceremony, and the caller decides which collection to search.
  * Thumbnails and media are POINTERS (drive_id, thumb path), never base64.
    Embedding them is what made the demo 45.8 MB.
"""
import os
import re
import json
import threading

# ── the corpus we score against ────────────────────────────────────────────
# Full rows live in Postgres. Memory holds only the fields the scorer reads,
# so a 100k-record archive costs ~15 MB here instead of ~50 MB.
_corpus = []          # list of dicts: id, ord, event, k, t, cat, ses, s, w, qb
_corpus_lock = threading.Lock()
_corpus_event = None  # which event_key the loaded corpus covers (None = all)

# Full records, kept resident so a search does not need a database round trip.
#
# MEASURED, not assumed: with hydrate going to Postgres on every query, live
# search ran 815-844 ms across 38 queries. That variance is far too tight for
# compute — scoring 1,873 records in memory is single-digit milliseconds — so
# the whole cost was one cross-region round trip per search.
#
# Convention 2026 is 1,873 records and about 2.5 MB of pointers (no media, no
# base64), so holding all of it costs nothing worth measuring. RESIDENT_MAX is
# the guard for later: when the archive grows past it we stop filling the cache
# and fall back to fetching the seven rows a person is actually looking at,
# which is the behaviour this replaced.
RESIDENT_MAX = 25000
_records = {}         # id -> full record dict
_records_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════
# THE PORT — everything between here and END OF PORT mirrors the demo's JS.
# ═══════════════════════════════════════════════════════════════════════════

STOP = set(
    "the a an of from in on at to for with and or is are was were be been "
    "show me find get all any some that this it's our your my we i".split(" ")
)

# Order matters: multi-word keys are tested against the raw query first, then
# per-token. Python dicts preserve literal order, which is what JS Map did.
SYN = {
    "iconic": ["candlelight", "night of champions", "winning", "podium", "medal",
               "belt", "break", "celebration", "arms raised", "finale"],
    "best": ["candlelight", "winning", "podium", "champion", "medal", "celebration", "finale"],
    "highlight": ["candlelight", "winning", "champion", "medal", "celebration", "night of champions"],
    "emotional": ["candlelight", "proud", "moms", "cheering", "celebration", "family", "mother"],
    "powerful": ["break", "board", "strike", "champion", "candlelight"],
    "moment": ["moments"],
    "moments": ["celebration", "candlelight", "winning", "medal"],
    "ceremony": ["candlelight", "belt", "rank", "presentation", "masters"],
    "candle": ["candlelight", "candles"],
    "kids": ["kid", "children", "child", "students", "youth"],
    "children": ["kid", "kids", "child", "students"],
    "parents": ["mother", "mom", "moms", "father", "dad", "family", "proud"],
    "crowd": ["audience", "cheering", "spectators", "packed"],
    "win": ["winning", "winner", "won", "podium", "medal", "champion", "victory"],
    "winning": ["winner", "podium", "medal", "champion", "arms raised"],
    "champion": ["champions", "winning", "podium", "medal", "night of champions"],
    "blackbelt": ["black belt", "belt", "testing", "rank"],
    "black belt": ["belt", "testing", "rank", "presentation"],
    "belt": ["black belt", "rank", "presentation", "testing"],
    "break": ["board", "breaking", "hammer fist", "strike"],
    "boards": ["board", "break", "breaking"],
    "sparring": ["spar", "fight", "exchange", "headgear"],
    "forms": ["form", "kata", "pattern", "solo form"],
    "weapons": ["bo staff", "staff", "weapon"],
    "training": ["drill", "drills", "class", "practice", "seminar"],
    "instructor": ["instructors", "teaching", "coach", "master", "masters"],
    "grandmaster": ["grand master", "master", "masters", "founder"],
    "drone": ["aerial", "overhead"],
    "perseverance": ["persevere", "never give up", "keep going", "push through",
                     "didn't quit", "discipline", "hard work"],
    "respect": ["respect", "discipline", "responsibility", "courtesy"],
    "confidence": ["confident", "self esteem", "shy", "believe"],
    "community": ["together", "team", "family", "support", "school"],
    "tournament": ["competition", "finals", "compete", "competitor"],
    "interview": ["interviews", "podcast", "testimonial", "said", "says", "talking"],
    "quote": ["said", "says", "interview", "podcast"],
    "speech": ["address", "talk", "speaking", "said"],
}

# Queries asking for editorial peak rather than a subject. These lean on
# Victory's OWN priority markers (the call sheet's HERO/HIGH tags), not ours.
PEAK = re.compile(
    r"\b(iconic|best|greatest|highlight|highlights|top|standout|memorable|"
    r"emotional|powerful|hero|strongest|moving)\b", re.I)

SPEECH = re.compile(
    r"\b(on|about|talking|talks|speak|speaks|speaking|said|says|saying|quote|"
    r"quotes|story|stories|testimonial|interview|explains|describes)\b|"
    r"\b(perseverance|confidence|discipline|respect|gratitude|why|meaning)\b", re.I)

_NON_WORD = re.compile(r"[^a-z0-9\s']")
_WS = re.compile(r"\s+")


def norm(s):
    """Lowercase, strip punctuation to spaces, collapse whitespace."""
    s = (s or "").lower()
    s = _NON_WORD.sub(" ", s)
    return _WS.sub(" ", s).strip()


def expand(q):
    """Query -> {term: weight}. Literal terms weigh 1.0, synonyms 0.62.

    A synonym never overwrites a term the user actually typed, which is why
    every insert is guarded on absence rather than assigned outright.
    """
    raw = norm(q)
    toks = [w for w in raw.split(" ") if w and w not in STOP]
    out = {}
    for t in toks:
        out[t] = 1.0
    for k, syns in SYN.items():          # multi-word keys, against the raw query
        if " " in k and k in raw:
            for s in syns:
                out.setdefault(s, 0.62)
    for t in toks:                       # then single tokens
        for s in SYN.get(t, []):
            out.setdefault(s, 0.62)
    return out


def field_hit(padded, term):
    """Word-boundary matching, not substring.

    'bo staff' must not match 'aBOut', 'BOard', 'BOy' — which is exactly what a
    naive substring test does, and it turned a nine-result query into
    ninety-eight. A term matches a WHOLE word, or the START of a word when the
    term is long enough for that to mean something (so 'candle' still reaches
    'candlelight').
    """
    if (" " + term + " ") in padded:
        return 1.0
    if len(term) >= 4 and (" " + term) in padded:
        return 0.75
    return 0.0


def score(rec, terms, peak, speech):
    """One record against the expanded query. Weights are the demo's, exactly."""
    sc = 0.0
    hits = 0
    title = " " + norm(rec.get("t")) + " "
    cat = " " + norm(rec.get("cat")) + " "
    ses = " " + norm(rec.get("ses")) + " "
    blob = " " + (rec.get("s") or "") + " "
    for term, w in terms.items():
        got = 0.0
        h = field_hit(title, term)
        if h:
            got = max(got, 3.40 * w * h)
        h = field_hit(cat, term)
        if h:
            got = max(got, 2.50 * w * h)
        h = field_hit(ses, term)
        if h:
            got = max(got, 2.00 * w * h)
        h = field_hit(blob, term)
        if h:
            got = max(got, 1.15 * w * h)
        if got > 0:
            sc += got
            hits += 1
    if hits == 0:
        return 0.0
    sc *= (1 + 0.16 * (hits - 1))                       # breadth beats one hard hit
    sc += 2.9 * (rec.get("w") or 0.4) * (1.9 if peak else 1)
    if peak and rec.get("k") == "quote":
        sc *= 0.55                                      # 'iconic moments' wants pictures
    if speech:                                          # '...on perseverance' wants a voice
        if rec.get("k") == "quote" and rec.get("qb"):
            sc *= 1.85
        elif rec.get("k") == "clip":
            sc *= 0.72
    if rec.get("k") == "quote" and rec.get("qb") is False:
        sc *= 0.34
    return sc


HONESTY_FLOOR = 0.42
FALLBACK_ROWS = 8


def search_corpus(q, corpus):
    """Rank a corpus against a query. Returns (rows, peak, speech, fallback).

    The honesty floor is the part worth defending. Synonym expansion is
    generous on purpose — it is what lets 'iconic' reach the candlelight — but
    that generosity would let us print '171 moments found' for a query that
    really has nine good answers. Only results within reach of the best one
    are counted as found.
    """
    qs = q or ""
    peak = bool(PEAK.search(qs))
    speech = bool(SPEECH.search(qs)) and not peak
    terms = expand(qs)

    if not terms:
        rows = sorted([r for r in corpus if r.get("k") == "clip"],
                      key=lambda r: -(r.get("w") or 0))[:FALLBACK_ROWS]
        return rows, peak, speech, True

    scored = []
    for r in corpus:
        s = score(r, terms, peak, speech)
        if s > 0:
            scored.append((s, r))
    scored.sort(key=lambda x: -x[0])          # stable: ties keep corpus order

    rows = []
    if scored:
        top = scored[0][0]
        rows = [r for s, r in scored if s >= top * HONESTY_FLOOR]

    fallback = False
    if not rows:
        rows = sorted([r for r in corpus if r.get("k") == "clip"],
                      key=lambda r: -(r.get("w") or 0))
        fallback = True
    return rows, peak, speech, fallback

# ═══════════════════════════════════════════ END OF PORT ═══════════════════


# ── schema ─────────────────────────────────────────────────────────────────
DDL = [
    """CREATE TABLE IF NOT EXISTS vi_event (
           event_key   TEXT PRIMARY KEY,
           title       TEXT NOT NULL,
           client      TEXT NOT NULL DEFAULT 'victory',
           starts_on   DATE,
           ends_on     DATE,
           note        TEXT,
           created_at  TIMESTAMPTZ DEFAULT now()
       )""",
    """CREATE TABLE IF NOT EXISTS vi_session (
           id            BIGSERIAL PRIMARY KEY,
           event_key     TEXT NOT NULL REFERENCES vi_event(event_key) ON DELETE CASCADE,
           day_no        INT,
           date_label    TEXT,
           session_label TEXT NOT NULL,
           priority      TEXT NOT NULL DEFAULT 'standard'
       )""",
    """CREATE TABLE IF NOT EXISTS vi_card_range (
           id           BIGSERIAL PRIMARY KEY,
           session_id   BIGINT NOT NULL REFERENCES vi_session(id) ON DELETE CASCADE,
           camera       TEXT NOT NULL,
           camera_body  TEXT,
           camera_short TEXT,
           card         TEXT NOT NULL,
           id_kind      TEXT NOT NULL,
           lo           INT NOT NULL,
           hi           INT NOT NULL
       )""",
    """CREATE TABLE IF NOT EXISTS vi_record (
           id          TEXT PRIMARY KEY,
           event_key   TEXT NOT NULL REFERENCES vi_event(event_key) ON DELETE CASCADE,
           ord         INT NOT NULL,
           kind        TEXT NOT NULL,
           title       TEXT,
           category    TEXT,
           session     TEXT,
           blob        TEXT,
           weight      REAL NOT NULL DEFAULT 0.4,
           quotable    BOOLEAN,
           day_no      INT,
           date_label  TEXT,
           camera      TEXT,
           file        TEXT,
           folder      TEXT,
           source_id   TEXT,
           drive_id    TEXT,
           thumb       TEXT,
           timecode    TEXT,
           duration    TEXT,
           seconds     REAL,
           priority    TEXT,
           quote       TEXT,
           topics      JSONB,
           media       JSONB,
           created_at  TIMESTAMPTZ DEFAULT now()
       )""",
    "CREATE INDEX IF NOT EXISTS vi_record_event_ord ON vi_record (event_key, ord)",
    "CREATE INDEX IF NOT EXISTS vi_record_kind ON vi_record (kind)",
]

# The scorer reads these and nothing else.
CORPUS_COLS = "id, ord, event_key, kind, title, category, session, blob, weight, quotable"

# Everything a result row shows. Deliberately excludes `blob`, which is only
# search fodder and would double the resident size for no display value.
FULL_COLS = ("id, event_key, kind, title, category, session, weight, quotable, "
             "day_no, date_label, camera, file, folder, source_id, drive_id, "
             "thumb, timecode, duration, seconds, priority, quote, topics, media")


def _row_to_rec(row):
    """DB row -> the compact shape score() expects (demo key names kept)."""
    return {"id": row[0], "ord": row[1], "event": row[2], "k": row[3],
            "t": row[4], "cat": row[5], "ses": row[6], "s": row[7],
            "w": row[8], "qb": row[9]}


def init_schema():
    """Create the Victory Intelligence tables. Returns True on success."""
    try:
        import pg_store
        if not pg_store.enabled():
            return False
        with pg_store._conn() as c, c.cursor() as cur:
            for stmt in DDL:
                cur.execute(stmt)
        return True
    except Exception as e:
        print(f"[VI] init_schema failed: {e}")
        return False


def load_corpus(event_key=None, force=False):
    """Pull the scoreable fields into memory. Returns the record count.

    Called once at boot and after an ingest. Cheap enough to re-run; the guard
    is only there to stop every request paying for it.
    """
    global _corpus, _corpus_event, _records
    with _corpus_lock:
        if _corpus and not force and _corpus_event == event_key:
            return len(_corpus)
    try:
        import pg_store
        if not pg_store.enabled():
            return len(_corpus)
        where = " WHERE event_key = %s" if event_key else ""
        args = (event_key,) if event_key else ()
        with pg_store._conn() as c, c.cursor() as cur:
            cur.execute(f"SELECT {CORPUS_COLS} FROM vi_record{where}"
                        " ORDER BY event_key, ord", args)
            rows = [_row_to_rec(r) for r in cur.fetchall()]
            # One extra query at boot buys every later search its round trip
            # back. Skipped entirely once the archive outgrows RESIDENT_MAX.
            resident = {}
            if len(rows) <= RESIDENT_MAX:
                cur.execute(f"SELECT {FULL_COLS} FROM vi_record{where}", args)
                cols = [d[0] for d in cur.description]
                for r in cur.fetchall():
                    rec = dict(zip(cols, r))
                    resident[rec["id"]] = rec
        with _corpus_lock:
            _corpus = rows
            _corpus_event = event_key
        with _records_lock:
            _records = resident
        print(f"[VI] corpus loaded: {len(rows)} records"
              f"{' for ' + event_key if event_key else ''}"
              f", {len(resident)} resident")
        return len(rows)
    except Exception as e:
        print(f"[VI] load_corpus failed: {e}")
        return len(_corpus)


def corpus_size():
    with _corpus_lock:
        return len(_corpus)


def set_corpus(records, resident=None):
    """Install a corpus directly. Used by the tests and by offline tooling.

    Clears the resident cache unless one is supplied, so a test can never be
    served a row left behind by an earlier one.
    """
    global _corpus, _corpus_event, _records
    with _corpus_lock:
        _corpus = list(records)
        _corpus_event = None
    with _records_lock:
        _records = dict(resident or {})
    return len(_corpus)


def resident_count():
    with _records_lock:
        return len(_records)


def snapshot(event_key=None):
    """Every record, as the page would show it (the resident row when there
    is one, the compact one otherwise). For the helper's briefing and the
    ready-made ideas; never touches the database."""
    with _corpus_lock:
        rows = list(_corpus)
    with _records_lock:
        res = dict(_records)
    out = []
    for r in rows:
        if event_key and r.get("event") != event_key:
            continue
        out.append(res.get(r["id"]) or {"id": r["id"], "kind": r["k"], "title": r["t"],
                                        "category": r["cat"], "session": r["ses"],
                                        "weight": r["w"], "quotable": r["qb"]})
    return out


def hydrate(ids):
    """Fetch full rows for the handful of results actually being shown.

    This is the half of the design that lets the corpus stay small: we score
    against ten fields and only ever fetch the whole record for the seven rows
    a person is about to look at.
    """
    if not ids:
        return {}
    ids = list(ids)
    with _records_lock:
        out = {i: _records[i] for i in ids if i in _records}
    missing = [i for i in ids if i not in out]
    if not missing:
        return out
    try:
        import pg_store
        if not pg_store.enabled():
            return out
        with pg_store._conn() as c, c.cursor() as cur:
            cur.execute(f"SELECT {FULL_COLS} FROM vi_record WHERE id = ANY(%s)",
                        (missing,))
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                rec = dict(zip(cols, r))
                out[rec["id"]] = rec
        return out
    except Exception as e:
        print(f"[VI] hydrate failed: {e}")
        return out


def search(q, event_key=None, limit=7):
    """The public entry point. Returns a dict ready to be JSON-encoded.

    'found' is the honest count (after the floor), 'shown' is what we return.
    """
    with _corpus_lock:
        corpus = _corpus
    if event_key:
        corpus = [r for r in corpus if r.get("event") == event_key]
    rows, peak, speech, fallback = search_corpus(q, corpus)
    shown = rows[: max(1, int(limit or 7))]
    full = hydrate([r["id"] for r in shown])
    out = []
    for r in shown:
        rec = full.get(r["id"])
        out.append(rec if rec else {"id": r["id"], "kind": r["k"], "title": r["t"],
                                    "category": r["cat"], "session": r["ses"]})
    return {"ok": True, "query": q or "", "found": len(rows), "shown": len(out),
            "peak": peak, "speech": speech, "fallback": fallback,
            "event": event_key, "corpus": len(corpus), "results": out}
