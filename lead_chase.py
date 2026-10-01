"""
lead_chase.py — PATCH #143. The chase chain, decided without a database.

WHAT WAS THERE BEFORE
─────────────────────
`_followup_scheduler` (S28) posts a DIGEST to #susan every six hours listing
who is due. It sends nothing. The "five chase emails" ERIC briefed on 26 Sep
were never written and never wired, so on 30 Sep — the night before the C1
launch — a form lead who did not answer the first touch would have heard
nothing, ever, unless a human read a Slack digest and acted. Michael's
standard (30 Sep): "automated all the way to the end".

THE CHAIN (ERIC's cadence, 26 Sep)
──────────────────────────────────
  t0        first touch — SMS (consent) + email           (lead_form path)
  day 1     email 1  "what a Studio Strategy Visit looks like"
  day 2     text  1  slots nudge                           (consent only)
  day 5     email 2  case study by industry
  day 9     text  2  last slots nudge                      (consent only)
  day 10    email 3  "the three videos every [industry] needs"
  day 14    email 4  recap of the visit offer
  day 30    email 5  "I'll stop here; the door stays open"

STOPS (checked before every step, never retroactively "unsent"):
  replied    the lead wrote back on any channel after the chain was armed
  booked     a visit is on the calendar
  client     they pay us (roster / relationship / outcome)
  disqualified, do_not_sms (texts only), email suppressed (emails only),
  closed     the chain ran out

Each step fires at most once (a sent stamp is written BEFORE the send, so a
crash between send and write cannot double a message). A step that cannot
go out — quiet hours, a cap, a transport failure — is left due and retried
on the next pass; after `max_late_h` it is skipped with a named reason so a
lead never gets day-5 copy on day 12.

PURE: the loop in app.py asks `next_step()` and `stop_reason()`; nothing
here touches pg_store, Flask or the clock.
"""

from datetime import datetime, timedelta

EMAIL = "email"
SMS = "sms"

# (key, channel, hours after arming, copy step number)
STEPS = (
    ("e1", EMAIL, 24, 1),
    ("s1", SMS, 48, 1),
    ("e2", EMAIL, 24 * 5, 2),
    ("s2", SMS, 24 * 9, 2),
    ("e3", EMAIL, 24 * 10, 3),
    ("e4", EMAIL, 24 * 14, 4),
    ("e5", EMAIL, 24 * 30, 5),
)
STEP_BY_KEY = {s[0]: s for s in STEPS}

# A step older than this past its due time is skipped, not sent late.
MAX_LATE_H = 72

# The first-touch text waits for the sending window; past this it is dropped
# (the email already went) rather than texting a two-day-old "thanks for
# applying".
FIRST_TOUCH_SMS_MAX_WAIT_H = 36

STOP_REPLIED = "replied"
STOP_BOOKED = "booked"
STOP_CLIENT = "client"
STOP_DISQUALIFIED = "disqualified"
STOP_CLOSED = "closed"
STOP_MANUAL = "manual"


def arm(now, channels=("email", "sms"), verdict="yes"):
    """A fresh chain state. `channels` says which rails this lead can use:
    no email -> no email steps; no SMS consent -> no text steps."""
    return {
        "armed_at": now.isoformat(),
        "channels": sorted(set(channels)),
        "verdict": verdict,
        "sent": {},          # key -> iso time
        "skipped": {},       # key -> reason
        "stopped": "",       # reason, once stopped
        "stopped_at": "",
    }


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def hours_since_armed(state, now):
    at = _parse((state or {}).get("armed_at"))
    if at is None:
        return None
    if at.tzinfo is None and now.tzinfo is not None:
        at = at.replace(tzinfo=now.tzinfo)
    return (now - at).total_seconds() / 3600.0


def stop_reason(state, lead, now, last_inbound=None, is_client=False,
                email_suppressed=False):
    """Why this chain must not send anything (any more). '' when it may."""
    if not state:
        return STOP_CLOSED
    if state.get("stopped"):
        return state["stopped"]
    lead = lead or {}
    if is_client or str(lead.get("relationship") or "") in (
            "client", "existing_client", "new_client", "known"):
        return STOP_CLIENT
    if lead.get("booked") or lead.get("appointment_booked"):
        return STOP_BOOKED
    if isinstance(lead.get("disqualified"), dict):
        return STOP_DISQUALIFIED
    armed = _parse(state.get("armed_at"))
    if last_inbound is not None and armed is not None:
        li = last_inbound
        if li.tzinfo is None and armed.tzinfo is not None:
            li = li.replace(tzinfo=armed.tzinfo)
        if armed.tzinfo is None and li.tzinfo is not None:
            armed = armed.replace(tzinfo=li.tzinfo)
        if li > armed + timedelta(minutes=1):
            return STOP_REPLIED
    return ""


def next_step(state, now, max_late_h=MAX_LATE_H):
    """-> (key, channel, copy_step) for the step to send now, or None.

    Walks the chain in order; a step past its lateness window is marked
    skipped (returned as a ('skip', key, reason) tuple first, so the caller
    can persist it) and the walk continues."""
    h = hours_since_armed(state, now)
    if h is None:
        return None
    sent = state.get("sent") or {}
    skipped = state.get("skipped") or {}
    chans = set(state.get("channels") or ())
    for key, chan, due_h, copy_step in STEPS:
        if key in sent or key in skipped:
            continue
        if chan not in chans:
            continue
        if h < due_h:
            return None            # nothing due yet; later steps are later
        if h - due_h > max_late_h:
            return ("skip", key, f"missed by {h - due_h:.0f}h")
        return (key, chan, copy_step)
    return None


def remaining(state):
    """Steps not yet sent or skipped, in order."""
    sent = (state or {}).get("sent") or {}
    skipped = (state or {}).get("skipped") or {}
    chans = set((state or {}).get("channels") or ())
    return [s for s in STEPS if s[0] not in sent and s[0] not in skipped
            and s[1] in chans]


def is_finished(state):
    return not remaining(state)


def summary(state, now):
    """One readable line for /health and the admin page."""
    if not state:
        return "not armed"
    if state.get("stopped"):
        return f"stopped: {state['stopped']}"
    rem = remaining(state)
    h = hours_since_armed(state, now) or 0.0
    if not rem:
        return f"finished ({len(state.get('sent') or {})} sent)"
    key, chan, due_h, _ = rem[0]
    wait = due_h - h
    when = ("due now" if wait <= 0 else
            f"in {wait:.0f}h" if wait < 48 else f"in {wait / 24:.0f}d")
    return (f"next {key} ({chan}) {when}; sent {len(state.get('sent') or {})}, "
            f"skipped {len(state.get('skipped') or {})}")
