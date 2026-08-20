#!/usr/bin/env python3
"""test_patch106.py — the description is a client-facing document.

Google renders the event description in full to every attendee, and it
travels into their calendar when they accept. Michael raised this ONCE
already: §S87, he found "Sales rail: OFF" sitting in a client's invite, and
the rail's stamp was moved to extendedProperties.private.

THAT FIX WAS THE INSTANCE, NOT THE CLASS, and the proof arrived on Aug 20.
Vanessa Serrano's Aug 21 booking — with her on the attendee list — was still
carrying this, typed there BY HAND by DEV during a repair:

    REPAIRED BY DEV, Aug 10 2026 — attendee, location and reminders added.
    History: the automatic sync failed Aug 6 at 10:17:52 with HTTP 403
    forbiddenForServiceAccounts ... That diagnosis was wrong. Domain-Wide
    Delegation had been granted the whole time ... Fixed in Patch #69.

A paying client's invite, describing our outage, naming our wrong diagnosis,
carrying a patch number. Eleven future events were leaking something of this
kind and a client was an attendee on every one.

§1 replays the real leaked descriptions, verbatim, off the live calendar.
§4 is the half nobody remembers: moving the data out is only safe if the
FIVE code paths that read it back still work. The confirmation rail decides
who gets a T-24 from those fields — left unmigrated it would have found empty
strings and sent nothing, and a rail that silently stops confirming looks
exactly like a quiet week.

Run: python3 test_patch106.py
"""

import io
import re
import sys

from event_rail import (client_safe_description, client_description,
                        description_is_client_safe, event_lead_facts,
                        machine_created, harden_event_body, classify_event,
                        KIND_STUDIO_VISIT, KIND_PORTAL_BOOKING,
                        KIND_STRATEGY_CALL, MWM_PHONE, MWM_EMAIL)

_passed = _failed = 0
_FAILS = []


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  PASS  " + label)
    else:
        _failed += 1
        _FAILS.append(label)
        print("  FAIL  %s\n          got=%r want=%r" % (label, got, want))


def ok(label, cond):
    check(label, bool(cond), True)


# ── the real thing, off the live calendar ───────────────────────────
VANESSA = """Studio Package portal booking #59
Client: Vanessa Serrano (vanessa@vsinternationalproperties.com)
Notes: —
Source: portal (auto-synced by machine S12)

Lead: Vanessa Serrano
Business: VS International Properties
Email: vanessa@vsinternationalproperties.com
Booked by: Portal (Studio Package)
Booked via: Portal
—— Event Rail ——
Source channel: Email   (resolved from identifier, not from a label)
Reminder channel: email

REPAIRED BY DEV, Aug 10 2026 — attendee, location and reminders added.
History: the automatic sync failed Aug 6 at 10:17:52 with HTTP 403
forbiddenForServiceAccounts ("Service accounts cannot invite attendees without
Domain-Wide Delegation"), so the event was created with no attendee, no address
and no reminders. That diagnosis was wrong. Domain-Wide Delegation had been
granted the whole time — Google only honours it when the code IMPERSONATES a
user, and this webhook did not. Fixed in Patch #69."""

MARC = """Studio Visit with Michael Moraes / MWM Creations Studios

Lead: Marc Holmes
Business: In the Driver's Seat with Marc Holmes (motorsports podcast brand)
Email: mhholmes2000@gmail.com
Booked by: Maya
Booked via: Instagram"""

PINEDA = """Studio Package portal booking #74
Client: Jonathan Pineda (john.pineda@fidelityfl.com)
Notes: Created in wp-admin
Source: portal (auto-synced by machine S12)"""

print("\n=== 1. the actual leak, replayed verbatim ===")
_clean, _removed = client_safe_description(VANESSA)
ok("the postmortem is gone", "REPAIRED BY DEV" not in _clean)
ok("the patch number is gone", "Patch #69" not in _clean)
ok("the HTTP error is gone", "403" not in _clean)
ok("our wrong diagnosis is gone", "diagnosis was wrong" not in _clean)
ok("Domain-Wide Delegation is gone", "Delegation" not in _clean)
ok("the word 'webhook' is gone", "webhook" not in _clean)
ok("the machine id is gone", "S12" not in _clean)
ok("'Booked by' is gone", "Booked by" not in _clean)
ok("the Event Rail block is gone", "Event Rail" not in _clean)
ok("'Lead:' — our funnel word for a person — is gone", "Lead:" not in _clean)
check("nothing at all survives that description", _clean, "")
ok("and every removed passage is handed back for safekeeping", len(_removed) >= 3)
ok("the full postmortem is among them",
   any("REPAIRED BY DEV" in r for r in _removed))

for name, src in (("Marc Holmes", MARC), ("Jonathan Pineda", PINEDA)):
    c, r = client_safe_description(src)
    ok("%s: no agent name reaches the client" % name, "Maya" not in c)
    ok("%s: no CRM fields reach the client" % name,
       "Business:" not in c and "Email:" not in c)
    ok("%s: something was actually removed" % name, len(r) > 0)

print("\n=== 2. an empty invite is a different failure, not a solved one ===")
# Run the stripper over Vanessa's and NOTHING survives — every line existed
# for us. Redaction alone would hand the client a blank invite.
ADDR = "1500 Park Center Dr, Suite 230, Orlando, FL 32835"
for kind in (KIND_PORTAL_BOOKING, KIND_STUDIO_VISIT, KIND_STRATEGY_CALL):
    copy = client_description(kind, studio_address=ADDR)
    ok("%s: says what the event is" % kind, len(copy.split("\n")[0]) > 15)
    ok("%s: gives a way to reach a human" % kind,
       MWM_PHONE in copy and MWM_EMAIL in copy)
    ok("%s: is itself client-safe" % kind, description_is_client_safe(copy))
    ok("%s: names no agent" % kind, "Maya" not in copy and "DEV" not in copy)
    ok("%s: carries no funnel vocabulary" % kind,
       "Lead" not in copy and "lead" not in copy)

ok("studio events carry the address",
   ADDR in client_description(KIND_PORTAL_BOOKING, studio_address=ADDR))
ok("a call does NOT tell the client to drive to the studio",
   ADDR not in client_description(KIND_STRATEGY_CALL, studio_address=ADDR))
ok("a call re-voices the dial number FOR THE CLIENT",
   "call you at +1 407-555-0100" in
   client_description(KIND_STRATEGY_CALL, callback_number="+1 407-555-0100"))
ok("...rather than instructing Michael inside the client's invite",
   "Call this number" not in
   client_description(KIND_STRATEGY_CALL, callback_number="+1 407-555-0100"))

print("\n=== 3. the GATE enforces it, whatever composed the text ===")
# Enforced in harden_event_body rather than at each write-site, because the
# write-sites are not the only author: Vanessa's leak was TYPED BY HAND into
# Google Calendar. No amount of tidying the creation code would have caught it.
_reports = []
body, issues = harden_event_body(
    {"summary": "🎬 Studio: Vanessa Serrano (3h)", "location": ADDR,
     "description": VANESSA},
    source_identifier="vanessa@vsinternationalproperties.com",
    attendee_email="vanessa@vsinternationalproperties.com",
    context="test", default_location=ADDR,
    reporter=lambda *a: _reports.append(a))
ok("the gate strips it", description_is_client_safe(body["description"]))
ok("...and replaces it with real client copy", MWM_PHONE in body["description"])
ok("nothing is destroyed — it is kept privately",
   "REPAIRED BY DEV" in
   body["extendedProperties"]["private"]["redacted_from_description"])
ok("a strip is REPORTED, not quietly papered over",
   any("internal_text_in_description" in str(r[0]) for r in _reports))

_clean_body, _ = harden_event_body(
    {"summary": "Studio Visit — X (Y)", "location": ADDR,
     "description": client_description(KIND_STUDIO_VISIT, studio_address=ADDR)},
    source_identifier="x@y.com", attendee_email="x@y.com",
    context="test", default_location=ADDR,
    reporter=lambda *a: _reports.append(("SHOULD-NOT-FIRE",)))
ok("already-clean copy passes through untouched",
   MWM_PHONE in _clean_body["description"])
ok("...and does NOT fire the reporter — no crying wolf on every booking",
   not any(r[0] == "SHOULD-NOT-FIRE" for r in _reports))

print("\n=== 4. THE HALF NOBODY REMEMBERS — five paths READ these fields ===")
# Moving the data out is only safe if the code reading it back still works.
# The confirmation rail decides who receives a T-24 from "Lead:" and "Phone:".
# Left unmigrated it would have parsed a description that no longer contains
# them, found empty strings, and sent nothing — and a rail that silently stops
# confirming looks exactly like a quiet week.
NEW_STYLE = {
    "summary": "Studio Visit — Marc Holmes (In the Driver's Seat)",
    "description": client_description(KIND_STUDIO_VISIT, studio_address=ADDR),
    "extendedProperties": {"private": {
        "lead_name": "Marc Holmes", "lead_business": "In the Driver's Seat",
        "lead_email": "mhholmes2000@gmail.com", "lead_phone": "14075551212",
        "booked_by_agent": "Maya", "booked_via_channel": "Instagram"}},
}
f = event_lead_facts(NEW_STYLE)
check("name survives the move", f["lead_name"], "Marc Holmes")
check("email survives", f["lead_email"], "mhholmes2000@gmail.com")
check("PHONE survives — the confirmation rail needs it", f["lead_phone"], "14075551212")
check("channel survives", f["booked_via_channel"], "Instagram")
ok("...and none of it is in the client-visible description",
   "14075551212" not in NEW_STYLE["description"]
   and "mhholmes2000" not in NEW_STYLE["description"])

LEGACY = {"summary": "Studio Visit — Marc Holmes (In the Driver's Seat)",
          "description": MARC}
lf = event_lead_facts(LEGACY)
check("LEGACY events still resolve — no migration required",
      lf["lead_name"], "Marc Holmes")
check("...including the channel", lf["booked_via_channel"], "Instagram")
check("...and the agent", lf["booked_by_agent"], "Maya")

# The eleven leaking events had to be rewritten IN PLACE, and the MCP write
# path cannot set extendedProperties. Without a title fallback, cleaning them
# would have cost the briefer every client name it knew.
CLEANED = {"summary": "Studio Visit — Marc Holmes (In the Driver's Seat)",
           "description": client_description(KIND_STUDIO_VISIT, studio_address=ADDR)}
cf = event_lead_facts(CLEANED)
check("a cleaned event still yields the name — from the TITLE",
      cf["lead_name"], "Marc Holmes")
check("...and says so, so nobody mistakes it for a stored fact",
      cf["name_source"], "title")
check("portal titles parse too",
      event_lead_facts({"summary": "🎬 Studio: Jonathan Pineda (1h)",
                        "description": ""})["lead_name"], "Jonathan Pineda")
check("strategy call titles parse too",
      event_lead_facts({"summary": "Strategy Call — Prime Vacation Orlando (Prime Vacation Orlando)",
                        "description": ""})["lead_name"], "Prime Vacation Orlando")
check("a gym session yields nothing — no false client facts",
      event_lead_facts({"summary": "🏋️ TREINO EMS Vida Fit", "description": ""}), {})

print("\n=== 5. classification must not regress ===")
# classify_event's machine-write-path fallback keyed on "Booked by: Maya" in
# the description. That string stops being written the moment the description
# is client-safe — so every new event with an unrecognised title would have
# fallen through to "unknown" and lost its whole reminder ladder.
ok("a machine event is recognised from the PRIVATE stamp",
   machine_created({"description": "clean copy",
                    "extendedProperties": {"private": {"booked_by_agent": "Maya"}}}))
ok("...and from a portal booking id",
   machine_created({"description": "clean copy",
                    "extendedProperties": {"private": {"portal_booking_id": "74"}}}))
ok("legacy description markers still work",
   machine_created({"description": "Booked by: Maya"}))
ok("a hand-made event is NOT claimed as ours",
   not machine_created({"summary": "Coffee", "description": "with a friend"}))
check("a clean Maya booking still classifies as a client studio visit",
      classify_event(NEW_STYLE)[1], True)

print("\n=== 6. it must not eat legitimate client copy ===")
SAFE = ("Studio session at MWM Creations & Studios.\n\n" + ADDR +
        "\nPlease arrive a few minutes early so we can start on time.\n\n"
        "Bring the two outfits we discussed, and the product samples.\n\n"
        "Questions? Call or text %s." % MWM_PHONE)
c2, r2 = client_safe_description(SAFE)
check("genuine client instructions are untouched", r2, [])
ok("...and survive verbatim", "product samples" in c2)
check("an empty description stays empty", client_safe_description(""), ("", []))
check("None", client_safe_description(None), ("", []))
ok("a description of only internal text yields empty, not garbage",
   client_safe_description("Booked by: Maya")[0] == "")

print("\n=== 7. the TITLE is client-facing too ===")
from event_rail import client_safe_title, title_is_client_safe
for raw, want in [
    ("🎬 Studio: Todd Berger (rental) (1.00h)", "🎬 Studio: Todd Berger"),
    ("🎬 Studio: Priti (rental — rescheduled) (1.00h)", "🎬 Studio: Priti"),
    ("🎬 Studio: Jonathan Pineda (1h)", "🎬 Studio: Jonathan Pineda"),
    ("Studio Visit — Marc Holmes (In the Driver's Seat (motorsports podcast brand))",
     "Studio Visit — Marc Holmes"),
    ("Studio Visit — Angie Starrz (Starrz Talk — podcast/radio show (98.5 The Wire))",
     "Studio Visit — Angie Starrz"),
    ("Strategy Call — Prime Vacation Orlando (Prime Vacation Orlando)",
     "Strategy Call — Prime Vacation Orlando"),
]:
    check("cleaned: %s" % raw[:40], client_safe_title(raw)[0], want)

# THE DANGER: classify_event matches _TITLE_PATTERNS and the whole reminder
# ladder hangs off that match. A title rewrite that breaks the prefix silently
# un-books every confirmation.
for t, want_kind in [("Studio Visit — Marc Holmes", KIND_STUDIO_VISIT),
                     ("🎬 Studio: Todd Berger", KIND_PORTAL_BOOKING),
                     ("Strategy Call — Prime Vacation Orlando", KIND_STRATEGY_CALL)]:
    k, is_client, _ = classify_event({"summary": t, "description": "clean copy"})
    check("PREFIX SURVIVES — %s still classifies" % t[:28], k, want_kind)
    ok("...and is still a client event", is_client)
    check("...and the name is still recoverable",
          event_lead_facts({"summary": t, "description": ""}).get("lead_name") is not None, True)

print("\n=== 8. titles Michael typed himself are HIS ===")
for t in ["🏋️ TREINO EMS Vida Fit",
          "🎥 VICTORY — Grand Master VonSchmeling · Book Tour Launch",
          "FILM SHOOT — ENZO AUTO SERVICE (On Location)",
          "GRAVAÇÃO Natalia Tavares",
          "✈️ Levar o sogro ao aeroporto — MCO Terminal B",
          "🎉 Aniversário River (9) & Riley (7)"]:
    check("untouched: %s" % t[:34], client_safe_title(t)[0], t)
    ok("...and reported as needing nothing", title_is_client_safe(t))
check("an empty title", client_safe_title(""), ("", []))
check("None", client_safe_title(None)[0], "")
ok("a title that would clean to nothing is left ALONE, never made nameless",
   client_safe_title("🎬 Studio: (rental)")[0] == "🎬 Studio: (rental)")

print("\n=== 9. the sweep: the gap the gate cannot close ===")
APP = io.open("app.py", encoding="utf-8").read()
SW = APP.split("def _sweep_client_visible_leaks")[1].split("\ndef ")[0]
ok("it only touches events with an EXTERNAL attendee",
   "mwmcreations.com" in SW and "if not ext:" in SW)
ok("...which is the entire safety margin — it edits only what is already client-facing",
   "continue" in SW.split("if not ext:")[1][:40])
ok("nothing is removed before it is preserved",
   SW.index("redacted_from_description") < SW.index("events().patch"))
ok("the client is NEVER mailed about our tidy-up",
   'sendUpdates="none"' in SW)
ok("an empty description is replaced with real client copy, not left blank",
   "client_description(" in SW)
ok("the alert quotes what was removed, verbatim",
   "removed" in SW and "_post_to_slack_async" in SW)
ok("...and says it was almost certainly typed by hand",
   "typed by hand" in SW)
ok("it reports each event ONCE, not every 15 minutes",
   "_LEAK_SWEEP_DONE" in SW)
ok("one bad event cannot abort the sweep",
   "non-fatal" in SW)
ok("it rides the existing 15-minute pass rather than a new thread",
   "_sweep_client_visible_leaks()" in
   APP.split("def _lead_reminder_thread")[1].split("while True")[1][:2000])

print("\n" + "=" * 64)
print("  %d passed, %d failed" % (_passed, _failed))
for f_ in _FAILS:
    print("   x " + f_)
print("=" * 64)
sys.exit(1 if _failed else 0)
