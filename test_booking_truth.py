#!/usr/bin/env python3
"""test_booking_truth.py — S30.

§1 replays James Perry exactly: flagged booked, no event, and a machine that
told him twice it was on.
§2 is the one that would do the most damage if it were wrong — a calendar
lookup that FAILS must never be read as "no booking". If it were, one API blip
would declare every real client a phantom.
§3 proves the gate is closed by default: anything we cannot prove is not
something we tell a client.

Run: python3 test_booking_truth.py
"""

import sys

import booking_truth as bt

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


NOW = "2026-08-24T13:00:00-04:00"


def cal(events):
    """A calendar. Unknown ids are genuinely absent; 'boom' raises."""
    def _get(eid):
        if eid == "boom":
            raise RuntimeError("Google says 503")
        if eid == "quiet-fail":
            return bt.LOOKUP_FAILED
        return events.get(eid)
    return _get


LIVE = {"id": "e1", "status": "confirmed",
        "start": {"dateTime": "2026-08-25T15:00:00-04:00"}}
OLD = {"id": "e2", "status": "confirmed",
       "start": {"dateTime": "2026-08-19T15:00:00-04:00"}}
GONE = {"id": "e3", "status": "cancelled",
        "start": {"dateTime": "2026-08-25T15:00:00-04:00"}}
BOOK = cal({"e1": LIVE, "e2": OLD, "e3": GONE})

# ── §1 · James Perry, replayed ───────────────────────────────────────────────
james = {"name": "James Perry", "email": "Rolljames5@gmail.com", "booked": True}
state, _ = bt.derive(james, BOOK, NOW)
ok(state == bt.NO_ID, "a lead flagged booked with no event_id is NO_ID, not confirmed")
ok(bt.is_booked(james, BOOK, NOW) is False,
   "THE GATE: the machine may not say James is booked")

james2 = dict(james, event_id="deleted-999")
ok(bt.derive(james2, BOOK, NOW)[0] == bt.PHANTOM,
   "an event_id that resolves to nothing is a PHANTOM")
ok(bt.is_booked(james2, BOOK, NOW) is False, "and it is not bookable truth either")

rep = bt.reconcile({"ig:james": james, "ig:james2": james2}, BOOK, NOW)
ok(len(rep["no_event_id"]) == 1 and len(rep["phantom"]) == 1,
   "the sweep separates 'never had one' from 'lost it'")
ok("James Perry" in bt.describe(rep), "and it names him — this is the alert Aug 15 never sent")
ok("Rolljames5@gmail.com" in bt.describe(rep), "with a way to reach him")

# ── §2 · THE ONE THAT MATTERS · a failed lookup is not an absent booking ────
real = {"name": "Todd", "booked": True, "event_id": "boom"}
ok(bt.derive(real, BOOK, NOW)[0] == bt.UNKNOWN,
   "a lookup that RAISES yields UNKNOWN, never PHANTOM")
real2 = {"name": "Todd", "booked": True, "event_id": "quiet-fail"}
ok(bt.derive(real2, BOOK, NOW)[0] == bt.UNKNOWN,
   "a lookup that returns LOOKUP_FAILED yields UNKNOWN too")

rep2 = bt.reconcile({"a": real, "b": real2}, BOOK, NOW)
ok(len(rep2["phantom"]) == 0 and len(rep2["no_event_id"]) == 0,
   "an outage produces ZERO phantoms — one API blip must not condemn every client")
ok(len(rep2["unknown"]) == 2, "they land in their own bucket")
ok(bt.describe(rep2) == "",
   "and a sweep that only failed to look posts NOTHING — a false alarm here would "
   "train everyone to ignore the real one")

rep3 = bt.reconcile({"j": james, "t": real}, BOOK, NOW)
ok("could not be checked" in bt.describe(rep3),
   "but when there IS something to report, the unchecked ones are disclosed too")

ok(bool(bt.LOOKUP_FAILED) is False, "the sentinel is falsy, so a careless `if event:` still fails safe")
ok(bt.LOOKUP_FAILED is not None, "yet it is distinguishable from a genuine None")

# ── §3 · the honest states ───────────────────────────────────────────────────
good = {"name": "Marc", "booked": True, "event_id": "e1"}
ok(bt.derive(good, BOOK, NOW)[0] == bt.CONFIRMED, "a real future booking is CONFIRMED")
ok(bt.is_booked(good, BOOK, NOW) is True, "and only this state opens the gate")

ok(bt.derive({"booked": True, "event_id": "e2"}, BOOK, NOW)[0] == bt.PAST,
   "a session that already happened is PAST, not phantom — it was honoured")
ok(bt.is_booked({"booked": True, "event_id": "e2"}, BOOK, NOW) is False,
   "and PAST is not something to reconfirm to a client")

ok(bt.derive({"booked": True, "event_id": "e3"}, BOOK, NOW)[0] == bt.CANCELLED,
   "a cancelled event with the flag still set is CANCELLED")
ok(bt.derive({"booked": False, "event_id": "e1"}, BOOK, NOW)[0] == bt.UNFLAGGED,
   "an event nobody flagged — Michael booking straight on the calendar — is UNFLAGGED")
ok(bt.derive({"booked": False}, BOOK, NOW)[0] == bt.CLEAR, "no flag, no event, no drama")

ok(bt.derive({}, BOOK, NOW)[0] == bt.CLEAR, "an empty lead does not crash")
ok(bt.derive(None, BOOK, NOW)[0] == bt.CLEAR, "nor does None")
ok(bt.reconcile(None, BOOK, NOW)["checked"] == 0, "nor an empty book of leads")

# a date-only all-day event must not crash the comparison
allday = cal({"ad": {"id": "ad", "status": "confirmed", "start": {"date": "2026-08-30"}}})
ok(bt.derive({"booked": True, "event_id": "ad"}, allday, NOW)[0] == bt.CONFIRMED,
   "an all-day event (date, not dateTime) is handled")

# ── §4 · the sweep stays quiet when it should ───────────────────────────────
quiet = bt.reconcile({"a": {"booked": False}, "b": good}, BOOK, NOW)
ok(bt.describe(quiet) == "", "a clean sweep posts nothing at all")
ok(quiet["confirmed"] == 1 and quiet["clear"] == 1, "but the counts are still there for /health")
ok(len(bt.describe(rep)) > 0, "and a dirty sweep is loud")

big = {("k%d" % i): dict(james, name="P%d" % i) for i in range(25)}
ok("…and 15 more" in bt.describe(bt.reconcile(big, BOOK, NOW)),
   "a large backlog is truncated rather than flooding the channel")

print("\nS30_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  BOOKING TRUTH (S30): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
