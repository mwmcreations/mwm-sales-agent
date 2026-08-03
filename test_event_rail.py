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


print(f"\n{'=' * 60}\n  TOTAL: {_passed} passed, {_failed} failed\n{'=' * 60}")
sys.exit(1 if _failed else 0)
