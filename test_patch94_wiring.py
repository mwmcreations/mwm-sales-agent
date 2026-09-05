#!/usr/bin/env python3
"""
test_patch94_wiring.py — slots.py passing 27 checks proves the rule.
It does not prove app.py runs it. Patch #105 passed every unit test and never
fired in production. Prove the wiring.

Run: python3 test_patch94_wiring.py
"""
import sys

APP = open("app.py").read()
import io

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


def body(start, end):
    i = APP.index(start)
    return APP[i:APP.index(end, i + len(start))]


# ── §1 · imported and actually called ───────────────────────────────────────
ok("import slots as _slots" in APP, "app.py imports slots")
ok("_slots.compute_slots(" in APP, "and calls compute_slots")

fn = body("def get_available_slots():", "\ndef ")
ok("_slots.compute_slots(" in fn, "the call is inside get_available_slots, not somewhere dead")

# ── §2 · the real calendar and the real cap are handed in ───────────────────
ok("count_fn=_count_bookings_on_date" in fn,
   "the live booking counter is passed — capacity must not silently become 0")
ok("max_per_day=MAX_BOOKINGS_PER_DAY" in fn,
   "the configured daily cap is passed, not the module default")
ok("busy_times" in fn, "the fetched calendar blocks are passed in")

# ── §3 · the old gate is GONE, not just bypassed ────────────────────────────
ok("day_patterns[len(slots)]" not in APP,
   "the period-as-gate lookup is removed — leaving it invites a revert by merge")
ok("day_patterns = [" not in fn, "and its table with it")

# ── §4 · the rule lives in ONE place ────────────────────────────────────────
ok(APP.count("(15, 0), (14, 0)") == 0,
   "the afternoon time table is not duplicated back into app.py")
# PATCH #118 moved this rule OUT of app.py and into slots.busy_row, which is
# the whole point of #118 — three call sites each had their own version and one
# disagreed, so an all-day Busy block did not block Maya. This check used to
# grep app.py for the word "transparency"; it now checks the rule wherever it
# actually lives, so #94's intent survives #118 instead of failing on it.
_SLOTS = io.open("slots.py", encoding="utf-8").read()
ok('"transparent"' in _SLOTS,
   "FREE/transparent events are still skipped — the rule now lives in "
   "slots.busy_row (PATCH #118), not inline in app.py")
ok("_slots.busy_row(" in fn,
   "and this function asks slots.busy_row rather than rolling its own")

# ── §5 · the docstring no longer promises the broken behaviour ──────────────
doc = body("def get_available_slots():", '"""', )
_d2 = APP[APP.index("def get_available_slots():"):]
_d2 = _d2[:_d2.index("try:")]
ok("alternating morning -> afternoon -> morning." not in _d2,
   "the docstring no longer states the rule that caused the bug")
ok("starting TODAY" in _d2, "and says what it actually does now")

print("\nPATCH94_WIRING_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  PATCH #94 WIRING: {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
