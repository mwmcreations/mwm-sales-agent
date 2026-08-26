#!/usr/bin/env python3
"""
test_slots.py — PATCH #94.

The regression that matters is one line: at 11:09 on an empty Wednesday, the
first slot offered must be TODAY. The old code offered Friday, and Maya called
that "fully booked" to a client who was standing by to come in that afternoon.

Run: python3 test_slots.py
"""
import sys
from datetime import datetime

import pytz

import slots as S

TZ = pytz.timezone("America/New_York")
PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


def at(y, m, d, hh, mm=0):
    return TZ.localize(datetime(y, m, d, hh, mm, 0))


def never_full(_d):
    return 0


def busy(a, b):
    return [{"start": a.isoformat(), "end": b.isoformat()}]


def days(sl):
    return [datetime.fromisoformat(x["id"]).date() for x in sl]


def hours(sl):
    return [datetime.fromisoformat(x["id"]).hour for x in sl]


# ── §1 · the ordering rule ──────────────────────────────────────────────────
ok(S.slot_times_for("morning")[:2] == [(10, 0), (11, 0)], "morning tries 10 then 11 first")
ok(S.slot_times_for("afternoon")[:2] == [(15, 0), (14, 0)], "afternoon tries 3pm then 2pm first")
for _p in ("morning", "afternoon"):
    _t = S.slot_times_for(_p)
    ok(set(_t) == {(10, 0), (11, 0), (15, 0), (14, 0)},
       "every time stays reachable from %s — that is the fix" % _p)
    ok(len(_t) == len(set(_t)), "no time is offered twice from %s" % _p)
ok(S.slot_times_for("teatime"), "an unknown period falls back rather than killing the day")
ok(S.period_for(0) == "morning" and S.period_for(1) == "afternoon" and S.period_for(2) == "morning",
   "the morning/afternoon/morning cycle is intact")
ok(S.period_for(3) == "morning", "the cycle wraps instead of raising")

# ── §2 · THE REGRESSION — Jaysee Soto, 11:09 on an empty Wednesday ──────────
NOW = at(2026, 8, 26, 11, 9)
sl = S.compute_slots(NOW, [], TZ, count_fn=never_full)
ok(bool(sl), "an empty afternoon must produce a slot at all")
ok(days(sl)[0] == NOW.date(),
   "the first slot must be TODAY — the old code offered Friday and called today full")
ok(datetime.fromisoformat(sl[0]["id"]) > NOW, "and it must be in the future")
ok(hours(sl)[0] == 15, "3pm is the first afternoon candidate")

# ── §3 · it still refuses what it should refuse ─────────────────────────────
ok(all(datetime.fromisoformat(x["id"]) > NOW for x in sl), "no past time is ever offered")

late = S.compute_slots(at(2026, 8, 26, 16, 30), [], TZ, count_fn=never_full)
ok(bool(late) and days(late)[0] > at(2026, 8, 26, 16, 30).date(),
   "after the last candidate has passed, today genuinely has nothing left")

fri = S.compute_slots(at(2026, 8, 28, 12, 0), [], TZ, count_fn=never_full)
ok(all(d.weekday() < 5 for d in days(fri)), "weekends are never offered")

full_today = S.compute_slots(
    at(2026, 8, 26, 9, 0), [], TZ,
    count_fn=lambda d: 99 if d == datetime(2026, 8, 26).date() else 0)
ok(bool(full_today) and days(full_today)[0] != datetime(2026, 8, 26).date(),
   "a day at capacity is still skipped")

# ── §4 · the busy calendar and the buffer are untouched ─────────────────────
# 3pm-4pm booked leaves 2pm unusable too: a 2-3pm visit would butt straight
# into it, and the 15-minute buffer exists to stop exactly that. Today is then
# genuinely finished — which is what "no slots today" is supposed to mean.
b3 = S.compute_slots(NOW, busy(at(2026, 8, 26, 15, 0), at(2026, 8, 26, 16, 0)), TZ,
                     count_fn=never_full)
ok(days(b3)[0] > NOW.date(),
   "3pm booked also buffers out 2pm, so today is correctly exhausted")

# Move it half an hour later and 2pm clears the buffer — the fallback fires and
# the day is saved. THIS is the path the old code could never reach.
b2 = S.compute_slots(NOW, busy(at(2026, 8, 26, 15, 30), at(2026, 8, 26, 16, 30)), TZ,
                     count_fn=never_full)
ok(days(b2)[0] == NOW.date() and hours(b2)[0] == 14,
   "3pm unusable but 2pm free keeps the visit TODAY: %s" % hours(b2)[:1])

buf = S.compute_slots(NOW, busy(at(2026, 8, 26, 13, 0), at(2026, 8, 26, 14, 50)), TZ,
                      count_fn=never_full)
ok(not (days(buf)[0] == NOW.date() and hours(buf)[0] in (14, 15)),
   "the 15-minute buffer still blocks 2pm and 3pm around a 13:00-14:50 event")

ok(S.is_busy(at(2026, 8, 26, 15, 0), [{"start": "not-a-date", "end": "nope"}], TZ) is True,
   "an unparseable busy row counts as BUSY — a withheld slot beats a double-booking")
ok(S.is_busy(at(2026, 8, 26, 15, 0), [], TZ) is False, "an empty calendar is not busy")
ok(S.is_busy(at(2026, 8, 26, 15, 0), None, TZ) is False, "and neither is a missing one")

# ── §5 · the design the alternation was for still holds ─────────────────────
mon = S.compute_slots(at(2026, 8, 24, 8, 0), [], TZ, count_fn=never_full)   # Monday 8am
ok(len(mon) == 3, "a clear week still yields three slots")
ok(hours(mon) == [10, 15, 10],
   "morning -> afternoon -> morning survives when nothing is in the way: %s" % hours(mon))
ok(len(set(days(mon))) == 3, "one slot per day, three distinct days")
ok(len(S.compute_slots(at(2026, 8, 24, 8, 0), [], TZ, count_fn=never_full)) <= 3,
   "never more than three")

print("\nPATCH94_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  SLOTS (Patch #94): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
