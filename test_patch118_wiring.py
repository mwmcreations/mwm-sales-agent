#!/usr/bin/env python3
"""
test_patch118_wiring.py — PATCH #118, the wiring half.

slots.busy_row can be perfect and Maya can still book over an all-day block,
because what mattered was never the rule — it was that THREE call sites each
wrote their own version of it and one surface disagreed with the other.

The evidence this exists for: "YASMIN surgery", an all-day Busy event, was
created 21 Aug 2026 for 16 Sep. On 1 Sep — eleven days later — "Studio Visit
— Karen Fam" was booked onto that same day. The public booking form would
have refused it. Maya did not, because her three guards all skipped all-day
events outright.

Run: python3 test_patch118_wiring.py
"""
import io
import re

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


SRC = io.open("app.py", encoding="utf-8").read()


def body(fn):
    return SRC.split("def %s(" % fn)[1].split("\ndef ")[0]


# ── 1 · all three of Maya's guards use the shared rule ────────────────
for fn in ("get_available_slots", "book_appointment", "check_specific_slot"):
    ok("_slots.busy_row(" in body(fn),
       "%s asks slots.busy_row what blocks" % fn)

ok(SRC.count("_slots.busy_row(") == 3,
   "exactly three call sites — no fourth guard quietly rolling its own rule")


# ── 2 · the old skips are gone, by name ───────────────────────────────
# The old guard, by its exact shape. (The phrase "Skip all-day events" still
# appears twice on purpose: once quoted in #118's own comment, and once in
# meeting_report_meetings, which REPORTS meetings and has no business listing
# an all-day block as one. That one is correct and stays.)
ok('if "dateTime" not in start_info or "dateTime" not in end_info:'
   not in body("check_specific_slot"),
   "check_specific_slot no longer drops an event for lacking dateTime")
ok("_slots.busy_row(" not in body("meeting_report_meetings"),
   "meeting_report_meetings is left alone — it reports meetings, it gates nothing")
ok('if "dateTime" in start_info and "dateTime" in end_info:' not in body("get_available_slots"),
   "get_available_slots no longer requires dateTime on both ends to count a block")
ok('if "dateTime" in ev.get("start", {})' not in body("book_appointment"),
   "the race guard no longer filters all-day events out of the conflict list")


# ── 3 · it still fails closed ─────────────────────────────────────────
cs = body("check_specific_slot")
ok("_slots.row_window(" in cs, "check_specific_slot resolves the window explicitly")
ok(re.search(r"_win is None:.*?blocking_events\.append", cs, re.S) is not None,
   "an unreadable block REFUSES the slot rather than booking over it")


# ── 4 · FREE still means free, or every birthday closes a day ─────────
ok('if (event or {}).get("transparency") == "transparent":' in
   io.open("slots.py", encoding="utf-8").read(),
   "busy_row honours transparency — a FREE all-day event blocks nothing")


# ── 5 · the booking form must NOT regress the other way ───────────────
# It already handled all-day events; this pins that so a future tidy-up of the
# two rules into one does not accidentally drop the half that always worked.
for endpoint, marker in (("studio_availability", '_sa_s'), ("booking_form_availability", '_st')):
    b = body(endpoint)
    ok('elif "date" in %s and "date" in' % marker in b,
       "%s still blocks whole days for all-day events" % endpoint)
    ok('== "transparent"' in b,
       "%s still lets FREE events through" % endpoint)


print("\n" + "=" * 60)
print("  PATCH #118 WIRING: %d passed, %d failed" % (PASS, FAIL))
print("=" * 60)
raise SystemExit(1 if FAIL else 0)
