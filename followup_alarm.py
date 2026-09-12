"""followup_alarm.py — PATCH #141. Making the zero-send alarm watch the rail
it is named after.

WHAT WENT WRONG, AND WHY IT LOOKED LIKE NOTHING
-----------------------------------------------
The ZERO-SEND ALARM exists to page when follow-up work is due and the rail has
sent nothing for days. It fired last on 8 Sep. Between then and 12 Sep the
digest posted four more times, the due count went 5 → 5 → 6 → 6, Dondrique
Lewis aged 38.7 → 40.7 days at exactly +1.0 per day, and NOTHING left the
digest. A week of a dead rail, and the alarm built to catch it said nothing.

The alarm read `followup_last_send_at`. That key is written inside
`_email_send` — the shared wrapper for EVERY outbound email. Booking
confirmations, session reminders, operator self-tests, welcome mail: all of it
stamps the same key. MWM sends transactional email most hours of most days, so
the value is almost always minutes old.

So the alarm was asking *"has any email left the building?"* when the question
it exists to answer is *"has anyone been followed up?"* Those come apart
exactly when it matters, and they had come apart for a week.

THE BITTER PART
---------------
Patch #69 moved that stamp INTO the shared wrapper on purpose, to fix the
opposite bug: the counter read "never" while email flowed normally and the
alarm paged MATT three times chasing a sender that was never in that path.
That fix was right about the false positive and created a false negative — and
between the two, the false negative is far worse. A noisy alarm gets
investigated. A silent one is indistinguishable from a healthy rail, which is
precisely how this ran for seven days with a human reading the digest daily.

THE SIGNAL THAT WAS ALREADY THERE
---------------------------------
The scheduler already loads `followup_sent:{email}` for every lead in order to
work out who is due. The most recent of those stamps IS "when did we last
follow anyone up" — the exact quantity the alarm needs, already in memory, for
no extra database call. This module is the decision, kept pure so it can be
tested without a database, a clock, or an email account.

KEY: an alarm that cannot distinguish "nothing to do" from "cannot do
anything" is not an alarm. Every branch below returns WHY, so the reason can
never be invented downstream.
"""

from datetime import datetime, timedelta

# Due work plus no follow-up sends for this long means the rail is DOWN.
DRY_ALARM_DAYS = 2

# Above this the rail has never sent within instrumented history. Kept as a
# sentinel rather than None so the comparison below has nothing to special-case.
NEVER = 999.0


def days_between(later, earlier):
    """Whole-ish days between two aware datetimes. None when either is missing."""
    if later is None or earlier is None:
        return None
    try:
        return (later - earlier).total_seconds() / 86400.0
    except Exception:
        return None


def rail_state(now, due_count, last_followup_at, threshold_days=DRY_ALARM_DAYS):
    """Is the follow-up rail down?

    `last_followup_at` is the most recent `followup_sent` stamp across ALL
    leads — not the last email of any kind, and not the last stamp among the
    DUE leads. Among the due leads it would be old by definition (that is what
    makes them due), so the alarm would fire permanently and be ignored within
    a week. Across all leads it answers the real question: is anything moving?

    Returns a dict that always carries `reason`, so no caller has to guess.
    """
    if due_count <= 0:
        # Nothing is owed. A quiet rail with no work is not a broken one, and
        # paging here is how an alarm gets muted for the week it matters.
        return {"alarm": False, "reason": "no_work_due", "dry_days": None}

    dry = NEVER if last_followup_at is None else days_between(now, last_followup_at)
    if dry is None:
        # An unparseable stamp is NOT evidence of health. Refusing to decide
        # and saying so beats guessing in either direction.
        return {"alarm": False, "reason": "last_send_unreadable", "dry_days": None}

    if dry >= threshold_days:
        return {"alarm": True, "reason": "due_work_and_no_followups",
                "dry_days": round(dry, 1), "due_count": due_count}

    return {"alarm": False, "reason": "rail_moving", "dry_days": round(dry, 1)}


def alarm_text(state, due_count, oldest_name=None, oldest_days=None):
    """The page itself. Says what was measured, because the last version did
    not and six days were spent checking a send token that was never the
    problem."""
    if not state.get("alarm"):
        return None
    dry = state.get("dry_days")
    when = ("never, in instrumented history" if dry is None or dry >= NEVER
            else "%.1f days ago" % dry)
    lines = [
        ":rotating_light: *ZERO-SEND ALARM — the follow-up rail is not sending.*",
        "%d follow-up(s) are DUE and the last *follow-up* to any lead went out *%s*."
        % (due_count, when),
    ]
    if oldest_name and oldest_days is not None:
        lines.append("Oldest: *%s* at %.1f days overdue." % (oldest_name, oldest_days))
    lines.append(
        "_Measured from the `followup_sent` stamps, not from general outbound "
        "mail. The old alarm read a counter that every booking confirmation "
        "reset, which is why it stayed silent through a week of this._")
    return "\n".join(lines)
