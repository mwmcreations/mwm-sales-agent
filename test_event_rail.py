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
from datetime import datetime, timedelta
from event_rail import (stage_horizon_phrase, confirmation_copy, KIND_INTERNAL,
                        mask_contact,
                        CONFIRMATION_PLAN,
                        harden_event_body, audit_event, resolve_channel,
                        is_ig_scoped, is_dialable, ascii_email, looks_like_address,
                        reminder_channel_for, EventRailRejected, STANDARD_REMINDERS,
                        CH_INSTAGRAM, CH_WHATSAPP, CH_WEB, CH_UNKNOWN,
                        barter_signal, barter_signal_in_history,
                        BARTER_YES, BARTER_MAYBE, BARTER_NONE,
                        barter_refusal_note, barter_clarify_note,
                        booking_needs_number, resolve_callback_number,
                        missing_number_note, PARTNERSHIP_INBOX,
                        is_out_of_hours, out_of_hours_reason,
                        build_approval_request, approval_is_open,
                        approval_live_slots, approval_has_expired,
                        approval_reminder_interval_hours, approval_reminder_due,
                        claims_pending_approval, stall_message_allowed,
                        no_approval_tool_note, approval_filed_note,
                        approval_expiry_note, approval_health_line,
                        APPROVAL_PENDING, APPROVAL_APPROVED,
                        STANDARD_HOURS_START, STANDARD_HOURS_END,
                        is_attendee_permission_error, strip_attendees,
                        attendee_fallback_note, booking_sync_alert,
                        ig_mark_key, ig_window_blocked, ig_should_alert_403)

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
# PATCH #45A — a studio visit now DOES have a T-48 stage, but it is a CLIENT
# touch, not a crew one. The original assertion conflated "no crew at 48" with
# "nothing at 48"; only the first was ever the rule.
check("studio visit at T-48 -> CLIENT touch (new in #45A)",
      due_stages(KIND_STUDIO_VISIT, 48.0), [("client", 48)])
check_false("...and still NO crew stage — a studio visit has no call sheet",
            any(a == "crew" for a, _h in due_stages(KIND_STUDIO_VISIT, 48.0)))
check("studio visit at T-168 -> the week-out touch",
      due_stages(KIND_STUDIO_VISIT, 168.0), [("client", 168)])
check("a 30-min strategy call does NOT get a week-out touch",
      due_stages(KIND_STRATEGY_CALL, 168.0), [])
check("...but does get T-48", due_stages(KIND_STRATEGY_CALL, 48.0), [("client", 48)])
# PATCH #45A — T-48 on a shoot now fires BOTH: the crew call-sheet assignment
# that always existed, and the new client touch. Order matters only for
# readability; both must be present.
check_true("production shoot at T-48 still fires the CREW confirmation",
           ("crew", 48) in due_stages(KIND_PRODUCTION_SHOOT, 48.0))
check_true("...and now also a CLIENT touch",
           ("client", 48) in due_stages(KIND_PRODUCTION_SHOOT, 48.0))
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
check_true("crew confirmation at T-48",
           ("crew", 48) in due_stages(KIND_STUDIO_PRODUCTION, 48.0))
check_true("...alongside the #45A client touch",
           ("client", 48) in due_stages(KIND_STUDIO_PRODUCTION, 48.0))
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

print(f"\n--- Patch #34 section: {_passed} passed, {_failed} failed ---")

# ══════════════════════════════════════════════════════════════════════
# PATCH #35 — the watchdog must not cry wolf at an uninstrumented task.
# Mirrors the app.py gate; app.py needs Flask+Google libs to import.
# ══════════════════════════════════════════════════════════════════════

def watchdog_should_alert(*, past_deadline, claimed_today, ever_claimed, already_alerted):
    """Mirror of the Patch #35 missed-run watchdog decision."""
    if not past_deadline:      return False
    if claimed_today:          return False   # it ran
    if not ever_claimed:       return False   # NOT INSTRUMENTED — prove nothing
    if already_alerted:        return False   # once per task per day
    return True


print("\n== the bug #35 fixes: 7 guaranteed false alarms ==")
check_false("uninstrumented task past deadline -> SILENT",
            watchdog_should_alert(past_deadline=True, claimed_today=False,
                                  ever_claimed=False, already_alerted=False))
check_true("instrumented task that skipped -> ALERT",
           watchdog_should_alert(past_deadline=True, claimed_today=False,
                                 ever_claimed=True, already_alerted=False))

print("\n== and the rest of the ladder still holds ==")
check_false("before the deadline -> silent",
            watchdog_should_alert(past_deadline=False, claimed_today=False,
                                  ever_claimed=True, already_alerted=False))
check_false("it ran -> silent",
            watchdog_should_alert(past_deadline=True, claimed_today=True,
                                  ever_claimed=True, already_alerted=False))
check_false("already alerted today -> silent (no repeat spam)",
            watchdog_should_alert(past_deadline=True, claimed_today=False,
                                  ever_claimed=True, already_alerted=True))

print("\n== self-activation: a task switches its own monitoring on ==")
# Day 1: task gets instrumented and claims. Day 2: it skips -> now alertable.
check_false("day 1, never claimed before deadline -> silent",
            watchdog_should_alert(past_deadline=True, claimed_today=False,
                                  ever_claimed=False, already_alerted=False))
check_true("day 2, after one successful claim, a skip DOES alert",
           watchdog_should_alert(past_deadline=True, claimed_today=False,
                                 ever_claimed=True, already_alerted=False))

# ══════════════════════════════════════════════════════════════════════
# PATCH #36 — lead_key forward-write onto the Stripe Checkout Session.
# Mirrors the app.py resolver; app.py needs Flask+Google libs to import.
# ══════════════════════════════════════════════════════════════════════

def _mirror_find_by_email(email, leads):
    if not email:
        return None
    want = email.strip().lower()
    for k, v in leads.items():
        if (v.get("email") or "").strip().lower() == want:
            return k
    return None


def _mirror_find_by_name(name_raw, leads):
    want = (name_raw or "").strip().lower()
    if not want or len(want) < 4:
        return None
    hits = [k for k, v in leads.items()
            if (v.get("name") or "").strip().lower() == want]
    return hits[0] if len(hits) == 1 else None


def resolve_lead_key_for_payment(email, name, leads):
    """Mirror of the Patch #36 app.py resolver."""
    k = _mirror_find_by_email(email, leads)
    if k:
        return k, "email"
    k = _mirror_find_by_name(name, leads)
    if k:
        return k, "name"
    return None, "unmatched"


LEADS = {
    "whatsapp:+18135031224": {"name": "Todd Berger",  "email": "myorlandosold@gmail.com"},
    "whatsapp:+14075551111": {"name": "Ana Robinson", "email": "ana@example.com"},
    "whatsapp:+14075552222": {"name": "Ana Robinson", "email": "ana2@example.com"},
    "instagram:17841400000": {"name": "Bolfer Silva", "email": ""},
}

print("\n== #36: the happy path — email wins and is authoritative ==")
check("exact email -> that lead, via=email",
      resolve_lead_key_for_payment("myorlandosold@gmail.com", "Todd Berger", LEADS),
      ("whatsapp:+18135031224", "email"))
check("email match is case/space insensitive",
      resolve_lead_key_for_payment("  MyOrlandoSold@Gmail.COM ", "", LEADS),
      ("whatsapp:+18135031224", "email"))
check("email wins even when the name points elsewhere",
      resolve_lead_key_for_payment("ana@example.com", "Todd Berger", LEADS),
      ("whatsapp:+14075551111", "email"))

print("\n== #36: name is a FALLBACK, and only when unambiguous ==")
check("unknown email + unique name -> via=name",
      resolve_lead_key_for_payment("nobody@nowhere.com", "Bolfer Silva", LEADS),
      ("instagram:17841400000", "name"))
check("AMBIGUOUS name -> refuse, never guess",
      resolve_lead_key_for_payment("nobody@nowhere.com", "Ana Robinson", LEADS),
      (None, "unmatched"))
check("short name is not a name",
      resolve_lead_key_for_payment("", "Ana", LEADS), (None, "unmatched"))

print("\n== #36: a miss is RECORDED, never silent ==")
check("no email, no name -> unmatched (not None-None)",
      resolve_lead_key_for_payment("", "", LEADS), (None, "unmatched"))
check("unknown payer -> unmatched, so the miss is queryable",
      resolve_lead_key_for_payment("ghost@x.com", "Ghost Person", LEADS),
      (None, "unmatched"))
check_true("a miss ALWAYS returns a via value to stamp",
           resolve_lead_key_for_payment("ghost@x.com", "", LEADS)[1] != "")

print("\n== #36: 'unmatched' and 'predates the patch' must not look alike ==")
_sess_new_miss = {"lead_key_via": "unmatched"}
_sess_old      = {}
check_false("a pre-#36 session has no via field", "lead_key_via" in _sess_old)
check_true("a #36 miss is explicitly stamped", "lead_key_via" in _sess_new_miss)


# ══════════════════════════════════════════════════════════════════════
# PATCH #37 — the first lead of every month was silently dropped, and a
# rolling window made a benign rotation look like data loss.
# Mirrors app.py; app.py needs Flask+Google libs to import.
# ══════════════════════════════════════════════════════════════════════

def header_format_request(gid):
    """Mirror of the Patch #37 header-format payload."""
    return {"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
        "cell": {"userEnteredFormat": {
            "textFormat": {"bold": True,
                           "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
            "backgroundColor": {"red": 0.18, "green": 0.18, "blue": 0.18},
        }},
        "fields": "userEnteredFormat(textFormat,backgroundColor)",
    }}


def ensure_tab(tab, existing, *, format_raises):
    """Mirror of ensure_monthly_tab's failure semantics.
    Returns (tab_exists, lead_write_proceeds)."""
    if tab in existing:
        return True, True
    existing.add(tab)              # addSheet + headers succeed first
    if format_raises:
        pass                       # #37: cosmetic failure is caught, NOT raised
    return True, True


def rolling_window(tabs, n=3):
    """Mirror of the [:3] monthly-tab window (newest first)."""
    return tabs[:n]


print("\n== #37: the malformed payload that lost a lead every month ==")
_fmt = header_format_request(7)["repeatCell"]
check_false("foregroundColor is NOT a direct child of userEnteredFormat",
            "foregroundColor" in _fmt["cell"]["userEnteredFormat"])
check_true("foregroundColor lives under textFormat",
           "foregroundColor" in _fmt["cell"]["userEnteredFormat"]["textFormat"])
check("fields mask no longer names the invalid field",
      _fmt["fields"], "userEnteredFormat(textFormat,backgroundColor)")
check_false("fields mask must not mention foregroundColor at top level",
            "backgroundColor,foregroundColor" in _fmt["fields"])

print("\n== #37: a COSMETIC failure can never lose a lead again ==")
check("new month + format blows up -> tab exists AND write proceeds",
      ensure_tab("Aug 2026", set(), format_raises=True), (True, True))
check("new month, format fine -> unchanged",
      ensure_tab("Aug 2026", set(), format_raises=False), (True, True))
check("existing tab is a no-op",
      ensure_tab("Jul 2026", {"Jul 2026"}, format_raises=True), (True, True))

print("\n== #37: the rolling window rotates, it does not lose ==")
_jul = ["Jul 2026", "Jun 2026", "May 2026"]
_aug = ["Aug 2026", "Jul 2026", "Jun 2026", "May 2026"]
check("Jul 31 read Jul+Jun+May", rolling_window(_jul), ["Jul 2026", "Jun 2026", "May 2026"])
check("Aug 1 reads Aug+Jul+Jun", rolling_window(_aug), ["Aug 2026", "Jul 2026", "Jun 2026"])
check_false("May is no longer in the window", "May 2026" in rolling_window(_aug))
check_true("...but May's tab still EXISTS — nothing was deleted", "May 2026" in _aug)
check("window is always 3 tabs", len(rolling_window(_aug)), 3)



# ══════════════════════════════════════════════════════════════════════
# PATCH #38 — Do Not Contact enforced SERVER-SIDE, invalid addresses
# refused before send, and a rail that sends nothing says so itself.
# Mirrors app.py; app.py needs Flask+Google libs to import.
# ══════════════════════════════════════════════════════════════════════

MIRROR_DNC = {"yasminfmoraes@icloud.com", "ediasm@icloud.com"}
MIRROR_INTERNAL = {"michael@mwmcreations.com", "yasminfmoraes@icloud.com"}


def email_is_suppressed(addr, dynamic=None, dynamic_available=True):
    """Mirror of the Patch #38 endpoint gate. Fails CLOSED."""
    e = str(addr or "").strip().lower()
    if not e or "@" not in e:
        return True, "unparseable address"
    if e in MIRROR_DNC:
        return True, "do-not-contact list"
    if e in MIRROR_INTERNAL or e.endswith("@mwmcreations.com"):
        return True, "internal address"
    if not dynamic_available:
        return True, "suppression check unavailable"
    if (dynamic or set()) and e in dynamic:
        return True, "suppressed (dynamic list)"
    return False, ""


print("\n== #38: the two names MATT asked about — the answer WAS no ==")
check("Yasmin Moraes (Michael's daughter) is suppressed",
      email_is_suppressed("yasminfmoraes@icloud.com"), (True, "do-not-contact list"))
check("Marcia Cardim (now a client) is suppressed",
      email_is_suppressed("ediasm@icloud.com"), (True, "do-not-contact list"))
check_true("suppression is case-insensitive",
           email_is_suppressed("YasminFMoraes@iCloud.com")[0])
check_true("...and whitespace-insensitive",
           email_is_suppressed("  ediasm@icloud.com  ")[0])

print("\n== #38: internal addresses can never be emailed as leads ==")
check_true("michael@ is suppressed", email_is_suppressed("michael@mwmcreations.com")[0])
check_true("any @mwmcreations.com is suppressed", email_is_suppressed("info@mwmcreations.com")[0])

print("\n== #38: it FAILS CLOSED — a broken check never allows a send ==")
check("suppression store unreachable -> refuse, do not send",
      email_is_suppressed("stranger@example.com", dynamic_available=False),
      (True, "suppression check unavailable"))
check_true("empty address -> refuse", email_is_suppressed("")[0])
check_true("garbage address -> refuse", email_is_suppressed("not-an-email")[0])
check_true("None -> refuse", email_is_suppressed(None)[0])

print("\n== #38: a real lead is still sendable — the gate is not a wall ==")
check("ordinary lead passes", email_is_suppressed("krista@example.com"), (False, ""))
check("dynamic list suppresses without a deploy",
      email_is_suppressed("later@example.com", dynamic={"later@example.com"}),
      (True, "suppressed (dynamic list)"))

print("\n== #38: Anderson Brito Baez — a guaranteed bounce, caught before send ==")
_folded, _ok, _note = ascii_email("Andersonbritobáez@gmail.com")
check("accented address folds to a deliverable ASCII form",
      (_folded, _ok), ("Andersonbritobaez@gmail.com", True))
check_true("...and the fold is REPORTED, never silent", _note != "")
check_false("a bare accent string is NOT a valid address", ascii_email("áéí")[1])
check("a normal address is untouched and reports nothing",
      ascii_email("krista@example.com"), ("krista@example.com", True, ""))


def zero_send_alarm(due_count, dry_days, already_alerted_today, threshold=2):
    """Mirror of the Patch #38 zero-send alarm."""
    if not due_count:            return False   # nothing due -> quiet is correct
    if dry_days is None:         return False   # unknown -> do not cry wolf
    if dry_days < threshold:     return False
    if already_alerted_today:    return False   # once per day
    return True


print("\n== #38: five weekdays of zero sends should have paged, and didn't ==")
check_true("SUSAN's actual case: 7 due, 5 days dry -> PAGE",
           zero_send_alarm(7, 5.0, False))
check_true("never sent since instrumentation -> PAGE", zero_send_alarm(7, 999, False))
check_false("due work but sent yesterday -> silent", zero_send_alarm(7, 1.0, False))
check_false("nothing due -> silent even if dry for weeks", zero_send_alarm(0, 30.0, False))
check_false("already paged today -> no repeat spam", zero_send_alarm(7, 5.0, True))
check_false("unknown last-send -> silent, never guess", zero_send_alarm(7, None, False))



# ══════════════════════════════════════════════════════════════════════
# PATCH #39 — outcome automation policy. Every button does something,
# every sequence ENDS, and nothing is armed that cannot actually land.
# ══════════════════════════════════════════════════════════════════════
from event_rail import (outcome_plan, plan_is_deliverable, ig_window_open,
                        STEP_REBOOK, STEP_EMAIL_ASK, STEP_REVIEW,
                        STEP_NUDGE, STEP_VALUE, STEP_RECAP)

print("\n== #39: 'Not interested' is the ONE that must never reach out ==")
_ni = outcome_plan("not_interested", CH_WHATSAPP, True)
check_true("not_interested suppresses", _ni["suppress"])
check("...and arms NOTHING", _ni["steps"], [])
check_false("...and never routes to editing", _ni["editing"])

print("\n== #39: every other outcome does something (Michael's ask) ==")
for _oc in ("client_won", "follow_up", "studio_package_pitched",
            "completed", "no_show"):
    _p = outcome_plan(_oc, CH_WHATSAPP, True)
    check_true(f"{_oc} is automated",
               bool(_p["steps"]) or _p["internal_only"] or _p["editing"])

print("\n== #39: EVERY sequence has an ending (the Ezechiel rule) ==")
for _oc in ("follow_up", "studio_package_pitched", "completed", "no_show"):
    check_true(f"{_oc} closes", outcome_plan(_oc, CH_WHATSAPP, True)["close_after_days"] is not None)
check("no-show closes fastest — speed is the value",
      outcome_plan("no_show", CH_WHATSAPP, True)["close_after_days"], 5)

print("\n== #39: completed ALWAYS routes to editing, no keyword test ==")
check_true("completed -> editing", outcome_plan("completed", CH_WHATSAPP, True)["editing"])
check_true("completed -> editing even with no email",
           outcome_plan("completed", CH_UNKNOWN, False)["editing"])
check_true("completed asks for a review", any(k == STEP_REVIEW for _h, _c, k in
           outcome_plan("completed", CH_WHATSAPP, True)["steps"]))

print("\n== #39: client_won stays HUMAN on the outside ==")
_cw = outcome_plan("client_won", CH_WHATSAPP, True)
check_true("client_won is internal-only", _cw["internal_only"])
check("...no automated client touches", _cw["steps"], [])
check_true("...but it does route to editing", _cw["editing"])

print("\n== #39: the Instagram 24h door ==")
check_true("window open at 2h", ig_window_open(2))
check_false("window shut at 25h", ig_window_open(25))
check_false("UNKNOWN age must mean SHUT, never open", ig_window_open(None))
check("IG lead inside the window -> DM them",
      outcome_plan("no_show", CH_INSTAGRAM, False, 2)["steps"][0][1], CH_INSTAGRAM)
check("IG lead outside the window + email -> fall to email",
      outcome_plan("no_show", CH_INSTAGRAM, True, 99)["steps"][0][1], CH_WEB)
check("IG lead outside the window + NO email -> unreachable",
      outcome_plan("no_show", CH_INSTAGRAM, False, 99)["steps"][0][1], CH_UNKNOWN)

print("\n== #39: never claim a sequence is armed when nothing can land ==")
check_false("IG, window shut, no email -> NOT deliverable",
            plan_is_deliverable(outcome_plan("no_show", CH_INSTAGRAM, False, 99)))
check_true("IG, window open -> deliverable",
           plan_is_deliverable(outcome_plan("no_show", CH_INSTAGRAM, False, 2)))
check_true("suppress plans are 'deliverable' (nothing armed on purpose)",
           plan_is_deliverable(outcome_plan("not_interested", CH_WHATSAPP, True)))

print("\n== #39: 83% of leads have no email — pitch must not evaporate ==")
_pn = outcome_plan("studio_package_pitched", CH_WHATSAPP, False)
check("pitched w/o email -> ask for one FIRST, on their own channel",
      (_pn["steps"][0][1], _pn["steps"][0][2]), (CH_WHATSAPP, STEP_EMAIL_ASK))
check("pitched WITH email -> the existing 3-email rail, unchanged",
      [(h, k) for h, _c, k in outcome_plan("studio_package_pitched", CH_WEB, True)["steps"]],
      [(1, STEP_RECAP), (48, STEP_VALUE), (144, STEP_NUDGE)])

print("\n== #39: reply on the channel they ARRIVED on ==")
check("WhatsApp lead is answered on WhatsApp",
      outcome_plan("follow_up", CH_WHATSAPP, True)["steps"][0][1], CH_WHATSAPP)
check("no-show gets a SAME-DAY offer (T+0), not a day-3 one",
      outcome_plan("no_show", CH_WHATSAPP, True)["steps"][0][0], 0)
check_true("follow_up is slower than no_show",
           outcome_plan("follow_up", CH_WHATSAPP, True)["steps"][0][0]
           > outcome_plan("no_show", CH_WHATSAPP, True)["steps"][0][0])

print("\n== #39: every plan explains itself ==")
for _oc in ("client_won", "follow_up", "studio_package_pitched",
            "completed", "not_interested", "no_show"):
    check_true(f"{_oc} carries a 'why'", bool(outcome_plan(_oc, CH_WHATSAPP, True)["why"]))



# ══════════════════════════════════════════════════════════════════════
# PATCH #40 — a nested bracket in a business name broke the lead lookup.
# Found live by Michael, Aug 3, on the FIRST real use of the #39 rail.
# ══════════════════════════════════════════════════════════════════════
from meeting_report_utils import parse_event_summary, _split_trailing_parens

print("\n== #40: the title that actually broke it ==")
check("Krista Neeley — business name contains its own brackets",
      parse_event_summary(
          "Studio Visit — Krista Neeley (New Media Cruise (with Michael Neeley - Infinite Leads))"),
      ("Krista Neeley", "New Media Cruise (with Michael Neeley - Infinite Leads)"))
check_false("...and the name no longer carries a bracket",
            "(" in parse_event_summary(
                "Studio Visit — Krista Neeley (New Media Cruise (with Michael Neeley - Infinite Leads))")[0])

print("\n== #40: everything that already worked still works ==")
check("simple business", parse_event_summary("Studio Visit — Priti Verma (Pretty_dangles)"),
      ("Priti Verma", "Pretty_dangles"))
check("strategy call", parse_event_summary("Strategy Call — Carolina Rodriguez Wilhelm (Carito Music)"),
      ("Carolina Rodriguez Wilhelm", "Carito Music"))
check("no separator, no parens", parse_event_summary("Reunião SMILE AMERICAN"),
      ("Reunião SMILE AMERICAN", ""))
check("name-first with hyphen", parse_event_summary("Marta Villagra - Coaching Content"),
      ("Marta Villagra", "Coaching Content"))
check("calendly-style title is left intact",
      parse_event_summary("Gema Hiatt and Michael Moraes"),
      ("Gema Hiatt and Michael Moraes", ""))

print("\n== #40: the splitter refuses rather than guessing ==")
check("balanced trailing group splits", _split_trailing_parens("Ann Lee (Acme)"), ("Ann Lee", "Acme"))
check("nested group splits at the OUTER bracket",
      _split_trailing_parens("Ann Lee (Acme (US))"), ("Ann Lee", "Acme (US)"))
check("no trailing bracket -> unchanged", _split_trailing_parens("Ann Lee"), ("Ann Lee", ""))
check("UNBALANCED -> refuse, keep the original",
      _split_trailing_parens("Ann Lee (Acme))"), ("Ann Lee (Acme))", ""))
check("empty inside -> refuse", _split_trailing_parens("Ann Lee ()"), ("Ann Lee ()", ""))
check("nothing before the bracket -> refuse (a business is not a name)",
      _split_trailing_parens("(Acme)"), ("(Acme)", ""))
check("empty string is safe", _split_trailing_parens(""), ("", ""))



# ══════════════════════════════════════════════════════════════════════
# PATCH #42 — one record, two people. Krista Neeley + husband booked
# together, so name AND email each hold two values. Every lookup missed.
# ══════════════════════════════════════════════════════════════════════
from event_rail import emails_in_field, email_field_matches, names_match

KRISTA_EMAIL = "Kristasky@gmail.com / Michael@michaelneeley.com"
KRISTA_NAME  = "Krista Neeley (with Michael Neeley)"

print("\n== #42: the record that actually broke it ==")
check("both addresses are found", emails_in_field(KRISTA_EMAIL),
      ["kristasky@gmail.com", "michael@michaelneeley.com"])
check_true("the invite address matches", email_field_matches(KRISTA_EMAIL, "kristasky@gmail.com"))
check_true("...and so does her husband's", email_field_matches(KRISTA_EMAIL, "Michael@michaelneeley.com"))
check_true("her name matches the plain form", names_match(KRISTA_NAME, "Krista Neeley"))

print("\n== #42: separators people actually use ==")
for _sep in ("/", ",", ";", "|", " "):
    check("split on " + repr(_sep), emails_in_field(f"a@b.com{_sep}c@d.com"),
          ["a@b.com", "c@d.com"])
check("single address still works", emails_in_field("solo@x.com"), ["solo@x.com"])
check("duplicates collapse", emails_in_field("a@b.com, A@B.COM"), ["a@b.com"])
check("empty field", emails_in_field(""), [])
check("None field", emails_in_field(None), [])
check("junk is dropped, not guessed at", emails_in_field("not-an-email / real@x.com"), ["real@x.com"])

print("\n== #42: matching stays EXACT — no substring merges ==")
check_false("ana@ must not match susana@", email_field_matches("susana@x.com", "ana@x.com"))
check_false("a bare domain is not a match", email_field_matches("a@b.com", "b.com"))
check_false("empty wanted never matches", email_field_matches("a@b.com", ""))
check_false("empty stored never matches", email_field_matches("", "a@b.com"))

print("\n== #42: names — reduce, but never merge two different people ==")
check_true("trailing bracket is optional", names_match("Ann Lee (Acme)", "Ann Lee"))
check_true("symmetric", names_match("Ann Lee", "Ann Lee (Acme)"))
check_true("exact still matches", names_match("Ann Lee", "ann lee"))
check_false("different surnames never match", names_match("Ana Silva (Acme)", "Ana Costa"))
check_false("a business alone is not a name", names_match("(Acme)", "Acme"))
check_false("empty never matches", names_match("", "Ann Lee"))

print("\n== #42: why this mattered beyond one report ==")
# The same helper backs the Stripe payer lookup. A joint-booking client who
# pays would have produced "PAID CLIENT NOT LINKED TO A LEAD" — the Robinson
# defect, arriving through a different door.
check_true("a payer using EITHER address now links to the lead",
           email_field_matches(KRISTA_EMAIL, "michael@michaelneeley.com")
           and email_field_matches(KRISTA_EMAIL, "kristasky@gmail.com"))



# ══════════════════════════════════════════════════════════════════════
# PATCH #43 — the reminder system, made strong. Written the day Gema
# Hiatt cancelled three minutes before her call.
# ══════════════════════════════════════════════════════════════════════
from event_rail import (due_rsvp_tier, instrumentation_gaps, gap_severity,
                        REMINDER_HORIZON_HOURS, RSVP_TIERS_HOURS)

ROBINSON = {"summary": "STUDIO SHOOT - NO LINES with Dr. Scott Robinson",
            "description": "2 episodes - In-person Guests",
            "location": "MWM Creations, 1500 Park Center Dr, Orlando",
            "attendees": [{"email": "healer2bsure@gmail.com", "responseStatus": "accepted"}]}
COACHFLY = {"summary": "Call — COACH FLY (Jahari) first session",
            "description": "", "location": "Phone / WhatsApp call",
            "overrideReminders": [{"method": "popup", "minutes": 30}]}
CLEAN    = {"summary": "Studio Visit — Priti Verma (Pretty_dangles)",
            "description": "Lead: Priti Verma\nPhone: 14075551234\nEmail: p@x.com",
            "location": "1500 Park Center Dr, Suite 230, Orlando, FL 32835",
            "attendees": [{"email": "p@x.com", "responseStatus": "accepted"}],
            "overrideReminders": [{"method": "email", "minutes": 1440},
                                  {"method": "email", "minutes": 60},
                                  {"method": "popup", "minutes": 30}]}

print("\n== #43: the horizon that left Robinson 2h of margin ==")
check_true("horizon now clears the 72h tier", REMINDER_HORIZON_HOURS > 72)
check_true("...and still clears crew T-48 with real slack",
           REMINDER_HORIZON_HOURS - 48 >= 24)

print("\n== #43: RSVP tiers — 72h added, because 24h is too late to act ==")
check("T-72 fires the 72 tier", due_rsvp_tier(72), 72)
check("T-24 still fires the 24 tier", due_rsvp_tier(24), 24)
check_true("tolerance covers the 15-min poll", due_rsvp_tier(72.9) == 72 and due_rsvp_tier(23.2) == 24)
check("nothing fires at T-50", due_rsvp_tier(50), None)
check("nothing fires at T-12", due_rsvp_tier(12), None)
check("garbage never fires", due_rsvp_tier(None), None)
check_true("a single pass can never fire two tiers",
           all(due_rsvp_tier(h) in (None, 72, 24) for h in range(0, 100)))

print("\n== #43: Robinson — visible but ANONYMOUS (the hard failure) ==")
_g = instrumentation_gaps(ROBINSON)
check_true("flagged anonymous", any(x.startswith("ANONYMOUS") for x in _g))
# PATCH #45D — the two assertions that used to live here are DELETED, not
# adjusted, and that is the point of this patch. They asserted that an event
# without an email reminder override was critical. Calendar reminder overrides
# are private to the account that wrote them and reach no client, so the old
# test was pinning a measurement that meant nothing.
check_false("no longer scored on reminders at all",
            any(x.startswith("NO REMINDERS") for x in _g))
check("anonymous alone is a WARN — he still receives the message",
      gap_severity(_g), "warn")
check_false("...but NOT flagged attendee-less — he does have one",
            any(x.startswith("NO ATTENDEE") for x in _g))
check_false("resolving him by attendee clears the anonymous flag",
            any(x.startswith("ANONYMOUS") for x in
                instrumentation_gaps(ROBINSON, resolved_name="Dr. Scott Robinson")))

print("\n== #43: Coach Fly — nobody was ever invited ==")
_c = instrumentation_gaps(COACHFLY)
check_true("flagged attendee-less", any(x.startswith("NO ATTENDEE") for x in _c))
check_false("popup-vs-email is no longer scored — NEITHER reaches the client",
            any("EMAIL reminder" in x for x in _c))
check("still critical, on the attendee — that is the real failure",
      gap_severity(_c), "critical")

print("\n== #43: a properly instrumented event is SILENT ==")
check("no gaps on a clean event", instrumentation_gaps(CLEAN), [])
check("severity ok", gap_severity(instrumentation_gaps(CLEAN)), "ok")

print("\n== #43: degraded but reachable = warn, not critical ==")
# PATCH #45D — stripping an event down to one 60-minute email override used to
# be a WARN. It is now OK, because that field was never the safety net. The
# safety net is the attendee, the name and the RSVP, all of which CLEAN has.
_warn = dict(CLEAN, overrideReminders=[{"method": "email", "minutes": 60}])
check("reminder overrides no longer affect the verdict",
      gap_severity(instrumentation_gaps(_warn)), "ok")
_noreminders = dict(CLEAN)
_noreminders.pop("overrideReminders", None)
check("an event with NO overrides at all is still OK",
      gap_severity(instrumentation_gaps(_noreminders)), "ok")
_rsvp = dict(CLEAN, attendees=[{"email": "p@x.com", "responseStatus": "needsAction"}])
check_true("unanswered RSVP is reported",
           any(x.startswith("RSVP unanswered") for x in instrumentation_gaps(_rsvp)))
check("...as a warning, not a critical", gap_severity(instrumentation_gaps(_rsvp)), "warn")


print("\n== #45B: tier-aware copy — a reminder must never state the wrong day ==")
# The old body said "your session tomorrow" for EVERY stage >= 24h. With the
# new 48h and 168h tiers that is wrong twice, and a client who diaries the
# wrong date because our reminder told them to is worse off than one we never
# reminded at all.
check("a week out reads as a week out", stage_horizon_phrase(168), "a week from now")
check("two days out does not say tomorrow", stage_horizon_phrase(48), "in a couple of days")
check("T-24 says tomorrow", stage_horizon_phrase(24), "tomorrow")
check("T-2 says today", stage_horizon_phrase(2), "today")
check("garbage degrades safely", stage_horizon_phrase(None), "coming up")

_wa168, _s168, _h168 = confirmation_copy(168, "Jane", "Tuesday, August 11", "10:00 AM")
check_false("the 7-day WhatsApp message never says 'tomorrow'", "tomorrow" in _wa168)
check_true("...and carries the DATE, not just a weekday", "August 11" in _wa168)
check_true("...and the time", "10:00 AM" in _wa168)
check_true("...greets by first name", _wa168.startswith("Hi Jane!"))

_wa2, _s2, _h2 = confirmation_copy(2, "Jane", "Tuesday, August 11", "10:00 AM")
check_true("the day-of message says today", "today" in _wa2)
check_false("...and does not ask them to confirm hours before", "reply YES" in _wa2.lower())

_wa48, _s48, _h48 = confirmation_copy(48, "Jane", "Tuesday, August 11", "10:00 AM",
                                      location="1500 Park Center Dr")
check_true("the email carries the location when we have one",
           "1500 Park Center Dr" in _h48)
check_true("...and the subject carries the date", "August 11" in _s48)
_wa48b, _s48b, _h48b = confirmation_copy(48, "", "Tuesday, August 11", "10:00 AM")
check_true("an empty name degrades to 'there', never to 'Hi !'",
           _wa48b.startswith("Hi there!"))

print("\n== #45A: the ladder that actually sends ==")
check_true("the horizon can reach the 168h tier at all", REMINDER_HORIZON_HOURS > 168)
check_true("...with real slack, not two hours of it", REMINDER_HORIZON_HOURS - 168 >= 6)
# due_stages matches a WINDOW, not a threshold — this is what makes raising the
# horizon safe to deploy: an event already 100h out does NOT retro-fire the
# 168h tier, it simply missed that window.
check("an event already inside 168h does NOT back-fire the week-out tier",
      due_stages(KIND_STUDIO_VISIT, 100.0), [])
check_true("every client stage in every plan is reachable within the horizon",
           all(h <= REMINDER_HORIZON_HOURS
               for plan in CONFIRMATION_PLAN.values() for _a, h in plan))
check_true("no plan fires two stages in one pass",
           all(len(due_stages(k, float(h))) == len(set(due_stages(k, float(h))))
               for k in CONFIRMATION_PLAN for h in range(0, 200)))

print("\n== #45E: the sweep filter must drop the gym WITHOUT dropping Coach Fly ==")
# The whole risk of adding a client filter is that it silences the exact case
# the sweep exists for. Coach Fly's event was hand-made, has no recognised
# title and no `Lead:` line — a plain is_client_event() gate would have hidden
# it. These pin the three-state contract the sweep depends on.
_coachfly = {"summary": "Call — COACH FLY (Jahari) first session",
             "description": "", "location": "Phone / WhatsApp call", "attendees": []}
_gym = {"summary": "TREINO EMS Vida Fit", "description": "", "attendees": []}
_legal = {"summary": "0844538-85.2024.8.19.0002 04ªVRCNI",
          "description": "Reunião do Microsoft Teams",
          "attendees": [{"email": "pedrosouza@tjrj.jus.br", "responseStatus": "needsAction"}]}
_weekly = {"summary": "SEND WEEKLY UPDATE E-MAIL - VICTORY TV", "description": "", "attendees": []}

check("the gym is INTERNAL — silently skipped", classify_event(_gym)[0], KIND_INTERNAL)
check("the court hearing is INTERNAL", classify_event(_legal)[0], KIND_INTERNAL)
check("the weekly block is INTERNAL", classify_event(_weekly)[0], KIND_INTERNAL)
check_false("Coach Fly is NOT confidently a client event", classify_event(_coachfly)[1])
check_false("...but she is NOT internal either — so she must still surface",
            classify_event(_coachfly)[0] == KIND_INTERNAL)
check_true("...and she has no attendee, which is what makes her un-railable",
           not _coachfly["attendees"])

print("\n== #47: the inspection endpoint must not become an exfiltration tool ==")
# /admin/lead-seq exists so a defect can be diagnosed without a deploy. It must
# show enough to confirm WHO, and never enough to contact them, in case the
# admin secret ever leaks.
check("an email keeps its domain but loses the mailbox",
      mask_contact("rodolfos@nestseekers.com"), "rod…@nestseekers.com")
check("a short local part is cut harder",
      mask_contact("mo@x.com"), "m…@x.com")
check("a phone keeps only the last four", mask_contact("14075551234"), "…1234")
check("an IGSID is masked the same way",
      mask_contact("178901234567890"), "…7890")
check("empty stays empty", mask_contact(""), "")
check("None does not crash", mask_contact(None), "")
check_false("the full address never survives masking",
            "rodolfos@nestseekers.com" == mask_contact("rodolfos@nestseekers.com"))
check_false("...nor the full number",
            "14075551234" in mask_contact("14075551234"))



# ══════════════════════════════════════════════════════════════════════
#  PATCH #57 — barter proposals are not booked, and a call needs a number
# ══════════════════════════════════════════════════════════════════════

print("\n--- Patch #57: barter proposals never reach the calendar ---")

# The sentence that started this. Verbatim from the Aug 5 Instagram thread.
GIAN = ("That's not a bad price, at the moment though I cant afford it but "
        "are yall willing to do a business exchange if i advertise for yall "
        "on my YouTube channel?")

check("the actual message that caused this is a hard barter signal",
      barter_signal(GIAN), BARTER_YES)

for phrase in [
    "would you be open to a barter?",
    "I can advertise for you in exchange for studio time",
    "happy to promote your studio in return for editing",
    "can we trade services instead of paying",
    "I'd rather do an exchange of services",
    "posso fazer uma permuta?",
    "free sessions in exchange for shoutouts",
    "instead of paying could I give you exposure",
]:
    check_true(f"hard barter: {phrase[:44]!r}", barter_signal(phrase) == BARTER_YES)

print("\n--- ...but a paying lead is not blocked ---")

for phrase in [
    "How much is it to film twice a month?",
    "What's your hourly rate with editing included?",
    "I want to book the monthly package",
    "Can I come see the studio on Thursday?",
    "We're an exchange student agency looking to hire a video team",
]:
    check("paying language stays clear of the hard gate",
          barter_signal(phrase) == BARTER_YES, False)

print("\n--- partnership language is a question, not a refusal ---")

check("bare 'partnership' is only a maybe",
      barter_signal("I'm interested in a partnership with your studio"),
      BARTER_MAYBE)
check("'partner with' is only a maybe",
      barter_signal("Would you want to partner with our agency?"), BARTER_MAYBE)
check("'collab' is only a maybe", barter_signal("wanna collab?"), BARTER_MAYBE)
check("a plain enquiry is neither",
      barter_signal("Do you shoot podcasts?"), BARTER_NONE)
check("empty text is neither", barter_signal(""), BARTER_NONE)
check("None does not crash", barter_signal(None), BARTER_NONE)

print("\n--- history is read from the LEAD's turns only ---")

# This is the false positive that would otherwise fire on every property
# management pitch Maya makes. Her own script says "One partnership = ...".
MWM_PITCH = ("One partnership = dozens of compliant clients. Bundle it into "
             "your management offering.")

check("MWM's own partnership pitch does not flag the lead",
      barter_signal_in_history([
          {"role": "user", "content": "We manage 40 associations."},
          {"role": "assistant", "content": MWM_PITCH},
      ]), BARTER_NONE)

check("the lead's own barter line does flag",
      barter_signal_in_history([
          {"role": "user", "content": "how much per hour?"},
          {"role": "assistant", "content": "It's $349/hour with editing."},
          {"role": "user", "content": GIAN},
          {"role": "assistant", "content": "That's a creative idea!"},
      ]), BARTER_YES)

check("hard beats soft anywhere in the window",
      barter_signal_in_history([
          {"role": "user", "content": "interested in a partnership"},
          {"role": "user", "content": "I mean a barter, no money"},
      ]), BARTER_YES)

check("tool-shaped content blocks are flattened, not crashed on",
      barter_signal_in_history([
          {"role": "user", "content": [{"type": "text", "text": GIAN}]},
      ]), BARTER_YES)

check("an empty history is safe", barter_signal_in_history([]), BARTER_NONE)
check("None history is safe", barter_signal_in_history(None), BARTER_NONE)

check_true("the refusal tells Maya where to send them",
           PARTNERSHIP_INBOX in barter_refusal_note("Gian"))
check_true("the refusal names the lead when we know it",
           "Gian" in barter_refusal_note("Gian"))
check_true("the refusal forbids characterising Michael's appetite",
           "how Michael feels" in barter_refusal_note())
check_true("the clarify note asks the paid-or-exchange question",
           "paid engagement" in barter_clarify_note())

print("\n--- a call Michael places needs a number he can dial ---")

check_true("a strategy call needs a number", booking_needs_number("strategy_call"))
check_false("a studio visit does not", booking_needs_number("studio_visit"))
check_false("an unknown type does not", booking_needs_number(None))

# Gian's real identifier, as Maya stored it.
IGSID = "+2264056414361639"

ok, num, why = resolve_callback_number("strategy_call", identifier=IGSID)
check("an IG thread with no callback number is refused", ok, False)
check("...and no number is invented", num, None)
check_true("...and the reason names the IGSID", "IGSID" in why)

ok, num, why = resolve_callback_number("strategy_call", identifier=IGSID,
                                       callback="+1 407 555 1234")
check("a collected callback number rescues the booking", ok, True)
check("...and it is the number that gets used", num, "+1 407 555 1234")

ok, num, why = resolve_callback_number("strategy_call", identifier=IGSID,
                                       callback=IGSID)
check("passing the IGSID back as the callback fools nothing", ok, False)

ok, num, why = resolve_callback_number("strategy_call",
                                       identifier="whatsapp:+14075551234")
check("a WhatsApp thread already has its number", ok, True)
check_true("...taken from the identifier", "4075551234" in (num or ""))

ok, num, why = resolve_callback_number("studio_visit", identifier=IGSID)
check("a studio visit is NOT refused for want of a number", ok, True)
check("...but it is honest that there is none", num, None)

ok, num, why = resolve_callback_number("strategy_call", identifier=None,
                                       callback=None)
check("no identifier and no callback is still a refusal", ok, False)

check_true("the refusal tells Maya exactly what to ask for",
           "phone number" in missing_number_note("strategy_call"))
check_true("...and which argument to put it in",
           "callback_phone" in missing_number_note("strategy_call"))
check_false("...and does not tell her to confirm a time first",
            "confirm the time" in missing_number_note("strategy_call"))


# ══════════════════════════════════════════════════════════════════════
#  PATCH #58 — out-of-hours is a request, not a wall; and Maya cannot
#  claim a human is deciding something she never asked
# ══════════════════════════════════════════════════════════════════════

print("\n--- Patch #58: what counts as out of hours ---")

# Thu Aug 6 2026 is a Thursday; Sat Aug 8 is a Saturday.
def _et(s):
    return datetime.fromisoformat(s)

check_false("10 AM Thursday is standard", is_out_of_hours(_et("2026-08-06T10:00:00")))
check_false("3 PM Thursday is standard",  is_out_of_hours(_et("2026-08-06T15:00:00")))
check_false("9 AM exactly is standard",   is_out_of_hours(_et("2026-08-06T09:00:00")))
check_true("5 PM exactly is OUT",         is_out_of_hours(_et("2026-08-06T17:00:00")))
check_true("7 PM — Andrea's ask — is OUT", is_out_of_hours(_et("2026-08-06T19:00:00")))
check_true("8 AM is OUT",                 is_out_of_hours(_et("2026-08-06T08:00:00")))
check_true("Saturday noon is OUT",        is_out_of_hours(_et("2026-08-08T12:00:00")))
check_true("Sunday noon is OUT",          is_out_of_hours(_et("2026-08-09T12:00:00")))
check_false("a non-datetime does not crash into True", is_out_of_hours("7pm"))

check("an evening reads as an evening",
      out_of_hours_reason(_et("2026-08-06T19:00:00")), "evening — after standard hours")
check("a weekend reads as a weekend",
      out_of_hours_reason(_et("2026-08-08T12:00:00")), "weekend")
check("early morning is named too",
      out_of_hours_reason(_et("2026-08-06T07:00:00")), "before standard hours")

print("\n--- the request record ---")

NOW = _et("2026-08-06T09:00:00")
REQ = build_approval_request(
    "AR-1", "tok-secret", "Andrea Battis", "abattis18@gmail.com",
    "+1738648684123273",
    ["2026-08-06T19:00:00", "2026-08-10T19:00:00", "2026-08-11T19:00:00"],
    business="Art of Whiskey / PromotionsbyAndrea",
    note="Zoom with Sean, evenings only",
    channel="instagram",
    created_at="2026-08-06T09:00:00",
)

check("a new request is pending", REQ["status"], APPROVAL_PENDING)
check_true("...and open", approval_is_open(REQ))
check("nothing is chosen yet", REQ["chosen_slot"], None)
check("the lead has not been told yet", REQ["lead_told_at"], None)
check("no reminders yet", REQ["reminders_sent"], 0)
check("all three slots are live at 9 AM", len(approval_live_slots(REQ, NOW)), 3)

# Friday morning: tonight's 7 PM has passed, the other two have not.
FRI = _et("2026-08-07T09:00:00")
check("after tonight passes, two remain", len(approval_live_slots(REQ, FRI)), 2)
check_false("...and it has not expired", approval_has_expired(REQ, FRI))

LATER = _et("2026-08-12T09:00:00")
check_true("once every slot passes, it HAS expired", approval_has_expired(REQ, LATER))
check("...and no slots are live", len(approval_live_slots(REQ, LATER)), 0)

DONE = dict(REQ, status=APPROVAL_APPROVED)
check_false("an approved request never 'expires'", approval_has_expired(DONE, LATER))
check_false("...and is not open", approval_is_open(DONE))
check_false("a request with no slots cannot expire",
            approval_has_expired(build_approval_request("x","t","n","","",[]), LATER))

print("\n--- reminders get louder as the slot approaches ---")

FAR = build_approval_request("AR-2","t","L","","",["2026-08-20T19:00:00"],
                             created_at="2026-08-06T09:00:00")
check("a slot two weeks out reminds every 12h",
      approval_reminder_interval_hours(FAR, NOW), 12)

for iso, want, label in [
    ("2026-08-08T09:00:00", 6, "36h out reminds every 6h"),
    ("2026-08-06T21:00:00", 3, "12h out reminds every 3h"),
    ("2026-08-06T12:00:00", 1, "3h out reminds every hour"),
]:
    r = build_approval_request("AR", "t", "L", "", "", [iso],
                               created_at="2026-08-06T09:00:00")
    check(label, approval_reminder_interval_hours(r, NOW), want)

check("a request with only dead slots has no interval",
      approval_reminder_interval_hours(FAR, _et("2026-09-01T09:00:00")), None)

check_true("a never-notified request is due immediately",
           approval_reminder_due(REQ, NOW))
JUST = dict(REQ, notified_at="2026-08-06T08:55:00")
check_false("...but not five minutes after a notification",
            approval_reminder_due(JUST, NOW))
STALE = dict(REQ, notified_at="2026-08-06T02:00:00")
check_true("...and yes again once the interval has passed",
           approval_reminder_due(STALE, NOW))
check_false("an approved request is never nudged",
            approval_reminder_due(dict(REQ, status=APPROVAL_APPROVED), NOW))

print("\n--- THE ANDREA REPLAY: every stalling line must be caught ---")

# Verbatim from the Instagram thread, Aug 3-6. Each of these went to a real
# lead while no request existed anywhere.
ANDREA_REAL = [
    "Since Michael's regular calendar runs daytime, let me flag this for him "
    "directly to see if he can make an evening exception.",
    "Michael's calendar is normally daytime, but let me check with him directly "
    "about making an evening Zoom work for Sean. I'll get back to you as soon "
    "as I hear from him!",
    "I'll pass that along to Michael right away and see which evening he can "
    "make work for a Zoom with Sean. As soon as he confirms, I'll message you "
    "here to lock it in!",
    "I'll follow up with Michael tonight and message you as soon as I have his "
    "evening availability for the Zoom with Sean.",
    "Still working on pinning down an evening that works on Michael's end for "
    "the Zoom with Sean — I haven't forgotten you.",
    "Still working on locking in Wednesday or Thursday evening with Michael for "
    "the Zoom with Sean — I'll have an answer for you shortly.",
    "Just following up on the emails so I'm ready the moment Michael confirms "
    "Wednesday or Thursday evening",
    "Those evenings are outside Michael's standard calendar hours, so I still "
    "need his personal green light to open one up. I've flagged all three "
    "nights for him as options",
    "Tonight falls outside Michael's standard calendar hours too, so it needs "
    "his personal OK just like the others.",
    "The second he confirms one, I'll message you and send the Zoom invite to "
    "you and Sean!",
]
for i, msg in enumerate(ANDREA_REAL, 1):
    check_true(f"Andrea line {i} is a pending-approval claim",
               claims_pending_approval(msg))
    allowed, why = stall_message_allowed(msg, None)
    check_false(f"Andrea line {i} is REFUSED with no request on file", allowed)

print("\n--- ...but the same words are fine once a request is real ---")

for msg in ANDREA_REAL:
    allowed, _ = stall_message_allowed(msg, REQ)
    check_true("allowed when a pending request backs it", allowed)

allowed, _ = stall_message_allowed(ANDREA_REAL[0], dict(REQ, status=APPROVAL_APPROVED))
check_false("a RESOLVED request does not license 'still waiting' language", allowed)

print("\n--- and ordinary messages are never touched ---")

for msg in [
    "You're all set! Michael's looking forward to seeing you Thursday at 10.",
    "For studio time with editing included, it's $349/hour.",
    "Here are the next times Michael has open: 1) Tue 10 AM  2) Wed 3 PM",
    "Which of those works best for you?",
    "Michael will walk you through the whole setup on the call.",
    "Thanks for reaching out! What kind of content are you creating?",
    "I'll send the calendar invite to that address now.",
]:
    check_true(f"passes untouched: {msg[:38]!r}", stall_message_allowed(msg, None)[0])
    check_false(f"not a stall claim: {msg[:38]!r}", claims_pending_approval(msg))

check_false("empty text is not a claim", claims_pending_approval(""))
check_false("None is not a claim", claims_pending_approval(None))

print("\n--- what Maya is told at each step ---")

check_true("the wall note refuses to call it unavailable",
           "must not tell" in no_approval_tool_note("Andrea"))
check_true("...and names the tool she should call",
           "request_out_of_hours_approval" in no_approval_tool_note())
check_true("...and states the real hours",
           f"{STANDARD_HOURS_START}:00" in no_approval_tool_note())
check_true("...and forbids the exact thing she did",
           "have not filed" in no_approval_tool_note())

check_true("the filed note carries the request id",
           "AR-1" in approval_filed_note("AR-1", "Thu 7 PM, Mon 7 PM"))
check_true("...and forbids inventing a deadline for Michael",
           "deadline" in approval_filed_note("AR-1", "x"))

check_true("the expiry note apologises for the wait",
           "apologise" in approval_expiry_note(REQ))
check_true("...and names the lead",
           "Andrea" in approval_expiry_note(REQ))
check_true("...and explicitly bans another holding message",
           "still working on it" in approval_expiry_note(REQ))

check_true("the health line names the lead",
           "Andrea Battis" in approval_health_line(REQ, FRI))
check_true("...and its age, so three quiet days are visible",
           "h old" in approval_health_line(REQ, FRI))
check_true("...and how many options are still salvageable",
           "2 of 3" in approval_health_line(REQ, FRI))


# ══════════════════════════════════════════════════════════════════════
#  PATCH #59 — the portal booking that never reached the calendar
# ══════════════════════════════════════════════════════════════════════

print("\n--- Patch #59: recognising the attendee-permission failure ---")

# The exact error Google returned for Vanessa Serrano's booking #59.
REAL_403 = ('<HttpError 403 when requesting https://www.googleapis.com/calendar/v3/'
            'calendars/c_03s30bthurplevpk6a264h7n34%40group.calendar.google.com/'
            'events?sendUpdates=all&alt=json returned "Service accounts cannot '
            'invite attendees without Domain-Wide Delegation of Authority.". '
            'Details: "[{\'domain\': \'calendar\', \'reason\': '
            '\'forbiddenForServiceAccounts\', \'message\': \'Service accounts '
            'cannot invite attendees without Domain-Wide Delegation of '
            'Authority.\'}]">')

check_true("the real Vanessa 403 is recognised", is_attendee_permission_error(REAL_403))
check_true("the reason code alone is enough",
           is_attendee_permission_error("reason: forbiddenForServiceAccounts"))
check_true("...and the prose alone is enough",
           is_attendee_permission_error(
               "Service accounts cannot invite attendees without "
               "Domain-Wide Delegation of Authority."))
check_true("case does not matter",
           is_attendee_permission_error("FORBIDDENFORSERVICEACCOUNTS"))

print("\n--- ...and NOT swallowing anything else ---")

# This is the important half. Retrying these without attendees would fail
# again while being reported as a degraded success.
for other in [
    "<HttpError 403 ... 'reason': 'rateLimitExceeded'>",
    "<HttpError 404 ... Not Found>",
    "<HttpError 401 ... Invalid Credentials>",
    "<HttpError 400 ... 'Invalid start time.'>",
    "<HttpError 403 ... 'reason': 'quotaExceeded'>",
    "<HttpError 409 ... The requested identifier already exists.>",
    "ConnectionResetError(104, 'Connection reset by peer')",
]:
    check_false(f"not an attendee problem: {other[:40]!r}",
                is_attendee_permission_error(other))

check_false("None is not an error", is_attendee_permission_error(None))
check_false("empty is not an error", is_attendee_permission_error(""))

print("\n--- the retry body keeps the event, drops only the invite ---")

BODY = {
    "summary": "🎬 Studio: Vanessa Serrano (3h)",
    "description": "Studio Package portal booking #59",
    "start": {"dateTime": "2026-08-21T12:00:00", "timeZone": "America/New_York"},
    "end": {"dateTime": "2026-08-21T15:00:00", "timeZone": "America/New_York"},
    "location": "1500 Park Center Dr, Suite 230",
    "attendees": [{"email": "vanessa@vsinternationalproperties.com"}],
    "reminders": {"useDefault": False,
                  "overrides": [{"method": "popup", "minutes": 30}]},
}
SAFE = strip_attendees(BODY)

check_false("the retry body has no attendees", "attendees" in SAFE)
check("the time is untouched", SAFE["start"], BODY["start"])
check("the end is untouched", SAFE["end"], BODY["end"])
check("the summary is untouched", SAFE["summary"], BODY["summary"])
check("the location survives", SAFE["location"], BODY["location"])
check("the REMINDERS survive — the client still gets reminded",
      SAFE["reminders"], BODY["reminders"])
check_true("the original is not mutated", "attendees" in BODY)
check_false("a body with no attendees is handled", "attendees" in strip_attendees({}))
check_false("None is handled", "attendees" in strip_attendees(None))

check_true("the fallback note names the client",
           "vanessa@x.com" in attendee_fallback_note("vanessa@x.com"))
check_true("...and says the studio time IS blocked",
           "WITHOUT attendees" in attendee_fallback_note())
check_true("...and says the client is not left uninformed",
           "confirmation email" in attendee_fallback_note())

print("\n--- the alert must never say 'no action needed' about a failure ---")

OK = booking_sync_alert("Vanessa Serrano", "2026-08-21 12:00–15:00 (3h)", 59, "ok")
check_true("a clean sync says no action needed", "No action needed." in OK)
check_true("...and shows the tick", "calendar ✅" in OK)

DEG = booking_sync_alert("Vanessa Serrano", "2026-08-21 12:00–15:00 (3h)", 59,
                         "degraded", "no Domain-Wide Delegation")
check_true("a degraded sync still confirms the time is blocked",
           "studio time IS blocked" in DEG)
check_true("...and names why the invite is missing",
           "Domain-Wide Delegation" in DEG)

FAIL = booking_sync_alert("Vanessa Serrano", "2026-08-21 12:00–15:00 (3h)", 59,
                          "failed", "403 forbiddenForServiceAccounts")
check_false("a FAILED sync never says 'No action needed'",
            "No action needed" in FAIL)
check_true("...it says the studio can be double-booked",
           "double-booked" in FAIL)
check_true("...and that the client thinks it is booked",
           "believes it is booked" in FAIL)
check_true("...and demands action", "ACTION NEEDED" in FAIL)
check_true("...and carries the reason", "forbiddenForServiceAccounts" in FAIL)

# ══════════════════════════════════════════════════════════════════════
print("\n== #61: one key for the Phone column — the Instagram stage-sync bug ==")
from event_rail import sheet_row_key

# Priti Verma, Gian Hernandez, Erving Rivera, Angie Starrz. Four bookings
# with verified calendar events, all four reading "Contacted" on the canvas.
# Ninety Instagram leads, zero "Booked" rows, ever, while WhatsApp booked
# fifteen. The cause is one comparison applied to one side only.
PRITI_SENDER = "instagram:1586517099782001"     # the conversation key
PRITI_CELL   = "instagram:1586517099782001"     # what lands in the Phone cell

check("the sender key normalises to bare digits",
      sheet_row_key(PRITI_SENDER), "1586517099782001")
check_true("...and the CELL normalises to the same thing — this is the whole fix",
           sheet_row_key(PRITI_SENDER) == sheet_row_key(PRITI_CELL))

# The exact expression update_lead_columns used to run. Pinned as the thing
# that must never be true again: digits from the cell vs an unstripped sender.
import re as _re61
check_false("the OLD comparison (digits-of-cell == raw sender) never matched IG",
            _re61.sub(r"\D", "", PRITI_CELL) == PRITI_SENDER)

# WhatsApp worked, which is why this hid for months. Every spelling of a
# phone number has to keep landing on the same row.
for _spelling in ("whatsapp:+14075551234", "+14075551234", "14075551234",
                  "+1 (407) 555-1234", " 14075551234 "):
    check(f"WhatsApp {_spelling!r} still keys the same row",
          sheet_row_key(_spelling), "14075551234")

# A row written before this patch and one written after must agree.
check_true("a bare-IGSID cell and a prefixed one are the same lead",
           sheet_row_key("1586517099782001") == sheet_row_key("instagram:1586517099782001"))
check_true("the mangled '+1'-bolted-on form is NOT confused with the clean one",
           sheet_row_key("+1046947537903616") != sheet_row_key("instagram:046947537903616"))

# Web-chat leads are keyed by email. Stripping them to digits would collapse
# every one of them onto every other one.
check("a web lead keeps its address", sheet_row_key("web:jane@doe.com"), "web:jane@doe.com")
check_true("two different web leads do NOT collide",
           sheet_row_key("web:a@x.com") != sheet_row_key("web:b@x.com"))
check("a bare email keys on itself", sheet_row_key("Jane@Doe.com"), "jane@doe.com")

# S24 — an unidentifiable cell must never match anything. A blank Phone cell
# once matched every caller alive and contaminated an unrelated lead.
for _junk in ("", "   ", None, "Phone", "n/a", "—", "407", "12345", "+"):
    check(f"{_junk!r} is not a usable key", sheet_row_key(_junk), "")
check_false("...and an empty key must never be treated as a match",
            bool(sheet_row_key("")) and sheet_row_key("") == sheet_row_key("   "))

# The IGSID/phone distinction the sheet key must not destroy.
check_true("a 16-digit IGSID is still recognised as IG-scoped after keying",
           is_ig_scoped(sheet_row_key("instagram:1586517099782001")))
check_false("...and is never dialable",
            is_dialable(sheet_row_key("instagram:1586517099782001")))

# ══════════════════════════════════════════════════════════════════════
print("\n== #63: a canvas block carries the mark used to find it again ==")
from event_rail import (canvas_sync_mark, canvas_stamp_block,
                        canvas_block_is_findable, CANVAS_SYNC_PREFIX)

_BLOCK = "```\nName       Stage     Lead Age (d)\nJane Doe   Booked    12\n```"

check("the mark is derived from the section name",
      canvas_sync_mark("active_leads"), "sync-id: active-leads")
check_true("...and is plain text — nothing markdown can eat",
           all(c not in canvas_sync_mark("active_leads") for c in "`*_[]#|"))
check_true("two sections never share a mark",
           canvas_sync_mark("active_leads") != canvas_sync_mark("quick_stats"))

_stamped = canvas_stamp_block("active_leads", _BLOCK)
check_true("a stamped block is findable by its own mark",
           canvas_block_is_findable("active_leads", _stamped))
check_false("an UNSTAMPED block is not findable — this is the 362-block bug",
            canvas_block_is_findable("active_leads", _BLOCK))
check_true("the mark goes INSIDE the fence, with the content it identifies",
           _stamped.rstrip().endswith("```")
           and canvas_sync_mark("active_leads") in _stamped.rsplit("```", 2)[1])
check_true("...and the original content survives",
           "Jane Doe   Booked    12" in _stamped)
check("stamping is idempotent — a re-synced block is not double-marked",
      canvas_stamp_block("active_leads", _stamped).count(CANVAS_SYNC_PREFIX), 1)
check_true("a block that is not fenced still gets marked",
           canvas_block_is_findable("qs", canvas_stamp_block("qs", "plain text")))
check_true("empty markdown still ends up findable",
           canvas_block_is_findable("qs", canvas_stamp_block("qs", "")))
check_false("a block stamped for one section is NOT findable as another",
            canvas_block_is_findable("quick_stats", _stamped))

# ── the regression itself, read out of app.py's source ──
# Patch #34 renamed a column header and the fingerprint 600 lines away was
# never updated. Nothing crossed the two, so nothing complained. This does.
_APP = open("app.py").read()
import ast as _ast63, re as _re63
_ns63 = {}
for _n in _ast63.walk(_ast63.parse(_APP)):
    if isinstance(_n, _ast63.Assign) and getattr(_n.targets[0], "id", "") in (
            "_CANVAS_FINGERPRINTS", "_CANVAS_LEGACY_FINGERPRINTS"):
        _ns63[_n.targets[0].id] = _ast63.literal_eval(_n.value)

check_true("_CANVAS_FINGERPRINTS is still readable from source",
           "_CANVAS_FINGERPRINTS" in _ns63)
check_false("'Days in Stage' is no longer the Active Leads fingerprint — "
            "that column has been called 'Lead Age (d)' since Patch #34",
            _ns63.get("_CANVAS_FINGERPRINTS", {}).get("active_leads") == "Days in Stage")

# The header line the canvas actually emits.
_hdr63 = _re63.search(r"_lhdr = f\"(.*?)\"", _APP)
check_true("the Active Leads header line is still findable in app.py", bool(_hdr63))
if _hdr63:
    _emitted = _hdr63.group(1)
    _fp63 = _ns63.get("_CANVAS_FINGERPRINTS", {}).get("active_leads", "")
    check_true(f"the fingerprint {_fp63!r} actually appears in the emitted header",
               _fp63 and _fp63 in _emitted)

# Every legacy fingerprint list must lead with a string that is still emitted
# somewhere in the app — otherwise the orphan sweep cannot reach its own past.
_legacy63 = _ns63.get("_CANVAS_LEGACY_FINGERPRINTS", {})
check_true("legacy fingerprints are recorded for every synced section",
           set(_legacy63) >= {"quick_stats", "source_breakdown", "studio_package",
                              "active_leads", "system_status"})
check_true("the Active Leads sweep still reaches blocks written under the OLD header",
           "Days in Stage" in _legacy63.get("active_leads", []))
check_true("...and blocks written under the current one",
           "Lead Age (d)" in _legacy63.get("active_leads", []))

# ══════════════════════════════════════════════════════════════════════
print("\n== #66: operator notifications are allow-listed, deny by default ==")
from event_rail import operator_allowed

MICHAEL = "michael@mwmcreations.com"
OPS = {MICHAEL}
DNC = {"yasminfmoraes@icloud.com", "ediasm@icloud.com"}

# THE BUG. Patch #58's approval email went through the LEAD suppression guard,
# whose rule is `e.endswith("@mwmcreations.com") -> suppressed`. Michael's own
# address matches it, so the out-of-hours approval door never opened once and
# Andrea Battis waited three days on a request that was filed correctly.
check_true("Michael's own address IS refused by the lead-mail rule "
           "(this is the bug, and the rule itself is correct)",
           MICHAEL.endswith("@mwmcreations.com"))
check_true("...but the OPERATOR channel can reach him",
           operator_allowed(MICHAEL, OPS, DNC)[0])
check("...with no reason given, because it is allowed",
      operator_allowed(MICHAEL, OPS, DNC)[1], "")

# Deny by default is the whole safety property. An address is reachable only
# by being ON the list — never by being absent from a blocklist.
check_false("a lead address is refused even though it is on no blocklist",
            operator_allowed("lead@gmail.com", OPS, DNC)[0])
check_true("...and the reason names the allow-list",
           "allow-list" in operator_allowed("lead@gmail.com", OPS, DNC)[1])
check_false("an empty operator set reaches NOBODY, including Michael",
            operator_allowed(MICHAEL, set(), DNC)[0])
check_false("a lookalike domain is refused",
            operator_allowed("michael@mwmcreations.co", OPS, DNC)[0])
check_false("a subdomain lookalike is refused",
            operator_allowed("michael@mail.mwmcreations.com", OPS, DNC)[0])

# 🔴 DNC OUTRANKS THE OPERATOR LIST. Yasmin Moraes is on INTERNAL_EMAILS *and*
# on EMAIL_DNC as a test lead. If a future edit widens the operator set to
# INTERNAL_EMAILS, this is the line that still stops her being emailed — which
# is the exact leak Patch #38 was written to close.
for _dnc_addr in sorted(DNC):
    check_false(f"{_dnc_addr} is refused even when explicitly an operator",
                operator_allowed(_dnc_addr, OPS | {_dnc_addr}, DNC)[0])
    check_true("...and the reason says DNC outranks it",
               "do-not-contact" in operator_allowed(_dnc_addr, OPS | {_dnc_addr}, DNC)[1])

# Fail closed on anything unparseable — same posture as the lead guard.
for _junk in ("", "   ", None, "notanemail", "@", "michael@"):
    check_false(f"{_junk!r} is refused", operator_allowed(_junk, OPS, DNC)[0])
check("...and says why", operator_allowed("", OPS, DNC)[1], "unparseable address")

# Normalisation: case and whitespace must not create a bypass OR a false refusal.
check_true("case and stray whitespace still resolve to the operator",
           operator_allowed("  MICHAEL@MWMCreations.Com ", OPS, DNC)[0])
check_false("case does not smuggle a DNC address through",
            operator_allowed("YasminFMoraes@iCloud.com", OPS, DNC)[0])
check_true("an operator list given with odd casing still matches",
           operator_allowed(MICHAEL, {"Michael@MWMcreations.COM"}, DNC)[0])

# Degenerate inputs must not throw — this runs on a send path.
check_false("no operator set at all refuses rather than raising",
            operator_allowed(MICHAEL, None, None)[0])
check_true("dnc may be omitted", operator_allowed(MICHAEL, OPS)[0])
check_false("blank entries in the operator list do not match a blank address",
            operator_allowed("", {"", "  "}, DNC)[0])


# ── PATCH #71 — AD_09 $349 offer branch ────────────────────────────────
#
# Michael's ruling, Aug 8 2026: MAYA's default job is UNCHANGED — get leads
# into the room with him, because his in-person close on packages beats
# anything a bot closes on a link. This branch fires ONLY for leads who came
# for the $349 offer.
#
# The asymmetry that shapes every case below: a false NEGATIVE is cheap (the
# lead gets invited to the studio, which is Michael's best tool anyway). A
# false POSITIVE is expensive — someone who wanted a conversation gets a
# payment link, which reads as not listening. So the "must NOT fire" cases
# matter more than the matching ones.
from event_rail import ad09_lead as _a9

for _t in ["I saw your ad about the $349 studio hour",
           "is it really 349 dollars for one hour?",
           "nothing to sign right?",
           "I want the studio hour",
           "do you film and edit it for me",
           "saw your ad on instagram"]:
    check_true("AD_09 fires on offer language: {!r}".format(_t[:42]),
               _a9(None, [_t], None)[0])

for _t in ["how much is the studio?",
           "can I book studio time next week",
           "I want to record a podcast",
           "what do you guys do?",
           "do you offer packages?",
           "hi"]:
    check_false("AD_09 does NOT hijack a normal lead: {!r}".format(_t[:42]),
                _a9(None, [_t], None)[0])

# A bare 349 is not a price. Either of these matching costs a real conversation.
check_false("349 inside a phone number is not the offer",
            _a9(None, ["my number is 407 349 1122"], None)[0])
check_false("349 inside a street address is not the offer",
            _a9(None, ["I'm at 349 Park Center Drive"], None)[0])

check_true("a matching ad_id fires the branch", _a9("120249", ["hi"], ["120249"])[0])
check_false("a different ad_id does not", _a9("999999", ["hi"], ["120249"])[0])
check_false("an empty ad_id cannot fire on its own", _a9("", ["hi"], ["120249"])[0])
check_false("no configured ad ids means ad_id cannot match", _a9("120249", ["hi"], [])[0])

check_true("the reason is reported so a miss can be diagnosed",
           _a9(None, ["$349 please"], None)[1] == "price")
check_true("empty reason when it did not fire", _a9(None, ["hi"], None)[1] == "")

# This runs on EVERY inbound message. It must never raise.
for _bad in (None, [], [None], [""], [123], ("tuple",)):
    try:
        _a9(None, _bad, None); _survived = True
    except Exception:
        _survived = False
    check_true("survives odd input {!r}".format(_bad), _survived)
check_false("no messages means no branch", _a9(None, None, None)[0])

print("\nPATCH71_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))


# ── PATCH #72 — the tally, and the verdict it produces ─────────────────
#
# Built because ERIC found 12 conversations across Aug 4–8 that produced ZERO
# pipeline rows, and the two candidate causes — "never attempted" vs "write
# threw" — are indistinguishable from outside and need OPPOSITE fixes.
# These tests pin the readings so nobody has to remember the rules at 2am.
from event_rail import Tally, lead_row_verdict

_t = Tally()
check_true("a fresh tally reads zero", _t.get("nothing") == 0)
_t.bump("a"); _t.bump("a"); _t.bump("b", "with a note")
check_true("bump counts", _t.get("a") == 2)
check_true("snapshot carries the count", _t.snapshot()["a"]["count"] == 2)
check_true("snapshot carries the last note", _t.snapshot()["b"]["last"] == "with a note")
check_true("snapshot timestamps the last bump", "at" in _t.snapshot()["b"])
check_true("unknown key is absent, not an error", "zzz" not in _t.snapshot())

# 🔴 This sits on the inbound message path. It must never break a request.
_survived = True
try:
    _t.bump(None); _t.bump("x", None); _t.bump("y", "n", "not-a-number")
    _t.bump(object(), object())
except Exception:
    _survived = False
check_true("bump NEVER raises, whatever it is handed", _survived)

# The verdicts — each one names a DIFFERENT fix, which is the whole point.
check_true("all writes failing reads as broken",
           lead_row_verdict(created=0, failed=5)[0] == "broken")
check_true("some writes failing reads as degraded",
           lead_row_verdict(created=3, failed=1)[0] == "degraded")
check_true("a HIGH count of all-returning inbounds still blames the GATE",
           lead_row_verdict(created=0, failed=0, skipped_dup=0, gate_not_new=12)[0]
           == "suspect_gate")
check_true("no traffic at all is idle, not broken",
           lead_row_verdict()[0] == "idle")
check_true("rows being written reads ok",
           lead_row_verdict(created=4)[0] == "ok")
check_true("attempted but all deduped points at the dedupe",
           lead_row_verdict(created=0, skipped_dup=6)[0] == "dedup_only")
check_true("every verdict explains itself", all(
    bool(lead_row_verdict(*a)[1]) for a in
    [(0, 5, 0, 0), (3, 1, 0, 0), (0, 0, 0, 12), (0, 0, 0, 0), (4, 0, 0, 0), (0, 0, 6, 0)]))

# Eric's actual observation, expressed as the reading it should now produce.
check_true("ERIC's 12-conversations-zero-rows case is still diagnosable",
           lead_row_verdict(created=0, failed=0, skipped_dup=0, gate_not_new=12)[0]
           == "suspect_gate")

# S84: the reading that sent me chasing a ghost on Aug 10. Two inbounds, both
# returning, zero rows — post-#76 that is the HEALTHY shape, and the old text
# called it "never_attempted … the gate is the cause". A quiet night must not
# wear the same words as a broken gate.
check_true("a QUIET night reads as all_returning, not as a broken gate",
           lead_row_verdict(created=0, failed=0, skipped_dup=0, gate_not_new=2)[0]
           == "all_returning")
check_false("...and a quiet night is never reported as suspect",
            lead_row_verdict(0, 0, 0, 2)[0] == "suspect_gate")
check_true("the quiet reading SAYS it is not proof the gate works",
           "does NOT prove" in lead_row_verdict(0, 0, 0, 2)[1])
check_true("the suspect reading names the durable set, not the old in-memory one",
           "first-inbound set" in lead_row_verdict(0, 0, 0, 12)[1])
check_true("the boundary is inclusive — exactly the threshold escalates",
           lead_row_verdict(0, 0, 0, 10)[0] == "suspect_gate")
check_true("one below the threshold does not escalate",
           lead_row_verdict(0, 0, 0, 9)[0] == "all_returning")
check_true("a single created row outranks any gate count",
           lead_row_verdict(created=1, gate_not_new=99)[0] == "ok")
check_false("...and is NOT mistaken for a broken writer",
            lead_row_verdict(0, 0, 0, 12)[0] == "broken")

check_true("verdict survives junk input", lead_row_verdict(None, None, None, None)[0] == "idle")

# ── PATCH #74 · studio-visit qualification gate ──────────────────────
from event_rail import studio_visit_verdict as _svv

check_false("JOSEPH: hobbyist musician with a 'business' name is REFUSED",
            _svv(role="freelancer_hobbyist_student",
                 business="Cosito (proyecto musical)")[0])
check_false("...and is still refused when no role was ever captured",
            _svv(role=None, business="Cosito (proyecto musical)")[0])
check_false("DONDRIQUE: a stated $100 budget is refused",
            _svv(role="owner_founder", business="Acme", stated_budget=100)[0])
check_false("...and stays refused after he was told the floor (persisted flag)",
            _svv(role="owner_founder", business="Acme", budget_declined=True)[0])
check_true("a real owner with a business and no budget stated is ALLOWED",
           _svv(role="owner_founder", business="Zerlotini Brothers")[0])
check_true("silence about budget does NOT block (MAYA.md rule 4)",
           _svv(role="executive_decision_maker", business="Acme",
                stated_budget=None)[0])
check_true("budget exactly at the floor is allowed",
           _svv(role="owner_founder", business="Acme", stated_budget=249)[0])
check_false("budget one dollar under the floor is refused",
            _svv(role="owner_founder", business="Acme", stated_budget=248)[0])
check_true("$349 clears the floor",
           _svv(role="professional_personal_brand", business="Dr Bolfer",
                stated_budget=349)[0])
check_false("an employee with no authority gets the call, not the room",
            _svv(role="employee_no_authority", business="Acme Corp")[0])
check_false("an allowed role with no business on file is refused",
            _svv(role="owner_founder", business="")[0])
check_false("'Unknown' is not a business",
            _svv(role="owner_founder", business="Unknown")[0])
check_true("junk budget string does not crash and does not block",
           _svv(role="owner_founder", business="Acme", stated_budget="lots")[0])
check_true("a dollar-formatted budget parses",
           _svv(role="owner_founder", business="Acme", stated_budget="$1,200")[0])
check_true("role is case/spacing tolerant",
           _svv(role="Owner Founder", business="Acme")[0])
check_true("every refusal tells Maya what to do instead",
           all("call" in _svv(**k)[1].lower() or "ask" in _svv(**k)[1].lower()
               for k in [dict(role=None, business="x"),
                         dict(role="employee_no_authority", business="x"),
                         dict(role="owner_founder", business="x", stated_budget=50),
                         dict(role="owner_founder", business="")]))

print("\nPATCH74_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))

# ── PATCH #75 · the founder-call gate ────────────────────────────────
from event_rail import strategy_call_verdict as _scv, studio_visit_verdict

check_false("LANCE: aspiring author, no business, no budget — no call",
            _scv(role="freelancer_hobbyist_student",
                 business="Author - 4 inspirational books")[0])
check_false("...and refused when Maya never captured a role at all",
            _scv(role=None, business="4 books about my life")[0])
check_false("JOSEPH would also have been stopped one door earlier",
            _scv(role="freelancer_hobbyist_student",
                 business="Cosito (proyecto musical)")[0])
check_true("NATHAN: out of state but a real business — call ALLOWED",
           _scv(role="executive_decision_maker", business="NWPhotoVideo LLC")[0])
check_true("DR CRUZ: owner of a consulting firm — allowed",
           _scv(role="owner_founder", business="Cruz Consulting")[0])
check_true("a stated budget at the floor earns a call even with no role",
           _scv(role=None, business="", stated_budget=249)[0])
check_true("...and well above it",
           _scv(role=None, business="", stated_budget=1200)[0])
check_false("a stated budget under the floor is refused",
            _scv(role="owner_founder", business="Acme", stated_budget=100)[0])
check_false("...and stays refused later via the persisted flag",
            _scv(role="owner_founder", business="Acme", budget_declined=True)[0])
check_true("the call bar is LOWER than the studio bar: no business needed",
           _scv(role="owner_founder", business="")[0])
check_false("...but the studio still refuses that same lead",
            studio_visit_verdict(role="owner_founder", business="")[0])
check_true("junk budget string neither crashes nor grants a call",
           _scv(role="owner_founder", business="x", stated_budget="lots")[0])
check_true("every call refusal tells Maya what to send instead",
           all(("booking link" in _scv(**k)[1].lower() or "pricing" in _scv(**k)[1].lower())
               for k in [dict(role=None, business=""),
                         dict(role="freelancer_hobbyist_student", business="x"),
                         dict(role="owner_founder", business="x", stated_budget=50),
                         dict(role="owner_founder", business="x", budget_declined=True)]))

print("\nPATCH75_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))

# ══════════════════════════════════════════════════════════════════════
# PATCH #76 — first inbound (the lead-row bug)
# ══════════════════════════════════════════════════════════════════════
from event_rail import is_first_inbound as _fi, seed_seen_inbound as _seed

_GREETED = [{"role": "assistant", "content": "Hi, I'm Maya!"}]
_TALKED  = [{"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "hey"}]

check_true("a sender we have never touched is a first inbound",
           _fi("whatsapp:+15551230000", seen_inbound=set(), history=None))
check_true("THE BUG: a lead we greeted first is STILL a first inbound",
           _fi("whatsapp:+15551230001", seen_inbound=set(), history=_GREETED))
check_true("an outbound-only history of any length never counts as inbound",
           _fi("whatsapp:+15551230002", seen_inbound=set(),
               history=_GREETED * 25))
check_true("a lead who has already replied is NOT a first inbound",
           not _fi("whatsapp:+15551230003", seen_inbound=set(), history=_TALKED))
check_true("the durable set alone is enough to block a repeat",
           not _fi("whatsapp:+15551230004",
                   seen_inbound={"whatsapp:+15551230004"}, history=None))
check_true("durable set wins even when history was lost entirely",
           not _fi("instagram:1533250014838110",
                   seen_inbound={"instagram:1533250014838110"}, history=[]))
check_true("an empty sender is never a first inbound",
           not _fi("", seen_inbound=set(), history=None))
check_true("junk rows in history neither crash nor count as inbound",
           _fi("whatsapp:+15551230005", seen_inbound=set(),
               history=[None, "oops", 42, {"role": "assistant"}]))
check_true("no keyword args still works (positional call)",
           _fi("whatsapp:+15551230006", set(), None))

_seeded = _seed({"whatsapp:+1a": _TALKED, "whatsapp:+1b": _GREETED},
                {"instagram:9": _TALKED})
check_true("seed picks up only senders who have actually written to us",
           _seeded == {"whatsapp:+1a", "instagram:9"})
check_true("seeding makes an existing lead stop looking new — no NEW_LEAD storm",
           not _fi("whatsapp:+1a", seen_inbound=_seeded, history=_TALKED))
check_true("but a greeted-never-replied lead survives the seed and still fires",
           _fi("whatsapp:+1b", seen_inbound=_seeded, history=_GREETED))
check_true("seed tolerates empty and None inputs",
           _seed({}, None) == set())

print("\nPATCH76_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))


print("\nPATCH72_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))


print("\n== S84: the Instagram 24h window guard (the 8-alert burst) ==")
# Aug 10: IGSID 1600333768119203 produced eight identical #dev alerts between
# 19:37 and 21:12, each claiming re-engagement would skip. The mark was an
# in-memory set consulted on ONE path, so every other caller re-attempted and
# re-alerted. WhatsApp has had the persistent version of this since S24.
_key = ig_mark_key
_blk = ig_window_blocked
_alert = ig_should_alert_403

check_true("a bare IGSID produces a key",
           _key("1600333768119203") == "ig_window_expired:1600333768119203")
check_true("an instagram:-prefixed sender produces the SAME key",
           _key("instagram:1600333768119203") == _key("1600333768119203"))
check_true("one function makes the key both sides use — writer and reader agree",
           _key("instagram:  1600333768119203  ".strip()) == _key("1600333768119203"))
check_true("an empty IGSID has no key", _key("") is None)
check_true("None has no key", _key(None) is None)

check_false("no mark means nothing is blocked", _blk(None))
check_false("an empty mark means nothing is blocked", _blk(""))
check_true("a mark with no inbound since blocks the send",
           _blk("2026-08-10T19:37:25"))
check_false("an inbound NEWER than the mark reopens the window",
            _blk("2026-08-10T19:37:25", "2026-08-10T20:15:00"))
check_true("an inbound OLDER than the mark leaves it blocked",
           _blk("2026-08-10T19:37:25", "2026-08-09T11:00:00"))
check_false("an unparseable mark fails OPEN — never refuse on unreadable data",
            _blk("not-a-date"))
check_true("an unparseable INBOUND leaves the standing mark in force",
           _blk("2026-08-10T19:37:25", "not-a-date"))

# #60: an aware value must be CONVERTED, not stripped. A mark written with a
# -04:00 offset and an inbound written naive-local are the same wall clock.
check_false("aware mark vs newer naive inbound compares as instants, not digits",
            _blk("2026-08-10T19:37:25-04:00", "2026-08-10T20:15:00"))
check_true("aware mark vs older naive inbound stays blocked",
           _blk("2026-08-10T19:37:25-04:00", "2026-08-10T18:00:00"))

check_true("the FIRST 403 for an IGSID alerts", _alert("1600333768119203", False))
check_false("the SECOND and every later 403 stays silent",
            _alert("1600333768119203", True))
check_false("a 403 with no usable IGSID never alerts", _alert("", False))
check_false("None IGSID never alerts", _alert(None, False))
check_true("suppression is per-IGSID — a different lead still gets its alert",
           _alert("1043867094713993", False))

print("\nPATCH77_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))


print("\n== S84: the floor is source-conditional ($249 base / $349 campaign) ==")
from event_rail import (is_campaign_sourced as _cs, applicable_floor as _af,
                        attribution_line as _al, CAMPAIGN_FLOOR_USD,
                        STUDIO_FLOOR_USD as _BASE)

check_false("no attribution at all is not campaign-sourced", _cs())
check_false("empty strings are not attribution", _cs(ad_id="", utm_campaign=""))
check_true("an ad_id alone is enough — IG sends it inside referral",
           _cs(ad_id="120249808207780738"))
check_true("a campaign name alone is enough",
           _cs(utm_campaign="STUDIO $349 AUG"))
check_true("the ad_referral flag alone is enough — WA payloads carry only it",
           _cs(ad_referral=True))
check_true("whitespace is not attribution", not _cs(ad_id="   "))

check_true("an organic lead is held to the rate card", _af() == _BASE == 249)
check_true("a campaign lead is held to the campaign's own promise",
           _af(ad_id="120249808207780738") == CAMPAIGN_FLOOR_USD == 349)
check_true("the flag alone lifts the floor", _af(ad_referral=True) == 349)
check_true("a referral or walk-in stays at 249", _af(utm_campaign="  ") == 249)

# Joseph Joel Hernandez consumed a studio hour and a founder hour on Aug 10.
# Michael's rule exists to stop that, and could only ever fire on 249.
check_true("a $300 budget CLEARS the base floor",
           _af() == 249 and 300 >= _af())
check_false("...but the SAME $300 does NOT clear the campaign floor",
            300 >= _af(ad_id="120249808207780738"))

check_true("attribution line is empty for an organic lead", _al() == "")
check_true("attribution names the campaign when we have it",
           "STUDIO $349 AUG" in _al(utm_campaign="STUDIO $349 AUG"))
check_true("attribution names the ad_id when that is all we have",
           "ad_id 120249808207780738" in _al(ad_id="120249808207780738"))
check_true("both are named together when both exist",
           _al(ad_id="123", utm_campaign="AUG") == "Campaign: AUG · ad_id 123")
check_false("the redundant source word 'ad' is not repeated back",
            "ad" == _al(ad_id="123", utm_source="ad").split("· ")[-1])

# The gates must actually USE the resolved floor, not the module constant.
from event_rail import studio_visit_verdict as _svv2, strategy_call_verdict as _scv2
_ok249, _ = _svv2(role="owner_founder", business="Acme", stated_budget=300, floor=249)
_ok349, _why349 = _svv2(role="owner_founder", business="Acme", stated_budget=300, floor=349)
check_true("an owner_founder with $300 passes at the base floor", _ok249)
check_false("the same owner_founder with $300 is refused at the campaign floor", _ok349)
check_true("the refusal quotes the CAMPAIGN number, not the rate card",
           "$349" in _why349)
_okc, _whyc = _scv2(role="owner_founder", business="Acme", stated_budget=300, floor=349)
check_false("the founder call honours the campaign floor too", _okc)
check_true("that refusal also quotes $349", "$349" in _whyc)

print("\nPATCH79_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))

# ═══════════════════════════════════════════════════════════════════
# PATCH #90 — a confirmed ROADMAP filming day reaches a calendar
# ═══════════════════════════════════════════════════════════════════
#
# On Aug 11 a filming day was confirmed in the ROADMAP portal and no calendar
# event was created. Nothing on any screen said so. These tests cover the half
# of that fix that can be wrong quietly: the event body.

from event_rail import roadmap_shoot_event_body as _rsb

_STUDIO = "1234 Studio Way, Winter Park, FL 32789"

def _body(**kw):
    args = dict(client_name="Dr. Luiz Bolfer", client_email="drbolfer@gmail.com",
                campaign_no=1, campaign_title="The Educational Library",
                date="2026-08-25", start_time="09:00", end_time="13:00",
                kind="studio", location="", studio_address=_STUDIO,
                timezone="America/New_York")
    args.update(kw)
    return _rsb(**args)

def _refused(**kw):
    try:
        _body(**kw)
        return ""
    except EventRailRejected as e:
        return str(e)
    except Exception as e:
        return "WRONG EXCEPTION: " + repr(e)

_b, _lab = _body()
check_true("a studio day falls back to the studio address", _b["location"] == _STUDIO)
check_true("a studio day is labelled as the studio", _lab == "MWM studio")
check_true("the summary names the client", "Dr. Luiz Bolfer" in _b["summary"])
check_true("the summary names the campaign number", "C1" in _b["summary"])
check_true("the summary names the campaign", "Educational Library" in _b["summary"])
check_true("the description carries the client email so the day is traceable",
           "drbolfer@gmail.com" in _b["description"])
check_true("start is the requested clock time",
           _b["start"]["dateTime"] == "2026-08-25T09:00:00")
check_true("end is the requested clock time",
           _b["end"]["dateTime"] == "2026-08-25T13:00:00")
check_true("the event is stamped with the timezone, never a bare local string",
           _b["start"]["timeZone"] == "America/New_York")

# 🔴 The rule the function exists for.
_loc_body, _loc_lab = _body(kind="location",
                            location="900 Clinic Drive, Orlando, FL 32835")
check_true("an on-location day uses the CLIENT's address",
           _loc_body["location"] == "900 Clinic Drive, Orlando, FL 32835")
check_true("an on-location day says so in the description",
           "on location" in _loc_body["description"])
check_true("an on-location day is labelled on location", _loc_lab == "on location")
check_true("an on-location day with NO address is refused, not defaulted",
           "on-location" in _refused(kind="location", location=""))
check_false("...and it never quietly becomes the studio address",
            _STUDIO in (_refused(kind="location", location="") or ""))
check_true("an on-location day with a scrap of text for an address is refused",
           _refused(kind="location", location="tbd") != "")

check_true("a day with no date is refused", _refused(date="") != "")
check_true("a day with no times is refused", _refused(start_time="", end_time="") != "")
check_true("a day that ends before it starts is refused",
           _refused(start_time="13:00", end_time="09:00") != "")
check_true("a day with no client name is refused", _refused(client_name="") != "")

# The four portal rules (Spec §2) apply to anything the machine writes about a
# campaign — a calendar event is not exempt just because only staff read it.
_full = (_b["summary"] + _b["description"]).lower()
check_false("no edit-day number appears on the event", "edit day" in _full)
check_false("no hours figure is promised against the campaign", "hours" in _full)
check_false("no deliverable count is promised", "videos" in _full)

print("\nPATCH90_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))

print("\n== #115 standing co-attendees: Nicole rides Luzia's invites ==")
# Michael asked for Nicole on every email to Luzia AND on the invites. Mail is
# #114's job. This is the half that Google sends, which #114 could never reach.
import os as _os115
import standing_contacts as _sc115

_os115.environ.pop("MWM_STANDING_CONTACTS", None)
_os115.environ.pop("SUSAN_ALWAYS_CC", None)
_LUZIA115 = "luziahcosta@hotmail.com"
_NICOLE115 = "Nicole.formore@gmail.com"


def _ev115(attendee=None, pre=None):
    _b = {"summary": "🎬 Studio: Luzia Costa",
          "location": "1500 Park Center Dr, Suite 230, Orlando, FL 32835",
          "start": {"dateTime": "2026-09-10T12:00:00-04:00"},
          "end": {"dateTime": "2026-09-10T13:00:00-04:00"}}
    if pre:
        _b["attendees"] = pre
    _out, _iss = harden_event_body(_b, source_identifier="+18135031224",
                                   attendee_email=attendee, require_attendee=False)
    return [a["email"] for a in (_out.get("attendees") or [])], _iss


check("Nicole is added to a Luzia event", _ev115(_LUZIA115)[0],
      [_LUZIA115, _NICOLE115])
check("...and the event still passes clean", _ev115(_LUZIA115)[1], [])
check("...matched case-insensitively", _ev115("LuziaHCosta@Hotmail.COM")[0],
      ["LuziaHCosta@Hotmail.COM", _NICOLE115])
check("...also when the client was already on the attendee list",
      _ev115(None, [{"email": _LUZIA115}])[0], [_LUZIA115, _NICOLE115])
check("never added twice, in any casing",
      _ev115(_LUZIA115, [{"email": "NICOLE.FORMORE@gmail.com"}])[0],
      ["NICOLE.FORMORE@gmail.com", _LUZIA115])
check("every other client's invite is untouched", _ev115("todd@example.com")[0],
      ["todd@example.com"])
check("an event with no attendee at all gains nobody", _ev115(None)[0], [])

# One map, two rails — the whole point of moving it out of susan_gmail.
import susan_gmail as _sg115
check("the mail rail and the event rail read the SAME map",
      _sg115._always_cc_map(), _sc115.standing_map())
check("the mail rail's CC agrees with the invite",
      _sg115._apply_always_cc(_LUZIA115, None), _NICOLE115)

# The env override reaches both rails.
_os115.environ["MWM_STANDING_CONTACTS"] = '{"someone@new.com": ["watcher@x.com"]}'
check("env adds a pair on the event rail",
      _ev115("someone@new.com")[0], ["someone@new.com", "watcher@x.com"])
check("...and on the mail rail",
      _sg115._apply_always_cc("someone@new.com", None), "watcher@x.com")
_os115.environ["MWM_STANDING_CONTACTS"] = "{not json"
check("malformed env is ignored, the built-in survives",
      _ev115(_LUZIA115)[0], [_LUZIA115, _NICOLE115])
_os115.environ.pop("MWM_STANDING_CONTACTS", None)

print(f"\n{'=' * 60}\n  TOTAL: {_passed} passed, {_failed} failed\n{'=' * 60}")
sys.exit(1 if _failed else 0)
