#!/usr/bin/env python3
"""
test_sms_copy.py — PATCH #113, the words half.

A bad reminder reaches a paying client's phone and cannot be recalled, so the
copy is tested harder than the plumbing. Three things are proven of EVERY
message this company can send by text: the brand is on the front, the opt-out
is on the back, and it is plain ASCII that costs at most two segments.

Run: python3 test_sms_copy.py
"""
import sms_copy as c

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


ADDR = "1500 Park Center Dr, Suite 230, Orlando"

# Every message the machine can produce, built the way senders build them.
ALL = [
    ("optin/transactional", c.opt_in_confirmation("ana", False)),
    ("optin/marketing", c.opt_in_confirmation("ana", True)),
    ("optin/no name", c.opt_in_confirmation(None, False)),
    ("booking", c.studio_booking_confirmed("Ana", "Friday, September 4", "10:00 AM", ADDR)),
    ("booking/no address", c.studio_booking_confirmed("Ana", "Friday, September 4", "10:00 AM")),
    ("shoot", c.film_shoot_confirmed("Jaysee", "Friday, September 4", "9:00 AM", ADDR, "Fall Campaign")),
    ("shoot/no title", c.film_shoot_confirmed("Jaysee", "Friday, September 4", "9:00 AM", ADDR)),
    ("reminder/168h", c.session_reminder(168, "Ana", "Friday, September 4", "10:00 AM")),
    ("reminder/48h", c.session_reminder(48, "Ana", "Friday, September 4", "10:00 AM")),
    ("reminder/24h", c.session_reminder(24, "Ana", "Friday, September 4", "10:00 AM")),
    ("reminder/2h", c.session_reminder(2, "Ana", "Friday, September 4", "10:00 AM")),
]

# ── §1 · THE THREE INVARIANTS, ON EVERY MESSAGE ────────────────────────────
for label, msg in ALL:
    ok(msg.startswith("MWM Creations & Studios: "),
       "%s names the brand first — a carrier requirement, not a style" % label)
    ok(msg.endswith("Reply STOP to opt out, HELP for help."),
       "%s carries the opt-out last" % label)
    ok(c.is_gsm7(msg),
       "%s is GSM-7 — one stray smart quote would triple the bill" % label)
    ok(c.segments(msg) <= 2, "%s costs at most 2 segments (%d chars)" % (label, len(msg)))
    ok("None" not in msg, "%s never renders the word None" % label)
    ok("  " not in msg, "%s has no doubled spaces" % label)
    ok(msg == msg.strip(), "%s has no stray whitespace" % label)

# ── §2 · THE REGISTERED SAMPLE IS WHAT WE ACTUALLY SEND ────────────────────
# Campaign CM87b3... was approved against this shape. Drifting from it is how
# a working campaign becomes a suspended one.
booking = c.studio_booking_confirmed("Ana", "Thu Aug 21", "10:00 AM", ADDR)
ok(booking == ("MWM Creations & Studios: Hi Ana, your studio session is "
               "confirmed for Thu Aug 21 at 10:00 AM at " + ADDR +
               ". Reply STOP to opt out, HELP for help."),
   "the booking confirmation matches the sample registered with the carriers")

# ── §3 · NAMES ARE NOT A WAY IN ────────────────────────────────────────────
ok(c.safe_name(None) == "there", "a missing name becomes 'there'")
ok(c.safe_name("") == "there", "an empty name becomes 'there'")
ok(c.safe_name("   ") == "there", "whitespace is not a name")
ok(c.safe_name("4075551234") == "there",
   "a phone number is not a name — 'Hi 4075551234' tells them we do not know them")
ok(c.safe_name("ana@example.com") == "Ana", "an email yields the local part, not the address")
ok(c.safe_name("ana") == "Ana", "a lowercase name is capitalised")
ok(c.safe_name("ANA") == "ANA", "an all-caps name is left alone")
ok(c.safe_name("Ana Maria Sofia") == "Ana", "only the first name is used")
ok(c.safe_name("O'Brien") == "O'Brien", "an apostrophe survives")
ok(c.safe_name("Jean-Luc") == "Jean-Luc", "a hyphen survives")
ok(c.safe_name("José") == "Jose", "an accent is folded, not dropped")
ok(c.safe_name("x" * 40) == "there", "an absurdly long token is refused")
ok(c.safe_name("Ana\nSTOP") == "Ana",
   "a newline cannot be smuggled into a name to fake a second message")
ok(c.safe_name("Ana\r\nReply STOP") == "Ana", "nor a CRLF")
ok("\n" not in c.opt_in_confirmation("Ana\nMWM Creations: free money", False),
   "and no composed message contains a newline")

# ── §4 · A MESSAGE WITH NOTHING TO SAY IS NOT SENT ─────────────────────────
for bad_date in ("", None, "   "):
    try:
        c.studio_booking_confirmed("Ana", bad_date, "10:00 AM", ADDR)
        ok(False, "a booking with date %r must refuse, not send" % bad_date)
    except ValueError:
        ok(True, "a booking with date %r refuses to build" % bad_date)
for bad_time in ("", None):
    try:
        c.film_shoot_confirmed("Ana", "Friday, September 4", bad_time)
        ok(False, "a shoot with time %r must refuse" % bad_time)
    except ValueError:
        ok(True, "a shoot with time %r refuses to build" % bad_time)
try:
    c.compose("")
    ok(False, "an empty body must refuse")
except ValueError:
    ok(True, "an empty body refuses")
try:
    c.compose("x" * 400)
    ok(False, "an over-long body must refuse rather than cost 4 segments")
except ValueError:
    ok(True, "an over-long body refuses")

# ── §5 · THE ADDRESS IS A COURTESY, THE TIME IS NOT ────────────────────────
long_addr = "Suite 230, " + ("Extremely Long Boulevard " * 6) + "Orlando, Florida"
msg = c.studio_booking_confirmed("Ana", "Friday, September 4", "10:00 AM", long_addr)
ok(c.segments(msg) <= 2, "an unusable address is dropped rather than paid for")
ok("Friday, September 4" in msg and "10:00 AM" in msg,
   "...and the date and time survive, because those are the message")
ok(long_addr[:30] not in msg, "the long address really was dropped")

# ── §6 · TIERS READ DIFFERENTLY, AND ALWAYS CARRY A REAL DATE ──────────────
same_day = c.session_reminder(2, "Ana", "Friday, September 4", "10:00 AM")
week_out = c.session_reminder(168, "Ana", "Friday, September 4", "10:00 AM")
ok("today" in same_day, "the 2h reminder says today")
ok("today" not in week_out, "the 168h reminder does not")
ok("Friday, September 4" in week_out,
   "an early reminder carries the DATE — Patch #45B's lesson, in SMS")
ok(same_day != week_out, "the tiers are not the same message")
for h in (168, 48, 24, 12, 11, 2, 0, "48", None, "junk"):
    m = c.session_reminder(h, "Ana", "Friday, September 4", "10:00 AM")
    ok(c.segments(m) <= 2 and c.is_gsm7(m),
       "reminder tier %r still produces a sane message" % (h,))

# ── §7 · STUDIO AND FILM DAY ARE TELLABLE APART AT A GLANCE ────────────────
b = c.studio_booking_confirmed("Ana", "Friday, September 4", "10:00 AM", ADDR)
f = c.film_shoot_confirmed("Ana", "Friday, September 4", "10:00 AM", ADDR)
ok("studio session" in b and "filming day" in f,
   "a client holding both can tell which is which from the first line")
ok(b != f, "the two confirmations are different messages")

# ── §8 · THE PORTAL'S OWN STRINGS ARE NEVER SHOWN RAW ──────────────────────
ok(c.pretty_date("2026-09-04") == "Friday, September 4", "an ISO date is made readable")
ok(c.pretty_time("14:30") == "2:30 PM", "24h time becomes 12h")
ok(c.pretty_time("09:00") == "9:00 AM", "a leading zero is dropped")
ok(c.pretty_time("00:15") == "12:15 AM", "midnight reads as 12 AM")
ok(c.pretty_time("12:00") == "12:00 PM", "noon reads as 12 PM")
ok(c.pretty_date("2026-09-04T10:00:00") == "Friday, September 4",
   "a datetime is accepted, not just a date")
for bad in ("", None, "nonsense", "2026-13-04", "2026-02-30", "04/09/2026"):
    ok(c.pretty_date(bad) == "", "pretty_date(%r) returns '' so the sender refuses" % (bad,))
for bad in ("", None, "nonsense", "25:00", "10:99"):
    ok(c.pretty_time(bad) == "", "pretty_time(%r) returns ''" % (bad,))

# ── §9 · FOLDING AND SEGMENTS ──────────────────────────────────────────────
ok(c.ascii_fold("don’t — “quote”…") == "don't - \"quote\"...",
   "typography is folded to plain ASCII")
ok(c.ascii_fold("café \U0001f600") == "cafe", "accents fold and emoji are dropped")
ok(c.segments("") == 0, "an empty body is zero segments")
ok(c.segments("x" * 160) == 1, "160 chars is one segment")
ok(c.segments("x" * 161) == 2, "161 chars is two")
ok(c.segments("x" * 306) == 2, "306 chars is still two")
ok(c.segments("x" * 307) == 3, "307 chars is three")

print("\n%d passed, %d failed" % (PASS, FAIL))
raise SystemExit(1 if FAIL else 0)
