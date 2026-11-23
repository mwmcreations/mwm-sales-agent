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

# PATCH #265 (Michael, Mon 2 Nov 21:30, via ERIC): "Maya can and should always
# offer visit time based on our calendar" — not only the four house times when
# the calendar has other open hours. The studio's open hours are 9 to 5; the
# house four stay FIRST (they spread visits the way Michael likes), the rest
# of the open hours come after, in this order. Off by default in the pure
# functions (extended=False) so nothing that reads these changes until the
# app turns it on; the app passes extended=True once Michael has said yes.
# PATCH #292 (Michael, 22 Nov 23:19): "3 PM the last time a visit can start" - the
# 4 PM start left the extended set.
EXTRA_SLOT_TIMES = [(9, 0), (12, 0), (13, 0)]


def slot_times_for(period, extended=False):
    """Candidate times for one day: preferred period first, then the other,
    then (extended) the rest of the open hours."""
    times = list(SLOT_PERIOD_ORDER.get(period, SLOT_PERIOD_ORDER["morning"]))
    if extended:
        times += [t for t in EXTRA_SLOT_TIMES if t not in times]
    return times


def all_slot_times(extended=False):
    """Every candidate start time, chronological."""
    base = {t for v in SLOT_PERIOD_ORDER.values() for t in v}
    if extended:
        base |= set(EXTRA_SLOT_TIMES)
    return sorted(base)


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


def is_busy(candidate, busy_times, tz, minutes=None):
    """
    True when `candidate` overlaps anything in `busy_times`, counting the
    15-minute buffer either side so visits are not booked back to back.

    `busy_times` — [{"start": iso8601, "end": iso8601}]
    """
    slot_end = candidate + timedelta(minutes=(minutes or SLOT_MINUTES))   # PATCH #292: a call is 15 minutes
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
                  log=None, extended=False):
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

        for (hour, minute) in slot_times_for(period_for(len(slots)), extended=extended):
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


# ── PATCH #157 — only slots inside the next 48 hours (ERIC, 9 Oct, item 2) ──
# "Maya offers only slots inside the next 48 hours (Michael is opening
# morning + late-afternoon slots Mon-Fri). If nothing is open inside 48 h,
# offer the two nearest and tell me in #eric." A lead who can come the day
# after tomorrow shows up; one offered a slot next week drifts.
WINDOW_HOURS_DEFAULT = 48
FALLBACK_SLOTS = 2
# every house time, chronological, for the window search
ALL_SLOT_TIMES = sorted({t for v in SLOT_PERIOD_ORDER.values() for t in v})


def compute_slots_window(now, busy_times, tz, count_fn=None, max_per_day=4,
                         within_hours=WINDOW_HOURS_DEFAULT, max_slots=DEFAULT_MAX_SLOTS,
                         log=None, extended=False):
    """Every free house time that STARTS inside the next `within_hours`, in
    order, up to `max_slots` (more than one per day is fine here — the point
    is soon). Pure. -> list of {"id", "display"}."""
    if count_fn is None:
        def count_fn(_d):
            return 0
    limit = now + timedelta(hours=within_hours)
    out = []
    day = now.date()
    while len(out) < max_slots:
        day_start = tz.localize(datetime(day.year, day.month, day.day, 0, 0, 0))
        if day_start > limit:
            break
        if day.weekday() < 5 and count_fn(day) < max_per_day:
            for (hour, minute) in all_slot_times(extended):
                candidate = tz.localize(datetime(day.year, day.month, day.day, hour, minute, 0))
                if candidate <= now or candidate > limit:
                    continue
                if is_busy(candidate, busy_times, tz):
                    continue
                out.append({"id": candidate.isoformat(),
                            "display": candidate.strftime("%A, %B %d at %I:%M %p EST")})
                if len(out) >= max_slots:
                    break
        elif log and day.weekday() < 5:
            log("[Capacity] %s has %s+ bookings — skipping" % (day, max_per_day))
        day += timedelta(days=1)
    return out


def offer_slots(now, busy_times, tz, count_fn=None, max_per_day=4,
                within_hours=WINDOW_HOURS_DEFAULT, max_slots=DEFAULT_MAX_SLOTS, log=None,
                extended=False):
    """The slots Maya may OFFER: inside the window when any exist, otherwise
    the FALLBACK_SLOTS nearest (one per business day) with fallback=True so
    the caller can say so in #eric. -> (slots, fallback: bool).
    extended=True (PATCH #265) also tries the rest of the open hours."""
    inside = compute_slots_window(now, busy_times, tz, count_fn, max_per_day,
                                  within_hours, max_slots, log, extended=extended)
    if inside:
        return inside, False
    nearest = compute_slots(now, busy_times, tz, count_fn=count_fn, max_per_day=max_per_day,
                            max_slots=FALLBACK_SLOTS, log=log, extended=extended)
    return nearest, True


# ── PATCH #292 — the 15-minute video call has its own hours ────────────────
# Michael, 22 Nov 2026: "Video call hours weekdays 9-5". A call is short, so
# it is offered on the half hour all day; the last one starts 4:30 and ends
# before 5. Two hours' notice, because nobody joins a call offered for "in ten
# minutes". One per day, soonest first.
VIDEO_CALL_MINUTES = 15
VIDEO_CALL_FIRST = (9, 0)
VIDEO_CALL_LAST = (16, 30)
VIDEO_CALL_STEP_MIN = 30
VIDEO_CALL_NOTICE_MIN = 120
CLOSURE_WORDS = ("studio closed",)


def is_closure_event(event):
    """True for the calendar block that closes the STUDIO (not Michael): a
    visit cannot happen then, a video call can."""
    return any(w in str((event or {}).get("summary") or "").lower() for w in CLOSURE_WORDS)


def video_call_times():
    """Every candidate start time for a call, chronological."""
    out = []
    h, m = VIDEO_CALL_FIRST
    while (h, m) <= VIDEO_CALL_LAST:
        out.append((h, m))
        m += VIDEO_CALL_STEP_MIN
        if m >= 60:
            h, m = h + 1, m - 60
    return out


def video_call_slots(now, busy_times, tz, within_hours=WINDOW_HOURS_DEFAULT, max_slots=1,
                     horizon_days=DEFAULT_HORIZON_DAYS, notice_minutes=VIDEO_CALL_NOTICE_MIN):
    """Up to `max_slots` call times, one per business day, soonest first.
    Pure. -> (slots, fallback) where fallback is True when even the soonest
    starts after the `within_hours` window. Each slot carries kind=video_call."""
    earliest = now + timedelta(minutes=notice_minutes)
    limit = now + timedelta(hours=within_hours)
    out = []
    day = now.date()
    for _ in range(max(1, int(horizon_days))):
        if len(out) >= max_slots:
            break
        if day.weekday() < 5:
            for (hour, minute) in video_call_times():
                candidate = tz.localize(datetime(day.year, day.month, day.day, hour, minute, 0))
                if candidate < earliest:
                    continue
                if is_busy(candidate, busy_times, tz, minutes=VIDEO_CALL_MINUTES):
                    continue
                out.append({"id": candidate.isoformat(),
                            "display": candidate.strftime("%A, %B %d at %I:%M %p EST"),
                            "kind": "video_call"})
                break
        day += timedelta(days=1)
    fallback = bool(out) and datetime.fromisoformat(out[0]["id"]) > limit
    return out, fallback
