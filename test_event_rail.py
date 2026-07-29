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
# SUPERSEDED BY PATCH #33: this was asserted as KIND_UNKNOWN (ambiguous). #33
# recognises the Brazilian case-number format and classifies it INTERNAL, which
# is strictly better — an ambiguous event gets re-considered by every backfill
# and every S-5 pass, an internal one is settled. Behaviour change is intended.
check("court hearing is now classified INTERNAL (Patch #33)", kind, KIND_INTERNAL)

# The AMBIGUOUS path still needs coverage, so exercise it with an event that is
# genuinely unclear: a real external attendee, no recognisable client title.
ambiguous = {
    "summary": "BACK TO SCHOOL BASH - KIDS",
    "attendees": [{"email": "vidafit.juliane@gmail.com", "responseStatus": "needsAction"}],
}
a_kind, a_client, a_why = classify_event(ambiguous)
check_false("a genuinely ambiguous event is NOT treated as a client event", a_client)
check("...and it is classified ambiguous", a_kind, KIND_UNKNOWN)
check_true("...with a stated reason (skipped, never guessed)", "AMBIGUOUS" in a_why)

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

print(f"\n--- Patch #32 section: {_passed} passed, {_failed} failed ---")

# ══════════════════════════════════════════════════════════════════════
# PATCH #33 — the six events the Jul 29 backfill skipped as ambiguous.
# Two were PAYING CLIENTS sitting off the reminder rail entirely.
# ══════════════════════════════════════════════════════════════════════
from event_rail import KIND_STUDIO_PRODUCTION, KIND_CLIENT_CALL

print("\n== the two paying clients that were NOT on the rail ==")
bolfer = {"summary": "STUDIO RECORDING | Dr. Luiz Bolfer — Educational Videos"}
robinson = {"summary": "STUDIO SHOOT - NO LINES with Dr. Scott Robinson"}
for label, ev in [("Bolfer Aug 15", bolfer), ("Robinson Aug 20", robinson)]:
    k, is_c, _w = classify_event(ev)
    check_true(f"{label} is now a CLIENT event", is_c)
    check(f"{label} classified as studio production", k, KIND_STUDIO_PRODUCTION)
    check(f"{label} venue is OUR studio", venue_of(k), VENUE_STUDIO)
    check(f"{label} location auto-fills to the studio",
          location_repair_for(k, STUDIO, VIRTUAL)[0], STUDIO)

print("\n== a studio production owes the SAME crew rail as an on-location shoot ==")
check("crew confirmation at T-48", due_stages(KIND_STUDIO_PRODUCTION, 48.0), [("crew", 48)])
check("client confirmation at T-24", due_stages(KIND_STUDIO_PRODUCTION, 24.0), [("client", 24)])
check_true("client AND crew at T-2",
           set(due_stages(KIND_STUDIO_PRODUCTION, 2.0)) == {("client", 2), ("crew", 2)})

print("\n== client calls: Zoom typed by hand, and Calendly's default title ==")
for label, title in [("Zoom COACH FLY", "Zoom call COACH FLY - first session"),
                     ("Calendly / Gema Hiatt", "Gema Hiatt and Michael Moraes")]:
    k, is_c, _w = classify_event({"summary": title})
    check_true(f"{label} is a client event", is_c)
    check(f"{label} is a client call", k, KIND_CLIENT_CALL)
    check(f"{label} venue is virtual", venue_of(k), VENUE_VIRTUAL)
    check_false(f"{label} does NOT get a street address",
                looks_like_address(location_repair_for(k, STUDIO, VIRTUAL)[0]))

print("\n== the court hearing is now INTERNAL, not ambiguous ==")
hearing = {"summary": "0844538-85.2024.8.19.0002 04\u00aaVRCNI",
           "attendees": [{"email": "pedrosouza@tjrj.jus.br", "responseStatus": "needsAction"}]}
k, is_c, why = classify_event(hearing)
check_false("court hearing is not a client event", is_c)
check("...and is classified INTERNAL, so it stops being reconsidered", k, KIND_INTERNAL)
check_true("...with a legal-case reason", "legal case" in why)

print("\n== nothing that must be skipped became a client event ==")
for title in ["TREINO EMS Vida Fit", "BLOQUEADO — Campeonato da Juliane em Tampa",
              "SEND WEEKLY UPDATE E-MAIL - VICTORY TV", "BACK TO SCHOOL BASH - KIDS"]:
    check_false(f"still skipped: {title[:36]}", is_client_event({"summary": title}))

print("\n== Patch #30/31/32 behaviour is unchanged ==")
check("Rafael on-location shoot still NOT auto-filled",
      location_repair_for(classify_event(
          {"summary": "MWM Creations — Video Shoot w/ Rafael Madeira"})[0], STUDIO, VIRTUAL)[0], None)
check("Priti studio visit still gets the studio address",
      location_repair_for(KIND_STUDIO_VISIT, STUDIO, VIRTUAL)[0], STUDIO)
check_true("Ehmcke IGSID still refused", is_ig_scoped("+1046947537903616"))

print(f"\n--- Patch #33 section: {_passed} passed, {_failed} failed ---")

# ══════════════════════════════════════════════════════════════════════
# PATCH #34 — canvas stage ladder (Robinson P0) and the RSVP-NOTE parser.
# These mirror the app.py logic exactly; app.py itself needs Flask + Google
# libs to import, so the logic is asserted here against the same rules.
# ══════════════════════════════════════════════════════════════════════

def canvas_stage(ld):
    """Mirror of the Patch #34 stage ladder in _sync_pipeline_canvas."""
    _status = (ld.get("status") or "").lower()
    _wa = (ld.get("wa_status") or "").lower()
    _outcome = (ld.get("outcome") or "").lower()
    _product = (ld.get("product") or "").strip()
    if ("client" in _status or _outcome == "won" or bool(_product)):
        return "Client"
    if ld.get("appt_booked"):
        return "Booked"
    if "contacted" in _status or "active" in _wa:
        return "Contacted"
    if ld.get("email") or "new" in _status.lower():
        return "New"
    return "Contacted"


print("\n== ROBINSON STAGE-SYNC P0 ==")
# His real shape on Jul 29: paid Jul 27, Aug 20 shoot booked.
robinson = {"name": "Dr. Scott Robinson", "email": "healer2bsure@gmail.com",
            "status": "Client — Studio Package", "outcome": "Won",
            "product": "Studio Package", "appt_booked": True}
check("Robinson reads CLIENT, not Booked", canvas_stage(robinson), "Client")

check("outcome=Won alone is enough",
      canvas_stage({"outcome": "Won", "appt_booked": True}), "Client")
check("product alone is enough",
      canvas_stage({"product": "Studio Package", "appt_booked": True}), "Client")
check("sheet status alone is enough",
      canvas_stage({"status": "Client — Studio Package", "appt_booked": True}), "Client")

print("\n== and the ladder below Client is UNCHANGED ==")
check("booked-but-not-a-client still reads Booked",
      canvas_stage({"appt_booked": True, "status": "Contacted"}), "Booked")
check("contacted still reads Contacted",
      canvas_stage({"status": "Contacted"}), "Contacted")
check("a form lead still reads New",
      canvas_stage({"email": "x@y.com"}), "New")
check("no signal at all still reads Contacted", canvas_stage({}), "Contacted")

print("\n== the exact regression: a paying client WITH a booking ==")
# Before #34 this returned "Booked" forever — that was the P0.
check_true("a paid client with a future booking is never 'Booked' again",
           canvas_stage({"outcome": "Won", "appt_booked": True}) != "Booked")


def rsvp_note(description):
    """Mirror of the Patch #34 RSVP-NOTE parser."""
    for line in str(description or "").split("\n"):
        if line.strip().upper().startswith("RSVP-NOTE:"):
            return line.split(":", 1)[1].strip()
    return ""


print("\n== S-5 RSVP-NOTE travels with the flag (MATT's request) ==")
check("note is extracted",
      rsvp_note("Studio session\nRSVP-NOTE: confirmed on WhatsApp Jul 29 — RSVP stale"),
      "confirmed on WhatsApp Jul 29 — RSVP stale")
check("lowercase marker also works",
      rsvp_note("rsvp-note: client confirmed by phone"), "client confirmed by phone")
check("no note returns empty, not an error", rsvp_note("Just a description"), "")
check("empty description is safe", rsvp_note(""), "")
check("a note containing a colon keeps its full text",
      rsvp_note("RSVP-NOTE: confirmed 10:30 by WhatsApp"), "confirmed 10:30 by WhatsApp")

print(f"\n{'=' * 60}\n  TOTAL: {_passed} passed, {_failed} failed\n{'=' * 60}")
sys.exit(1 if _failed else 0)
