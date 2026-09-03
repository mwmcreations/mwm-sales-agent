#!/usr/bin/env python3
"""Patch #117 — the code must say what the website says.

Three rejections of campaign CM87b39e12 came from drift between the published
terms, the opt-in form and the message copy. These tests pin all three
together so the next drift fails here, in a second, instead of at a carrier
review six weeks later.

Run: python3 test_sms_promises.py
"""
import io
import re
import sys

import sms_copy as C
import sms_consent as SC
import sms_promises as P

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok else f"\n          got={got!r}\n         want={want!r}"))
    if not ok:
        FAILS.append(label)


def section(t):
    print(f"\n{t}\n" + "-" * len(t))


# The two caps as app.py declares them. Read from source rather than imported,
# because importing app.py needs Flask, Postgres and a Twilio env this test has
# no business requiring.
APP = io.open("app.py", encoding="utf-8").read()


def env_default(name):
    m = re.search(r'%s\s*=\s*int\(os\.getenv\("%s",\s*"(\d+)"\)\)' % (name, name), APP)
    return int(m.group(1)) if m else None


BUNDLED = env_default("SMS_MONTHLY_CAP")
MARKETING = env_default("SMS_MONTHLY_CAP_MARKETING")


# ══════════════════════════════════════════════════════════════════════
section("1 · the caps in app.py are the caps on the website")
check("SMS_MONTHLY_CAP is readable from app.py", BUNDLED is not None, True)
check("SMS_MONTHLY_CAP_MARKETING is readable", MARKETING is not None, True)
check("bundled cap matches the published 4 a month",
      BUNDLED, P.PUBLISHED["marketing_monthly_cap"])
check("marketing cap matches the published 4 a month",
      MARKETING, P.PUBLISHED["marketing_monthly_cap"])


# ══════════════════════════════════════════════════════════════════════
section("2 · every message identifies us and carries the keywords")
check("the brand in our copy is the published business name",
      C.BRAND, P.PUBLISHED["business_name"])
check("every message opens with the business name",
      C.compose("test body").startswith(P.PUBLISHED["business_name"]), True)
check("...and carries STOP", P.PUBLISHED["opt_out_keyword"] in C.SUFFIX, True)
check("...and HELP", P.PUBLISHED["help_keyword"] in C.SUFFIX, True)

# Carrier rules are about what ARRIVES, so test the composed message, not the
# constants it was built from.
for label, msg in (
    ("opt-in (marketing)", C.opt_in_confirmation("Ana", marketing=True)),
    ("opt-in (booking only)", C.opt_in_confirmation("Ana", marketing=False)),
    ("studio booking", C.studio_booking_confirmed("Ana", "Friday, September 4", "2:30 PM")),
    ("session reminder", C.session_reminder(24, "Ana", "Friday, September 4", "2:30 PM")),
):
    check(f"{label}: names the business", P.PUBLISHED["business_name"] in msg, True)
    check(f"{label}: says STOP", "STOP" in msg, True)
    check(f"{label}: says HELP", "HELP" in msg, True)
    check(f"{label}: is GSM-7 (no smart quotes or emoji on the wire)",
          C.is_gsm7(msg), True)
    check(f"{label}: fits 2 segments", C.segments(msg) <= C.MAX_SEGMENTS, True)


# ══════════════════════════════════════════════════════════════════════
section("3 · we promise the cap we published, and only where we published it")
_mk = C.opt_in_confirmation("Ana", marketing=True)
_tx = C.opt_in_confirmation("Ana", marketing=False)
check("the marketing confirmation states the 4-a-month cap",
      str(P.PUBLISHED["marketing_monthly_cap"]) in _mk, True)
check("the booking-only confirmation promises NO monthly frequency",
      any(t in _tx.lower() for t in ("a month", "per month")), False)
check("...because the published terms cap marketing only",
      P.PUBLISHED["transactional_capped"], False)


# ══════════════════════════════════════════════════════════════════════
section("4 · the policy engine keeps the published shape")
_split = SC.policy(SC.KIND_TRANSACTIONAL, True, BUNDLED, MARKETING, (10, 20), (8, 21))
_bundled = SC.policy(SC.KIND_TRANSACTIONAL, False, BUNDLED, MARKETING, (10, 20), (8, 21))
_mkt = SC.policy(SC.KIND_MARKETING, True, BUNDLED, MARKETING, (10, 20), (8, 21))
check("split live: booking messages are not capped", _split["cap"], None)
check("split OFF: booking messages keep the stricter bundled cap",
      _bundled["cap"], BUNDLED)
check("marketing is always capped at the published number",
      _mkt["cap"], P.PUBLISHED["marketing_monthly_cap"])
check("an unknown kind is treated as marketing, never as transactional",
      SC.policy("anything-else", True, BUNDLED, MARKETING, (10, 20), (8, 21))["kind"],
      SC.KIND_MARKETING)


# ══════════════════════════════════════════════════════════════════════
section("5 · the drift report, which /health can also read")
_drift = P.drift(C.BRAND, C.SUFFIX, _mk, _tx, MARKETING, BUNDLED, split_live=True)
check("with the flag set, nothing drifts", _drift, [])

_held = P.drift(C.BRAND, C.SUFFIX, _mk, _tx, MARKETING, BUNDLED, split_live=False)
check("with the flag still at 0, exactly one item is reported", len(_held), 1)
check("...and it is an action, not a defect",
      "NOT A DEFECT, AN ACTION" in _held[0], True)

# And the report must actually catch a real regression, or it is decoration.
check("a wrong brand is caught",
      len(P.drift("MWM Studios", C.SUFFIX, _mk, _tx, MARKETING, BUNDLED, True)), 1)
check("a dropped STOP keyword is caught",
      any("STOP" in d for d in
          P.drift(C.BRAND, " Reply HELP for help.", _mk, _tx, MARKETING, BUNDLED, True)),
      True)
check("a cap raised in code but not on the website is caught",
      any("marketing cap is 8" in d for d in
          P.drift(C.BRAND, C.SUFFIX, _mk, _tx, 8, BUNDLED, True)), True)
check("a monthly promise smuggled into a booking message is caught",
      any("promises a monthly frequency" in d for d in
          P.drift(C.BRAND, C.SUFFIX, _mk, "you get 4 a month", MARKETING, BUNDLED, True)),
      True)


print("\n" + "=" * 60)
print(f"  TOTAL: {'FAILED — ' + str(len(FAILS)) if FAILS else 'ALL PASS'}")
for f in FAILS:
    print("   -", f)
print("=" * 60)
sys.exit(1 if FAILS else 0)
