#!/usr/bin/env python3
"""
test_patch112.py — PATCH #112, the policy half.

The question this answers: when the machine is told to send a booking
confirmation, does it check the RIGHT consent box, the RIGHT quiet window and
the RIGHT cap — and does it stay strict while /terms/ §19 still contradicts
/sms-opt-in/?

Every rule is proven BOTH ways: bundled (today, §19 uncorrected) and split
(after §19 is corrected). The flag is the only thing that moves.

Run: python3 test_patch112.py
"""
import sms_consent as sc

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


QM = (10, 20)       # marketing window,   /terms §19
QT = (8, 21)        # transactional window
BUNDLED = dict(split_live=False, cap_bundled=4, cap_marketing=4,
               quiet_marketing=QM, quiet_transactional=QT)
SPLIT = dict(BUNDLED, split_live=True)


def pol(kind, **kw):
    args = dict(BUNDLED)
    args.update(kw)
    return sc.policy(kind, args["split_live"], args["cap_bundled"],
                     args["cap_marketing"], args["quiet_marketing"],
                     args["quiet_transactional"])


# ── §1 · THE KIND DECIDES WHICH BOX MUST BE TICKED ─────────────────────────
# This is the whole point. A booking confirmation must not require the
# marketing box, and a promotion must never be satisfied by the booking box.
ok(pol(sc.KIND_TRANSACTIONAL)["consent_field"] == "transactional",
   "transactional checks the transactional box")
ok(pol(sc.KIND_MARKETING)["consent_field"] == "marketing",
   "marketing checks the marketing box")
ok(pol(sc.KIND_TRANSACTIONAL, **SPLIT)["consent_field"] == "transactional",
   "...and that does not change when the pages are aligned")
ok(pol(sc.KIND_MARKETING, **SPLIT)["consent_field"] == "marketing",
   "...for either kind")

# ── §2 · AN UNKNOWN KIND IS TREATED AS MARKETING ───────────────────────────
# A typo in a caller must cost us a message, never a violation.
for bad in ("", None, "transaction", "TRANSACTIONAL", "promo", 0, 1, "txn"):
    p = pol(bad)
    ok(p["kind"] == sc.KIND_MARKETING, "unknown kind %r falls back to marketing" % (bad,))
    ok(p["consent_field"] == "marketing",
       "unknown kind %r demands the marketing box" % (bad,))
    ok(p["cap"] is not None, "unknown kind %r is never uncapped" % (bad,))
ok(pol("TRANSACTIONAL")["consent_field"] == "marketing",
   "the match is exact — case is not a way in")

# ── §3 · WHILE §19 IS UNCORRECTED, NOTHING GETS A WIDER ALLOWANCE ──────────
# The strictest reading of the two public pages, enforced.
ok(pol(sc.KIND_TRANSACTIONAL)["cap"] == 4,
   "bundled: transactional is capped at 4, exactly as §19 promises")
ok(pol(sc.KIND_MARKETING)["cap"] == 4, "bundled: marketing is capped at 4")
ok(pol(sc.KIND_TRANSACTIONAL)["counter_field"] == "monthly_count",
   "bundled: transactional counts on the shared counter")
ok(pol(sc.KIND_MARKETING)["counter_field"] == "monthly_count",
   "bundled: marketing counts on the same shared counter")
ok(pol(sc.KIND_TRANSACTIONAL)["counter_field"]
   == pol(sc.KIND_MARKETING)["counter_field"],
   "bundled: ONE counter — four messages total, whatever their kind")
ok(pol(sc.KIND_TRANSACTIONAL)["cap"] is not None,
   "bundled: nothing is uncapped, which is what makes this the strict reading")

# ── §4 · AFTER §19 IS CORRECTED, THE SPLIT IS REAL ─────────────────────────
ok(pol(sc.KIND_TRANSACTIONAL, **SPLIT)["cap"] is None,
   "split: transactional is uncapped — a confirmation is not a promotion")
ok(pol(sc.KIND_MARKETING, **SPLIT)["cap"] == 4,
   "split: marketing keeps the 4/month cap /sms-opt-in/ promises")
ok(pol(sc.KIND_TRANSACTIONAL, **SPLIT)["counter_field"]
   != pol(sc.KIND_MARKETING, **SPLIT)["counter_field"],
   "split: the two kinds count on two different counters")
ok(pol(sc.KIND_MARKETING, **SPLIT)["counter_field"] == "monthly_count_marketing",
   "split: marketing counts on its own counter, so confirmations cannot "
   "consume the promotional allowance")
ok(pol(sc.KIND_TRANSACTIONAL, **SPLIT)["counter_field"]
   == "monthly_count_transactional", "split: transactional counts on its own")
ok(pol(sc.KIND_MARKETING, **SPLIT)["cap"]
   == pol(sc.KIND_MARKETING)["cap"],
   "the marketing cap is 4 either way — the correction loosens nothing "
   "promotional")

# ── §5 · A DIFFERENT MARKETING CAP IS HONOURED ONLY WHEN SPLIT ─────────────
ok(pol(sc.KIND_MARKETING, cap_marketing=2)["cap"] == 4,
   "bundled: the marketing-only cap is ignored — §19's number governs")
ok(pol(sc.KIND_MARKETING, **dict(SPLIT, cap_marketing=2))["cap"] == 2,
   "split: the marketing-only cap governs")
ok(pol(sc.KIND_TRANSACTIONAL, cap_bundled=1)["cap"] == 1,
   "bundled: §19's number is the transactional cap too")

# ── §6 · QUIET HOURS ARE PER KIND, AND NEITHER RUNS OVERNIGHT ──────────────
t = pol(sc.KIND_TRANSACTIONAL)
m = pol(sc.KIND_MARKETING)
ok((t["quiet_start"], t["quiet_end"]) == (8, 21),
   "transactional may send 08:00-21:00 — it answers something just done")
ok((m["quiet_start"], m["quiet_end"]) == (10, 20),
   "marketing keeps the narrower 10:00-20:00 window")
ok(t["quiet_start"] <= m["quiet_start"] and t["quiet_end"] >= m["quiet_end"],
   "the transactional window contains the marketing one — promotion is never "
   "allowed at an hour a confirmation is not")
for p in (t, m, pol(sc.KIND_TRANSACTIONAL, **SPLIT), pol(sc.KIND_MARKETING, **SPLIT)):
    ok(0 <= p["quiet_start"] < p["quiet_end"] <= 24,
       "%s window is a real, non-wrapping daytime range" % p["kind"])
    ok(p["quiet_start"] >= 8, "%s never sends before 08:00" % p["kind"])
    ok(p["quiet_end"] <= 21, "%s never sends after 21:00" % p["kind"])
ok(pol(sc.KIND_TRANSACTIONAL, **SPLIT)["quiet_start"] == 8,
   "correcting §19 does not widen the clock — only the cap")

# ── §7 · THE FLAG IS REPORTED HONESTLY ─────────────────────────────────────
ok(pol(sc.KIND_TRANSACTIONAL)["split_live"] is False,
   "bundled mode says so, so /health cannot claim a promise we are not keeping")
ok(pol(sc.KIND_MARKETING, **SPLIT)["split_live"] is True, "split mode says so")
ok(pol(sc.KIND_TRANSACTIONAL, split_live=1)["split_live"] is True,
   "the flag is coerced to a real bool")

# ── §8 · RE-ENGAGEMENT STILL DEMANDS THE MARKETING BOX ─────────────────────
# Patch #109's rule must survive Patch #112. A transactional-only lead is not
# reachable by the 7-touch sequence, split or not.
txn_only = {"status": "yes", "transactional": True, "marketing": False}
both = {"status": "yes", "transactional": True, "marketing": True}
allowed, why = sc.should_fallback_to_sms("ig_window_expired", txn_only, 0, 4)
ok(not allowed and why == "transactional_consent_only",
   "a booking-only consent still cannot be re-engaged")
allowed, why = sc.should_fallback_to_sms("ig_window_expired", both, 0, 4)
ok(allowed, "a marketing consent still can")
allowed, why = sc.should_fallback_to_sms("ig_window_expired", both, 4, 4)
ok(not allowed and why == "monthly_cap", "the marketing cap still bites at 4")
allowed, why = sc.should_fallback_to_sms("ig_window_expired", both, 0, None)
ok(not allowed and why == "monthly_cap_unreadable",
   "an absent cap fails CLOSED here — re-engagement is never uncapped")

# ── §9 · THE RETURNED SHAPE IS COMPLETE ────────────────────────────────────
keys = {"kind", "consent_field", "quiet_start", "quiet_end", "cap",
        "counter_field", "split_live"}
for kind in (sc.KIND_TRANSACTIONAL, sc.KIND_MARKETING, "junk"):
    for mode in (BUNDLED, SPLIT):
        p = pol(kind, **mode)
        ok(set(p) == keys, "%s/%s returns every key a caller needs"
           % (kind, "split" if mode["split_live"] else "bundled"))
        ok(isinstance(p["counter_field"], str) and p["counter_field"],
           "%s/%s names a counter" % (kind, "split" if mode["split_live"] else "bundled"))

print("\n%d passed, %d failed" % (PASS, FAIL))
raise SystemExit(1 if FAIL else 0)
