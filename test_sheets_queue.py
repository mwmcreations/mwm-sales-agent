#!/usr/bin/env python3
"""test_sheets_queue.py — PATCH #107.

The failure this replays is real. On 23 Aug 2026 at 19:51:26 ET a first
contact from whatsapp:+13059673476 hit `403 The caller does not have
permission` and was discarded. Two more followed. The board stayed green for
34 hours because the lead COUNTER reads Postgres and the lead REPORT reads
the sheet, and only one of them was broken.

§1 replays those exact three failures.
§2 is the rule that actually matters: a queued UPDATE must never overtake a
   queued CREATE for the same lead, because update_lead_columns DISCARDS an
   update whose row does not exist — so replaying out of order would lose
   precisely what we queued it to save.
§3 proves we drop a status change before we drop a person.
§4 proves a 400 is not retried forever.

Run: python3 test_sheets_queue.py
"""

import sys

import sheets_queue as sq

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


class Sheet(object):
    """A fake spreadsheet that can be broken and repaired, and that refuses
    an update to a row that does not exist — exactly like the real one."""

    def __init__(self, err=None):
        self.rows = {}
        self.err = err
        self.calls = []

    def create(self, sender):
        self.calls.append(("create", sender))
        if self.err:
            raise Exception(self.err)
        self.rows.setdefault(sender, {})

    def update(self, sender, updates):
        self.calls.append(("update", sender, dict(updates)))
        if self.err:
            raise Exception(self.err)
        if sender not in self.rows:
            # The real function logs "NO ROW" and returns — the update is gone.
            raise AssertionError("update applied to a row that does not exist")
        self.rows[sender].update(updates)


PERM403 = "HttpError 403 The caller does not have permission"
BAD400 = "HttpError 400 Invalid argument: range malformed"

# ── §1 · the incident, replayed ──────────────────────────────────────────────
sq.reset()
alerts = []
cb = lambda c, m, d="": alerts.append(c)

sq.enqueue(sq.OP_CREATE, "whatsapp:+13059673476", now=100, alert_cb=cb)
sq.enqueue(sq.OP_CREATE, "instagram:1050687607860400", now=200, alert_cb=cb)
sq.enqueue(sq.OP_UPDATE, "instagram:1082716294436102",
           {"Status": "Booked"}, now=300, alert_cb=cb)

ok(sq.depth() == 3, "all three failed writes are held, not discarded")
ok(sq.stats()["queued"] == 3, "queued counter reflects three")
ok("sheets_queue.depth" in alerts, "the first queued write speaks once")

broken = Sheet(err=PERM403)
r = sq.drain(broken.create, broken.update, now=1000, alert_cb=cb)
ok(r["kept"] == 3 and r["drained"] == 0, "a 403 keeps everything queued")
ok(sq.depth() == 3, "nothing was lost while the ACL was still wrong")

fixed = Sheet()
fixed.rows["instagram:1082716294436102"] = {}
r = sq.drain(fixed.create, fixed.update, now=9999, alert_cb=cb)
ok(r["drained"] == 3 and sq.depth() == 0, "everything replays once sharing is fixed")
ok("whatsapp:+13059673476" in fixed.rows, "the lost 19:51 lead exists after replay")
ok("instagram:1050687607860400" in fixed.rows, "the lost 02:25 lead exists after replay")
ok(fixed.rows["instagram:1082716294436102"] == {"Status": "Booked"},
   "the 05:33 status update landed too")

# ── §2 · ordering: a create must drain before its own updates ────────────────
sq.reset()
sq.enqueue(sq.OP_CREATE, "whatsapp:+1555", now=1)
sq.enqueue(sq.OP_UPDATE, "whatsapp:+1555", {"Status": "New Lead"}, now=2)
sq.enqueue(sq.OP_UPDATE, "whatsapp:+1555", {"Email": "a@b.c"}, now=3)

ok(sq.depth() == 2, "two updates for one lead collapse into one entry")
s = Sheet()
r = sq.drain(s.create, s.update, now=10)
ok(r["drained"] == 2 and r["dropped"] == 0, "both entries drained without error")
ok(s.calls[0][0] == "create", "the CREATE went first — this is the whole rule")
ok(s.rows["whatsapp:+1555"] == {"Status": "New Lead", "Email": "a@b.c"},
   "merged updates keep every column, not just the last one")

# a later update must NOT overtake the create it depends on
sq.reset()
sq.enqueue(sq.OP_CREATE, "x", now=1)
sq.enqueue(sq.OP_UPDATE, "y", {"A": 1}, now=2)
sq.enqueue(sq.OP_UPDATE, "x", {"B": 2}, now=3)
sq.enqueue(sq.OP_UPDATE, "x", {"C": 3}, now=4)   # merges into the entry at idx 2
ok([e["op"] for e in sq.snapshot()] == [sq.OP_CREATE, sq.OP_UPDATE, sq.OP_UPDATE],
   "merging in place does not reorder the queue")
ok(sq.snapshot()[2]["updates"] == {"B": 2, "C": 3},
   "the merge landed on the existing entry, not a new one at the front")

# last write wins on the same column
sq.reset()
sq.enqueue(sq.OP_UPDATE, "z", {"Status": "New Lead"}, now=1)
sq.enqueue(sq.OP_UPDATE, "z", {"Status": "Booked"}, now=2)
ok(sq.snapshot()[0]["updates"] == {"Status": "Booked"}, "later value wins per column")

# ── §3 · saturation drops a status change, never a person ────────────────────
sq.reset()
alerts = []
for i in range(sq.MAX_QUEUE - 1):
    sq.enqueue(sq.OP_UPDATE, "u%d" % i, {"Status": "x"}, now=i)
sq.enqueue(sq.OP_CREATE, "person-1", now=9000)
ok(sq.depth() == sq.MAX_QUEUE, "queue is exactly at the cap")

sq.enqueue(sq.OP_CREATE, "person-2", now=9001, alert_cb=cb)
ok(sq.depth() == sq.MAX_QUEUE, "the cap holds — the queue cannot grow without limit")
ops = [e["op"] for e in sq.snapshot()]
ok(ops.count(sq.OP_CREATE) == 2, "both people are still queued")
ok(sq.stats()["dropped_overflow"] == 1, "exactly one update was evicted")
ok(sq.snapshot()[0]["sender"] == "u1", "the OLDEST update was the one dropped")

# a queue that is all creates evicts nobody
sq.reset()
alerts = []
for i in range(sq.MAX_QUEUE):
    sq.enqueue(sq.OP_CREATE, "p%d" % i, now=i)
sq.enqueue(sq.OP_CREATE, "p-overflow", now=99999, alert_cb=cb)
ok(sq.stats()["dropped_overflow"] == 0, "no person is dropped to make room for a person")
ok("sheets_queue.full_of_creates" in alerts, "and it says so, loudly")

# ── §4 · permanent vs retryable ──────────────────────────────────────────────
ok(sq.is_retryable(PERM403) is True, "403 is retryable — it clears when a human shares the sheet")
ok(sq.is_retryable("HttpError 429 quota exceeded") is True, "429 is retryable")
ok(sq.is_retryable("HttpError 503 backend error") is True, "5xx is retryable")
ok(sq.is_retryable(BAD400) is False, "400 is NOT retryable")
ok(sq.is_retryable("") is True, "an unknown error is held, not discarded")

sq.reset()
alerts = []
sq.enqueue(sq.OP_CREATE, "bad", now=1)
s = Sheet(err=BAD400)
r = sq.drain(s.create, s.update, now=10, alert_cb=cb)
ok(r["dropped"] == 1 and sq.depth() == 0, "a malformed write is dropped once, not looped")
ok("sheets_queue.permanent_failure" in alerts, "and the drop is announced with its reason")

# ── §5 · backoff ─────────────────────────────────────────────────────────────
sq.reset()
sq.enqueue(sq.OP_CREATE, "b", now=0)
s = Sheet(err=PERM403)
sq.drain(s.create, s.update, now=0)
n_calls = len(s.calls)
sq.drain(s.create, s.update, now=1)
ok(len(s.calls) == n_calls, "a just-failed entry is not retried one second later")
sq.drain(s.create, s.update, now=0 + sq.BACKOFF_BASE + 1)
ok(len(s.calls) == n_calls + 1, "it is retried once the backoff elapses")

# ── §6 · persistence across a deploy ─────────────────────────────────────────
sq.reset()
sq.enqueue(sq.OP_CREATE, "whatsapp:+13059673476", now=1)
sq.enqueue(sq.OP_UPDATE, "instagram:123", {"Status": "Booked"}, now=2)
store = {}
ok(sq.save(lambda k, v: store.__setitem__(k, v) or True), "save reports success")
ok(sq.STATE_KEY in store, "the queue is written under its own key")

sq.reset()
ok(sq.depth() == 0, "process restarted with an empty queue")
n = sq.restore(lambda k, d=None: store.get(k, d))
ok(n == 2 and sq.depth() == 2, "the queue survives a deploy")
ok(sq.snapshot()[0]["op"] == sq.OP_CREATE, "and it survives IN ORDER")
ok(sq.snapshot()[1]["updates"] == {"Status": "Booked"}, "with its column values intact")

sq.reset()
ok(sq.restore(lambda k, d=None: "not a list") == 0, "a broken payload restores nothing and does not raise")
ok(sq.restore(lambda k, d=None: [{"op": "nonsense", "sender": "x"},
                                 {"op": "create"},
                                 {"op": "create", "sender": "good"}]) == 1,
   "unknown ops and senderless rows are skipped, the good one survives")

# ── §7 · the instrument ──────────────────────────────────────────────────────
sq.reset()
ok(sq.stats()["depth"] == 0, "/health reads depth 0 when there is nothing waiting")
sq.enqueue(sq.OP_CREATE, "q", now=1)
st = sq.stats()
ok(st["depth"] == 1 and st["queued"] == 1, "depth and queued are both readable")
s = Sheet()
sq.drain(s.create, s.update, now=100)
ok(sq.stats()["drained"] == 1, "drained is counted, so recovery is provable")
ok(sq.stats()["depth"] == 0, "and depth returns to zero")

# a silent writer must not be read as success is NOT testable here by design:
# drain treats "did not raise" as success, which is why the docstring on
# drain() requires the injected writers to raise. That contract is the reason
# update() above raises instead of returning when the row is missing.
sq.reset()
sq.enqueue(sq.OP_UPDATE, "ghost", {"Status": "Booked"}, now=1)
s = Sheet()
r = sq.drain(s.create, s.update, now=100)
ok(r["kept"] == 1 and sq.depth() == 1,
   "an update whose row is missing raises, so it stays queued instead of vanishing")

print("\nPATCH107_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))

print("\n" + "=" * 62)
print("  SHEETS WRITE QUEUE (#107): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
