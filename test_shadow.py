#!/usr/bin/env python3
"""
test_shadow.py — PATCH #95.

The failure this pins: on 26 Aug 2026 Michael went looking in #maya-shadow for
the conversation that had just booked a studio visit, and could not find it.
It was there — threaded under a card from 5 July titled "Conversation with
Unknown". Nothing appeared in the channel for that day at all.

Run: python3 test_shadow.py
"""
import sys

import shadow as S

PASS = FAIL = 0
DAY = 86400.0
NOW = 1787757192.0          # Wed 26 Aug 2026 11:13 ET
JULY_5 = 1783279694.0       # the parent card that hid the conversation


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


# ── §1 · placeholder names ──────────────────────────────────────────────────
for _n in ("", "Unknown", "unknown lead", "  UNKNOWN  ", "there", None, "lead"):
    ok(S.is_placeholder_name(_n), "placeholder recognised: %r" % (_n,))
for _n in ("Jaysee Soto", "Z Brothers", "Dr Bolfer", "kvn"):
    ok(not S.is_placeholder_name(_n), "a real name is not a placeholder: %r" % _n)

# ── §2 · THE REGRESSION — a 52-day-old thread must not swallow today ────────
ok(S.should_start_new_thread("1783279694.849589", JULY_5, NOW) is True,
   "a thread quiet since 5 July gets a NEW card — this is the bug")
ok(round(S.idle_days(JULY_5, NOW)) == 52, "and we can say how long it was quiet: %s"
   % round(S.idle_days(JULY_5, NOW)))

ok(S.should_start_new_thread("1.1", NOW - 3600, NOW) is False,
   "an hour-old thread is still the right place")
ok(S.should_start_new_thread("1.1", NOW - 2 * DAY, NOW) is False,
   "two days is still one conversation")
ok(S.should_start_new_thread("1.1", NOW - 4 * DAY, NOW) is True,
   "four days is a new episode")
ok(S.should_start_new_thread(None, None, NOW) is True,
   "no thread at all obviously starts one")
ok(S.should_start_new_thread("1.1", None, NOW) is True,
   "a thread with NO recorded activity predates this patch — treat as stale")
ok(S.should_start_new_thread("1.1", NOW - 30 * DAY, NOW, max_idle_days=90) is False,
   "the window is tunable")

ok(S.idle_days(None, NOW) is None, "unknown last-activity reports as unknown, not 0")
ok(S.idle_days(NOW + 500, NOW) == 0.0, "a clock skew never yields a negative age")

# ── §3 · the card says who it is ────────────────────────────────────────────
h = S.header_text("Jaysee Soto", "+1 (305) 967-3476",
                  email="jsoto@altamontefamilyhearing.com", role="lead",
                  business="Altamonte Family Hearing", resumed_after_days=52.0)
ok("Jaysee Soto" in h, "the name is on the card")
ok("Altamonte Family Hearing" in h, "so is the business — searchable by company")
ok("jsoto@altamontefamilyhearing.com" in h, "so is the email")
ok("52 day" in h, "and it says this is someone coming back after 52 days")

h0 = S.header_text("", "+1 (305) 967-3476")
ok("Unknown" in h0, "an unnamed card still renders")
ok("Returning" not in h0, "a first contact is not labelled as returning")
ok("day" not in S.header_text("X", "p", resumed_after_days=0.4),
   "a gap under a day is not worth a line")
ok("1 day" in S.header_text("X", "p", resumed_after_days=1.0),
   "one day is singular")

# ── §4 · renaming, and what must never be renamed ───────────────────────────
ok(S.better_name("Unknown", "Jaysee Soto") == "Jaysee Soto",
   "a placeholder is replaced the moment we know better")
ok(S.better_name("Jaysee Soto", "J. Soto") is None,
   "a name a human may already recognise is NEVER overwritten")
ok(S.better_name("Unknown", "") is None, "and never replaced by nothing")
ok(S.better_name("Unknown", "unknown") is None, "nor by another placeholder")

ok(S.should_rename("Unknown", "Jaysee Soto") is True, "rename on a real name")
ok(S.should_rename("Unknown", "Unknown", "", "jsoto@x.com") is True,
   "an email arriving alone is still worth putting on the card")
ok(S.should_rename("Jaysee Soto", "Jaysee Soto", "a@b.com", "a@b.com") is False,
   "nothing new means no Slack call")
ok(S.should_rename("Unknown", "Unknown", "a@b.com", "a@b.com") is False,
   "an email we already had is not news")

print("\nPATCH95_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  SHADOW (Patch #95): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
