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
# S30b replaced `if msg:` with the fingerprint guard. Same property, new
# mechanism: there must be NO unconditional post — every posting path sits
# behind either "the broken set changed" or "it just cleared".
ok("if msg:" not in once_fn, "the old post-every-sweep guard is gone")
ok("if fp:" in once_fn and "elif prev:" in once_fn,
   "and staying silent when there is nothing to say — both posts are guarded")
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


# ── §6 · S30b · the alert posts on CHANGE, not on a timer ──────────────────
# It shipped firing every hour with an identical list. #dev carried the same
# five names all night. Patch #103 solved this on the Postgres path already.
once_fn2 = body("def _bt_sweep_once(", "def _bt_sweep_loop(")
ok("_bt.fingerprint(report)" in once_fn2, "the sweep fingerprints the broken set")
ok("if fp != prev:" in once_fn2, "and only posts when that set CHANGES")
ok("_pg.save_state(\"booking_truth.fingerprint\"" in once_fn2,
   "the fingerprint is persisted, so a redeploy does not re-announce the same list")
ok("_pg.load_state(\"booking_truth.fingerprint\"" in once_fn2, "and is restored at first sweep")
ok("Bookings reconciled" in once_fn2,
   "when the list empties, that is announced ONCE — silence must not be the only signal of a fix")
ok(once_fn2.count("_post_to_slack_async") == 2,
   "exactly two posting paths: something changed, or everything cleared")

# ── §7 · S30b · a real event under the lead's email is linkage, not a lie ──
link = body("def _bt_upcoming_by_email(", "_bt_last_fingerprint")
ok("timeMin=" in link and "singleEvents=True" in link, "the attendee index reads real upcoming events")
ok('status", "")).lower() == "cancelled"' in link, "cancelled events are excluded from it")
ok("return {}" in link,
   "a failed lookup returns an EMPTY index — no evidence, never an invented link")
ok("_bt.reconcile(lead_data, _bt_get_event, now_iso, _bt_upcoming_by_email())" in APP,
   "and the sweep actually passes it in")

print("\nS30_WIRING_GATE: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  S30 WIRING: {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
