"""victory_ingest.py — load an event into the Victory Intelligence index.

Reads a folder under victory_source/<EVENT_KEY>/ containing:

    event.json      one object: event_key, title, client, starts_on, ends_on
    sessions.json   the sessions and their camera-card ranges, as DATA
    clips.json      the delivered clips (title, category, drive_id, weight, ...)
    quotes.json     the transcript lines (quote, quotable, weight, ...)

and writes them into vi_event / vi_session / vi_card_range / vi_record.

Two things this file exists to protect:

  ORDER. The demo's ranking is stable only because ties break on the record's
  position in the DATA array — clips first in clips.json order, then quotes in
  quotes.json order. `ord` preserves that exactly. Ingest in any other order
  and test_victory_index's parity assertions start failing for reasons that
  look like scoring bugs and are not.

  IDEMPOTENCE. Re-running an ingest must produce the same table, not a second
  copy. Every write is an upsert keyed on a deterministic id, and a re-ingest
  of an event first clears that event's records, so a corrected source file
  can simply be re-run.

Run it from the repo root:

    python3 victory_ingest.py VWC26            # ingest
    python3 victory_ingest.py VWC26 --dry-run  # parse and report, write nothing
"""
import os
import sys
import json

SOURCE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "victory_source")


# ── reading the source ─────────────────────────────────────────────────────
def _read(event_key, name, required=True):
    path = os.path.join(SOURCE_ROOT, event_key, name)
    if not os.path.exists(path):
        if required:
            raise FileNotFoundError(path)
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _make_id(event_key, natural, seen):
    """Event-scoped, unique, deterministic, and stable across re-ingests.

    The demo identified a quote as '<transcript>@<second>'. That was safe there
    because records lived in an array and the id was never used as a key. It is
    NOT safe as a primary key: two speaker turns can begin inside the same
    second, and Convention 2026 has eight such collisions. Left alone, Postgres
    would have accepted 1,865 of 1,873 records and the ranking would have
    drifted from the demo for reasons no one would have thought to look for.

    So the natural id is kept where it is unique, and only a colliding one
    takes a '#2', '#3' suffix, in source order. Same input, same ids, every run.

    (Note for the render worker: a timecode is therefore not a unique locator
    for a quote either. Cut from the record, not from the timecode.)
    """
    base = "%s:%s" % (event_key, natural)
    n = seen.get(base, 0) + 1
    seen[base] = n
    return base if n == 1 else "%s#%d" % (base, n)


def build_rows(event_key):
    """Source files -> (event, sessions, records). Pure; touches no database.

    Kept separate from the write so the shape can be tested without Postgres.
    """
    event = _read(event_key, "event.json")
    sessions = _read(event_key, "sessions.json")
    clips = _read(event_key, "clips.json")
    quotes = _read(event_key, "quotes.json", required=False) or []

    if event.get("event_key") != event_key:
        raise ValueError("event.json says %r but the folder is %r"
                         % (event.get("event_key"), event_key))

    records = []
    ord_no = 0
    seen = {}

    for c in clips:                      # clips first — the demo's DATA order
        records.append({
            "id": _make_id(event_key, c["id"], seen),
            "event_key": event_key,
            "ord": ord_no,
            "kind": "clip",
            "title": c.get("title"),
            "category": c.get("category"),
            "session": c.get("session"),
            "blob": c.get("text"),
            "weight": c.get("weight") or 0.4,
            "quotable": None,
            "day_no": c.get("day"),
            "date_label": c.get("date"),
            "camera": c.get("camera"),
            "file": c.get("file"),
            "folder": c.get("folder"),
            "source_id": c.get("source_id"),
            "drive_id": c.get("drive_id"),
            "thumb": c.get("thumb"),
            "timecode": None,
            "duration": c.get("duration"),
            "seconds": c.get("seconds"),
            "priority": c.get("priority"),
            "quote": None,
            "topics": None,
            "media": None,
        })
        ord_no += 1

    for q in quotes:                     # then quotes, in file order
        records.append({
            "id": _make_id(event_key, q["id"], seen),
            "event_key": event_key,
            "ord": ord_no,
            "kind": "quote",
            "title": q.get("title"),
            "category": q.get("category"),
            "session": q.get("session"),
            "blob": q.get("text"),
            "weight": q.get("weight") or 0.4,
            "quotable": bool(q.get("quotable")),
            "day_no": None,
            "date_label": q.get("date"),
            "camera": q.get("room"),
            "file": q.get("file"),
            "folder": q.get("folder"),
            "source_id": None,
            "drive_id": q.get("drive_id"),
            "thumb": None,
            "timecode": q.get("timecode"),
            "duration": q.get("duration"),
            "seconds": q.get("seconds"),
            "priority": q.get("priority"),
            "quote": q.get("quote"),
            "topics": q.get("topics"),
            "media": None,
        })
        ord_no += 1

    return event, sessions, records


# ── writing ────────────────────────────────────────────────────────────────
RECORD_COLS = [
    "id", "event_key", "ord", "kind", "title", "category", "session", "blob",
    "weight", "quotable", "day_no", "date_label", "camera", "file", "folder",
    "source_id", "drive_id", "thumb", "timecode", "duration", "seconds",
    "priority", "quote", "topics", "media",
]

_JSON_COLS = {"topics", "media"}

INSERT_CHUNK = 500


def _insert_many(cur, sql, rows, chunk=INSERT_CHUNK):
    """Insert rows in batches, falling back to one-at-a-time if psycopg2's
    extras are unavailable.

    `sql` must end in `VALUES %s` for the batched path. The fallback rebuilds a
    normal parameterised INSERT — still safe, just slow — so a missing extras
    module degrades the speed rather than the correctness.
    """
    if not rows:
        return 0
    try:
        from psycopg2.extras import execute_values
    except Exception:
        execute_values = None
    if execute_values is not None:
        for i in range(0, len(rows), chunk):
            execute_values(cur, sql, rows[i:i + chunk], page_size=chunk)
        return len(rows)
    marks = "(" + ",".join(["%s"] * len(rows[0])) + ")"
    one = sql.replace("VALUES %s", "VALUES " + marks)
    for r in rows:
        cur.execute(one, r)
    return len(rows)


def ingest(event_key, dry_run=False):
    """Load one event. Returns a summary dict; never raises into a caller."""
    try:
        event, sessions, records = build_rows(event_key)
    except Exception as e:
        return {"ok": False, "event": event_key, "error": "source: %s" % e}

    summary = {
        "ok": True, "event": event_key, "title": event.get("title"),
        "sessions": len(sessions),
        "ranges": sum(len(s.get("ranges") or []) for s in sessions),
        "records": len(records),
        "clips": sum(1 for r in records if r["kind"] == "clip"),
        "quotes": sum(1 for r in records if r["kind"] == "quote"),
        "with_drive_id": sum(1 for r in records if r.get("drive_id")),
        "dry_run": bool(dry_run),
        "written": 0,
    }
    if dry_run:
        return summary

    try:
        import pg_store
        import victory_index as vi
        if not pg_store.enabled():
            summary["ok"] = False
            summary["error"] = "DATABASE_URL not set"
            return summary
        if not vi.init_schema():
            summary["ok"] = False
            summary["error"] = "init_schema failed"
            return summary

        with pg_store._conn() as c, c.cursor() as cur:
            cur.execute(
                """INSERT INTO vi_event (event_key, title, client, starts_on, ends_on, note)
                        VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (event_key) DO UPDATE SET
                        title=EXCLUDED.title, client=EXCLUDED.client,
                        starts_on=EXCLUDED.starts_on, ends_on=EXCLUDED.ends_on,
                        note=EXCLUDED.note""",
                (event_key, event.get("title"), event.get("client") or "victory",
                 event.get("starts_on") or None, event.get("ends_on") or None,
                 event.get("note")))

            # Sessions and ranges are rebuilt wholesale: they are small, and a
            # partial update would leave a camera range that no longer exists.
            cur.execute("DELETE FROM vi_session WHERE event_key = %s", (event_key,))
            for s in sessions:
                cur.execute(
                    """INSERT INTO vi_session (event_key, day_no, date_label,
                                               session_label, priority)
                            VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                    (event_key, s.get("day_no"), s.get("date_label"),
                     s.get("session_label"), s.get("priority") or "standard"))
                sid = cur.fetchone()[0]
                for r in (s.get("ranges") or []):
                    cur.execute(
                        """INSERT INTO vi_card_range (session_id, camera, camera_body,
                                camera_short, card, id_kind, lo, hi)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (sid, r.get("camera"), r.get("camera_body"),
                         r.get("camera_short"), r.get("card"),
                         r.get("id_kind"), r.get("lo"), r.get("hi")))

            # Records: clear this event, then insert in ord order.
            #
            # BATCHED, and not as an optimisation. The first version issued one
            # INSERT per record — 1,873 round trips to a cross-region Postgres
            # from inside a web request — and Railway killed the worker at two
            # minutes with a 500. execute_values sends them in chunks, so this
            # is four statements instead of 1,873.
            #
            # The DELETE and the INSERTs share one transaction: a failure part
            # way through rolls the whole thing back rather than leaving the
            # event half-loaded, which would be worse than not loading it.
            cur.execute("DELETE FROM vi_record WHERE event_key = %s", (event_key,))
            rows = []
            for rec in records:
                vals = []
                for col in RECORD_COLS:
                    v = rec.get(col)
                    vals.append(json.dumps(v) if col in _JSON_COLS and v is not None else v)
                rows.append(tuple(vals))
            sql = "INSERT INTO vi_record (%s) VALUES %%s" % ",".join(RECORD_COLS)
            _insert_many(cur, sql, rows)
            summary["written"] = len(rows)

        vi.load_corpus(force=True)
        summary["corpus"] = vi.corpus_size()
        return summary
    except Exception as e:
        summary["ok"] = False
        summary["error"] = repr(e)
        return summary


def list_events():
    """Which events have source folders on disk."""
    if not os.path.isdir(SOURCE_ROOT):
        return []
    return sorted(d for d in os.listdir(SOURCE_ROOT)
                  if os.path.isfile(os.path.join(SOURCE_ROOT, d, "event.json")))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if not args:
        print("events with source on disk:", ", ".join(list_events()) or "(none)")
        print("usage: python3 victory_ingest.py <EVENT_KEY> [--dry-run]")
        sys.exit(0)
    out = ingest(args[0], dry_run=dry)
    print(json.dumps(out, indent=2))
    sys.exit(0 if out.get("ok") else 1)
