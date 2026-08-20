#!/usr/bin/env python3
"""test_patch104.py — Patch #104. Do not delete a booking you have not replaced.

TWO defects, both in book_appointment's "auto-cleanup" block.

(1) ORDER. The block deleted the lead's existing calendar event at the TOP of
    the function — before the race-condition guard, before the capacity guard,
    and before a single insert had been attempted. Four separate paths return
    None after that point. On every one of them the client's confirmed
    appointment was already gone, no replacement was created, Maya told the
    lead "Could not book the appointment. Please try again.", and nothing
    anywhere reported that a real booking had just been destroyed. That is the
    exact shape of the Aug 24 complaint: a studio visit that exists in the
    record and on no calendar.

(2) MATCH. It decided ownership with a raw substring test —
    `lead_name.lower() in (summary + " " + description).lower()` — with no
    minimum length and no field structure. But this system writes that
    description itself: every Maya booking carries "Studio Visit with Michael
    Moraes / MWM Creations Studios", "Lead:", "Business:", "Booked by: Maya";
    every portal booking carries "Client:", "Source: portal". The boilerplate
    was part of the match surface. The events below are REAL — pulled from the
    MWM CREATIONS calendar on Aug 20 2026 — and against them the old matcher
    fired for a lead named "Ed", "Al", "Jo", "Lead" or "Business". "Jo"
    resolved to Jonathan Pineda's PAID Studio Package booking, which the old
    code then deleted with sendUpdates="all" — a cancellation email to a
    client who had done nothing.

The two failure modes are not symmetric. A MISS leaves a duplicate event:
visible on the calendar, fixed in ten seconds. A FALSE HIT destroys a paying
client's booking and emails them about it. Patch #104 errs toward the miss,
and section 6 of this file is what holds that line.

Run: python3 test_patch104.py
"""

import io
import os
import re
import sys

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


# ── load the helpers out of app.py without importing app.py ─────────────────
# app.py wants a database, Google credentials and a Meta token at import time.
# The four helpers under test are pure and need nothing but `re`.
_APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
_SRC = io.open(_APP, encoding="utf-8").read()

# PATCH #106 — _cleanup_phone_matches now consults the event's PRIVATE
# properties before its description, because the phone number stopped being
# published in a field the attendee can read. That is a real dependency, so
# the real function is injected rather than stubbed: a test that mocks the
# lookup would pass while the live matcher failed.
from event_rail import event_lead_facts

_ns = {"re": re, "event_lead_facts": event_lead_facts}
for _fn in ("_cleanup_norm", "_cleanup_identity_strings",
            "_cleanup_name_matches", "_cleanup_phone_matches"):
    _m = re.search(r"^def %s\(.*?(?=^\S)" % re.escape(_fn), _SRC, re.S | re.M)
    assert _m, "%s not found in app.py — did Patch #104 get reverted?" % _fn
    exec(compile(_m.group(0), "app.py", "exec"), _ns)
_cleanup_norm = _ns["_cleanup_norm"]
_cleanup_identity_strings = _ns["_cleanup_identity_strings"]
_cleanup_name_matches = _ns["_cleanup_name_matches"]
_cleanup_phone_matches = _ns["_cleanup_phone_matches"]


# ── the real calendar, Aug 20 2026 ──────────────────────────────────────────
BOLFER = {
    "id": "mm586g36m6ap903adviopl2hgc",
    "summary": "\U0001F7E1 FOLLOW UP — Dr. Luiz Bolfer has not sent a new date",
    "description": ("RSVP-NOTE: Aug 20 2026, 9:00 AM ET — MICHAEL IS HANDLING THIS "
                    "PERSONALLY, BY MESSAGE (not email). Owner: Michael. "
                    "Dr. Bolfer emailed info@mwmcreations.com cancelling..."),
}
PINEDA = {
    "id": "e37blp6mleii49p0sno0k645nk",
    "summary": "\U0001F3AC Studio: Jonathan Pineda (1h)",
    "description": ("Studio Package portal booking #71\n"
                    "Client: Jonathan Pineda (john.pineda@fidelityfl.com)\n"
                    "Notes: Created in wp-admin\n"
                    "Source: portal (auto-synced by machine S12)"),
}
HOLMES = {
    "id": "7osqoca7mojkcevfae65vns2uc",
    "summary": ("Studio Visit — Marc Holmes (In the Driver's Seat with Marc Holmes "
                "(motorsports podcast brand))"),
    "description": ("Studio Visit with Michael Moraes / MWM Creations Studios\n\n"
                    "Lead: Marc Holmes\n"
                    "Business: In the Driver's Seat with Marc Holmes (motorsports podcast brand)\n"
                    "Email: mhholmes2000@gmail.com\n"
                    "Booked by: Maya\n"
                    "Booked via: Website Chat"),
}
SERRANO = {
    "id": "8sg35relqdn5bql03hm4jiq9tc",
    "summary": "\U0001F3AC Studio: Vanessa Serrano (3h)",
    "description": ("Studio Package portal booking #59\n"
                    "Client: Vanessa Serrano (vanessa@vsinternationalproperties.com)\n"
                    "Lead: Vanessa Serrano\n"
                    "Business: VS International Properties\n"
                    "Booked by: Portal (Studio Package)\n"
                    "Booked via: Portal"),
}
PRIME = {
    "id": "uokjoanqe10nbnlmc55d3t2kjk",
    "summary": "Strategy Call — Prime Vacation Orlando (Prime Vacation Orlando)",
    "description": ("Strategy Call with Michael Moraes / MWM Creations\n\n"
                    "Lead: Prime Vacation Orlando\n"
                    "Business: Prime Vacation Orlando\n"
                    "Booked via: Maya (WhatsApp)\n"
                    "Call this number: +14075551212"),
}
EMS = {
    "id": "8chk853903tom1hfb1hans0b6g_20260820T123000Z",
    "summary": "\U0001F3CB️ TREINO EMS Vida Fit",
    "description": "Treino EMS na Vida Fit — TERÇAS e QUINTAS. Vida Fit by Juliane Almeida",
}
CALENDAR = [EMS, BOLFER, PINEDA, SERRANO, HOLMES, PRIME]


def old_matcher(lead_name, ev):
    """Verbatim reproduction of the pre-#104 logic, for contrast."""
    n = (lead_name or "").strip().lower()
    blob = "%s %s" % (ev.get("summary", ""), ev.get("description", ""))
    return bool(n) and n in blob.lower()


def first_hit(lead_name, matcher):
    """app.py breaks on the first match, so only the first one is ever deleted."""
    for ev in CALENDAR:
        if matcher(lead_name, ev):
            return ev["id"]
    return None


print("\n=== 1. the old matcher really did hit unrelated events ===")
print("    (if these stop passing, the fixtures drifted — the bug was real)")
for _name, _victim in [("Ed", BOLFER), ("Al", EMS), ("Jo", PINEDA),
                       ("Lead", SERRANO), ("Business", SERRANO), ("Maya", HOLMES)]:
    check("OLD: a lead named %r would have deleted %r" % (_name, _victim["summary"][:36]),
          first_hit(_name, old_matcher), _victim["id"])

print("\n=== 2. #104 refuses all of them ===")
for _name in ["Ed", "Al", "Jo", "Lead", "Business", "Maya", "Studio", "Michael",
              "Client", "Moraes", "MWM", "Vida", "Prime", "Marc"]:
    check("NEW: %r matches nothing" % _name, first_hit(_name, _cleanup_name_matches), None)

print("\n=== 3. ...and still finds the lead's own booking ===")
check("Marc Holmes finds his own studio visit",
      first_hit("Marc Holmes", _cleanup_name_matches), HOLMES["id"])
check("marc  HOLMES — spacing and case are irrelevant",
      first_hit("marc  HOLMES", _cleanup_name_matches), HOLMES["id"])
check("Vanessa Serrano finds her portal booking",
      first_hit("Vanessa Serrano", _cleanup_name_matches), SERRANO["id"])
check("Jonathan Pineda finds his own booking (Client: line)",
      first_hit("Jonathan Pineda", _cleanup_name_matches), PINEDA["id"])
check("Prime Vacation Orlando — a business as a lead name still resolves",
      first_hit("Prime Vacation Orlando", _cleanup_name_matches), PRIME["id"])

print("\n=== 4. phone is the strong identifier and is checked first ===")
check("full number in the body matches", _cleanup_phone_matches("14075551212", PRIME), True)
check("a different number does not", _cleanup_phone_matches("14079998888", PRIME), False)
check("6 digits is too short to trust", _cleanup_phone_matches("407555", PRIME), False)
check("empty phone never matches", _cleanup_phone_matches("", PRIME), False)
check("phone finds the event even when the name is wrong",
      _cleanup_phone_matches("14075551212", PRIME) and not
      _cleanup_name_matches("Someone Else", PRIME), True)

print("\n=== 5. identity fields, not the whole body ===")
check("Holmes resolves to his name only",
      set(_cleanup_identity_strings(HOLMES)), {"Marc Holmes"})
check("Pineda includes the Client: line",
      "Jonathan Pineda (john.pineda@fidelityfl.com)" in _cleanup_identity_strings(PINEDA), True)
check("a personal note event exposes no Lead:/Client: identity",
      any(s.startswith(("Lead", "Client")) for s in _cleanup_identity_strings(EMS)), False)

print("\n=== 6. a single token is never enough on its own ===")
check("'Holmes' alone does not match Marc Holmes",
      _cleanup_name_matches("Holmes", HOLMES), False)
check("'Marc' alone does not match Marc Holmes",
      _cleanup_name_matches("Marc", HOLMES), False)
check("empty name matches nothing", _cleanup_name_matches("", HOLMES), False)
check("None name matches nothing", _cleanup_name_matches(None, HOLMES), False)
check("whitespace-only name matches nothing", _cleanup_name_matches("   ", HOLMES), False)


print("\n=== 7. ORDER: the delete must come after the insert ===")
# A static read of app.py. The whole point of #104 is WHERE the delete call
# sits relative to `if not created:` — no unit test of the helpers can see
# that, and it is the half of the defect that actually cost a booking.
_bk = _SRC.index("def book_appointment(slot_id")
_end = _SRC.index("\ndef ", _bk + 10)
_body = _SRC[_bk:_end]
_scan_ends = _body.index("if appointment_type ==")
check("exactly one delete call in book_appointment",
      _body.count("service.events().delete("), 1)
check("nothing is deleted during the scan",
      "service.events().delete(" in _body[:_scan_ends], False)
check("delete happens AFTER insert",
      _body.index("service.events().delete(") > _body.index("service.events().insert("), True)
check("delete happens AFTER the `if not created` bail-out",
      _body.index("service.events().delete(") > _body.index("if not created:"), True)

print("\n=== 8. every early return says the old booking survived ===")
check("three bail-outs log the kept event (race, capacity, all-attempts-failed)",
      _body.count("PATCH #104: kept existing event"), 3)
check("capacity guard excludes the held event",
      'exclude_event_id=(_stale["id"] if _stale else None)' in _body, True)
check("race guard excludes the held event",
      'not (_stale and ev.get("id") == _stale["id"])' in _body, True)
check("a failed delete is reported rather than swallowed",
      "Duplicate Calendar Event Left Behind" in _body, True)

print("\n=== 9. _count_bookings_on_date honours the exclusion ===")
_cb = _SRC.index("def _count_bookings_on_date(")
_cb_body = _SRC[_cb:_SRC.index("\ndef ", _cb + 10)]
check("signature takes exclude_event_id",
      "def _count_bookings_on_date(target_date, exclude_event_id=None):" in _cb_body, True)
check("the excluded id is skipped in the loop",
      'if exclude_event_id and event.get("id") == exclude_event_id:' in _cb_body, True)

print("\n=== 10. the stored event_id is tried before any text guess ===")
_scan = _body[_body.index("_stale = None"):_body.index("if appointment_type ==")]
check("the lead record's event_id is consulted",
      'get("event_id")' in _scan, True)
# compare CALL SITES, not the prose above them
_c_phone = _scan.index("matched = _cleanup_phone_matches")
_c_name = _scan.index("matched = _cleanup_name_matches")
check("event_id is checked BEFORE the phone match",
      _scan.index('get("event_id")') < _c_phone, True)
check("phone is still checked BEFORE the name match", _c_phone < _c_name, True)

print("\n=== 6. Patch #106 — the phone moved out of the description ===")
# The number is no longer written where an attendee can read it. If the
# matcher had gone on searching the description alone, no match would mean no
# delete, and a rebooking would leave the old event standing beside the new.
PRIVATE_ONLY = {
    "id": "p106",
    "summary": "Studio Visit — Prime Vacation Orlando (Prime Vacation Orlando)",
    "description": ("Studio visit with Michael Moraes at MWM Creations & Studios.\n\n"
                    "1500 Park Center Dr, Suite 230, Orlando, FL 32835\n"
                    "Please arrive a few minutes early."),
    "extendedProperties": {"private": {"lead_phone": "14075551212",
                                       "lead_name": "Prime Vacation Orlando"}},
}
check("the client-safe description contains no phone number",
      "14075551212" in PRIVATE_ONLY["description"], False)
check("...and the matcher still finds it, from the private properties",
      _cleanup_phone_matches("14075551212", PRIVATE_ONLY), True)
check("a different number still does not match",
      _cleanup_phone_matches("19995551212", PRIVATE_ONLY), False)
check("legacy events — number only in the description — still match",
      _cleanup_phone_matches("14075551212", PRIME), True)

print("\n" + "=" * 64)
print("  %d passed, %d failed" % (_passed, _failed))
for _f in _FAILS:
    print("   x " + _f)
print("=" * 64)
sys.exit(1 if _failed else 0)


