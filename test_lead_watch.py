#!/usr/bin/env python3
"""
test_lead_watch.py — PATCH #128, the rule and the wiring.

Eight booked records vanished at ~03:20 on 1 Sep 2026. Nothing alerted. By
8 Sep the logs that could have explained it were gone. #127 closed the one hole
we found; this is the part that means the next time we hear about it the same
minute instead of reconstructing it a week later from nothing.

Run: python3 test_lead_watch.py
"""
import io
import lead_watch as W

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


def settled(mapping, db=None):
    """A state past warmup, holding `mapping`."""
    s = W.new_state()
    for _ in range(W.DEFAULTS["warmup_samples"]):
        W.observe(s, mapping, db)
    return s


# ── 1 · it does not judge while it is still waking up ─────────────────
s = W.new_state()
for i in range(W.DEFAULTS["warmup_samples"]):
    ok(W.observe(s, {"a": {}, "b": {}}, 2)[0] == W.WARMING,
       "sample %d during boot restore is WARMING, not a verdict" % (i + 1))
ok(W.observe(s, {"a": {}, "b": {}}, 2)[0] == W.OK, "then it settles to OK")


# ── 2 · THE ONE IT EXISTS FOR ─────────────────────────────────────────
s = settled({"whatsapp:+1407": {}, "instagram:998": {}, "web:jackson": {}}, 300)
v, d = W.observe(s, {"whatsapp:+1407": {}}, 298)
ok(v == W.DROP, "two leads disappearing raises DROP")
ok(d["before"] == 3 and d["after"] == 1, "it reports both counts, not just a delta")
ok(set(d["missing"]) == {"instagram:998", "web:jackson"}, "and NAMES the leads that went")
msg = W.describe(d)
ok("3 to 1" in msg and "instagram:998" in msg,
   "the Slack sentence carries the numbers and the names — a count alone is not actionable")
ok("leads table fell from 300 to 298" in msg, "and the database side is reported separately")

# a single lead is still a client
s = settled({"a": {}, "b": {}}, 2)
ok(W.observe(s, {"a": {}}, 1)[0] == W.DROP, "ONE lead disappearing is enough — there is no safe drop")


# ── 3 · the false positives that would have killed it ─────────────────
# leads_db._promote renames a key when a better identifier arrives.
s = settled({"instagram:998": {}}, 1)
ok(W.observe(s, {"whatsapp:+14075551212": {}}, 1)[0] == W.OK,
   "a RENAME does not alert — count unchanged. This is the guard that keeps the "
   "alarm believable; a key-based rule would fire every promotion")
# the smoke test creates and deletes a synthetic key by design
s = settled({"a": {}, "smoke_test_000": {}}, 1)
ok(W.observe(s, {"a": {}}, 1)[0] == W.OK, "a synthetic key vanishing is not a lead")
ok(W.is_synthetic("smoke_test_000") and not W.is_synthetic("whatsapp:+1"),
   "synthetic keys are recognised by prefix")
# growth is not a drop
s = settled({"a": {}}, 1)
ok(W.observe(s, {"a": {}, "b": {}}, 2)[0] == W.OK, "new leads arriving is not an incident")
# an unreadable database is unknown, not zero
s = settled({"a": {}, "b": {}}, 50)
ok(W.observe(s, {"a": {}, "b": {}}, -1)[0] == W.OK,
   "leads_db.count() == -1 means 'could not answer' and must never read as a wipe")


# ── 4 · it says it once, and it says when it is over ──────────────────
s = settled({"a": {}, "b": {}, "c": {}}, 3)
ok(W.observe(s, {"a": {}}, 1)[0] == W.DROP, "first drop speaks")
ok(W.observe(s, {"a": {}}, 1)[0] == W.OK, "the same drop does not speak again every minute")
ok(W.observe(s, {"a": {}}, 1)[0] == W.OK, "still quiet")
ok(W.observe(s, {"a": {}, "b": {}, "c": {}}, 3)[0] == W.RECOVERED,
   "and recovery is announced — silence is never the all-clear")
ok(W.observe(s, {"a": {}, "b": {}, "c": {}}, 3)[0] == W.OK, "then quiet again, re-armed")


# ── 5 · it cannot be the thing that breaks ────────────────────────────
ok(W.observe(None, {"a": {}})[0] == W.OK, "a broken state returns OK, never an exception")
ok(W.real_keys(None) == set(), "an unusable mapping yields no keys rather than raising")
ok(isinstance(W.describe(None), str), "describe survives nonsense")


# ── 6 · WIRING ────────────────────────────────────────────────────────
APP = io.open("app.py", encoding="utf-8").read()
ok("import lead_watch as _lw" in APP, "app.py imports it")
ok("threading.Thread(target=_lead_watch_loop" in APP, "and the thread is actually STARTED")
ok('name="lead_watch"' in APP, "the thread is named")
loop = APP.split("def _lead_watch_loop(")[1].split("\ndef ")[0]
ok(loop.index("_lead_watch_tick()") < loop.index('_heartbeat("lead_watch")', loop.index("while True")),
   "the heartbeat comes AFTER the work — #124's lesson, or the watchdog stays "
   "green while the watchdog itself achieves nothing")
tick = APP.split("def _lead_watch_tick(")[1].split("\ndef ")[0]
ok('severity="CRITICAL"' in tick, "a disappearance is CRITICAL, not a note")
ok('"LEADS DISAPPEARED"' in tick, "with a title nobody can scroll past")
ok("_lw.describe(detail)" in tick, "the alert carries the names, not just a number")
ok("Railway logs NOW" in tick, "and says to grab the logs immediately — on 1 Sep they expired first")
ok("_leads_db.count()" in tick, "it watches the DATABASE as well as memory")
ok("restore_checked" in tick and "before the last restart" in tick,
   "the bad-restore check exists — memory and the table can agree and both be short")
ok("_pgs.enabled()" in APP and "LEAD_WATCH_PEAK_KEY" in APP,
   "the high-water mark is persisted, so a restart has something to be compared against")
ok('"lead_watch": dict(_lead_watch_last)' in APP, "/health can be asked whether it is working")
ok("except Exception" in loop, "the loop cannot die — a watchdog that can die is not one")

print("\n" + "=" * 60)
print("  PATCH #128 LEAD WATCH: %d passed, %d failed" % (PASS, FAIL))
print("=" * 60)
raise SystemExit(1 if FAIL else 0)
