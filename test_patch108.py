#!/usr/bin/env python3
"""
test_patch108.py — PATCH #108.

27 Aug 2026: the A2P campaign was approved. Five weeks, eight submissions,
four Twilio agents. The failure mode on a day like that is not technical, it
is a story: "SMS is approved" becomes "SMS is working" in the retelling, and
nobody checks again until a re-engagement campaign silently sends nothing.

So the readiness report has to be pessimistic, and — more importantly — it has
to stay TRUE as the code changes. SMS_SEND_WIRED is a hand-maintained flag,
and a hand-maintained flag rots. §3 reads app.py itself and fails if either
flag disagrees with the source, so the lie cannot survive a commit.

Run: python3 test_patch108.py
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


def flag(name):
    m = re.search(r"^%s\s*=\s*(True|False)" % name, SRC, re.M)
    return None if not m else (m.group(1) == "True")


def callers(fn):
    """Calls to fn that are not its own definition and not inside a string."""
    n = 0
    for line in SRC.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith("def "):
            continue
        if re.search(r"(?<![\w\"'])%s\(" % re.escape(fn), s):
            n += 1
    return n


# ── §1 · THE FLAGS EXIST AND START SHUT ────────────────────────────────────
ok(flag("SMS_SEND_WIRED") is not None, "SMS_SEND_WIRED is declared in app.py")
ok(flag("SMS_CONSENT_WIRED") is not None, "SMS_CONSENT_WIRED is declared in app.py")

# ── §2 · THE REPORT IS SHAPED RIGHT ────────────────────────────────────────
ok("_sms_readiness" in SRC, "_sms_readiness() exists")
ok('"sms": _sms_readiness()' in SRC, "and /health actually calls it")
for field in ("campaign", "a2p_status", "env_complete", "would_send",
              "blocked_by", "note"):
    ok('"%s":' % field in SRC.split("def _sms_readiness")[1][:2000],
       "_sms_readiness reports %s" % field)

body = SRC.split("def _sms_readiness")[1][:2000]
ok("would_send" in body and "not blocked" in body,
   "would_send is derived from blocked_by, not asserted independently")
ok("APPROVED means the carriers accept us" in body,
   "the note says plainly that approval is not the same as live")

# ── §3 · THE FLAGS CANNOT DRIFT AWAY FROM THE SOURCE ───────────────────────
# This is the part that matters. If someone wires a caller and forgets the
# flag, /health would keep reporting a blocker that no longer exists — or
# worse, the reverse. Either way the report stops being evidence.
send_callers    = callers("_send_sms")
consent_callers = callers("_sms_consent_set")

ok(flag("SMS_SEND_WIRED") == (send_callers > 0),
   "SMS_SEND_WIRED (%s) matches reality — %d caller(s) of _send_sms in app.py"
   % (flag("SMS_SEND_WIRED"), send_callers))
ok(flag("SMS_CONSENT_WIRED") == (consent_callers > 0),
   "SMS_CONSENT_WIRED (%s) matches reality — %d caller(s) of _sms_consent_set"
   % (flag("SMS_CONSENT_WIRED"), consent_callers))

# ── §4 · THE GATE ITSELF STILL FAILS CLOSED ────────────────────────────────
gates = SRC.split("def _sms_gates")[1][:2500]
ok('return False, "twilio_env_missing"' in gates,
   "_sms_gates still refuses when the Twilio env is incomplete")
ok('!= "yes"' in gates and '"no_consent"' in gates,
   "_sms_gates still requires an explicit recorded consent")
ok('"do_not_sms_check_failed"' in gates and '"touch_state_check_failed"' in gates,
   "_sms_gates still fails CLOSED when its own state reads throw")

print("\nPATCH108_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  SMS READINESS (Patch #108): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
