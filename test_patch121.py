#!/usr/bin/env python3
"""
test_patch121.py — the "a day" event, reproduced and then refused.

On 3 Sep 2026 at 11:11 ET a calendar event was created for the next morning
10:00-11:00 whose summary was literally `a day` and whose location was
literally `all`. It had no attendees, and it carried the exact machine
studio-visit description template — so it read, to anyone looking at the
calendar, like a real client booking. It sat immediately before a live crew
call and nobody could say which real booking it was, because it was not one.

Two independent parser bugs in one sentence produced it:
  * `_parse_event_details`'s "add X to my calendar" branch keeps the
    indefinite article (the verb branch strips it) -> title "a day"
  * the location regex reads the English idiom "at all" as a place name,
    and "all" is not in its skip list -> location "all"

And a third bug dressed the result up: `harden_event_body` composes client
copy when the description is empty, and `client_description`'s fallback arm
IS the studio-visit script — so an event it could not classify at all was
narrated to the client as a studio visit.

This test reproduces the original artifact against the real functions and
proves each gate now stops it.

Run: python3 test_patch121.py
"""
import ana_calendar
import event_rail

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


# ── 1 · the parser still produces the fragments (we did NOT chase the regex) ──
MSG = "add a day to my calendar for Sep 4, I'm not available at all on that day"
d = ana_calendar._parse_event_details(MSG)
ok(d.get("title") == "a day",
   "the original sentence still parses to the title 'a day' — the parser was "
   "deliberately not rewritten; the GATE is the fix")
ok(d.get("location") == "all",
   "and still to the location 'all', from the idiom 'at all'")


# ── 2 · the implausible sets name the real fragments ──────────────────────
ok("a day" in ana_calendar._IMPLAUSIBLE_TITLES,
   "'a day' — the actual title that shipped — is refused by name")
ok("all" in ana_calendar._IMPLAUSIBLE_LOCATIONS,
   "'all' — the actual location that shipped — is refused by name")
for frag in ("all day", "a meeting", "an event"):
    ok(frag in ana_calendar._IMPLAUSIBLE_TITLES,
       "the neighbouring fragment %r is refused too" % frag)


# ── 3 · _create_event refuses rather than writing it ──────────────────────
SRC = open("ana_calendar.py", encoding="utf-8").read()
CREATE = SRC.split("def _create_event(")[1].split("\ndef ")[0]
ok("_IMPLAUSIBLE_TITLES" in CREATE and "_IMPLAUSIBLE_LOCATIONS" in CREATE,
   "_create_event consults both sets")
ok("return" in CREATE.split("_IMPLAUSIBLE_TITLES")[1].split("\n\n")[0],
   "an implausible title RETURNS — it never reaches the calendar write")
ok('details["location"] = None' in CREATE,
   "an implausible location is dropped rather than written")
ok(CREATE.index("_IMPLAUSIBLE_LOCATIONS") < CREATE.index("service ="),
   "both gates run BEFORE the calendar service is even built")


# ── 4 · the studio-visit script is no longer handed to a stranger ─────────
# This is the one that made a junk block look like a client booking.
body = {"summary": "a day", "location": "all", "description": "",
        "start": {"dateTime": "2026-09-04T10:00:00-04:00"},
        "end": {"dateTime": "2026-09-04T11:00:00-04:00"}}
out, issues = event_rail.harden_event_body(
    dict(body), context="test.patch121", strict=False,
    require_attendee=False, require_postal=False)
desc = (out.get("description") or "")
ok("Studio visit with Michael Moraes" not in desc,
   "an unclassifiable event is NOT narrated as a studio visit")
ok(desc.strip() == "",
   "its description is left blank rather than guessed")
ok(any("unclassifiable" in str(i) for i in issues),
   "and the refusal is raised as an issue, not swallowed")

# a REAL studio visit must still get its copy — the gate must not overreach
real = {"summary": "🎬 Studio: Gema Hiatt", "location": "1500 Park Center Dr, Suite 230, Orlando, FL 32835",
        "description": "", "start": {"dateTime": "2026-09-20T12:00:00-04:00"},
        "end": {"dateTime": "2026-09-20T16:00:00-04:00"},
        "attendees": [{"email": "marketing@hisagents.com"}]}
out2, _ = event_rail.harden_event_body(
    dict(real), context="test.patch121", strict=False,
    require_attendee=False, require_postal=False)
ok((out2.get("description") or "").strip() != "",
   "a REAL classifiable booking still gets its client copy — no overreach")


print("\n" + "=" * 60)
print("  PATCH #121: %d passed, %d failed" % (PASS, FAIL))
print("=" * 60)
raise SystemExit(1 if FAIL else 0)
