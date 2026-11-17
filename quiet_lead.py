"""
quiet_lead.py — PATCH #285. The quiet-lead rail: a lead who talked to us and
then went quiet gets a machine touch every five days, Michael hears about it
on day ten, and nothing stops until the lead answers, books, or someone says
stop.

WHY (Michael, Tue 17 Nov 2026, by voice)
────────────────────────────────────────
"We need to be more proactive on chasing these leads." The chase chain (#143)
stops the moment a lead REPLIES, BOOKS, or Michael takes over (manual) — by
design: a conversation had started. From that moment the only machine that
looked at the lead was the S28 digest in #susan, which lists who is overdue
and sends nothing; by 17 Nov it listed the same 28 names for 33 to 71 days.
Vicente Orellana replied on 29 Oct, Michael offered video-call times on
10 Nov, nobody answered, nobody followed up until Michael texted by hand on
17 Nov. That gap is this rail.

THE RAIL
────────
  activity   the lead's last inbound on either number, or the last touch a
             human or another rail made (chase step, Michael's re-offer, a
             report filed). Our OWN quiet touches do not count — otherwise
             the clock would reset itself.
  day 5      touch 1 — one text (with consent) or one short email
  day 10     touch 2 + Michael is texted once: "<name> has been quiet 10 days"
  day 15     touch 3
  day 20     touch 4, then the rail closes ("quiet 20 days") and the lead
             belongs to the re-engagement list (#158/#275), as before.
  reset      any new activity moves `since` and the count starts over.

WHO IS ON IT
────────────
  A lead whose chase stopped as replied / booked (visit in the past, outcome
  filed as follow-up and the post-visit chain done) / manual, or who wrote to
  us at all, and who is NOT: a client, disqualified, do-not-contact, lost or
  not interested, booked for a date still ahead, or inside another live rail
  (chase still armed, outcome sequence or pitch sequence still running).

WHAT NEVER HAPPENS HERE
───────────────────────
  No sends while the `quiet_rail_live` switch is off: the pass computes and
  the admin route shows what it WOULD do, so Michael reads the list and the
  copy before the first text leaves (his rule: nothing unread goes out).
  No text without marketing consent; no email to a suppressed address; the
  8–18 ET window (every day — Michael keeps lead follow-up on weekends).

PURE: no clock, no store, no Flask. The loop in app.py asks eligible(),
next_actions() and the copy; it supplies the facts.
"""
from datetime import datetime, timedelta

QUIET_DAYS = 5
ESCALATE_DAY = 10
MAX_TOUCHES = 4
SEND_HOURS = (8, 18)      # ET, every day

STOP_REPLIED = "replied"      # chase stop reasons that put a lead on this rail
STOP_BOOKED = "booked"
STOP_MANUAL = "manual"
ELIGIBLE_STOPS = (STOP_REPLIED, STOP_BOOKED, STOP_MANUAL)

CLOSE_QUIET = "quiet %dd" % (QUIET_DAYS * MAX_TOUCHES)

EMAIL = "email"
SMS = "sms"

_LOST_OUTCOMES = ("lost", "not_interested", "not interested", "declined", "no", "disqualified", "closed_lost")


def _parse(ts):
    if ts is None or ts == "":
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def _aware(dt, like):
    if dt is None:
        return None
    if dt.tzinfo is None and like is not None and like.tzinfo is not None:
        return dt.replace(tzinfo=like.tzinfo)
    return dt


def latest(stamps, like=None):
    """The newest datetime among iso strings / datetimes / None."""
    best = None
    for s in stamps or ():
        d = _aware(_parse(s), like)
        if d is not None and (best is None or d > best):
            best = d
    return best


def activity_stamps(rec, chase=None):
    """Every stamp on the record that counts as activity (a human or another
    rail touched the lead, or the lead wrote). Our own quiet touches are NOT
    in here — see the header."""
    rec = rec or {}
    out = [rec.get("last_message_time"), rec.get("last_email_reply_at"),
           rec.get("last_outcome_at"), rec.get("booked_at"), rec.get("first_touch_sms_at"),
           rec.get("first_touch_wa_at"), rec.get("manual_since"), rec.get("reoffer_at")]
    los = rec.get("last_outbound_sms")
    out.append(los.get("at") if isinstance(los, dict) else los)
    ch = chase if isinstance(chase, dict) else (rec.get("chase") if isinstance(rec.get("chase"), dict) else {})
    out.extend((ch.get("sent") or {}).values())
    out.extend(t.get("at") for t in (ch.get("touches") or []) if isinstance(t, dict))
    out.append(ch.get("stopped_at"))
    return [s for s in out if s]


def eligible(rec, stage, booking=None, other_rail_active=False, is_client=False):
    """Is this lead the rail's to chase? -> (True, 'why on') or (False, 'why not').

    `stage` is the Desk's stage (desk.stage_of: facts first), `booking` the
    Desk's booking_of() dict or None. The Desk already read the record the
    way Michael sees it; this function only decides who belongs here."""
    rec = rec or {}
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else {}
    stopped = str(chase.get("stopped") or "")
    stage = str(stage or "")
    if is_client or stage == "Client" or rec.get("paid_at") or str(rec.get("outcome") or "").lower() == "won" \
            or str(rec.get("relationship") or "") in ("client", "existing_client", "new_client", "known"):
        return False, "client"
    if stage == "Lost" or isinstance(rec.get("disqualified"), dict) or rec.get("do_not_contact"):
        return False, "lost / do not contact"
    lo = str(rec.get("last_outcome") or "").lower()
    if lo in _LOST_OUTCOMES:
        return False, "lost / not interested"
    if rec.get("cold_fired"):
        return False, "cold audience"
    if other_rail_active:
        return False, "another rail is live"
    if chase.get("armed_at") and not stopped:
        return False, "chase still armed"
    if stage == "New":
        return False, "never talked to us"
    if stage == "Paused":
        return False, "quiet 30+ days: re-engagement list"
    if stage == "Booked":
        if booking and not booking.get("passed"):
            return False, "booked ahead"
        return False, "visit passed, not reported"
    if stage == "Visited":
        if lo != "follow_up":
            return False, "visit outcome: " + (lo or "?")
        if chase.get("kind") == "post_visit" and not stopped:
            return False, "post-visit chain running"
        return True, "follow-up after the visit, chain done"
    if stage == "Contacted":
        if stopped == STOP_MANUAL:
            return True, "Michael took over, then quiet"
        if stopped == STOP_REPLIED:       # the chase saw a reply the board cannot show (an email answer, an old record)
            return True, "replied (chase verdict), then quiet"
        return False, "never answered: the chase owns it"
    if stage == "Replied":
        if stopped and stopped not in ELIGIBLE_STOPS and stopped != "closed":
            return False, "chase stopped: " + stopped
        return True, ("replied, chase " + stopped) if stopped else "replied"
    return False, "stage " + (stage or "?")


def arm(now, since):
    return {"armed_at": now.isoformat(), "since": (since or now).isoformat(),
            "touches": [], "escalated_at": "", "stopped": "", "stopped_at": ""}


def refresh(state, since):
    """New activity after `since` resets the count (the conversation moved)."""
    if not isinstance(state, dict) or since is None:
        return state
    old = _aware(_parse(state.get("since")), since)
    if old is None or since > old + timedelta(minutes=1):
        state["since"] = since.isoformat()
        state["touches"] = []
        state["escalated_at"] = ""
        state["stopped"] = ""
        state["stopped_at"] = ""
        state["reset_at"] = since.isoformat()
    return state


def days_quiet(state, now):
    since = _aware(_parse((state or {}).get("since")), now)
    if since is None:
        return None
    return (now - since).total_seconds() / 86400.0


def next_actions(state, now):
    """What is due now: a list drawn from
    ('touch', n) · ('escalate',) · ('close', reason) — or []."""
    if not isinstance(state, dict) or state.get("stopped"):
        return []
    d = days_quiet(state, now)
    if d is None:
        return []
    touches = state.get("touches") or []
    n = len(touches)
    out = []
    if n >= MAX_TOUCHES:
        return [("close", CLOSE_QUIET)]
    # a touch is due at day 5, 10, 15, 20 of quiet — and never less than
    # QUIET_DAYS after the previous one (a lead found at day 11 gets touch 1
    # now and touch 2 five days later, not five minutes later)
    last_touch = latest([t.get("at") for t in touches if isinstance(t, dict)], like=now)
    gap_ok = last_touch is None or (now - last_touch).total_seconds() >= QUIET_DAYS * 86400 - 60
    if d >= QUIET_DAYS * (n + 1) and gap_ok:
        out.append(("touch", n + 1))
    if d >= ESCALATE_DAY and not state.get("escalated_at"):
        out.append(("escalate",))
    return out


def channel_for(n, has_email, sms_ok):
    """Odd touches go by text when they can, even touches by email when they
    can; whatever the lead has otherwise. '' when there is no road."""
    if n % 2 == 1:
        order = (SMS, EMAIL)
    else:
        order = (EMAIL, SMS)
    for ch in order:
        if ch == SMS and sms_ok:
            return SMS
        if ch == EMAIL and has_email:
            return EMAIL
    return ""


def within_hours(now, hours=SEND_HOURS):
    return hours[0] <= now.hour < hours[1]


def note_touch(state, now, n, channel):
    state.setdefault("touches", []).append({"n": int(n), "at": now.isoformat(), "channel": channel})
    return state


def stop(state, now, reason):
    state["stopped"] = str(reason)
    state["stopped_at"] = now.isoformat()
    return state


# ── copy — Michael's voice, first person. Texts ask one thing: still interested?
# (Michael, 17 Nov: "personal and professional at the same time"; a comma after
# the name, no dash symbols.) The brand prefix and the STOP line are added by
# sms_copy.compose, never here.
def _fn(name):
    s = str(name or "").strip().split()
    return s[0].strip(",.").title() if s else "there"


def touch_sms(n, name):
    fn = _fn(name)
    if n == 1:
        return f"Hi {fn}, Michael here from MWM. Still interested in what we talked about? If yes, I'll send you two options."
    if n == 2:
        return f"Hi {fn}, Michael again. Still interested? A yes or a not now is all I need."
    if n == 3:
        return f"Hi {fn}, Michael, MWM Creations. Still interested? If the timing is off, tell me when to come back."
    return f"Hi {fn}, Michael here. Last note from me on this. Still interested? The door stays open either way."


def touch_email(n, name, business=""):
    """(subject, lines) — the app wraps lines with studio_visit._as_html."""
    fn = _fn(name)
    biz = str(business or "").strip()
    about = f" for {biz}" if biz and len(biz) < 40 else ""
    if n == 1:
        subject = f"Still interested, {fn}?"
        lines = [f"Hi {fn},", "",
                 f"Michael here. We spoke about the videos{about} a few days ago and I have not heard back, "
                 "so one question: still interested?",
                 "If yes, reply with a yes and I'll send you two options to pick from. If the timing is off, "
                 "tell me when to come back and I will.",
                 "", "Michael Moraes", "MWM Creations & Studios, Orlando"]
    elif n == 2:
        subject = f"Still interested, {fn}? (second note)"
        lines = [f"Hi {fn},", "",
                 "Michael again. I don't want to chase you if the moment has passed, so a yes or a not now is all I need.",
                 "If it's a yes, I'll send two dates.",
                 "", "Michael Moraes", "MWM Creations & Studios, Orlando"]
    elif n == 3:
        subject = f"{fn}, still interested?"
        lines = [f"Hi {fn},", "",
                 f"Checking in one more time about the videos{about}. Still interested?",
                 "If the answer is later, tell me the month and I'll come back then.",
                 "", "Michael Moraes", "MWM Creations & Studios, Orlando"]
    else:
        subject = "Last note from me, the door stays open"
        lines = [f"Hi {fn},", "",
                 "This is my last note on this. I'd rather not keep writing if the timing is wrong.",
                 "The door stays open. When it makes sense to tell your story on video, write back and we pick it up "
                 "from where we left it.",
                 "", "Michael Moraes", "MWM Creations & Studios, Orlando"]
    return subject, lines


def escalation_text(name, business, days, channel_used):
    biz = f" ({business})" if business else ""
    road = f"touches by {channel_used}" if channel_used else "no channel I can use"
    return (f"MWM: {name}{biz} has been quiet {int(days)} days since you last spoke. "
            f"Rail: {road}. Reply with their name + 'stop' to stop it, or call them.")


def summary(state, now):
    if not isinstance(state, dict) or not state.get("since"):
        return "not on the rail"
    if state.get("stopped"):
        return f"stopped: {state['stopped']}"
    d = days_quiet(state, now) or 0.0
    n = len(state.get("touches") or [])
    nxt = QUIET_DAYS * (n + 1)
    due = "due now" if d >= nxt else f"in {nxt - d:.1f}d"
    esc = "" if not state.get("escalated_at") else "; Michael told"
    return f"quiet {d:.1f}d; {n} touch(es); next touch {due}{esc}"
