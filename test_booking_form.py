#!/usr/bin/env python3
"""Patch #50 — the direct-booking intake form, pinned.

The single most important assertion in this file is the ROUND TRIP: every
title `booking_title()` produces must be recognised by `classify_event()` as
the kind the type declares, and that kind must have a ladder in
CONFIRMATION_PLAN.

That is the whole safety property of the patch. The form's promise to Michael
is "fill this in and the automation understands it" — and that promise is
kept by a string template matching a regex in a different function. Nothing
enforces that at runtime, and nothing would complain if someone tidied
"Studio Recording - {name}" into "Recording: {name}" next month. It would
simply stop being a client event, silently, and the first symptom would be a
client who never got a reminder.
"""
import re
import sys

STUDIO = "1500 Park Center Dr, Suite 230, Orlando, FL 32835"
VIRTUAL = "Phone / WhatsApp call — Michael will dial the number on this booking"

from event_rail import (
    BOOKING_TYPES, BOOKING_TYPE_ORDER, RELATIONSHIPS, RELATIONSHIP_ORDER,
    BILLING, BILLING_ORDER, CONFIRMATION_PLAN,
    billing_options_for, billing_is_asked, BILLING_CONSULTATION,
    booking_title, booking_kind, booking_needs_address,
    relationship_sells, relationship_from_description,
    relationship_in_pipeline, relationship_converted,
    booking_description, validate_booking, booking_location,
    slot_conflicts, day_is_free, slot_runs_past_midnight,
    slot_buffer_warnings, BOOKING_BUFFER_MIN,
    classify_event, instrumentation_gaps, venue_of,
    VENUE_CLIENT_SITE, KIND_UNKNOWN,
)

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  {}".format(label))
    else:
        FAIL += 1
        print("  FAIL  {}".format(label))


def section(t):
    print("\n" + "=" * 60 + "\n  {}\n".format(t) + "=" * 60)


# ══════════════════════════════════════════════════════════════════
section("THE ROUND TRIP — a computed title must survive the classifier")
# ══════════════════════════════════════════════════════════════════
for key in BOOKING_TYPE_ORDER:
    spec = BOOKING_TYPES[key]
    title = booking_title(key, "Rodolfo Silva")
    kind, is_client, why = classify_event(
        {"summary": title, "description": "", "attendees": []})

    ok(is_client, "{}: {!r} classifies as a CLIENT event".format(key, title))
    ok(kind == spec["kind"],
       "{}: classifies as {} (declared {})".format(key, kind, spec["kind"]))
    ok(kind in CONFIRMATION_PLAN,
       "{}: {} has a confirmation ladder".format(key, kind))
    ok(booking_kind(key) == kind,
       "{}: booking_kind agrees with the classifier".format(key))

ok(set(BOOKING_TYPE_ORDER) == set(BOOKING_TYPES),
   "every booking type is displayable and every displayed type exists")
ok(set(RELATIONSHIP_ORDER) == set(RELATIONSHIPS), "relationship order covers all")
ok(set(BILLING_ORDER) | set(BILLING_CONSULTATION) == set(BILLING),
   "every billing value is reachable through either the delivery list or the consultation list")
ok("no_charge" not in BILLING_ORDER,
   "no_charge is never offered as a free choice — it is only ever filled in for a consultation")

# A name with awkward spacing must not break the match.
for messy in ["  Rodolfo   Silva ", "Dr. Luiz Bolfer", "Enzo Auto Service",
              "Krista Neeley (with Michael Neeley)", "Natália Tavares"]:
    for key in BOOKING_TYPE_ORDER:
        t = booking_title(key, messy)
        k, c, _ = classify_event({"summary": t, "description": "", "attendees": []})
        ok(c and k == BOOKING_TYPES[key]["kind"],
           "{}: {!r} still classifies correctly".format(key, messy[:22]))

ok(booking_title("nonsense", "X") == "", "an unknown type produces no title")
ok(booking_title("studio_visit", "   ") == "", "an empty name produces no title")
ok(booking_title("studio_visit", "-—-") == "", "a name of only dashes produces no title")


# ══════════════════════════════════════════════════════════════════
section("THE EVENT IS FULLY INSTRUMENTED — no gaps, by construction")
# ══════════════════════════════════════════════════════════════════
# This is the Coach Fly / Enzo failure expressed as a test: an event this form
# produces must have ZERO instrumentation gaps. If it can leave gaps, the form
# has not solved the problem it was built for.
for key in BOOKING_TYPE_ORDER:
    ev = {
        "summary": booking_title(key, "Enzo Auto Service"),
        "description": booking_description(
            "Enzo Auto Service", "contact@enzoauto.com", phone="14075551234",
            business="Enzo Auto Service", type_key=key,
            relationship="existing_client", billing="paid", amount="$2,400"),
        "attendees": [{"email": "contact@enzoauto.com"}],
        "location": booking_location(key, "1200 W Colonial Dr, Orlando FL 32804",
                                     STUDIO, VIRTUAL),
    }
    gaps = instrumentation_gaps(ev)
    ok(gaps == [], "{}: a form-built event has zero gaps ({})".format(key, gaps))

# ...and the same event WITHOUT the attendee is still critical, so the test
# above is proving something rather than passing vacuously.
ev_no_att = {
    "summary": booking_title("location_shoot", "Enzo Auto Service"),
    "description": "", "attendees": [],
}
ok(any("NO ATTENDEE" in g for g in instrumentation_gaps(ev_no_att)),
   "negative control: strip the attendee and it IS critical")
ok(any("ANONYMOUS" in g for g in instrumentation_gaps(ev_no_att)),
   "negative control: strip the Lead: line and it IS anonymous")

# The Lead: line alone must clear ANONYMOUS — that is the contract
# instrumentation_gaps() actually reads.
ev_lead_only = {
    "summary": booking_title("studio_visit", "Natalia Tavares"),
    "description": booking_description("Natalia Tavares", "n@example.com"),
    "attendees": [{"email": "n@example.com"}],
    "location": booking_location("studio_visit", "", STUDIO, VIRTUAL),
}
ok(instrumentation_gaps(ev_lead_only) == [],
   "the Lead: line the form writes is the one instrumentation_gaps reads")


# ══════════════════════════════════════════════════════════════════
section("LOCATION — never empty, and never invented for a client site")
# ══════════════════════════════════════════════════════════════════
# "no location and no meeting link" is a real instrumentation gap, so a form
# that can produce an event without one has not finished the job.
for key in BOOKING_TYPE_ORDER:
    supplied = "1200 W Colonial Dr, Orlando FL 32804" if booking_needs_address(key) else ""
    loc = booking_location(key, supplied, STUDIO, VIRTUAL)
    ok(loc.strip() != "", "{}: a validated booking always has a location".format(key))

ok(booking_location("studio_visit", "", STUDIO, VIRTUAL) == STUDIO,
   "a studio visit fills with OUR address")
ok(booking_location("studio_recording", "", STUDIO, VIRTUAL) == STUDIO,
   "a studio recording fills with OUR address")
ok(booking_location("strategy_call", "", STUDIO, VIRTUAL) == VIRTUAL,
   "a call gets the non-postal note, never a street address")
ok(STUDIO not in booking_location("strategy_call", "", STUDIO, VIRTUAL),
   "...and specifically NOT the studio address")
ok(booking_location("location_shoot", "", STUDIO, VIRTUAL) == "",
   "an on-location shoot is NEVER auto-filled — Patch #32's lesson")
ok(STUDIO not in booking_location("location_shoot", "", STUDIO, VIRTUAL),
   "...and above all never gets the studio address, which would misdirect the crew")
ok(booking_location("location_shoot", "1200 W Colonial Dr", STUDIO, VIRTUAL)
   == "1200 W Colonial Dr", "the human-supplied shoot address is used verbatim")
ok(booking_location("studio_visit", "Studio B", STUDIO, VIRTUAL) == "Studio B",
   "a location Michael types beats our default")


# ══════════════════════════════════════════════════════════════════
section("RELATIONSHIP — the sales rail is off by default, not on")
# ══════════════════════════════════════════════════════════════════
ok(relationship_sells("new_lead"), "a new lead may be sold to")
ok(not relationship_sells("existing_client"), "an existing client may NOT be sold to")
ok(not relationship_sells("partner"), "a partner may NOT be sold to")
ok(not relationship_sells("vendor"), "a vendor may NOT be sold to")
ok(not relationship_sells(""), "a MISSING relationship fails closed")
ok(not relationship_sells(None), "None fails closed")
ok(not relationship_sells("New_Lead"), "a near-miss fails closed rather than guessing")
ok(not relationship_sells("anything_else"), "an unknown value fails closed")

d = booking_description("Enzo", "e@x.com", type_key="location_shoot",
                        relationship="existing_client", billing="paid", amount="$2,400")
ok(relationship_from_description(d) == "existing_client",
   "the relationship survives a write/read round trip")
ok("Sales rail: OFF" in d, "a non-selling relationship says so in plain words")
ok(not relationship_sells(relationship_from_description(d)),
   "reading it back still refuses to sell")

d2 = booking_description("Someone", "s@x.com", type_key="studio_visit",
                         relationship="new_lead", billing="paid")
ok(relationship_from_description(d2) == "new_lead", "a new lead round-trips")
ok("Sales rail: OFF" not in d2, "a real prospect is not marked off")
ok(relationship_sells(relationship_from_description(d2)), "and may be sold to")

ok(relationship_from_description("") == "", "no description -> unknown")
ok(relationship_from_description("Lead: X\nEmail: y@z.com") == "",
   "a legacy hand-made event -> unknown, NOT new_lead")
ok(not relationship_sells(relationship_from_description("Lead: X")),
   "and unknown therefore does not sell")
ok(relationship_from_description("Relationship: garbage") == "",
   "an unrecognised value reads as unknown")
ok(relationship_from_description("  relationship:  VENDOR  ") == "vendor",
   "case and whitespace tolerated on read")


# ══════════════════════════════════════════════════════════════════
section("BILLING — unpaid work still gets its full reminder ladder")
# ══════════════════════════════════════════════════════════════════
# Natalia's two hours are unpaid; she still has to turn up. Billing must never
# reach the confirmation logic.
for billing in BILLING_ORDER:
    ev = {
        "summary": booking_title("studio_recording", "Natalia Tavares"),
        "description": booking_description(
            "Natalia Tavares", "natalia@example.com", type_key="studio_recording",
            relationship="vendor", billing=billing),
        "attendees": [{"email": "natalia@example.com"}],
        "location": booking_location("studio_recording", "", STUDIO, VIRTUAL),
    }
    kind, is_client, _ = classify_event(ev)
    ok(is_client and kind in CONFIRMATION_PLAN,
       "billing={}: still a client event with a full ladder".format(billing))
    ok(instrumentation_gaps(ev) == [], "billing={}: no gaps".format(billing))

paid = booking_description("X", "x@y.com", type_key="studio_visit",
                           relationship="new_lead", billing="paid", amount="$1,200")
ok("$1,200" in paid, "a paid booking records the amount")
free = booking_description("X", "x@y.com", type_key="studio_visit",
                           relationship="partner", billing="partnership")
ok("$" not in free, "an unpaid booking records no amount")
ok("partnership" in free.lower(), "and says why it is unpaid")


# ══════════════════════════════════════════════════════════════════
section("VALIDATION — refuse the four things that have actually gone wrong")
# ══════════════════════════════════════════════════════════════════
good = {"type": "studio_visit", "name": "Rodolfo Silva", "email": "r@nestseekers.com",
        "date": "2026-08-20", "start": "10:00", "minutes": "60",
        "relationship": "new_lead", "billing": "paid", "amount": "$349"}
errs, clean = validate_booking(good)
ok(errs == [], "a complete studio visit validates: {}".format(errs))
ok(clean["minutes"] == 60, "minutes coerced to int")

errs, _ = validate_booking(dict(good, email=""))
ok(any("email" in e for e in errs), "no email is refused")
errs, _ = validate_booking(dict(good, email="not-an-email"))
ok(any("email" in e for e in errs), "a malformed email is refused")
errs, _ = validate_booking(dict(good, email="a@b"))
ok(any("email" in e for e in errs), "an address with no TLD is refused")

errs, _ = validate_booking(dict(good, name=""))
ok(any("name" in e for e in errs), "no name is refused")
errs, _ = validate_booking(dict(good, type=""))
ok(any("kind of booking" in e for e in errs), "no type is refused")
errs, _ = validate_booking(dict(good, relationship=""))
ok(any("sales rail" in e for e in errs), "no relationship is refused")
# `good` is a studio_visit, which since #51 is not asked about money at all —
# so the "must answer" case has to be asserted against DELIVERED work.
errs, _ = validate_booking(dict(good, type="studio_recording", billing=""))
ok(any("paid" in e for e in errs),
   "no billing answer is refused — for work that is actually delivered")
errs, _ = validate_booking(dict(good, billing=""))
ok(errs == [],
   "...but a free studio visit needs no answer, which is the #51 fix")
errs, _ = validate_booking(dict(good, date="20/08/2026"))
ok(any("date" in e for e in errs), "a non-ISO date is refused")
errs, _ = validate_booking(dict(good, start="10am"))
ok(any("time" in e for e in errs), "a non-24h time is refused")
errs, _ = validate_booking(dict(good, minutes="900"))
ok(any("12 hours" in e for e in errs), "an absurd duration is refused")

# THE ENZO CASE — an on-location shoot with no address.
errs, _ = validate_booking(dict(good, type="location_shoot", location=""))
ok(any("street address" in e for e in errs),
   "an on-location shoot with no address is REFUSED (the Enzo failure)")
errs, _ = validate_booking(dict(good, type="location_shoot",
                                location="1200 W Colonial Dr, Orlando FL"))
ok(errs == [], "...and accepted once the address is there")

# The studio types must NOT demand an address — we know our own.
for key in ["studio_visit", "strategy_call", "studio_recording"]:
    errs, _ = validate_booking(dict(good, type=key, location=""))
    ok(errs == [], "{}: no address demanded, we know where we are".format(key))
    ok(not booking_needs_address(key), "{}: booking_needs_address is False".format(key))
ok(booking_needs_address("location_shoot"), "location_shoot DOES need an address")
ok(venue_of(booking_kind("location_shoot")) == VENUE_CLIENT_SITE,
   "and its venue is the client site, so nothing may auto-fill it")

errs, clean = validate_booking(dict(good, minutes=""))
ok(clean["minutes"] == BOOKING_TYPES["studio_visit"]["default_minutes"],
   "a blank duration falls back to the type's default")

ok(validate_booking({})[0], "an empty payload is refused rather than crashing")
ok(validate_booking(None)[0], "None is refused rather than crashing")


# ══════════════════════════════════════════════════════════════════
section("#50D — clash detection, so a live phone call can be answered")
# ══════════════════════════════════════════════════════════════════
DAY = [
    {"start": "09:00", "end": "12:00", "title": "Studio Recording - Bolfer"},
    {"start": "14:00", "end": "15:00", "title": "Strategy Call - Jorge"},
]

ok(slot_conflicts("09:00", 60, DAY), "a slot inside a booking clashes")
ok(slot_conflicts("11:30", 60, DAY), "a slot straddling the end clashes")
ok(slot_conflicts("08:30", 60, DAY), "a slot straddling the start clashes")
ok(slot_conflicts("08:00", 480, DAY), "a slot swallowing a booking clashes")
ok(len(slot_conflicts("08:00", 480, DAY)) == 2, "...and reports BOTH bookings")
ok(not slot_conflicts("12:00", 60, DAY),
   "back-to-back is NOT a clash — 12:00 may follow a 09:00-12:00")
ok(not slot_conflicts("13:00", 60, DAY), "13:00-14:00 fits the gap exactly")
ok(not slot_conflicts("15:00", 90, DAY), "starting as one ends is fine")
ok(not slot_conflicts("06:00", 120, DAY), "an early slot is clear")
ok(not slot_conflicts("10:00", 60, []), "an empty day never clashes")

# the reported block must be the real one, so the UI can name it
hit = slot_conflicts("10:00", 30, DAY)
ok(len(hit) == 1 and hit[0]["title"] == "Studio Recording - Bolfer",
   "the clash names the booking it collided with")

# "24:00" is the serialisation an all-day / midnight-spanning block uses
ok(slot_conflicts("23:00", 30, [{"start": "22:00", "end": "24:00"}]),
   "a block ending 24:00 is honoured (the S15.1 convention)")
ok(not slot_conflicts("21:00", 30, [{"start": "22:00", "end": "24:00"}]),
   "...and does not swallow the evening before it")

# malformed input must never read as free
for bad in [{"start": "x", "end": "y"}, {"start": "10:00"}, {"end": "11:00"},
            {"start": "11:00", "end": "10:00"}, {"start": "25:00", "end": "26:00"},
            {"start": None, "end": None}, "not a dict", None]:
    ok(slot_conflicts("10:00", 60, [bad]) == [],
       "a malformed block {!r} is skipped, not guessed".format(str(bad)[:28]))

ok(slot_conflicts("", 60, DAY) == [], "no start time -> no verdict")
ok(slot_conflicts("10:00", 0, DAY) == [], "zero duration -> no verdict")
ok(slot_conflicts("10:00", "abc", DAY) == [], "a junk duration -> no verdict")
ok(slot_conflicts("10:00", 60, None) == [], "no blocks at all -> no clash")

ok(day_is_free([]), "an empty day is free")
ok(not day_is_free(DAY), "a booked day is not free")
ok(day_is_free([{"start": "x", "end": "y"}]),
   "a day of only unparseable blocks reads as free — and the UI says so")

ok(slot_runs_past_midnight("23:00", 180), "a slot crossing midnight is flagged")
ok(not slot_runs_past_midnight("09:00", 180), "a daytime slot is not")
ok(not slot_runs_past_midnight("22:00", 120), "ending exactly at midnight is not")
ok(not slot_runs_past_midnight("bad", 60), "junk does not flag")
# the honest gap: conflicts are single-day, so the flag is what covers it
ok(not slot_conflicts("23:00", 180, DAY) and slot_runs_past_midnight("23:00", 180),
   "a midnight-spanning slot reports CLEAR but IS flagged as unchecked")


# ══════════════════════════════════════════════════════════════════
section("#52 — 'sells' and 'belongs in the pipeline' are two questions")
# ══════════════════════════════════════════════════════════════════
# Michael: "maybe a lead that paid me on the spot when they called?" That
# person had no correct answer — new_lead nurtured someone who had already
# bought, and existing_client created no record because they were not in the
# store yet.
EXPECT = {
    #                  sells  pipeline  converted
    "new_lead":        (True,  True,    False),
    "new_client":      (False, True,    True),
    "existing_client": (False, True,    True),
    "partner":         (False, False,   False),
    "vendor":          (False, False,   False),
}
ok(set(EXPECT) == set(RELATIONSHIPS), "every relationship is accounted for")
for rel, (sells, pipe, conv) in EXPECT.items():
    ok(relationship_sells(rel) is sells, "{}: sells={}".format(rel, sells))
    ok(relationship_in_pipeline(rel) is pipe, "{}: pipeline={}".format(rel, pipe))
    ok(relationship_converted(rel) is conv, "{}: converted={}".format(rel, conv))

# THE CASE HE ASKED ABOUT: paid on the call.
ok(relationship_in_pipeline("new_client"),
   "a lead who paid on the call DOES get a pipeline record")
ok(not relationship_sells("new_client"),
   "...and is never pitched again, because they already bought")
ok(relationship_converted("new_client"), "...and reads as converted")

# the hole this also closed
ok(relationship_in_pipeline("existing_client"),
   "an existing client not yet in the store now gets a record too (was the bug)")
ok(not relationship_sells("existing_client"), "...and is still never pitched")

# exactly one relationship may be sold to
ok([r for r in RELATIONSHIPS if relationship_sells(r)] == ["new_lead"],
   "new_lead is the ONLY relationship the sales rail may act on")
# everyone converted is unsellable, and vice versa where it matters
for rel in RELATIONSHIPS:
    if relationship_converted(rel):
        ok(not relationship_sells(rel),
           "{}: converted implies never sold to".format(rel))

# people we book rooms for but who are not prospects
for rel in ("partner", "vendor"):
    ok(not relationship_in_pipeline(rel),
       "{}: stays OUT of the sales pipeline".format(rel))

# fail-closed on every unknown
for bad in ["", None, "nonsense", "New_Client", "client"]:
    ok(not relationship_sells(bad), "{!r}: sells fails closed".format(bad))
    ok(not relationship_in_pipeline(bad), "{!r}: pipeline fails closed".format(bad))
    ok(not relationship_converted(bad), "{!r}: converted fails closed".format(bad))

# it must survive the write/read round trip through a calendar event
for rel in RELATIONSHIPS:
    d = booking_description("Marcus Webb", "m@webbmedia.com",
                            type_key="studio_recording", relationship=rel,
                            billing="paid", amount="$1,800")
    ok(relationship_from_description(d) == rel,
       "{}: round-trips through the event description".format(rel))
    ok(relationship_sells(relationship_from_description(d)) == relationship_sells(rel),
       "{}: and the sales verdict survives with it".format(rel))

# validation accepts the new option, and still refuses junk
_b52 = {"type": "studio_recording", "name": "Marcus Webb", "email": "m@webbmedia.com",
        "date": "2026-08-20", "start": "10:00", "minutes": "120", "billing": "paid"}
for rel in RELATIONSHIPS:
    errs, clean = validate_booking(dict(_b52, relationship=rel))
    ok(errs == [], "{}: validates ({})".format(rel, errs))
    ok(clean["relationship"] == rel, "{}: survives validation".format(rel))
errs, _ = validate_booking(dict(_b52, relationship="paid"))
ok(any("sales rail" in e for e in errs),
   "'paid' is NOT accepted as a relationship — money is not a relationship")

# and the whole point: paid never implies anything about the relationship
for bl in ("paid", "partnership", "trade", "internal"):
    for rel in RELATIONSHIPS:
        d = booking_description("X", "x@y.com", type_key="location_shoot",
                                relationship=rel, billing=bl)
        ok(relationship_sells(relationship_from_description(d)) == relationship_sells(rel),
           "billing={} rel={}: billing never changes the sales verdict".format(bl, rel))


# ══════════════════════════════════════════════════════════════════
section("#51 — do not ask a free sales meeting whether it is paid")
# ══════════════════════════════════════════════════════════════════
# Michael, on his first real use of the form: "on number four, paid or not —
# a studio visit, people don't need to pay to come for a visit." He was right,
# and none of the four answers fitted, so the form was forcing a wrong one.
CONSULT = ["studio_visit", "strategy_call"]
DELIVER = ["studio_recording", "location_shoot"]

for k in CONSULT:
    ok(not billing_is_asked(k), "{}: the form does NOT ask about money".format(k))
    ok(billing_options_for(k) == ["no_charge"],
       "{}: the only honest answer is 'no charge'".format(k))
for k in DELIVER:
    ok(billing_is_asked(k), "{}: delivered work IS asked about money".format(k))
    ok("paid" in billing_options_for(k), "{}: can be paid".format(k))
    ok("partnership" in billing_options_for(k), "{}: can be a partnership".format(k))
    ok("no_charge" not in billing_options_for(k),
       "{}: cannot be 'no charge' — free delivered work is a partnership or a trade".format(k))

_base = {"name": "Marcus Webb", "email": "m@webbmedia.com", "date": "2026-08-20",
         "start": "10:00", "minutes": "60", "relationship": "new_lead"}

# THE BUG HE HIT: a studio visit with the billing question unanswered.
for k in CONSULT:
    errs, clean = validate_booking(dict(_base, type=k, billing=""))
    ok(errs == [], "{}: submits CLEAN with no billing answer ({})".format(k, errs))
    ok(clean["billing"] == "no_charge", "{}: filled in as no_charge".format(k))

# ...and a wrong answer is overwritten rather than stored
for bad in ["paid", "partnership", "trade", "internal", "nonsense"]:
    errs, clean = validate_booking(dict(_base, type="studio_visit", billing=bad))
    ok(errs == [] and clean["billing"] == "no_charge",
       "studio_visit: {!r} is coerced to no_charge, never stored".format(bad))
errs, clean = validate_booking(dict(_base, type="studio_visit",
                                    billing="paid", amount="$2,400"))
ok(clean["billing"] == "no_charge",
   "a stale tab cannot stamp a price on a free studio visit")

# delivered work still MUST answer, and refuses the consultation-only value
for k in DELIVER:
    errs, _ = validate_booking(dict(_base, type=k, billing="",
                                    location="1200 W Colonial Dr"))
    ok(any("paid" in e for e in errs), "{}: still demands an answer".format(k))
    errs, _ = validate_booking(dict(_base, type=k, billing="no_charge",
                                    location="1200 W Colonial Dr"))
    ok(any("event report" in e for e in errs),
       "{}: 'no charge' is REFUSED, not guessed at".format(k))

# the description has to say where the money actually lives
_d = booking_description("Marcus Webb", "m@webbmedia.com", type_key="studio_visit",
                         relationship="new_lead", billing="no_charge")
ok("No charge" in _d, "a consultation records that there is no charge")
ok("Event Report" in _d, "...and points at where the price will be recorded")
ok("$" not in _d, "...and carries no amount")

# billing must not have leaked into the thing that decides follow-up
for b in BILLING:
    _dd = booking_description("X", "x@y.com", type_key="studio_visit",
                              relationship="new_lead", billing=b)
    ok(relationship_sells(relationship_from_description(_dd)),
       "billing={}: a new lead is STILL followed up — money never gates the sales rail".format(b))
_dd = booking_description("X", "x@y.com", type_key="studio_recording",
                          relationship="existing_client", billing="paid", amount="$5,000")
ok(not relationship_sells(relationship_from_description(_dd)),
   "and a paying client is still never pitched")

ok(billing_options_for("garbage") == list(BILLING_ORDER),
   "an unknown type gets the full list...")
ok(validate_booking(dict(_base, type="garbage", billing="paid"))[0],
   "...but an unknown type is refused outright anyway")


# ══════════════════════════════════════════════════════════════════
section("#50E — 30 minutes to reset between jobs")
# ══════════════════════════════════════════════════════════════════
ok(BOOKING_BUFFER_MIN == 30, "the buffer is the 30 minutes Michael asked for")

def gaps(st, mn, blocks=DAY):
    return [(w["gap"], w["side"], w["block"]["title"]) for w in slot_buffer_warnings(st, mn, blocks)]

ok(gaps("12:00", 60) == [(0, "before", "Studio Recording - Bolfer")],
   "starting the instant a shoot ends is TIGHT, not clear")
ok(gaps("12:15", 60) == [(0 + 15, "before", "Studio Recording - Bolfer")],
   "15 minutes after a shoot is still tight")
ok(gaps("12:29", 60) and gaps("12:29", 60)[0][0] == 29, "29 minutes is tight")
ok(gaps("12:30", 60) == [], "30 minutes exactly is ENOUGH — the boundary is inclusive")
ok(gaps("12:45", 30) == [], "45 minutes is comfortably clear")
ok(gaps("13:00", 60) == [(0, "after", "Strategy Call - Jorge")],
   "ending the instant the next job starts is tight, and named as 'after'")
ok(gaps("08:30", 30) == [(0, "after", "Studio Recording - Bolfer")],
   "the buffer works on the leading edge too")
ok(gaps("08:00", 30) == [], "an hour before the shoot is clear")

# a real overlap belongs to slot_conflicts and must NOT be double-reported
ok(slot_conflicts("10:00", 60, DAY) and slot_buffer_warnings("10:00", 60, DAY) == [],
   "an overlapping booking is reported ONCE, as a clash, never also as tight")
ok(slot_buffer_warnings("08:00", 480, DAY) == [],
   "a slot swallowing both bookings is all clash, no buffer noise")

# both sides at once
tight_both = slot_buffer_warnings("12:10", 100, DAY)   # 12:10-13:50
ok(len(tight_both) == 2, "a slot squeezed between two jobs warns about both")
ok([w["side"] for w in tight_both] == ["before", "after"]
   or [w["side"] for w in tight_both] == ["after", "before"],
   "...one on each side")
ok(tight_both[0]["gap"] <= tight_both[1]["gap"], "warnings are sorted tightest first")

# the buffer must be overridable without editing the function
ok(slot_buffer_warnings("12:00", 60, DAY, buffer_min=0) == [],
   "a zero buffer disables the warning entirely")
ok(len(slot_buffer_warnings("11:00", 60, DAY, buffer_min=240)) >= 1,
   "a wider buffer catches more")

# same fail-safe rules as slot_conflicts
for bad in [{"start": "x", "end": "y"}, {"start": "11:00", "end": "10:00"},
            "not a dict", None, {"start": "10:00"}]:
    ok(slot_buffer_warnings("13:00", 60, [bad]) == [],
       "a malformed block {!r} raises no buffer warning".format(str(bad)[:24]))
ok(slot_buffer_warnings("", 60, DAY) == [], "no start time -> no warning")
ok(slot_buffer_warnings("13:00", 0, DAY) == [], "zero duration -> no warning")
ok(slot_buffer_warnings("13:00", "x", DAY) == [], "junk duration -> no warning")
ok(slot_buffer_warnings("13:00", 60, None) == [], "no blocks -> no warning")


# ══════════════════════════════════════════════════════════════════
section("#50B — the auto-outcome guard's decision table")
# ══════════════════════════════════════════════════════════════════
# The 24h auto-outcome marks an unreported meeting `follow_up` and hands the
# person to Maya's nurture. This is the exact predicate that now stands in
# front of it. Expressed as a table because the DEFAULT matters as much as the
# hits: an event with no Relationship: line must behave EXACTLY as it did
# before #50, or going quiet on legacy events becomes a second, opposite bug.
GUARD = [
    ("Relationship: new_lead",        True,  "a referral is still nurtured"),
    ("Relationship: existing_client", False, "an active client is NOT sold to"),
    ("Relationship: partner",         False, "a partner is NOT sold to"),
    ("Relationship: vendor",          False, "an editor owed money is NOT sold to"),
    ("Lead: Someone\nEmail: a@b.com", True,  "a legacy event behaves EXACTLY as before"),
    ("",                              True,  "an empty description behaves as before"),
    ("Relationship: nonsense",        True,  "an unreadable value behaves as before"),
]
for desc, should_nurture, label in GUARD:
    rel = relationship_from_description(desc)
    # This mirrors the guard in app.py: skip only on a READ relationship that
    # does not sell. An unread relationship falls through to the old path.
    skipped = bool(rel) and not relationship_sells(rel)
    ok(skipped != should_nurture, label)

ok(relationship_from_description("Lead: X") == "",
   "a legacy event yields no relationship, so the guard cannot fire on it")
ok(relationship_from_description(
       booking_description("Enzo", "e@x.com", type_key="location_shoot",
                           relationship="existing_client", billing="paid")
   ) == "existing_client",
   "an event this form creates DOES carry a readable relationship")


# ══════════════════════════════════════════════════════════════════
section("NO CREDENTIAL OR SECRET LEAKS INTO AN EVENT BODY")
# ══════════════════════════════════════════════════════════════════
d = booking_description("X", "x@y.com", type_key="studio_visit",
                        relationship="new_lead", billing="paid",
                        notes="ignore me")
for bad in ["secret", "token", "pin", "password", "api_key"]:
    ok(bad not in d.lower(), "the description carries no {!r}".format(bad))


print("\n" + "=" * 60)
print("  BOOKING FORM (#50): {} passed, {} failed".format(PASS, FAIL))
print("=" * 60)
sys.exit(1 if FAIL else 0)
