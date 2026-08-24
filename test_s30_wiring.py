#!/usr/bin/env python3
"""test_s30_wiring.py — does the sweep actually sit in the running machine?

booking_truth.py passing 30 checks proves the logic. It does not prove app.py
runs it. Patch #105 passed every unit test and never fired in production; the
Sheets drain thread shipped unmonitored three hours ago. Prove the wiring.

§2 is the assertion I care about: the event lookup must return LOOKUP_FAILED
on anything that is not a 404. If an outage returned None instead, the sweep
would report every real client as a phantom and the alert would be worse than
no alert at all.

Run: python3 test_s30_wiring.py
"""

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


def body(start, end):
    i = APP.index(start)
    return APP[i:APP.index(end, i + len(start))]


# ── §1 · it is imported, defined and STARTED ────────────────────────────────
ok("import booking_truth as _bt" in APP, "app.py imports booking_truth")
ok("def _bt_sweep_once(" in APP, "the sweep exists")
ok("threading.Thread(target=_bt_sweep_loop" in APP, "and the thread is actually started")
ok('name="booking_truth_sweep"' in APP, "the thread is named")
ok(APP.index("def _bt_sweep_loop(") < APP.index("threading.Thread(target=_bt_sweep_loop"),
   "defined before it is started")

# ── §2 · THE ONE THAT MATTERS · an outage is not an absent booking ──────────
look = body("def _bt_get_event(", "def _bt_sweep_once(")
ok("_bt.LOOKUP_FAILED" in look, "the lookup can report that it could not answer")
ok("(404, 410)" in look, "only a genuinely gone event returns None")
ok(look.index("return None") < look.index("return _bt.LOOKUP_FAILED"),
   "the 404 branch comes first, and everything else falls through to LOOKUP_FAILED")
ok("except Exception" in look, "a raising API cannot kill the sweep")
ok(look.count("return None") == 1,
   "there is exactly ONE way to say 'no event' — anything else must be UNKNOWN")

# ── §3 · monitored, unlike the last thread I shipped ───────────────────────
loop = body("def _bt_sweep_loop(", "threading.Thread(target=_bt_sweep_loop")
ok('_heartbeat("booking_truth_sweep")' in loop, "the sweep registers a heartbeat every cycle")
ok('"booking_truth_sweep":' in APP, "and has a staleness threshold so the watchdog can call it dead")
ok(loop.index('_heartbeat("booking_truth_sweep")') < loop.index("_bt_sweep_once()"),
   "it beats before the work, so a slow sweep is not read as a dead thread")
ok("except Exception" in loop, "one bad lead cannot end the loop")

# ── §4 · it reports and does not mutate ────────────────────────────────────
once_fn = body("def _bt_sweep_once(", "def _bt_sweep_loop(")
ok("_bt.reconcile(lead_data" in once_fn, "it sweeps the real lead store")
ok("_bt.describe(report)" in once_fn, "and renders the human summary")
ok("SLACK_DEV_CHANNEL" in once_fn, "posting to #dev")
ok("if msg:" in once_fn, "and staying silent when there is nothing to say")
ok('lead_data[' not in once_fn and '["booked"] =' not in once_fn,
   "the sweep does NOT clear the flag — it is the only record that a promise was made")

# ── §5 · readable from outside ─────────────────────────────────────────────
ok("booking_truth_stats = dict(_bt_last)" in APP, "/health computes the stats")
ok('"booking_truth": booking_truth_stats' in APP, "/health exposes them")
health = APP[APP.index("def health_check("):]
ok(health.index("booking_truth_stats = dict(_bt_last)") < health.index('"booking_truth": booking_truth_stats'),
   "computed before returned — Patch #72 shipped a verdict read from counters "
   "nothing ever bumped; not again")
for k in ("phantom", "unknown", "checked"):
    ok('"%s":' % k in body("_bt_last = {", "def _bt_get_event("),
       "the stats block carries %s" % k)

print("\nS30_WIRING_GATE: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  S30 WIRING: {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
