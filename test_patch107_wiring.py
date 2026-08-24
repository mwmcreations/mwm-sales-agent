#!/usr/bin/env python3
"""test_patch107_wiring.py — does the queue actually SIT IN the write path?

sheets_queue.py passes 45 checks on its own. That proves the queue works. It
does not prove app.py uses it, and the difference between those two has cost
this board real time: Patch #105 passed every unit test and did not fire in
production because the live events were outside its horizon. Prove the wiring.

The single most important assertion here is §3: the drain must call BOTH
writers with _raise=True. Both functions swallow exceptions by design — if the
drain gets the swallowing version, every replay reads as a success and the
queue empties itself into the void. That failure would look exactly like a
working queue.

Run: python3 test_patch107_wiring.py
"""

import re
import sys

APP = open("app.py").read()

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


def body(start_marker, end_marker="\ndef "):
    seg = APP[APP.index(start_marker):]
    end = seg.index(end_marker, len(start_marker))
    return seg[:end]


# ── §1 · the module is imported and the helpers exist ────────────────────────
ok("import sheets_queue as _sq" in APP, "app.py imports sheets_queue")
ok("def _sq_alert(" in APP, "_sq_alert helper exists")
ok("def _sq_persist(" in APP, "_sq_persist helper exists")
ok(APP.index("def _sq_alert(") < APP.index("def log_new_contact_to_sheets("),
   "the helpers are defined BEFORE the writer that calls them")
ok(re.search(r"^import threading", APP, re.M) is not None,
   "threading is imported — the drain thread needs it")
ok(re.search(r"^import time", APP, re.M) is not None,
   "time is imported — the drain loop sleeps")

# ── §2 · both writers queue on failure instead of discarding ─────────────────
create = body("def log_new_contact_to_sheets(")
ok("_raise: bool = False" in create, "the create writer accepts _raise")
ok("_sq.enqueue(_sq.OP_CREATE" in create, "a failed create is ENQUEUED, not dropped")
ok("if _raise:\n            raise" in create, "and it re-raises when the drain calls it")
ok(create.index("if _raise:") < create.index("_sq.enqueue"),
   "the raise comes FIRST — a drain must never re-enqueue what it is draining")
ok("_sq_persist()" in create, "the queue is persisted after a create is queued")

update = body("def update_lead_columns(")
ok("_raise: bool = False" in update, "the update writer accepts _raise")
ok("_sq.enqueue(_sq.OP_UPDATE" in update, "a failed update is ENQUEUED, not dropped")
ok(update.count("if _raise:") == 2,
   "TWO raise points: the transport failure and the missing-row miss")
ok("_sq.enqueue" not in update[:update.index("data = []")],
   "a missing row is NOT enqueued from the live path — that is a Patch #61 bug, "
   "not a transport failure, and queueing it would retry it forever")
ok("raise RuntimeError" in update,
   "but during a drain a missing row raises, so the update stays queued")

# ── §3 · THE ONE THAT MATTERS · the drain gets the raising variants ──────────
drain = body("def _sq_drain_loop(")
ok("log_new_contact_to_sheets(snd, _raise=True)" in drain,
   "drain calls the create writer with _raise=True")
ok("update_lead_columns(snd, upd, _raise=True)" in drain,
   "drain calls the update writer with _raise=True")
ok(drain.count("_raise=True") == 2,
   "BOTH writers raise for the drain — one silent writer empties the queue into the void")
ok("_sq.drain(" in drain, "the loop actually calls sheets_queue.drain")
ok("_sq_persist()" in drain, "and persists whatever survives the drain")
ok("time.sleep(60)" in drain, "it waits between attempts rather than spinning")
ok("except Exception" in drain, "the loop cannot die on one bad entry")

# ── §4 · it starts, and it survives a deploy ─────────────────────────────────
ok("_sq.restore(_pg.load_state)" in APP, "the queue is restored from Postgres at boot")
ok('name="sheets_queue_drain"' in APP, "the drain thread is named, so it can be monitored")
ok("threading.Thread(target=_sq_drain_loop" in APP, "the drain thread is actually STARTED")
ok(APP.index("import pg_store as _pg") < APP.index("_sq.restore(_pg.load_state)"),
   "_pg is imported before restore uses it")
ok(APP.index("def _sq_drain_loop(") < APP.index("threading.Thread(target=_sq_drain_loop"),
   "the loop is defined before it is started")

# ── §5 · the instrument is readable ──────────────────────────────────────────
ok("sheets_queue_stats = _sq.stats()" in APP, "/health computes the queue stats")
ok('"sheets_queue": sheets_queue_stats' in APP, "/health EXPOSES them")
health = APP[APP.index("def health_check("):]
ok(health.index("sheets_queue_stats = _sq.stats()") < health.index('"sheets_queue": sheets_queue_stats'),
   "computed before it is returned — Patch #72 shipped a verdict read from "
   "counters nothing ever bumped; do not repeat it")

# ── §6 · the drainer is MONITORED ───────────────────────────────────────────
# It shipped in 9500a0a without this and /health could not see the thread.
# A drain loop that dies silently is the exact failure the queue exists to
# prevent, one level up.
ok('_heartbeat("sheets_queue_drain")' in drain,
   "the drain loop registers a heartbeat every cycle")
ok('"sheets_queue_drain":' in APP,
   "and it has a staleness threshold, so the watchdog can call it dead")
ok(drain.index('_heartbeat("sheets_queue_drain")') < drain.index("time.sleep(60)"),
   "it beats BEFORE the sleep, so the thread registers at startup and not 60s late")


print("\nPATCH107_WIRING_GATE: " + ("PASS" if FAIL == 0 else "FAIL"))

print("\n" + "=" * 62)
print("  PATCH #107 WIRING: {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
