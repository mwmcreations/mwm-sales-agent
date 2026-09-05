#!/usr/bin/env python3
"""booking_truth.py — S30. "Booked" was a flag. Now it is a question.

WHAT IT COST, 24 AUG 2026
-------------------------
James Perry asked on Instagram: "Are we still good for today?" Maya answered
"Yes sir, you're all good — Michael's expecting you today at 3:00 PM." He had
no calendar event. He had never had one. The booking tool had refused on 15
Aug and returned {"success": False}; the refusal went into a language model's
context as a sentence, and the model told him the opposite. Nine days later
she reconfirmed it from the conversation, because the conversation was the
only place the booking existed.

Michael found out from the client, in the room, an hour before the slot.

PATCH #38 ALREADY KNEW
----------------------
There is a comment in app.py, written weeks ago:

    this flag is set at booking CREATION and is never cleared on a no-show or
    a cancellation, so "booked" has meant "had an appointment once, may not
    have attended"

and SUSAN's digest prints " 📅booked (flag only — not calendar-verified)" in
its own output. The system has been labelling this value as untrustworthy and
then trusting it anyway.

THE FIX IS TO STOP STORING THE ANSWER
-------------------------------------
`booked` becomes DERIVED: a lead is booked only if it carries an event_id that
still resolves to a live, future event. Nothing to go stale, nothing to clear
on a no-show, and no wording anywhere that can promise a session the calendar
has never heard of.

THE FAIL-SAFE THAT MATTERS MOST
-------------------------------
A calendar lookup can fail for reasons that have nothing to do with the
booking — an API blip, a token, a timeout. If a failed lookup were read as
"no event", this module would declare every real booking a phantom and we
would delete a day's work on a network hiccup. So a lookup that could not
answer returns LOOKUP_FAILED and lands in its own bucket, which nothing acts
on. Unknown is not the same as absent. That distinction is the whole safety
of this module.

Run the tests: python3 test_booking_truth.py
"""

# ── lookup sentinel ──────────────────────────────────────────────────────────

class _LookupFailed(object):
    """Returned by an event lookup that could not answer. NOT a missing event."""
    def __repr__(self):
        return "LOOKUP_FAILED"
    def __bool__(self):
        return False
    __nonzero__ = __bool__


LOOKUP_FAILED = _LookupFailed()

# ── states ───────────────────────────────────────────────────────────────────

CONFIRMED = "confirmed"    # flag set, event exists, live, still ahead of us
PAST      = "past"         # flag set, event exists, already happened
CANCELLED = "cancelled"    # flag set, event exists but is cancelled
PHANTOM   = "phantom"      # flag set, event_id set, event GONE  <- James Perry
NO_ID     = "no_event_id"  # flag set, no event_id ever recorded <- also James
UNFLAGGED = "unflagged"    # flag not set, but a live event exists
CLEAR     = "clear"        # flag not set, no event. The common, honest case
UNKNOWN   = "unknown"      # the lookup could not answer. Act on nothing.
LINK_MISSING = "link_missing"  # a real event exists for this person, the LEAD
                               # record just is not pointing at it. Gema Hiatt:
                               # booked in wp-admin, so nothing wrote event_id
                               # back to her lead. Nobody was misled — the
                               # session is real — so this must not be reported
                               # as a broken promise.

# States in which it is TRUE to tell a client their session is on.
BOOKABLE_TRUTH = (CONFIRMED,)

# States that mean someone was told something we cannot stand behind.
BROKEN_PROMISE = (PHANTOM, NO_ID, CANCELLED)


def _event_start(event):
    if not isinstance(event, dict):
        return None
    start = event.get("start")
    if isinstance(start, dict):
        return start.get("dateTime") or start.get("date")
    return start


def _live_link(lead, events_by_email):
    """A future event whose attendee list contains this lead's email."""
    if not events_by_email:
        return None
    email = (lead.get("email") or "").strip().lower()
    return events_by_email.get(email) if email else None


def derive(lead, get_event, now_iso=None, events_by_email=None):
    """Return (state, event). `get_event(event_id)` must return a dict, None
    for a genuinely absent event, or LOOKUP_FAILED when it could not answer."""
    lead = lead or {}
    flagged = bool(lead.get("booked"))
    event_id = lead.get("event_id")

    if not event_id:
        if flagged:
            linked = _live_link(lead, events_by_email)
            return ((LINK_MISSING, linked) if linked else (NO_ID, None))
        return (CLEAR, None)

    try:
        event = get_event(event_id)
    except Exception:
        event = LOOKUP_FAILED

    if event is LOOKUP_FAILED:
        return (UNKNOWN, None)

    if not event:
        if flagged:
            linked = _live_link(lead, events_by_email)
            return ((LINK_MISSING, linked) if linked else (PHANTOM, None))
        return (CLEAR, None)

    if str(event.get("status", "")).lower() == "cancelled":
        # PATCH #120 — a wp-admin reschedule DELETES the old event and creates
        # a new one (see calendar_sync's own note), so the lead's event_id is
        # left pointing at a tombstone while the real session lives under a
        # new id nothing wrote back. Google returns that tombstone as
        # status=cancelled, which sent it straight to the red alert. Consult
        # the same link index the absent-event branch already consults.
        if flagged:
            linked = _live_link(lead, events_by_email)
            return ((LINK_MISSING, linked) if linked else (CANCELLED, event))
        return (CLEAR, event)

    start = _event_start(event)
    if now_iso and start and str(start) < str(now_iso):
        return (PAST, event)

    return ((CONFIRMED, event) if flagged else (UNFLAGGED, event))


def is_booked(lead, get_event, now_iso=None, events_by_email=None):
    """The gate. True only when a live future event actually exists.

    Deliberately False for UNKNOWN: if we cannot prove a session exists we do
    not assert it to a client. Silence is recoverable; a wrong promise is not.

    Also False for LINK_MISSING. A session may well be real, but this lead
    record cannot prove which one it is, and "probably yours" is exactly the
    sentence that put James Perry in a car.
    """
    state, _ = derive(lead, get_event, now_iso, events_by_email)
    return state in BOOKABLE_TRUTH


def reconcile(leads, get_event, now_iso=None, events_by_email=None):
    """Sweep every lead. Returns buckets plus counts.

    `leads` is {key: lead_dict}. Nothing here mutates anything — this reports.
    The flag is not cleared automatically: a flag is evidence that somebody was
    promised something, and erasing it destroys the only trace of the promise.
    """
    out = {
        "checked": 0,
        "confirmed": 0,
        "past": 0,
        "clear": 0,
        "unflagged": [],
        "phantom": [],
        "no_event_id": [],
        "cancelled": [],
        "unknown": [],
        "link_missing": [],
    }
    for key, lead in (leads or {}).items():
        out["checked"] += 1
        state, event = derive(lead, get_event, now_iso, events_by_email)
        row = {
            "key": key,
            "name": (lead or {}).get("name") or "",
            "email": (lead or {}).get("email") or "",
            "event_id": (lead or {}).get("event_id"),
            "start": _event_start(event),
        }
        if state == CONFIRMED:
            out["confirmed"] += 1
        elif state == PAST:
            out["past"] += 1
        elif state == CLEAR:
            out["clear"] += 1
        elif state == PHANTOM:
            out["phantom"].append(row)
        elif state == NO_ID:
            out["no_event_id"].append(row)
        elif state == CANCELLED:
            out["cancelled"].append(row)
        elif state == UNFLAGGED:
            out["unflagged"].append(row)
        elif state == UNKNOWN:
            out["unknown"].append(row)
        elif state == LINK_MISSING:
            out["link_missing"].append(row)
    return out


def fingerprint(report):
    """A stable signature of WHO is currently broken.

    S30b — the first version of this posted whenever anything was wrong, and
    the sweep runs hourly, so #dev got the same five names every hour through
    the night. That is the alert-storm failure Patch #103 already solved on
    the Postgres path ("loud on the first one, then counted") and I did not
    carry it one function across. An alert nobody can distinguish from the
    last one is not an alert.

    Caller posts only when this value CHANGES. Same people, same problem,
    silence.
    """
    keys = []
    for bucket in ("phantom", "no_event_id", "cancelled"):
        for r in report.get(bucket) or []:
            keys.append("%s:%s" % (bucket, r.get("key")))
    return "|".join(sorted(keys))


def describe(report, limit=10):
    """One human-readable block for #dev. Empty string when there is nothing
    to say — a sweep that finds nothing must not post."""
    broken = report["phantom"] + report["no_event_id"] + report["cancelled"]
    if not broken:
        return ""

    def _rows(rows, label):
        if not rows:
            return []
        out = ["*%s — %d*" % (label, len(rows))]
        for r in rows[:limit]:
            who = r["name"] or r["key"]
            extra = " <%s>" % r["email"] if r["email"] else ""
            out.append("• %s%s" % (who, extra))
        if len(rows) > limit:
            out.append("…and %d more" % (len(rows) - limit))
        return out

    lines = ["🔴 *BOOKINGS THAT DO NOT EXIST — %d lead(s) believe otherwise*" % len(broken)]
    lines += _rows(report["phantom"], "Event is gone (id recorded, nothing on the calendar)")
    lines += _rows(report["no_event_id"], "Never had an event at all")
    lines += _rows(report["cancelled"], "Event is cancelled but the lead still reads booked")
    lines.append("")
    lines.append("_These leads may have been told a session is confirmed. "
                 "The flag is left alone on purpose — it is the only record that "
                 "a promise was made._")
    if report.get("link_missing"):
        lines.append("ℹ️ %d lead(s) have a real session that their record is not "
                     "pointing at — a linkage gap, not a broken promise." % len(report["link_missing"]))
    if report["unknown"]:
        lines.append("⚠️ %d lead(s) could not be checked (calendar lookup failed) — "
                     "not counted above, nothing assumed." % len(report["unknown"]))
    return "\n".join(lines)
