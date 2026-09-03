#!/usr/bin/env python3
"""
test_patch112_wiring.py — PATCH #112, the wiring half.

sms_consent.policy() can be perfect and a promotional text can still go out on
a booking-only consent, because the policy is only worth anything if every
send path actually passes its kind. This reads app.py and proves it.

Run: python3 test_patch112_wiring.py
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

# ── §1 · THE FLAG EXISTS, IS OFF, AND IS DOCUMENTED ────────────────────────
ok('SMS_TERMS_SPLIT_LIVE      = os.getenv("SMS_TERMS_SPLIT_LIVE", "0") == "1"' in SRC,
   "the split flag defaults OFF — the strict reading is the default")
ok("Flip SMS_TERMS_SPLIT_LIVE=1 only AFTER §19 says what /sms-opt-in/ says" in SRC,
   "and the file says exactly what must be true before it is flipped")
ok('SMS_MONTHLY_CAP_MARKETING = int(os.getenv("SMS_MONTHLY_CAP_MARKETING", "4"))' in SRC,
   "the marketing cap is 4, matching /sms-opt-in/")
ok('SMS_TXN_QUIET_START_H = int(os.getenv("SMS_TXN_QUIET_START_H", "8"))' in SRC
   and 'SMS_TXN_QUIET_END_H   = int(os.getenv("SMS_TXN_QUIET_END_H", "21"))' in SRC,
   "the transactional window is 08:00-21:00")

# ── §2 · THE DECISION LIVES IN THE PURE MODULE ─────────────────────────────
pol = SRC.split("def _sms_policy(kind):")[1].split("\ndef ")[0]
ok("_sc.policy(" in pol, "_sms_policy delegates to sms_consent.policy()")
ok("SMS_TERMS_SPLIT_LIVE" in pol and "SMS_MONTHLY_CAP" in pol
   and "SMS_TXN_QUIET_START_H" in pol,
   "and hands it every live constant, so /health cannot drift from behaviour")

# ── §3 · THE GATES ARE KIND-AWARE AND DEFAULT TO THE STRICT PATH ───────────
gates = SRC.split("def _sms_gates(")[1].split("\ndef ")[0]
ok(SRC.count("def _sms_gates(lead_phone, kind=SMS_KIND_MARKETING):") == 1,
   "_sms_gates takes a kind, defaulting to MARKETING — a caller who forgets "
   "is refused, never over-permitted")
ok("pol = _sms_policy(kind)" in gates, "the gates ask the policy")
ok('if not consent.get(pol["consent_field"]):' in gates,
   "and check the box that kind actually requires")
ok('return False, f"no_consent_{pol[\'consent_field\']}"' in gates,
   "a missing box names WHICH box, so a silent lead is diagnosable")
ok('if not (pol["quiet_start"] <= now.hour < pol["quiet_end"]):' in gates,
   "quiet hours come from the policy, not from the marketing constants")
ok('if pol["cap"] is not None and _pg.enabled():' in gates,
   "an uncapped kind skips the cap check instead of tripping over None")
ok('int(st.get(pol["counter_field"], 0)) >= pol["cap"]' in gates,
   "the cap is measured against the counter that kind is counted on")

# The fail-closed spine of #108/#109 must survive the rewrite.
ok('return False, "twilio_env_missing"' in gates, "still refuses without env")
ok('return False, "do_not_sms"' in gates, "still honours do_not_sms")
ok('return False, "do_not_sms_check_failed"' in gates,
   "an unreadable do_not_sms still fails CLOSED")
ok('return False, "touch_state_check_failed"' in gates,
   "an unreadable counter still fails CLOSED")
ok('if consent.get("status") != "yes":' in gates, "still requires status yes")
ok(gates.index('consent.get("status")') < gates.index('pol["consent_field"]'),
   "status is checked before the per-kind box")

# ── §4 · EVERY SEND CARRIES ITS KIND, AND BOTH COUNTERS MOVE ───────────────
send = SRC.split("def _send_sms(")[1].split("\ndef ")[0]
ok(SRC.count("def _send_sms(lead_phone, body, kind=SMS_KIND_MARKETING):") == 1,
   "_send_sms takes a kind, defaulting to MARKETING")
ok("ok, reason = _sms_gates(lead_phone, kind)" in send,
   "and passes it to the gates — the gate and the counter cannot disagree")
ok('st["monthly_count"] = int(st.get("monthly_count", 0)) + 1' in send,
   "the combined counter is incremented on EVERY send, split or not")
ok('_kf = ("monthly_count_transactional"' in send and "monthly_count_marketing" in send,
   "and the per-kind counter alongside it")
ok('if kind == SMS_KIND_TRANSACTIONAL else' in send,
   "the per-kind counter is chosen by the kind actually sent")
ok("kind={kind}" in send, "the log line records the kind, so a send can be audited")

# The combined counter must keep moving even in split mode: otherwise flipping
# the flag would silently hand every number a fresh allowance.
reset = send.split('if st.get("month") != month:')[1][:400]
ok("monthly_count_marketing" in reset and "monthly_count_transactional" in reset
   and '"monthly_count": 0' in reset,
   "the month rollover resets all three counters together")

# ── §5 · RE-ENGAGEMENT IS EXPLICITLY MARKETING ─────────────────────────────
fb = SRC.split("def _sms_reengagement_fallback(")[1].split("\ndef ")[0]
ok("_send_sms(e164, body, kind=SMS_KIND_MARKETING)" in fb,
   "the 7-touch sequence sends as MARKETING — it is promotional and says so")
ok("_pol = _sms_policy(SMS_KIND_MARKETING)" in fb,
   "and reads its allowance from the marketing policy")
ok('int(_st.get(_pol["counter_field"], 0))' in fb,
   "counting against the marketing counter, not a hard-coded field")
ok('sent_this_month, _pol["cap"])' in fb,
   "and against the marketing cap, not a hard-coded constant")
ok("SMS_MONTHLY_CAP)" not in fb,
   "the old hard-coded cap is gone from this path")

# ── §6 · /health TELLS THE TRUTH ABOUT WHICH PROMISE IS BEING KEPT ─────────
rd = SRC.split("def _sms_readiness(")[1].split("\ndef ")[0]
ok('"terms_split_live": SMS_TERMS_SPLIT_LIVE' in rd,
   "/health publishes which mode is live")
# PATCH #117 — this line used to assert the string "§19 not yet corrected".
# On 2 Sep 2026 §19 WAS corrected: both /terms/ and /sms-signup/ now describe
# two separate consents. The old assertion pinned a claim that had become
# false, which is the worst kind of test — it defends a lie.
#
# The INTENT survives unchanged: /health must name the standing contradiction
# rather than hide it. Only the contradiction moved. It is no longer "the
# pages disagree with each other"; it is "the pages describe two consents
# while the flag is still 0, so booking reminders are capped like marketing".
ok("SMS_TERMS_SPLIT_LIVE=0" in rd,
   "and names the standing contradiction: the pages split, the flag does not")
ok("stricter bundled promise" in rd,
   "...saying plainly which way the machine errs while they disagree")
ok("_sms_promises.VERIFIED_ON" in rd,
   "...and dates the claim, so a stale reading of the website is visible")
ok('"published": _sms_published_block()' in rd,
   "/health carries the published-vs-code drift report (Patch #117)")
ok('"monthly_cap": _sms_policy(SMS_KIND_TRANSACTIONAL)["cap"]' in rd
   and '"monthly_cap": _sms_policy(SMS_KIND_MARKETING)["cap"]' in rd,
   "the caps shown are computed, not typed — /health cannot drift from code")
ok('"counter": _sms_policy(SMS_KIND_MARKETING)["counter_field"]' in rd,
   "and it names the counter each kind lands on")

# ── §7 · NOTHING SENDS BEHIND THE GATES' BACK ──────────────────────────────
ok(SRC.count("api.twilio.com") == SRC.count("api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json")
   or SRC.count("Messages.json") == 1,
   "there is exactly ONE place that posts a message to Twilio")
ok(SRC.count("Messages.json") == 1,
   "so every future sender must go through _send_sms and its gates")

print("\n%d passed, %d failed" % (PASS, FAIL))
raise SystemExit(1 if FAIL else 0)
