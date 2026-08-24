#!/usr/bin/env python3
"""sheets_queue.py — PATCH #107. The Sheets CRM write path loses people.

WHAT HAPPENED, 23 AUG 2026 19:51:26 ET
--------------------------------------
`log_new_contact_to_sheets` raised `HttpError 403 The caller does not have
permission` writing to the Maya Leads Report. It did what it has always done
on failure: reported the error and returned. The row was never written and
nothing ever tried again.

Three failures in ten hours. Two of them were FIRST CONTACT from a real human
being. The heartbeat stayed green through all of it — threads 20/20, Postgres
healthy, the lead counter still climbing — because the counter reads Postgres
and the report reads the sheet, and only one of them was broken.

This is the same defect PATCH #103 fixed on the Postgres path on 18 Aug, and
the comment there says it plainly: "a failed write used to be DISCARDED here."
Same sentence, different door. leads_db got a retry queue; this path never did.

WHY A 403 IS THE WORST CASE FOR A PATH WITH NO QUEUE
----------------------------------------------------
A dropped connection is transient — the next write succeeds and you lose one
record. A 403 is a STATE: it persists until a human changes a sharing setting.
Every capture in between goes the same way. The window here was over 34 hours
across a weekend, and the only reason it was caught is that DEV's error scan
reads a channel the checklist doesn't cover.

WHAT THIS MODULE IS
-------------------
A durable, bounded, ordered retry queue that sits between the writers and the
sheet. It is deliberately PURE — no app import, no network, no clock of its
own — so the ordering and eviction rules can be tested without a spreadsheet.
app.py injects the real writers at drain time and pg_store for persistence.

FOUR RULES, EACH OF THEM A DECISION
-----------------------------------
1. CREATES DRAIN BEFORE UPDATES for the same lead. An update whose row does
   not exist yet takes the `target_row is None` branch in update_lead_columns
   and is DISCARDED with a log line — so replaying them out of order would
   quietly lose exactly what we queued them to save. Insertion order gives us
   this for free: the create failed first, so it is queued first. Merging an
   update into an existing entry must therefore never move its position.

2. UNDER SATURATION WE DROP A STATUS CHANGE, NEVER A PERSON. When the queue is
   full the oldest UPDATE is evicted. A create is a human who contacted us and
   exists nowhere else; an update is a field on a row that already exists. If
   that trade is ever wrong, it is wrong in the recoverable direction.

3. A PERMANENT FAILURE IS NOT RETRIED. A 400 means the request is malformed
   and will be malformed forever; retrying it is an infinite loop wearing a
   queue costume. It is dropped once, loudly, with the reason.

4. ALERT ON DEPTH, NOT ON EVENTS. PATCH #103 learned this: a per-record alert
   during an outage is a denial-of-service on the person who has to fix it.
   Depth 1, 10 and 100 speak; everything between them counts.

Run the tests: python3 test_sheets_queue.py
"""

import json
import re
import time

# ── configuration ────────────────────────────────────────────────────────────

MAX_QUEUE = 500          # entries, not bytes — see rule 2 for what goes first
STATE_KEY = "sheets_queue.v1"
ALERT_DEPTHS = (1, 10, 100)

OP_CREATE = "create"     # log_new_contact_to_sheets(sender)
OP_UPDATE = "update"     # update_lead_columns(sender, updates)

BACKOFF_BASE = 30        # seconds
BACKOFF_MAX = 300        # a 403 waits on a human; hammering it helps nobody

# ── failure classification ───────────────────────────────────────────────────

# A 400 is the request's fault and will never succeed. Everything else we have
# actually seen on this path — 403 (ACL), 429 (quota), 5xx, socket resets — is
# a condition that clears, so it is worth holding.
_PERMANENT_RE = re.compile(r"\b(400|invalid[_ ]argument|malformed)\b", re.I)


def is_retryable(err):
    """False only when retrying is certain to fail forever."""
    return not bool(_PERMANENT_RE.search(str(err or "")))


# ── state ────────────────────────────────────────────────────────────────────

_queue = []
_stats = {"queued": 0, "drained": 0, "dropped_permanent": 0,
          "dropped_overflow": 0, "attempts": 0}
_alerted_depths = set()


def reset():
    """Tests only. Production state lives for the life of the process."""
    del _queue[:]
    for k in _stats:
        _stats[k] = 0
    _alerted_depths.clear()


def depth():
    return len(_queue)


def stats():
    """Read this at /health. `depth` climbing and never settling means the
    sheet is still unreachable and leads are waiting, not lost."""
    out = dict(_stats)
    out["depth"] = len(_queue)
    return out


def snapshot():
    """Serialisable copy — what gets persisted."""
    return [dict(e) for e in _queue]


# ── enqueue ──────────────────────────────────────────────────────────────────

def _find(op, sender):
    for e in _queue:
        if e["op"] == op and e["sender"] == sender:
            return e
    return None


def _evict_if_full(alert_cb=None):
    """Rule 2: make room by dropping the oldest UPDATE. Never a create."""
    if len(_queue) < MAX_QUEUE:
        return
    for i, e in enumerate(_queue):
        if e["op"] == OP_UPDATE:
            victim = _queue.pop(i)
            _stats["dropped_overflow"] += 1
            _emit(alert_cb, "sheets_queue.overflow",
                  "queue full (%d) — dropped the oldest column update" % MAX_QUEUE,
                  "lead=%s cols=%s. Creates are never evicted; a status change "
                  "was traded for a person." % (victim["sender"],
                                                sorted(victim.get("updates") or {})))
            return
    # All creates. We do not drop a person to make room for a person.
    _emit(alert_cb, "sheets_queue.full_of_creates",
          "queue is at %d and every entry is a new contact" % MAX_QUEUE,
          "Nothing was evicted. The sheet has been unwritable long enough that "
          "%d first-contact rows are waiting. This needs a human now." % MAX_QUEUE)


def enqueue(op, sender, updates=None, now=None, alert_cb=None):
    """A write failed. Hold it. Returns True if it is now queued."""
    if op not in (OP_CREATE, OP_UPDATE):
        return False
    now = time.time() if now is None else now

    existing = _find(op, sender)
    if existing is not None:
        if op == OP_UPDATE:
            # Merge in place. Later values win per column; the ENTRY KEEPS ITS
            # POSITION so it cannot overtake a queued create for this lead.
            merged = dict(existing.get("updates") or {})
            merged.update(updates or {})
            existing["updates"] = merged
            existing["last_failed"] = now
        # A duplicate create is a no-op: log_new_contact_to_sheets already
        # refuses to append a phone that is present in the tab.
        return True

    _evict_if_full(alert_cb)
    _queue.append({
        "op": op,
        "sender": sender,
        "updates": dict(updates or {}) if op == OP_UPDATE else None,
        "first_failed": now,
        "last_failed": now,
        "attempts": 0,
    })
    _stats["queued"] += 1
    _maybe_alert_depth(alert_cb)
    return True


def _maybe_alert_depth(alert_cb):
    d = len(_queue)
    if d in ALERT_DEPTHS and d not in _alerted_depths:
        _alerted_depths.add(d)
        _emit(alert_cb, "sheets_queue.depth",
              "%d Sheets CRM write(s) are queued, not lost" % d,
              "They will be replayed when the sheet is writable again. If this "
              "number keeps climbing, the spreadsheet is still unreachable — "
              "check that the service account is an Editor on it.")


def _emit(alert_cb, component, message, detail=""):
    print("[SHEETS_QUEUE] %s — %s %s" % (component, message, detail))
    if alert_cb:
        try:
            alert_cb(component, message, detail)
        except Exception:
            pass


# ── drain ────────────────────────────────────────────────────────────────────

def _due(entry, now):
    if entry["attempts"] == 0:
        return True
    wait = min(BACKOFF_MAX, BACKOFF_BASE * (2 ** (entry["attempts"] - 1)))
    return (now - entry["last_failed"]) >= wait


def drain(create_fn, update_fn, now=None, alert_cb=None, limit=None):
    """Replay queued writes in insertion order (rule 1).

    create_fn(sender) and update_fn(sender, updates) must RAISE on failure —
    a silent return is read as success, which is the bug this module exists
    to stop. Returns {'drained', 'kept', 'dropped'}.
    """
    now = time.time() if now is None else now
    drained = kept = dropped = 0
    survivors = []
    processed = 0

    for entry in _queue:
        if limit is not None and processed >= limit:
            survivors.append(entry)
            continue
        if not _due(entry, now):
            survivors.append(entry)
            kept += 1
            continue
        processed += 1
        entry["attempts"] += 1
        _stats["attempts"] += 1
        try:
            if entry["op"] == OP_CREATE:
                create_fn(entry["sender"])
            else:
                update_fn(entry["sender"], entry["updates"] or {})
            drained += 1
            _stats["drained"] += 1
        except Exception as e:
            entry["last_failed"] = now
            if is_retryable(e):
                survivors.append(entry)
                kept += 1
            else:
                dropped += 1
                _stats["dropped_permanent"] += 1
                _emit(alert_cb, "sheets_queue.permanent_failure",
                      "dropped a %s that can never succeed" % entry["op"],
                      "lead=%s error=%s" % (entry["sender"], e))

    del _queue[:]
    _queue.extend(survivors)
    if not _queue:
        _alerted_depths.clear()   # next outage gets its own first-alert
    return {"drained": drained, "kept": kept, "dropped": dropped}


# ── persistence ──────────────────────────────────────────────────────────────

def save(save_state_fn):
    """Persist so a deploy does not discard the queue. Never raises."""
    try:
        return bool(save_state_fn(STATE_KEY, snapshot()))
    except Exception as e:
        print("[SHEETS_QUEUE] save failed: %s" % e)
        return False


def restore(load_state_fn):
    """Load at boot. Unknown/broken payloads are ignored, not fatal."""
    try:
        raw = load_state_fn(STATE_KEY, [])
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, list):
            return 0
    except Exception as e:
        print("[SHEETS_QUEUE] restore failed: %s" % e)
        return 0
    del _queue[:]
    for e in raw:
        if not isinstance(e, dict) or e.get("op") not in (OP_CREATE, OP_UPDATE):
            continue
        if not e.get("sender"):
            continue
        _queue.append({
            "op": e["op"],
            "sender": e["sender"],
            "updates": dict(e.get("updates") or {}) if e["op"] == OP_UPDATE else None,
            "first_failed": e.get("first_failed") or 0,
            "last_failed": e.get("last_failed") or 0,
            "attempts": int(e.get("attempts") or 0),
        })
    return len(_queue)
