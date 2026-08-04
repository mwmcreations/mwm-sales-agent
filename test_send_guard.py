#!/usr/bin/env python3
"""Patch #44A — behavioural tests for the do-not-contact guard.

These test the ONE thing Patch #38 believed it had already done: that a lead on
the do-not-contact list cannot be emailed. #38 enforced it at /api/send-email,
which is the endpoint a human calls. Five automated call sites went straight to
send_gmail() and were never checked. These tests pin the guard at the chokepoint
so that bypass cannot come back.

Run: python3 test_send_guard.py
"""
import sys

import susan_gmail as sg

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok else f"\n          got={got!r}\n         want={want!r}"))
    if not ok:
        FAILS.append(label)


def section(title):
    print(f"\n{title}\n" + "-" * len(title))


# ══════════════════════════════════════════════════════════════════════
section("1 · unconfigured hook must FAIL CLOSED")
# If app.py never wires the predicate, the safe posture is to send NOTHING.
# The opposite default — send everything — is how a wiring regression turns
# into quietly emailing people who asked us to stop.
sg._SUPPRESSION_HOOK = None
check("suppression_configured() is False", sg.suppression_configured(), False)
check("_suppressed blocks when unconfigured", sg._suppressed("a@b.com")[0], True)
_r = sg.send_gmail("a@b.com", "s", "<p>x</p>")
check("send_gmail refuses", _r.get("ok"), False)
check("...and marks it suppressed", _r.get("suppressed"), True)
check("...and never reached Gmail", "message_id" in _r, False)


# ══════════════════════════════════════════════════════════════════════
section("2 · configured hook — allow the clean, block the listed")
sg.configure_suppression(lambda a: (str(a).strip().lower() == "dnc@x.com",
                                    "do-not-contact list"))
check("suppression_configured() is True", sg.suppression_configured(), True)
check("clean address passes the predicate", sg._suppressed("ok@x.com")[0], False)
check("listed address is blocked", sg._suppressed("dnc@x.com")[0], True)
check("blocking is case-insensitive", sg._suppressed("DNC@X.com")[0], True)
check("...and whitespace-insensitive", sg._suppressed("  dnc@x.com ")[0], True)

_r = sg.send_gmail("dnc@x.com", "s", "<p>x</p>")
check("send to a listed address is refused", _r.get("ok"), False)
check("...and names which address", _r.get("blocked_address"), "dnc@x.com")
check("...with a human-readable reason",
      "do-not-contact" in _r.get("error", ""), True)


# ══════════════════════════════════════════════════════════════════════
section("3 · CC is a recipient too")
# A DNC address in CC is still a DNC address receiving mail. The welcome-email
# path (app.py:13330) passes cc=, so this is a live shape, not a hypothetical.
check("comma-separated cc parsed",
      sg._recipients("a@x.com", "b@x.com, c@x.com"),
      ["a@x.com", "b@x.com", "c@x.com"])
check("semicolon-separated cc parsed",
      sg._recipients("a@x.com", "b@x.com; c@x.com"),
      ["a@x.com", "b@x.com", "c@x.com"])
check("empty cc ignored", sg._recipients("a@x.com", ""), ["a@x.com"])
check("None cc ignored", sg._recipients("a@x.com", None), ["a@x.com"])
check("blank fragments dropped",
      sg._recipients("a@x.com", "b@x.com,,  ,c@x.com"),
      ["a@x.com", "b@x.com", "c@x.com"])

_r = sg.send_gmail("ok@x.com", "s", "<p>x</p>", cc="dnc@x.com")
check("a listed CC blocks the WHOLE send", _r.get("ok"), False)
check("...and names the CC address", _r.get("blocked_address"), "dnc@x.com")


# ══════════════════════════════════════════════════════════════════════
section("4 · a predicate that RAISES must fail closed")
# Postgres down, import error, anything. An exception is not permission.
def _boom(_addr):
    raise RuntimeError("pg down")


sg.configure_suppression(_boom)
check("raising predicate blocks", sg._suppressed("ok@x.com")[0], True)
check("...with the cause in the reason",
      "raised" in sg._suppressed("ok@x.com")[1], True)
check("raising predicate refuses the send",
      sg.send_gmail("ok@x.com", "s", "x").get("ok"), False)


# ══════════════════════════════════════════════════════════════════════
section("5 · a predicate returning junk must fail closed")
sg.configure_suppression(lambda a: None)          # not a 2-tuple
check("None return blocks", sg._suppressed("ok@x.com")[0], True)
sg.configure_suppression(lambda a: (0, ""))       # falsy but well-formed
check("well-formed falsy allows", sg._suppressed("ok@x.com")[0], False)


# ══════════════════════════════════════════════════════════════════════
section("6 · the truthiness trap that made this invisible")
# send_gmail returns a dict on success AND failure, and BOTH are truthy.
# app.py:8871 and the studio-pitch dep both wrote `if send_gmail(...):`, so a
# refused send was recorded as delivered and the error branch was unreachable.
# This is the assertion that would have caught it.
sg.configure_suppression(lambda a: (True, "blocked"))
_blocked = sg.send_gmail("anyone@x.com", "s", "x")
check("the refusal dict is TRUTHY (the trap)", bool(_blocked), True)
check("...so callers must read ['ok'], which is False", _blocked.get("ok"), False)


print("\n" + "=" * 60)
print(f"  TOTAL: {'FAILED — ' + str(len(FAILS)) if FAILS else 'ALL PASS'}")
if FAILS:
    for f in FAILS:
        print("   -", f)
print("=" * 60)
sys.exit(1 if FAILS else 0)
