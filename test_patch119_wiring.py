#!/usr/bin/env python3
"""
test_patch119_wiring.py — PATCH #119, the decline branch must prove delivery.

THE DEFECT
==========
`approve_out_of_hours` has two branches. The APPROVE branch was written
carefully: it captures whether the lead was actually reached, stamps
`lead_told_at`, and alerts #dev when delivery failed. The DECLINE branch
called the very same function and **threw the answer away**, then returned
"Declined. The lead has been told and offered standard hours." — whether or
not one byte had left the building.

WHY THAT IS NOT COSMETIC
========================
Two of the three Instagram failure paths are silent BY DESIGN:
  * the S84 pre-flight gate returns early and logs "no API call, no alert"
  * a repeat 403 bumps `ig.window_expired_403` and suppresses the alert
Only a non-403 triple-failure is loud. So on an Instagram lead with **no email
on file** — no fallback channel whatsoever — the lead could sit waiting
forever while the page told Michael the opposite, and nothing anywhere would
disagree.

Found 5 Sep 2026 on request AR-A2B36E (lead "Joseph", channel Instagram, no
email on file) after Michael tapped "None of these work" and asked the only
question that mattered: *did that actually reach him?*

This is the "an assignment is not an invocation" family, in its meanest form —
here the intention was not merely stored, it was **reported back as an
outcome.**

Run: python3 test_patch119_wiring.py
"""
import io

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


SRC = io.open("app.py", encoding="utf-8").read()
ROUTE = SRC.split("def approve_out_of_hours(")[1].split("\n@app.route")[0]
# Slice structurally, not on prose: the decline block runs from its own `if`
# to the `try:` that opens the slot-approval path. (An earlier version of this
# test split on "return " and was defeated by the word "return" inside PATCH
# #119's own comment. A test that reads prose is a test that lies later.)
DECLINE = (ROUTE.split('if request.args.get("decline"):')[1]
                .split("\n    try:")[0])


# ── 1 · the result is captured, in BOTH branches ──────────────────────
ok(ROUTE.count("_approval_tell_lead(") == 2,
   "the route still tells the lead in exactly two places")
ok(ROUTE.count("told = _approval_tell_lead(") == 2,
   "BOTH calls capture the answer — neither discards it")
ok("\n        _approval_tell_lead(" not in SRC,
   "no bare, uncaptured _approval_tell_lead call survives anywhere in app.py")


# ── 2 · the decline branch stamps what it proved ──────────────────────
ok('req["lead_told_at"] = _now_naive.isoformat()' in DECLINE,
   "decline stamps lead_told_at when the lead really was reached")
ok(ROUTE.count('req["lead_told_at"]') == 2,
   "both branches stamp it — the record is symmetric")
ok("if told:" in DECLINE,
   "the stamp is conditional on delivery, not unconditional")
ok("with _approval_lock:" in DECLINE.split("told = _approval_tell_lead")[1],
   "the stamp is written under the approval lock, like every other mutation")


# ── 3 · a failed decline is LOUD ──────────────────────────────────────
ok("if not told:" in DECLINE,
   "decline has a failure path at all")
ok("_notify_error_to_dev(" in DECLINE,
   "a decline that could not be delivered reaches #dev")
ok('"Declined But Lead Not Reachable"' in DECLINE,
   "the alert has its own title — not shared with the approve case")
ok("still waiting and do not know" in DECLINE,
   "the alert says what is actually wrong: a human is waiting")
ok("no email on file" in DECLINE,
   "the alert names the missing fallback channel instead of printing None")
ok('severity="WARNING"' in DECLINE,
   "severity matches the sibling 'Approved But Lead Not Reachable'")


# ── 4 · the page cannot lie any more ──────────────────────────────────
ok("<p>Declined. The lead has been told and offered standard hours.</p>"
   not in SRC,
   "the old unconditional claim is GONE from the file entirely")
ok("if told else" in DECLINE or "if told else" in ROUTE,
   "the response text branches on the delivery result")
ok("could not reach the lead" in ROUTE,
   "there is a page to show when nothing was delivered")
ok("They have NOT been told" in ROUTE,
   "that page says so plainly, in Michael's words not a status code")


# ── 5 · the silent paths this defends against still exist ─────────────
# If either of these ever stops being silent the patch is still correct, but
# the REASON in the docstring would be stale — so pin them.
IGSEND = SRC.split("def send_instagram_dm(")[1].split("\ndef ")[0]
ok("no API call, no alert" in IGSEND,
   "the S84 pre-flight gate is still a silent refusal (the reason #119 exists)")
ok("ig_should_alert_403" in IGSEND,
   "repeat 403s can still be alert-suppressed (the second silent path)")
ok(IGSEND.count("return None") >= 3,
   "send_instagram_dm still has several falsy exits a caller must check")


# ── 6 · _approval_tell_lead still returns something checkable ─────────
TELL = SRC.split("def _approval_tell_lead(")[1].split("\ndef ")[0]
ok("return bool(send_instagram_dm(" in TELL,
   "the IG path returns a real boolean, so `told` means something")
ok(TELL.rstrip().endswith("return False"),
   "the fall-through is False — an unreachable lead never looks reached")


print("\n" + "=" * 60)
print("  PATCH #119 WIRING: %d passed, %d failed" % (PASS, FAIL))
print("=" * 60)
raise SystemExit(1 if FAIL else 0)
