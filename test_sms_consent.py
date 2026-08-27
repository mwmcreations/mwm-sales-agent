#!/usr/bin/env python3
"""
test_sms_consent.py — PATCH #109.

The A2P campaign took five weeks to approve because three reviewers in a row
could not verify our consent handling. Having won that argument, the way to
lose it again is to text somebody who did not agree to be texted.

So the bias of every test here is one-sided. Refusing to send costs a touch.
Sending wrongly costs the brand registration, and with it every channel that
depends on it. Where a rule is uncertain, the expected answer is "no".

Run: python3 test_sms_consent.py
"""
import sys

import sms_consent as C

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


# ── §1 · PHONE NORMALISATION AGREES WITH THE WHATSAPP SIDE ─────────────────
ok(C.to_e164("(407) 871-6473") == "+14078716473", "US 10-digit gets the 1")
ok(C.to_e164("+1 407 871 6473") == "+14078716473", "already-E.164 survives")
ok(C.to_e164("whatsapp:+13059673476") == "+13059673476", "whatsapp: prefix stripped")
ok(C.to_e164("14078716473") == "+14078716473", "11-digit passes through")
ok(C.to_e164("instagram:1512097870213397") is None,
   "an IG-scoped id is never a phone number")
ok(C.to_e164("12345") is None, "short garbage is refused")
ok(C.to_e164("0123456789012") is None, "leading-zero country code is refused")
ok(C.to_e164("") is None and C.to_e164(None) is None, "empty and None are refused")

# The two normalisers must agree or a lead is reachable on one channel and
# invisible on the other. This is the bug that hides for a month.
try:
    from maya_actions import normalize_wa_phone as _wa
    for raw in ("(407) 871-6473", "+13059673476", "whatsapp:+13059673476",
                "12345", "instagram:99", "0123456789012"):
        mine, theirs = C.to_e164(raw), _wa(raw)
        ok((mine is None) == (theirs is None),
           "to_e164 and normalize_wa_phone agree on reachability of %r" % raw)
        if mine and theirs:
            ok(mine == "+" + theirs, "and on the digits for %r" % raw)
except ImportError:
    ok(True, "maya_actions unavailable here — cross-check skipped")

# ── §2 · TIMESTAMPS, INCLUDING THE ONES WE CANNOT READ ─────────────────────
ok(C.ts_epoch("2026-08-27 14:30:00") is not None, "MySQL datetime parses")
ok(C.ts_epoch("2026-08-27T14:30:00Z") is not None, "ISO with Z parses")
ok(C.ts_epoch("2026-08-27") is not None, "bare date parses")
ok(C.ts_epoch("") is None and C.ts_epoch("null") is None, "placeholders are None")
ok(C.ts_epoch("not a date") is None, "garbage is None, not an exception")
ok(C.ts_epoch(1787855768.0) == 1787855768.0, "an epoch float passes through")
ok(C.ts_epoch("2026-08-27 14:30:00") < C.ts_epoch("2026-08-27 14:31:00"),
   "ordering is real")

# The ledger stamps created_at with gmdate() — UTC. If ts_epoch read it in the
# container's local timezone, the watermark we send back to WordPress would be
# off by that offset on every poll, and a window of consents would be skipped
# silently. Pin it: this string is a known UTC instant.
ok(C.ts_epoch("2026-08-27 18:36:08") == 1787855768.0,
   "naive timestamps are read as UTC, not as container-local time (%r)"
   % C.ts_epoch("2026-08-27 18:36:08"))
ok(C.ts_epoch("2026-08-27T18:36:08Z") == C.ts_epoch("2026-08-27 18:36:08"),
   "the Z form and the MySQL form agree")

# ── §3b · THE ACTUAL wp_mwm_sms_consent COLUMN NAMES ───────────────────────
# The table is created with transactional/marketing/phone_e164 — not txn/mkt.
# Reading the wrong column name returns 0 and every consent silently becomes
# "no", which would look exactly like nobody having opted in.
wp = C.row_to_record({
    "phone_e164": "+14078716473", "phone": "(407) 871-6473",
    "transactional": 1, "marketing": 1,
    "source_url": "https://mwmcreations.com/sms-signup/",
    "created_at": "2026-08-27 18:36:08",
})
ok(wp is not None, "a real wp_mwm_sms_consent row produces a record")
ok(wp["phone"] == "+14078716473", "phone_e164 is preferred over the raw phone")
ok(wp["marketing"] is True and wp["transactional"] is True,
   "the real column names transactional/marketing are read")
ok(C.row_to_record({"phone_e164": "+14078716473", "transactional": 1,
                    "marketing": 0, "created_at": "2026-08-27 18:36:08"}
                   )["marketing"] is False,
   "marketing 0 stays false — this is the column that gates re-engagement")

# ── §3 · ROW -> RECORD ─────────────────────────────────────────────────────
r = C.row_to_record({"phone": "4078716473", "txn": 1, "mkt": 1,
                     "ts": "2026-08-27 12:00:00", "source_url": "/sms-signup/"})
ok(r and r["phone"] == "+14078716473", "a good row normalises its phone")
ok(r["status"] == "yes" and r["marketing"] and r["transactional"],
   "both boxes ticked = yes, marketing, transactional")

r = C.row_to_record({"phone": "4078716473", "txn": 1, "mkt": 0,
                     "ts": "2026-08-27 12:00:00"})
ok(r["status"] == "yes" and not r["marketing"],
   "transactional only is a yes, but NOT a marketing yes")

# The reviewer's own test case: submitted with neither box ticked.
r = C.row_to_record({"phone": "4078716473", "txn": 0, "mkt": 0,
                     "ts": "2026-08-27 12:00:00"})
ok(r["status"] == "no", "neither box ticked is an explicit no, not a missing row")

r = C.row_to_record({"phone": "4078716473", "txn": 1, "mkt": 1, "revoked": 1,
                     "ts": "2026-08-27 12:00:00"})
ok(r["status"] == "no" and not r["marketing"],
   "revoked overrides both boxes")

ok(C.row_to_record({"phone": "junk", "txn": 1, "ts": "2026-08-27"}) is None,
   "unusable phone -> no record at all")
ok(C.row_to_record({"phone": "4078716473", "txn": 1, "ts": ""}) is None,
   "unreadable timestamp -> no record (cannot be ordered against a revoke)")
ok(C.row_to_record(None) is None and C.row_to_record("nope") is None,
   "non-dict input is refused, not crashed on")
ok(C.row_to_record({"mwm_phone": "4078716473", "mwm_txn": "1",
                    "created_at": "2026-08-27 12:00:00"})["status"] == "yes",
   "the WP column names work too")

# ── §4 · A REVOKE IS NEVER LOST ────────────────────────────────────────────
yes_old = {"phone": "+1", "status": "yes", "marketing": True, "ts": 1000.0}
no_new  = {"phone": "+1", "status": "no",  "marketing": False, "ts": 2000.0}
yes_new = {"phone": "+1", "status": "yes", "marketing": True, "ts": 3000.0}

ok(C.merge(yes_old, no_new) is no_new, "a newer revoke replaces an older yes")
ok(C.merge(no_new, yes_old) is no_new,
   "an OLDER yes arriving after a revoke does NOT resurrect consent")
ok(C.merge(no_new, yes_new) is yes_new,
   "but a genuinely newer opt-in does restore it")
ok(C.merge(None, no_new) is no_new, "first record wins by default")
ok(C.merge(yes_old, None) is yes_old, "nothing incoming changes nothing")

unreadable = {"phone": "+1", "status": "yes", "marketing": True, "ts": None}
ok(C.merge(no_new, unreadable) is no_new,
   "an incoming record with no timestamp never overwrites")
ok(C.merge(unreadable, no_new) is no_new,
   "but a readable record beats an unreadable one")

tie_no  = {"phone": "+1", "status": "no",  "marketing": False, "ts": 5000.0}
tie_yes = {"phone": "+1", "status": "yes", "marketing": True,  "ts": 5000.0}
ok(C.merge(tie_no, tie_yes) is tie_no,
   "same-instant tie resolves to the MORE restrictive record")
ok(C.merge(tie_yes, tie_no) is tie_no, "and does so in both orders")

# ── §5 · WHEN SMS IS ALLOWED TO CARRY A TOUCH ──────────────────────────────
mkt = {"status": "yes", "marketing": True}
txn = {"status": "yes", "marketing": False}
no  = {"status": "no",  "marketing": False}

ok(C.should_fallback_to_sms("ig_window_expired", mkt, 0, 4)[0],
   "dead IG window + marketing consent + room under the cap = send")

for alive in ("", None, "lead_replied", "ok", "wa_window_open"):
    got, why = C.should_fallback_to_sms(alive, mkt, 0, 4)
    ok(got is False and why == "primary_channel_alive",
       "SMS stays out while the primary channel works (%r)" % alive)

for dead in C.DEAD_PRIMARY:
    ok(C.should_fallback_to_sms(dead, mkt, 0, 4)[0] is True,
       "every declared dead-primary reason permits fallback: %s" % dead)

ok(C.should_fallback_to_sms("ig_403", txn, 0, 4)
   == (False, "transactional_consent_only"),
   "transactional consent does NOT authorise a re-engagement text")
ok(C.should_fallback_to_sms("ig_403", no, 0, 4)[1] == "consent_not_yes",
   "a revoked lead is never texted")
ok(C.should_fallback_to_sms("ig_403", None, 0, 4)[1] == "no_consent_record",
   "no record at all is a refusal with its own name")
ok(C.should_fallback_to_sms("ig_403", mkt, 4, 4)[1] == "monthly_cap",
   "the 4/month promise in /terms §19 is enforced here too")
ok(C.should_fallback_to_sms("ig_403", mkt, 9, 4)[1] == "monthly_cap",
   "and over-cap state stays refused")
ok(C.should_fallback_to_sms("ig_403", mkt, "x", 4)[1] == "monthly_cap_unreadable",
   "an unreadable counter fails CLOSED")
ok(C.should_fallback_to_sms("ig_403", mkt, 3, 4)[0] is True,
   "one under the cap still sends")

# Every refusal must name itself — a bare False would reach the error bus as
# a fault when it is a normal outcome.
for args in (("", mkt, 0, 4), ("ig_403", txn, 0, 4), ("ig_403", no, 0, 4),
             ("ig_403", None, 0, 4), ("ig_403", mkt, 4, 4)):
    got, why = C.should_fallback_to_sms(*args)
    ok(got is False and isinstance(why, str) and why and why != "ok",
       "refusal carries a reason: %s" % why)

print("\nPATCH109_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  SMS CONSENT (Patch #109): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
