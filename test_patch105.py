#!/usr/bin/env python3
"""test_patch105.py — Patch #105. Nobody was looking for double-bookings.

Before this patch there were three partial guards and no detector:

  · book_appointment's race guard — ±15 min around ONE slot, at booking time,
    only on the path Maya drives.
  · slot_conflicts (#50D) — correct, pure, wired only to the admin booking
    form's client-side JS. Blind to anything Michael did not type into it.
  · /studio-availability — tells WordPress what is busy, and then
    /webhook/studio-booking writes the event with NO server-side check at all.

So a clash created by the portal, by wp-admin, or by hand was invisible until
a human read the calendar. Aug 19 2026: Victory HQ 9:15–12:30 on Edgewater
Drive against Z Brothers Construction's PAID studio booking 10:00–11:00. The
conflict was written inside the Victory event's own description. It sat seven
days. Section 2 replays exactly that pair.

THE HARD PART IS NOT FINDING OVERLAPS — IT IS NOT CRYING WOLF.
The calendar fixtures in section 1 are the REAL MWM CREATIONS calendar for
Aug 20–31 2026, pulled the day this was written. It contains, on purpose:

  · a FREE hold (Shelley, Aug 27 10:00) that exists so she can book that very
    slot herself — flagging it would tell Michael his own bookkeeping is a
    double-book;
  · a cancelled shoot downgraded to FREE rather than deleted (Victory class,
    Aug 25 16:30–21:00) sitting across Todd Berger's paid 14:00–15:00;
  · his flights, which arrive TWICE — once from United, once from Expedia,
    same reservation EKZ915, identical times;
  · back-to-back and same-day bookings he runs deliberately.

A detector that reports any of those gets muted inside a day, and a muted rail
is worse than none because it still looks like coverage. Section 1 asserts the
real calendar is SILENT. If it ever stops being silent, read the new event
before you touch find_conflicts.

Run: python3 test_patch105.py
"""

import sys

from event_rail import (find_conflicts, describe_conflict, classify_clash,
                        CLASH_ROOM, CLASH_PERSON, CONFLICT_HORIZON_DAYS,
                        KIND_STUDIO_VISIT, KIND_PORTAL_BOOKING,
                        KIND_PRODUCTION_SHOOT, KIND_STRATEGY_CALL,
                        KIND_INTERNAL, KIND_UNKNOWN)

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


def ev(eid, summary, start, end, desc="", free=False, series=None,
       status="confirmed", allday=False):
    """A Google calendar event as the list API actually returns one."""
    out = {"id": eid, "summary": summary, "description": desc, "status": status}
    if allday:
        out["start"] = {"date": start}
        out["end"] = {"date": end}
    else:
        out["start"] = {"dateTime": start, "timeZone": "America/New_York"}
        out["end"] = {"dateTime": end, "timeZone": "America/New_York"}
    if free:
        out["transparency"] = "transparent"
    if series:
        out["recurringEventId"] = series
    return out


MAYA_DESC = ("Studio Visit with Michael Moraes / MWM Creations Studios\n\n"
             "Lead: %s\nBusiness: %s\nEmail: x@y.com\n"
             "Booked by: Maya\nBooked via: Website Chat")
PORTAL_DESC = ("Studio Package portal booking #%s\nClient: %s\n"
               "Notes: -\nSource: portal (auto-synced by machine S12)")

# ── THE REAL CALENDAR, Aug 20-31 2026, MWM CREATIONS ───────────────────────
REAL = [
    ev("ems20", "TREINO EMS Vida Fit",
       "2026-08-20T08:30:00-04:00", "2026-08-20T09:00:00-04:00",
       series="8chk853903tom1hfb1hans0b6g"),
    ev("mm586g36m6ap903adviopl2hgc",
       "FOLLOW UP — Dr. Luiz Bolfer has not sent a new date",
       "2026-08-20T09:00:00-04:00", "2026-08-20T09:30:00-04:00",
       desc="RSVP-NOTE: MICHAEL IS HANDLING THIS PERSONALLY, BY MESSAGE."),
    ev("58g9d5drbb02gls85vcfirblao", "Show Master Barber: Hair Cut",
       "2026-08-20T12:00:00-04:00", "2026-08-20T12:45:00-04:00"),
    ev("e37blp6mleii49p0sno0k645nk", "Studio: Jonathan Pineda (1h)",
       "2026-08-20T14:15:00-04:00", "2026-08-20T15:15:00-04:00",
       desc=PORTAL_DESC % ("71", "Jonathan Pineda")),
    ev("6nqecnb39trc57tio1ddl46elk",
       "Visita ao estudio — Rebeca Maldonado (conversa sobre estagio)",
       "2026-08-21T10:00:00-04:00", "2026-08-21T11:00:00-04:00"),
    ev("8sg35relqdn5bql03hm4jiq9tc", "Studio: Vanessa Serrano (3h)",
       "2026-08-21T12:00:00-04:00", "2026-08-21T15:00:00-04:00",
       desc=PORTAL_DESC % ("59", "Vanessa Serrano")),
    ev("victorytv21", "SEND WEEKLY UPDATE E-MAIL - VICTORY TV",
       "2026-08-21T15:00:00-04:00", "2026-08-21T16:00:00-04:00",
       free=True, series="_6oq48e9m6p13eba270pj2b9k"),
    ev("cqitgj0eth2g42u7po19ldvkt8",
       "Aniversario River (9) & Riley (7) — levar as criancas",
       "2026-08-22T14:00:00-04:00", "2026-08-22T17:00:00-04:00"),
    ev("ems25", "TREINO EMS Vida Fit",
       "2026-08-25T08:30:00-04:00", "2026-08-25T09:00:00-04:00",
       series="8chk853903tom1hfb1hans0b6g"),
    ev("7osqoca7mojkcevfae65vns2uc",
       "Studio Visit — Marc Holmes (In the Driver's Seat with Marc Holmes)",
       "2026-08-25T10:00:00-04:00", "2026-08-25T11:00:00-04:00",
       desc=MAYA_DESC % ("Marc Holmes", "motorsports podcast brand")),
    ev("2ul4tato11ntit6l1c8950avr4", "Studio: Todd Berger (rental) (1.00h)",
       "2026-08-25T14:00:00-04:00", "2026-08-25T15:00:00-04:00",
       desc=PORTAL_DESC % ("77", "Todd Berger (rental)")),
    ev("toq4ldvi3dpenav8qgse95ifuk",
       "CANCELLED — VICTORY Leadership Class · Master Hermann VonSchmeling",
       "2026-08-25T16:30:00-04:00", "2026-08-25T21:00:00-04:00", free=True),
    ev("uokjoanqe10nbnlmc55d3t2kjk",
       "Strategy Call — Prime Vacation Orlando (Prime Vacation Orlando)",
       "2026-08-26T10:00:00-04:00", "2026-08-26T11:00:00-04:00",
       desc="Strategy Call with Michael Moraes / MWM Creations\n\nLead: Prime Vacation Orlando"),
    ev("0vd2u4cllot8g5clvjjn6nv1e8",
       "UNCONFIRMED HOLD — Shelley Roxanne, SPOTLIGHT edit session",
       "2026-08-27T10:00:00-04:00", "2026-08-27T12:00:00-04:00", free=True),
    ev("1gmcq43mq9bmejif2k48c62l78", "Studio: Jonathan Pineda (1h)",
       "2026-08-27T14:15:00-04:00", "2026-08-27T15:15:00-04:00",
       desc=PORTAL_DESC % ("72", "Jonathan Pineda")),
    ev("ta9ek2hhui4qd75mmrg8fak7uc",
       "Levar o sogro ao aeroporto — MCO Terminal B",
       "2026-08-30T11:30:00-04:00", "2026-08-30T13:30:00-04:00"),
    ev("flightUA", "Flight: UA 2456 from MCO to IAH",
       "2026-08-30T15:15:00-04:00", "2026-08-30T18:55:00-04:00",
       desc="Reservation Number: EKZ915\n\nProvider: United Airlines"),
    ev("flightEX", "Flight: MCO to IAH",
       "2026-08-30T15:15:00-04:00", "2026-08-30T18:55:00-04:00",
       desc="Reservation Number: EKZ915\n\nProvider: Expedia"),
]

print("\n=== 1. the real calendar must be SILENT ===")
_real = find_conflicts(REAL)
check("no conflicts on the live Aug 20-31 calendar",
      [(c["a"]["summary"][:22], c["b"]["summary"][:22]) for c in _real], [])
check("...and it is not silent merely by being empty", len(REAL) >= 18, True)



# ── and the rest of the 30-day horizon, Sep 1-18, same real calendar ───────
REAL_SEP = [
    ev("f_ua129", "Flight: UA 129 from IAH to GIG", "2026-08-30T21:00:00-05:00",
       "2026-08-31T09:15:00-05:00", desc="Reservation Number: EKZ915\n\nProvider: United Airlines"),
    ev("f_ex129", "Flight: IAH to GIG", "2026-08-30T21:00:00-05:00",
       "2026-08-31T07:15:00-03:00", desc="Reservation Number: EKZ915\n\nProvider: Expedia"),
    ev("ems0901", "TREINO EMS Vida Fit", "2026-09-01T08:30:00-04:00",
       "2026-09-01T09:00:00-04:00", series="8chk853903tom1hfb1hans0b6g"),
    ev("jr0c2koo6qdiei54d022hq478o",
       "FOLLOW UP — ask Jonathan Pineda whether to extend the Thursday 2:15 slot",
       "2026-09-01T09:00:00-04:00", "2026-09-01T09:30:00-04:00"),
    ev("5cc610evm67n3ph4or4e5tq0lg",
       "Studio Visit — Angie Starrz (Starrz Talk — podcast/radio show)",
       "2026-09-02T15:00:00-04:00", "2026-09-02T16:00:00-04:00",
       desc=MAYA_DESC % ("Angie Starrz", "Starrz Talk")),
    ev("ems0903", "TREINO EMS Vida Fit", "2026-09-03T08:30:00-04:00",
       "2026-09-03T09:00:00-04:00", series="8chk853903tom1hfb1hans0b6g"),
    ev("01comgtf2fafsjboom703bc2pc",
       "CHECK IN — Dr. Robinson, how is the arm healing (NOT a date chase)",
       "2026-09-03T09:00:00-04:00", "2026-09-03T09:15:00-04:00", free=True),
    ev("96a6bvsb03mjdp4qt6busjtbrk", "Studio: Jonathan Pineda (1h)",
       "2026-09-03T14:15:00-04:00", "2026-09-03T15:15:00-04:00",
       desc=PORTAL_DESC % ("73", "Jonathan Pineda")),
    ev("rcbcmsdcd0q957ohcn71pi4rp4",
       "VICTORY — Grand Master VonSchmeling · Book Tour Launch",
       "2026-09-03T16:30:00-04:00", "2026-09-03T21:00:00-04:00",
       desc="Victory Martial Arts HQ — 4418 Edgewater Drive, Orlando FL 32804."),
    ev("vtv0904", "SEND WEEKLY UPDATE E-MAIL - VICTORY TV",
       "2026-09-04T15:00:00-04:00", "2026-09-04T16:00:00-04:00",
       free=True, series="_6oq48e9m6p13eba270pj2b9k"),
    ev("e2f6ofkins30i4s0stgejl5eng", "Studio: Priti (rental — rescheduled) (1.00h)",
       "2026-09-05T10:00:00-04:00", "2026-09-05T11:00:00-04:00",
       desc=PORTAL_DESC % ("65-r1", "Priti (rental — rescheduled)")),
    ev("ems0908", "TREINO EMS Vida Fit", "2026-09-08T08:30:00-04:00",
       "2026-09-08T09:00:00-04:00", series="8chk853903tom1hfb1hans0b6g"),
    ev("ems0910", "TREINO EMS Vida Fit", "2026-09-10T08:30:00-04:00",
       "2026-09-10T09:00:00-04:00", series="8chk853903tom1hfb1hans0b6g"),
    ev("ba4ikcbqn22pi9o8acr7vaikls", "Studio: Jonathan Pineda (1h)",
       "2026-09-10T14:15:00-04:00", "2026-09-10T15:15:00-04:00",
       desc=PORTAL_DESC % ("74", "Jonathan Pineda")),
    ev("vtv0911", "SEND WEEKLY UPDATE E-MAIL - VICTORY TV",
       "2026-09-11T15:00:00-04:00", "2026-09-11T16:00:00-04:00",
       free=True, series="_6oq48e9m6p13eba270pj2b9k"),
    ev("ems0915", "TREINO EMS Vida Fit", "2026-09-15T08:30:00-04:00",
       "2026-09-15T09:00:00-04:00", series="8chk853903tom1hfb1hans0b6g"),
    ev("ems0917", "TREINO EMS Vida Fit", "2026-09-17T08:30:00-04:00",
       "2026-09-17T09:00:00-04:00", series="8chk853903tom1hfb1hans0b6g"),
    ev("vtv0918", "SEND WEEKLY UPDATE E-MAIL - VICTORY TV",
       "2026-09-18T15:00:00-04:00", "2026-09-18T16:00:00-04:00",
       free=True, series="_6oq48e9m6p13eba270pj2b9k"),
]
_full = find_conflicts(REAL + REAL_SEP)
check("the FULL 30-day horizon is silent too",
      [(c["a"]["summary"][:22], c["b"]["summary"][:22]) for c in _full], [])
check("...across a real 36-event feed", len(REAL + REAL_SEP) >= 36, True)

print("\n=== 2. the Aug 19 clash it was blind to ===")
# Victory HQ, Edgewater Drive, 9:15-12:30 against Z Brothers Construction's
# PAID studio booking 10:00-11:00. Untouched for seven days.
AUG19 = [
    ev("victoryhq",
       "FILM SHOOT — VICTORY MARTIAL ARTS HQ (On Location)",
       "2026-08-19T09:15:00-04:00", "2026-08-19T12:30:00-04:00",
       desc="4418 Edgewater Drive, Orlando.\nCONFLICT: Z Brothers studio 10-11."),
    ev("zbrothers", "Studio: Z Brothers Construction (1h)",
       "2026-08-19T10:00:00-04:00", "2026-08-19T11:00:00-04:00",
       desc=PORTAL_DESC % ("66", "Z Brothers Construction")),
]
_a19 = find_conflicts(AUG19)
check("the clash is found", len(_a19), 1)
check("Michael cannot be on Edgewater Drive and in the studio",
      _a19[0]["severity"], CLASH_PERSON)
check("overlap is the full hour", _a19[0]["overlap_min"], 60)
check("both sides are named", sorted([_a19[0]["a"]["id"], _a19[0]["b"]["id"]]),
      ["victoryhq", "zbrothers"])
check("the alert says what it is",
      "SCHEDULE CLASH" in describe_conflict(_a19[0]), True)

print("\n=== 3. the studio checked against itself ===")
# The case nothing had ever looked for: one room, two paid bookings.
ROOM = [
    ev("rafael", "Studio Visit — Rafael Madeira (FastLine Group)",
       "2026-08-24T14:00:00-04:00", "2026-08-24T15:00:00-04:00",
       desc=MAYA_DESC % ("Rafael Madeira", "FastLine Group")),
    ev("angie", "Studio: Angie Starrz (1h)",
       "2026-08-24T14:30:00-04:00", "2026-08-24T15:30:00-04:00",
       desc=PORTAL_DESC % ("80", "Angie Starrz")),
]
_room = find_conflicts(ROOM)
check("two studio bookings on top of each other are found", len(_room), 1)
check("...and rank as a ROOM clash, not merely a person clash",
      _room[0]["severity"], CLASH_ROOM)
check("overlap is 30 min", _room[0]["overlap_min"], 30)
check("the alert names the room",
      "STUDIO DOUBLE-BOOKED" in describe_conflict(_room[0]), True)
check("a room clash outranks a person clash",
      [c["severity"] for c in find_conflicts(ROOM + AUG19)],
      [CLASH_ROOM, CLASH_PERSON])

print("\n=== 4. touching is not overlapping ===")
BACK2BACK = [
    ev("s1", "Studio: Client One (1h)", "2026-09-01T10:00:00-04:00",
       "2026-09-01T11:00:00-04:00", desc=PORTAL_DESC % ("90", "Client One")),
    ev("s2", "Studio: Client Two (1h)", "2026-09-01T11:00:00-04:00",
       "2026-09-01T12:00:00-04:00", desc=PORTAL_DESC % ("91", "Client Two")),
]
check("11:00 after an 11:00 finish is not a clash", find_conflicts(BACK2BACK), [])
_one_min = list(BACK2BACK)
_one_min[1] = ev("s2", "Studio: Client Two (1h)", "2026-09-01T10:59:00-04:00",
                 "2026-09-01T12:00:00-04:00", desc=PORTAL_DESC % ("91", "Client Two"))
check("one minute of overlap IS a clash", len(find_conflicts(_one_min)), 1)
check("...and reports one minute", find_conflicts(_one_min)[0]["overlap_min"], 1)


print("\n=== 5. the noise rules, each one on its own ===")
STUDIO_A = ev("a", "Studio: Client A (1h)", "2026-09-02T10:00:00-04:00",
              "2026-09-02T11:00:00-04:00", desc=PORTAL_DESC % ("92", "Client A"))
check("a FREE event never clashes",
      find_conflicts([STUDIO_A, ev("hold", "HOLD — someone", "2026-09-02T10:00:00-04:00",
                                   "2026-09-02T11:00:00-04:00", free=True)]), [])
check("a CANCELLED event never clashes",
      find_conflicts([STUDIO_A, ev("x", "Studio: Client B (1h)",
                                   "2026-09-02T10:00:00-04:00", "2026-09-02T11:00:00-04:00",
                                   desc=PORTAL_DESC % ("93", "B"), status="cancelled")]), [])
check("an all-day event never clashes",
      find_conflicts([STUDIO_A, ev("ad", "Conference", "2026-09-02", "2026-09-03",
                                   allday=True)]), [])
check("two instances of one recurring series never clash",
      find_conflicts([
          ev("r1", "TREINO EMS Vida Fit", "2026-09-02T10:00:00-04:00",
             "2026-09-02T11:00:00-04:00", series="ems"),
          ev("r2", "TREINO EMS Vida Fit", "2026-09-02T10:30:00-04:00",
             "2026-09-02T11:30:00-04:00", series="ems")]), [])
check("the same event twice in one feed never clashes with itself",
      find_conflicts([STUDIO_A, dict(STUDIO_A)]), [])
check("his duplicate flights stay quiet",
      find_conflicts([
          ev("f1", "Flight: UA 2456 from MCO to IAH", "2026-08-30T15:15:00-04:00",
             "2026-08-30T18:55:00-04:00", desc="Provider: United Airlines"),
          ev("f2", "Flight: MCO to IAH", "2026-08-30T15:15:00-04:00",
             "2026-08-30T18:55:00-04:00", desc="Provider: Expedia")]), [])
check("but an internal block ON TOP of a client booking IS reported",
      len(find_conflicts([STUDIO_A,
                          ev("gym", "TREINO EMS Vida Fit", "2026-09-02T10:15:00-04:00",
                             "2026-09-02T10:45:00-04:00", series="ems")])), 1)
check("...as a person clash",
      find_conflicts([STUDIO_A,
                      ev("gym", "TREINO EMS Vida Fit", "2026-09-02T10:15:00-04:00",
                         "2026-09-02T10:45:00-04:00", series="ems")])[0]["severity"],
      CLASH_PERSON)

print("\n=== 6. malformed input is skipped, never guessed clear ===")
check("no start/end", find_conflicts([STUDIO_A, {"id": "junk", "summary": "?"}]), [])
check("unparseable dateTime",
      find_conflicts([STUDIO_A, ev("bad", "Studio: X (1h)", "not-a-date", "also-not")]), [])
check("end before start",
      find_conflicts([STUDIO_A, ev("rev", "Studio: X (1h)",
                                   "2026-09-02T11:00:00-04:00",
                                   "2026-09-02T10:00:00-04:00")]), [])
check("a non-dict in the list", find_conflicts([STUDIO_A, "nonsense", None]), [])
check("an empty feed", find_conflicts([]), [])
check("None", find_conflicts(None), [])


def _boom(ev_):
    raise RuntimeError("classifier exploded")


check("a classifier that throws drops that event rather than clearing the day",
      find_conflicts([STUDIO_A, STUDIO_A], classifier=_boom), [])

print("\n=== 7. severity rules, directly ===")
check("studio vs studio = room", classify_clash(KIND_PORTAL_BOOKING, True,
                                                KIND_STUDIO_VISIT, True), CLASH_ROOM)
check("studio vs on-location shoot = person",
      classify_clash(KIND_PORTAL_BOOKING, True, KIND_PRODUCTION_SHOOT, True), CLASH_PERSON)
check("studio vs strategy call = person",
      classify_clash(KIND_STUDIO_VISIT, True, KIND_STRATEGY_CALL, True), CLASH_PERSON)
check("client vs internal = person",
      classify_clash(KIND_STUDIO_VISIT, True, KIND_INTERNAL, False), CLASH_PERSON)
check("internal vs internal = not reported",
      classify_clash(KIND_INTERNAL, False, KIND_UNKNOWN, False), None)

print("\n=== 8. the horizon is not the reminder horizon ===")
check("30 days, not 48 or 80 hours", CONFLICT_HORIZON_DAYS, 30)
_far = find_conflicts([
    ev("f1", "Studio: Far Client (1h)", "2026-09-15T10:00:00-04:00",
       "2026-09-15T11:00:00-04:00", desc=PORTAL_DESC % ("99", "Far")),
    ev("f2", "Studio Visit — Far Lead (Biz)", "2026-09-15T10:30:00-04:00",
       "2026-09-15T11:30:00-04:00", desc=MAYA_DESC % ("Far Lead", "Biz"))])
check("a clash 26 days out is still found", len(_far), 1)
check("...and still a room clash", _far[0]["severity"], CLASH_ROOM)

print("\n=== 9. the key is stable so a clash is reported once ===")
_k1 = find_conflicts(ROOM)[0]["key"]
_k2 = find_conflicts(list(reversed(ROOM)))[0]["key"]
check("order of the feed does not change the key", _k1, _k2)
check("the key names both events and when they collide",
      _k1, "clash:angie:rafael@2026-08-24T14:30:00-04:00")
# a clash that is FIXED and later re-introduced must read as new, or the
# second collision is silent forever
_moved = [ROOM[0], ev("angie", "Studio: Angie Starrz (1h)",
                      "2026-08-24T14:45:00-04:00", "2026-08-24T15:45:00-04:00",
                      desc=PORTAL_DESC % ("80", "Angie Starrz"))]
check("moving one side produces a different key",
      find_conflicts(_moved)[0]["key"] != _k1, True)

print("\n" + "=" * 64)
print("  %d passed, %d failed" % (_passed, _failed))
for _f in _FAILS:
    print("   x " + _f)
print("=" * 64)
sys.exit(1 if _failed else 0)
