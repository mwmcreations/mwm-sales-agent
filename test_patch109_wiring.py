#!/usr/bin/env python3
"""
test_patch109_wiring.py — PATCH #109, the wiring half.

sms_consent.py can be perfect and change nothing. Twice before, a fix was
reported as live and was not (#49, the SKILL.md episode), which is why the
house rule is that a module is not a feature until something calls it.

This reads app.py and proves the bridge is actually connected: the puller
exists and runs on a thread, the fallback is called from the re-engagement
checker's failure path and nowhere else dangerous, the Patch #108 honesty
flags now say True for real reasons, and the SMS copy will not detonate into
five billed segments.

Run: python3 test_patch109_wiring.py
"""
import io
import re
import sys

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


SRC = io.open("app.py", encoding="utf-8").read()

# ── §1 · THE CONSENT BRIDGE EXISTS AND RUNS ────────────────────────────────
ok("def _sms_consent_pull(" in SRC, "_sms_consent_pull() is defined")
ok("def _sms_consent_poller(" in SRC, "_sms_consent_poller() is defined")
ok("threading.Thread(target=_sms_consent_poller, daemon=True).start()" in SRC,
   "and the poller is actually started — a thread nobody starts is a comment")
ok('_heartbeat("sms_consent_poller")' in SRC,
   "the poller heartbeats, so the watchdog can see it die")

pull = SRC.split("def _sms_consent_pull")[1].split("def _sms_consent_poller")[0]
ok("mwm_sms_consent_since" in pull, "it calls the WordPress feed action")
ok("X-MWM-Portal-Secret" in pull, "with the same shared secret as provisioning")
ok("MWM-SalesMachine" in pull,
   "and the custom User-Agent — WP 406s python-requests/*, which cost us "
   "booking #51 once already")
ok("_sms_consent_set(" in pull,
   "it writes through _sms_consent_set, the canonical writer")
ok("_sc.merge(" in pull, "and merges rather than blindly overwriting")
ok(pull.index("if _pg.enabled() and newest > since") >
   pull.index("for row in rows or []"),
   "the watermark advances only AFTER the rows are processed")
for early in ("return (0, 0)",):
    ok(pull.count(early) >= 4,
       "every failure path returns early instead of advancing the watermark")

# ── §2 · THE SEND PATH IS CALLED, AND ONLY FROM THE FAILURE BRANCH ─────────
ok("def _sms_reengagement_fallback(" in SRC, "_sms_reengagement_fallback() exists")
calls = [l for l in SRC.splitlines()
         if "_sms_reengagement_fallback(" in l and "def " not in l]
ok(len(calls) == 1,
   "it is called from exactly one place (found %d)" % len(calls))

# The call must sit inside the guarded_send failure handling, after the
# outcome check — never on the success path, which would double-message.
tail = SRC.split("_outcome = guarded_send(")[1]
ok('if _outcome in ("failed", "failed-noretry"):' in tail.split("elif all(")[0],
   "the fallback fires only on a confirmed delivery failure")
ok(tail.index('_sms_reengagement_fallback(')
   > tail.index('if _outcome == "sent":'),
   "and sits after the success branch, not inside it")

fb = SRC.split("def _sms_reengagement_fallback")[1].split("\ndef ")[0]
ok("should_fallback_to_sms(" in fb, "it asks the policy module for permission")
ok("_send_sms(" in fb, "and sends through _send_sms, which re-checks every gate")
ok("no_phone_on_file" in fb,
   "an Instagram lead with no number on file is a named skip, not a crash")
ok("10 ** 6" in fb or "10**6" in fb,
   "an unreadable monthly counter fails CLOSED (treated as over cap)")
ok("_report_error(" in fb and "except Exception" in fb,
   "the whole thing is wrapped — a fallback must never break the checker")
ok("_TALLY.bump(" in fb, "skips and sends are counted for /health")

# ── §3 · THE PATCH #108 FLAGS NOW SAY TRUE FOR REAL REASONS ────────────────
def flag(name):
    m = re.search(r"^%s\s*=\s*(True|False)" % name, SRC, re.M)
    return None if not m else (m.group(1) == "True")


def callers(fn):
    n = 0
    for line in SRC.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith("def "):
            continue
        if re.search(r"(?<![\w\"'])%s\(" % re.escape(fn), s):
            n += 1
    return n


ok(flag("SMS_SEND_WIRED") is True, "SMS_SEND_WIRED is now True")
ok(flag("SMS_CONSENT_WIRED") is True, "SMS_CONSENT_WIRED is now True")
ok(callers("_send_sms") > 0, "...and _send_sms really does have a caller")
ok(callers("_sms_consent_set") > 0, "...and so does _sms_consent_set")

# ── §4 · SMS COPY THAT WILL NOT BILL AS FIVE SEGMENTS ──────────────────────
ok("SMS_REENGAGEMENT_MESSAGES = {" in SRC, "SMS copy is defined separately from IG copy")
# split on a closing brace at column 0 — "}" alone matches the {name}
# placeholder inside the very first message and truncates the block.
block = SRC.split("SMS_REENGAGEMENT_MESSAGES = {")[1].split("\n}")[0]
bodies = re.findall(r'"(T[1-7])": "([^"]+)"', block)
ok(len(bodies) == 7, "all seven stages have SMS copy (found %d)" % len(bodies))
for stage, body in bodies:
    ok(all(ord(c) < 128 for c in body),
       "%s is plain ASCII — one emoji forces UCS-2 and halves the segment" % stage)
    ok("STOP" in body, "%s carries an opt-out instruction" % stage)
    ok("MWM Creations" in body, "%s identifies the sender" % stage)
    rendered = body.replace("{name}", "Michael")
    ok(len(rendered) <= 160,
       "%s fits one GSM segment (%d chars)" % (stage, len(rendered)))

print("\nPATCH109_WIRING_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  SMS WIRING (Patch #109): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
