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

print(f"\n{'=' * 60}\n  {_passed} passed, {_failed} failed\n{'=' * 60}")
sys.exit(1 if _failed else 0)
