#!/usr/bin/env python3
"""
slots.py — PATCH #94. Which times we offer a lead, and why a free afternoon
is not "fully booked".

THE BUG THIS EXISTS TO KILL
---------------------------
`get_available_slots()` returned one slot per day and assigned each candidate
day a single period by slot index — morning, then afternoon, then morning. If
that day's assigned period had already passed, the day was skipped ENTIRELY.
Its other half was never looked at.

So every lead who wrote after 11:00 was told there was nothing available today,
on a day that was wide open from noon. On 26 Aug 2026 at 11:09 Maya put that in
her own words to Jaysee Soto — "Today is fully booked" — and offered him Friday,
Monday and Tuesday. He got his 2:30 visit that same afternoon only because he
named the time himself and pushed. A less determined lead takes Friday, or
leaves.

THE RULES
---------
1. The alternation is worth keeping. Spreading visits across morning and
   afternoon stops every booking stacking at 10am. So the day's preferred
   period is still tried FIRST.
2. It is a preference, not a gate. When the preferred period is gone or busy,
   the other period is tried before the day is given up.
3. A time in the past is never offered.
4. A day at capacity is skipped; weekends are skipped.
5. The 15-minute buffer either side of a slot is unchanged.

A busy row that cannot be parsed counts as BUSY. Withholding a slot costs a
reschedule; offering one we should not costs a double-booking in front of a
client. Those are not symmetric.

KEY: a tool that returns "nothing" without stating why will have the reason
invented by whatever narrates its output. This module's job is to make
"nothing" mean it.
"""

from datetime import datetime, timedelta

# Preferred period first, the other period as fallback. Order inside a period
# is the house priority: 10 before 11, 3pm before 2pm.
SLOT_PERIOD_ORDER = {
    "morning":   [(10, 0), (11, 0), (15, 0), (14, 0)],
    "afternoon": [(15, 0), (14, 0), (10, 0), (11, 0)],
}

# Which period each of the three offered slots prefers.
DAY_PERIOD_CYCLE = ("morning", "afternoon", "morning")

SLOT_MINUTES = 60
BUFFER_MINUTES = 15
DEFAULT_MAX_SLOTS = 3
DEFAULT_HORIZON_DAYS = 21


def slot_times_for(period):
    """Candidate times for one day: preferred period first, then the other."""
    return list(SLOT_PERIOD_ORDER.get(period, SLOT_PERIOD_ORDER["morning"]))


def period_for(slot_index):
    """The period slot number `slot_index` prefers."""
    return DAY_PERIOD_CYCLE[slot_index % len(DAY_PERIOD_CYCLE)]


ALL_DAY_START = "T00:00:00"


def busy_row(event, tz):
    """One busy row for `is_busy` from a Google Calendar event, or None.

    PATCH #118. Maya used to build her busy list with a bare
    `if "dateTime" in start and "dateTime" in end`, which silently dropped
    every ALL-DAY event — and `check_specific_slot` said so out loud with
    `# Skip all-day events`. Meanwhile /studio-availability and
    /book/availability, which the public booking form uses, DO honour all-day
    events. So the two surfaces disagreed, and on 21 Aug an all-day Busy block
    named "YASMIN surgery" went up for 16 Sep and a studio visit was booked
    onto that same day on 1 Sep, eleven days later, straight through it.

    The rule, now in one place for all three callers:

      * FREE means free. `transparency == "transparent"` blocks nothing —
        that is how a birthday or a "maybe" trip stays bookable.
      * A timed event blocks its own hours.
      * An ALL-DAY event marked Busy blocks the whole day, midnight to
        midnight local. Google's end date is EXCLUSIVE, so a one-day event
        ends at the following midnight and needs no adjustment.
      * An event we cannot read at all is returned AS a row anyway, with its
        raw values, so `is_busy` hits its parse failure and counts it busy.
        Withholding a slot costs a reschedule; offering one we should not
        costs a double-booking in front of a client.
    """
    if (event or {}).get("transparency") == "transparent":
        return None
    start = (event or {}).get("start") or {}
    end = (event or {}).get("end") or {}
    if "dateTime" in start and "dateTime" in end:
        return {"start": start["dateTime"], "end": end["dateTime"]}
    if "date" in start and "date" in end:
        try:
            s = tz.localize(datetime.strptime(start["date"], "%Y-%m-%d"))
            e = tz.localize(datetime.strptime(end["date"], "%Y-%m-%d"))
            return {"start": s.isoformat(), "end": e.isoformat()}
        except (ValueError, TypeError):
            pass
    # Neither shape read cleanly. Hand it back unparseable rather than drop it.
    return {"start": str(start.get("dateTime") or start.get("date") or ""),
            "end": str(end.get("dateTime") or end.get("date") or "")}


def row_window(row, tz):
    """(start, end) for a busy row, or None when it cannot be read.

    None means "treat as blocking" — the callers that need real datetimes
    rather than an overlap answer must fail the same way `is_busy` does.
    """
    try:
        return (datetime.fromisoformat(row["start"]).astimezone(tz),
                datetime.fromisoformat(row["end"]).astimezone(tz))
    except (KeyError, TypeError, ValueError):
        return None


def is_busy(candidate, busy_times, tz):
    """
    True when `candidate` overlaps anything in `busy_times`, counting the
    15-minute buffer either side so visits are not booked back to back.

    `busy_times` — [{"start": iso8601, "end": iso8601}]
    """
    slot_end = candidate + timedelta(minutes=SLOT_MINUTES)
    buffer_start = candidate - timedelta(minutes=BUFFER_MINUTES)
    buffer_end = slot_end + timedelta(minutes=BUFFER_MINUTES)
    for b in busy_times or ():
        try:
            b_start = datetime.fromisoformat(b["start"]).astimezone(tz)
            b_end = datetime.fromisoformat(b["end"]).astimezone(tz)
        except (KeyError, TypeError, ValueError):
            return True
        if b_start < buffer_end and b_end > buffer_start:
            return True
    return False


def compute_slots(now, busy_times, tz, count_fn=None, max_per_day=4,
                  max_slots=DEFAULT_MAX_SLOTS, horizon_days=DEFAULT_HORIZON_DAYS,
                  log=None):
    """
    Pick up to `max_slots` slots, one per business day, starting today.

    Pure: no calendar call, no network. `busy_times` is already fetched and
    `count_fn(date) -> int` reports bookings already on a date.
    """
    if count_fn is None:
        def count_fn(_d):
            return 0

    slots = []
    current_day = now.date() - timedelta(days=1)   # loop increments before checking
    days_checked = 0

    while len(slots) < max_slots and days_checked < horizon_days:
        current_day += timedelta(days=1)
        days_checked += 1

        if current_day.weekday() >= 5:             # Monday to Friday only
            continue

        if count_fn(current_day) >= max_per_day:
            if log:
                log("[Capacity] %s has %s+ bookings — skipping" % (current_day, max_per_day))
            continue

        for (hour, minute) in slot_times_for(period_for(len(slots))):
            candidate = tz.localize(datetime(
                current_day.year, current_day.month, current_day.day, hour, minute, 0
            ))
            if candidate <= now:                   # never offer a time that has passed
                continue
            if is_busy(candidate, busy_times, tz):
                continue
            slots.append({
                "id": candidate.isoformat(),
                "display": candidate.strftime("%A, %B %d at %I:%M %p EST"),
            })
            break                                  # one slot per day

    return slots
