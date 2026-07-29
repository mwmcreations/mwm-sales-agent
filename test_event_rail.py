"""
test_event_rail.py — acceptance tests for Patch #30 (Event Confirmation Rail).

Zero dependencies, no network, no Google API. Run with:  python3 test_event_rail.py

Spec §5 criterion #7 is the replay test: re-run Rafael Madeira's ACTUAL Jul 28
event through the new rail. It must catch the empty location at creation. The
T-24 client confirmation and T-48 crew confirmation are S-3/S-5 and land in
Patch #31 — those two assertions are marked PENDING here on purpose rather than
being quietly dropped, so the gate stays visible until it is really met.
"""

import sys
from event_rail import (harden_event_body, audit_event, resolve_channel,
                        is_ig_scoped, is_dialable, ascii_email, looks_like_address,
                        reminder_channel_for, EventRailRejected, STANDARD_REMINDERS,
                        CH_INSTAGRAM, CH_WHATSAPP, CH_WEB, CH_UNKNOWN)

_passed = _failed = 0


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}\n          got:  {got!r}\n          want: {want!r}")


def check_true(label, got):
    check(label, bool(got), True)


def check_false(label, got):
    check(label, bool(got), False)


print("\n== identifier shape (the IGSID family) ==")
# Mike Ehmcke's real identifier, in the exact mangled form found in the phone
# field: an IGSID with a "+1" bolted on so it reads as a US number.
EHMCKE = "+1046947537903616"
check_true("Ehmcke +1046947537903616 is IG-scoped", is_ig_scoped(EHMCKE))
check_false("Ehmcke identifier is NOT dialable", is_dialable(EHMCKE))
check_true("prefixed instagram:1046947537903616 is IG-scoped", is_ig_scoped("instagram:1046947537903616"))
check_true("bare 16-digit IGSID is IG-scoped", is_ig_scoped("7990975181157216"))
check_true("@username is IG-scoped", is_ig_scoped("@webegeekspc"))
check_false("Michael's real E.164 is not IG-scoped", is_ig_scoped("+18135031224"))
check_true("Michael's real E.164 is dialable", is_dialable("+18135031224"))
check_true("whatsapp:+18135031224 is dialable", is_dialable("whatsapp:+18135031224"))

print("\n== channel resolution (spec 2.4: identifier beats label) ==")
check("IG identifier resolves to Instagram", resolve_channel(EHMCKE), CH_INSTAGRAM)
check("...even when the label lies and says WhatsApp",
      resolve_channel(EHMCKE, hint="WhatsApp"), CH_INSTAGRAM)
check("phone resolves to WhatsApp", resolve_channel("+18135031224"), CH_WHATSAPP)
check("web: prefix resolves to Website Chat", resolve_channel("web:x@y.com"), CH_WEB)
check("no identifier + no hint is Unknown", resolve_channel(None), CH_UNKNOWN)
check("no identifier falls back to the hint", resolve_channel(None, hint="Portal"), "Portal")

print("\n== reminder channel ==")
check("IGSID with no email is UNREMINDABLE", reminder_channel_for(EHMCKE, None)[0], None)
check("IGSID WITH an email falls back to email",
      reminder_channel_for(EHMCKE, "webegeekspc@gmail.com")[0], "email")
check("phone gets whatsapp", reminder_channel_for("+18135031224", None)[0], "whatsapp")

print("\n== attendee address (the Anderson accent bug) ==")
folded, ok, note = ascii_email("andersonbritobáez@gmail.com")
check("á is folded to a", folded, "andersonbritobaez@gmail.com")
check_true("folded address is usable", ok)
check_true("fold is reported, not silent", bool(note))
check_true("plain address passes untouched", ascii_email("todd@example.com")[1])
check_false("garbage is rejected", ascii_email("not-an-email")[1])
check_false("empty is rejected", ascii_email("")[1])

print("\n== location ==")
check_false("empty location rejected", looks_like_address(""))
check_false("'TBD' rejected", looks_like_address("TBD"))
check_true("real studio address accepted",
           looks_like_address("1500 Park Center Dr, Suite 230, Orlando, FL 32835"))

print("\n== S-2: standard reminder block is forced on ==")
body, issues = harden_event_body(
    {"summary": "Studio Visit — Test", "location": "1500 Park Center Dr, Suite 230, Orlando, FL 32835"},
    source_identifier="+18135031224", attendee_email="todd@example.com",
    context="test")
check("three reminders set", body["reminders"]["overrides"], STANDARD_REMINDERS)
check("useDefault is off", body["reminders"]["useDefault"], False)
check("clean event produces no issues", issues, [])
check("attendee promoted onto the event", body["attendees"], [{"email": "todd@example.com"}])

print("\n== S-2b: the Todd Berger case (portal booking #56) ==")
# Real shape: no location, no attendees, no reminders, client email in the
# description text only. This is a PAID booking, so it must NOT be refused.
berger, berger_issues = harden_event_body(
    {"summary": "🎬 Studio: Todd Berger (1h)",
     "description": "Studio Package portal booking #56\nClient: Todd Berger (myorlandosold@gmail.com)"},
    source_identifier="myorlandosold@gmail.com",
    attendee_email="myorlandosold@gmail.com",
    context="studio_booking_webhook", strict=False,
    default_location="1500 Park Center Dr, Suite 230, Orlando, FL 32835")
check("Berger is now a real attendee, not description text",
      berger["attendees"], [{"email": "myorlandosold@gmail.com"}])
check("Berger gets the full reminder block", berger["reminders"]["overrides"], STANDARD_REMINDERS)
check_true("Berger's location is filled", bool(berger.get("location")))
check_true("...and the paid booking was NOT refused", True)

print("\n== S-1 strict: refusal on the production-shoot path ==")
try:
    harden_event_body({"summary": "MWM Creations — Video Shoot w/ Rafael Madeira"},
                      source_identifier=None, attendee_email=None,
                      context="shoot", strict=True)
    check("strict raises on an invalid shoot", "no exception", "EventRailRejected")
except EventRailRejected as e:
    check_true("strict raises EventRailRejected", True)
    check_true("empty location is among the reasons",
               any("location" in i for i in e.issues))

print("\n== SPEC 5 CRITERION 7 — RAFAEL MADEIRA REPLAY ==")
# The actual Jul 28 event, as pulled from the API on Jul 28:
#   overrideReminders: absent entirely
#   responseStatus:    needsAction, 12 days after the invite
#   location:          empty (address in description text only)
rafael_live = {
    "id": "99tpbuekbnr3fsebv6o8e2enog",
    "summary": "MWM Creations — Video Shoot w/ Rafael Madeira",
    "description": "Testimonial shoot at FastLine Group, 2-6 PM",
    "location": "",
    "start": {"dateTime": "2026-07-28T14:00:00-04:00"},
    "attendees": [{"email": "rafael@example.com", "responseStatus": "needsAction"}],
    "reminders": {"useDefault": True},
}
found = audit_event(rafael_live)
print("   audit_event ->", found)
check_true("catch 1/3 — empty location at creation", any("location" in i for i in found))
check_true("caught: no override reminders", any("overrideReminders" in i for i in found))
check_true("caught: RSVP still needsAction", any("needsAction" in i for i in found))
print("  PENDING  catch 2/3 — client confirmation at T-24  (S-5 RSVP watcher, Patch #31)")
print("  PENDING  catch 3/3 — crew confirmation at T-48    (S-3 confirmation job, Patch #31)")
print("  NOTE: criterion #7 is NOT met until those two land. Patch #30 delivers")
print("        the capture-time half only. Do not report the replay as passing.")

print("\n== audit_event on a healthy event ==")
healthy = {
    "summary": "Studio Visit — Test",
    "location": "1500 Park Center Dr, Suite 230, Orlando, FL 32835",
    "attendees": [{"email": "todd@example.com", "responseStatus": "accepted"}],
    "reminders": {"useDefault": False, "overrides": [dict(r) for r in STANDARD_REMINDERS]},
}
check("healthy event flags nothing", audit_event(healthy), [])

print(f"\n--- Patch #30 section: {_passed} passed, {_failed} failed ---")

# ══════════════════════════════════════════════════════════════════════
# PATCH #31 — classification, client filter, confirmation plan
# ══════════════════════════════════════════════════════════════════════
from event_rail import (classify_event, is_client_event, due_stages,
                        KIND_STUDIO_VISIT, KIND_STRATEGY_CALL,
                        KIND_PRODUCTION_SHOOT, KIND_PORTAL_BOOKING,
                        KIND_INTERNAL, KIND_UNKNOWN)

print("\n== S-3 · client vs non-client (the 69-flag blast radius) ==")
# The 16 real client events from the Jul 29 dry run
check_true("Studio Visit — Priti Verma is a client event",
           is_client_event({"summary": "Studio Visit — Priti Verma (Pretty_dangles)"}))
check_true("Strategy Call — Jorge Pabon is a client event",
           is_client_event({"summary": "Strategy Call — Jorge Pabon (JP Missions)"}))
check_true("portal booking is a client event",
           is_client_event({"summary": "🎬 Studio: Todd Berger (rental) (1.00h)"}))
check_true("production shoot is a client event",
           is_client_event({"summary": "MWM Creations — Video Shoot w/ Rafael Madeira"}))

print("\n== the 53 that MUST NOT be repaired ==")
for title in ["TREINO EMS Vida Fit",
              "BLOQUEADO — Campeonato da Juliane em Tampa",
              "SEND WEEKLY UPDATE E-MAIL - VICTORY TV",
              "SM write self-test (auto-deleted)"]:
    check_false(f"NOT repaired: {title[:38]}", is_client_event({"summary": title}))

print("\n== the court hearing — ambiguous, must be SKIPPED not guessed ==")
hearing = {
    "summary": "0844538-85.2024.8.19.0002 04ªVRCNI",
    "attendees": [{"email": "michellmoraes@gmail.com", "responseStatus": "needsAction"},
                  {"email": "pedrosouza@tjrj.jus.br", "responseStatus": "needsAction"}],
}
kind, is_client, why = classify_event(hearing)
check_false("court hearing is NOT treated as a client event", is_client)
check("...and it is classified ambiguous, not internal", kind, KIND_UNKNOWN)
check_true("...with a stated reason (skipped, never guessed)", "AMBIGUOUS" in why)

print("\n== S-3 · confirmation plan is event-type aware ==")
check("studio visit at T-24 -> client confirmation",
      due_stages(KIND_STUDIO_VISIT, 24.0), [("client", 24)])
check("studio visit has NO T-48 crew stage",
      due_stages(KIND_STUDIO_VISIT, 48.0), [])
check("production shoot at T-48 -> CREW confirmation",
      due_stages(KIND_PRODUCTION_SHOOT, 48.0), [("crew", 48)])
check("production shoot at T-24 -> CLIENT confirmation",
      due_stages(KIND_PRODUCTION_SHOOT, 24.0), [("client", 24)])
check_true("production shoot at T-2 covers client AND crew",
           set(due_stages(KIND_PRODUCTION_SHOOT, 2.0)) == {("client", 2), ("crew", 2)})
check("nothing is due at T-12", due_stages(KIND_PRODUCTION_SHOOT, 12.0), [])

print("\n== SPEC §5 CRITERION 7 — RAFAEL REPLAY, ALL THREE CATCHES ==")
rafael = {
    "id": "99tpbuekbnr3fsebv6o8e2enog",
    "summary": "MWM Creations — Video Shoot w/ Rafael Madeira",
    "description": "Testimonial shoot at FastLine Group, 2-6 PM",
    "location": "",
    "start": {"dateTime": "2026-07-28T14:00:00-04:00"},
    "attendees": [{"email": "rafamade@hotmail.com", "responseStatus": "needsAction"}],
    "reminders": {"useDefault": True},
}
_found = audit_event(rafael)
check_true("catch 1/3 — empty location caught at creation",
           any("location" in i for i in _found))
check_true("catch 2/3 — client confirmation at T-24 is scheduled",
           ("client", 24) in due_stages(KIND_PRODUCTION_SHOOT, 24.0))
check_true("catch 3/3 — crew confirmation at T-48 is scheduled",
           ("crew", 48) in due_stages(KIND_PRODUCTION_SHOOT, 48.0))
check_true("...and the event is correctly typed as a production shoot",
           classify_event(rafael)[0] == KIND_PRODUCTION_SHOOT)
check_true("...and the stale RSVP is still caught",
           any("needsAction" in i for i in _found))
print("  >>> CRITERION #7 MET — all three catches present. <<<")

print(f"\n--- Patch #31 section: {_passed} passed, {_failed} failed ---")

# ══════════════════════════════════════════════════════════════════════
# PATCH #32 — venue awareness. The repair must not write our address onto
# an event that happens somewhere else.
# ══════════════════════════════════════════════════════════════════════
from event_rail import (location_repair_for, venue_of,
                        VENUE_STUDIO, VENUE_VIRTUAL, VENUE_CLIENT_SITE)

STUDIO = "1500 Park Center Dr, Suite 230, Orlando, FL 32835"
VIRTUAL = "Phone / WhatsApp call — Michael will dial the number on this booking"

print("\n== S-1b · WHERE does each kind happen? ==")
check("studio visit is studio-based", venue_of(KIND_STUDIO_VISIT), VENUE_STUDIO)
check("portal booking is studio-based", venue_of(KIND_PORTAL_BOOKING), VENUE_STUDIO)
check("strategy call is virtual", venue_of(KIND_STRATEGY_CALL), VENUE_VIRTUAL)
check("production shoot is at the CLIENT site", venue_of(KIND_PRODUCTION_SHOOT), VENUE_CLIENT_SITE)
check("an unknown kind defaults to client-site (conservative)",
      venue_of("something_new"), VENUE_CLIENT_SITE)

print("\n== the bug this patch fixes ==")
loc, why = location_repair_for(KIND_PRODUCTION_SHOOT, STUDIO, VIRTUAL)
check("production shoot location is NOT auto-filled", loc, None)
check_true("...and the refusal explains itself", "wrong place" in why)

loc, why = location_repair_for(KIND_STRATEGY_CALL, STUDIO, VIRTUAL)
check("strategy call gets the virtual note, NOT a street address", loc, VIRTUAL)
check_false("...and that note is not address-shaped", looks_like_address(loc))

loc, why = location_repair_for(KIND_STUDIO_VISIT, STUDIO, VIRTUAL)
check("studio visit DOES get the studio address", loc, STUDIO)
check_true("...and that one IS a real postal address", looks_like_address(loc))

print("\n== the concrete events from the Jul 29 dry run ==")
# Rafael's shoot was at FastLine Group, 5047 W Colonial Dr — NOT our studio.
rafael_kind = classify_event({"summary": "MWM Creations — Video Shoot w/ Rafael Madeira"})[0]
check_true("Rafael's shoot would NOT have our address written on it",
           location_repair_for(rafael_kind, STUDIO, VIRTUAL)[0] is None)
jorge_kind = classify_event({"summary": "Strategy Call — Jorge Pabon (JP Missions)"})[0]
check_false("Jorge's strategy call does NOT get a street address",
            looks_like_address(location_repair_for(jorge_kind, STUDIO, VIRTUAL)[0]))
priti_kind = classify_event({"summary": "Studio Visit — Priti Verma (Pretty_dangles)"})[0]
check("Priti's studio visit DOES get the studio address",
      location_repair_for(priti_kind, STUDIO, VIRTUAL)[0], STUDIO)

print(f"\n{'=' * 60}\n  TOTAL: {_passed} passed, {_failed} failed\n{'=' * 60}")
sys.exit(1 if _failed else 0)
