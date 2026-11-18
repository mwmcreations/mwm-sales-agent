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
    # PATCH #285b — a text Michael sent from his own phone, recorded through
    # /admin/quiet-rail action=touched (the Mac Messages app leaves no trace here)
    out.extend(t.get("at") for t in (rec.get("hand_touches") or []) if isinstance(t, dict))
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


# ── copy — Michael's voice, first person. A creative studio does not ask
# "still interested?"; it brings the story back (Michael, 17 Nov 19:59: "that
# doesn't bring any emotion, doesn't bring any value… we do storytelling…
# short, but much more creative, just like MWM would do"). A comma after the
# name, no dash symbols. The brand prefix and the STOP line are added by
# sms_copy.compose, never here; the app tries the variants in order and sends
# the first that fits two segments.
def _fn(name):
    s = str(name or "").strip().split()
    return s[0].strip(",.").title() if s else "there"


def _biz(business):
    b = str(business or "").strip()
    return b if 0 < len(b) <= 40 else ""


def _mu(must_understand):
    m = str(must_understand or "").strip().rstrip(".")
    return m if 0 < len(m) <= 70 else ""


def touch_sms_variants(n, name, business="", must_understand=""):
    """Most specific first: with what they said their customers must understand,
    with the business name, plain, and finally without the name."""
    fn, biz, mu = _fn(name), _biz(business), _mu(must_understand)
    out = []
    if n == 1:
        if mu:
            out.append(f"Hi {fn}, Michael here. You said people need to understand {mu}. Nobody learns that from a flyer; they learn it from a face and a story. Two dates to film yours?")
        if biz:
            out.append(f"Hi {fn}, Michael here. I kept thinking about {biz} after we talked. Every business has a story; most never film it. Yours deserves to be seen. Two dates to start?")
        out.append(f"Hi {fn}, Michael here. I kept thinking about our conversation. Every business has a story; most never film it. Yours deserves to be seen. Two dates to start?")
        out.append("Hi there, Michael here from MWM. Every business has a story; most never film it. Yours deserves to be seen. Two dates to start?")
    elif n == 2:
        if biz:
            out.append(f"Hi {fn}, Michael. A free idea for {biz}: film one customer the moment they realize they chose right. 30 seconds, no script, one studio hour. It beats any ad. Want to shoot it?")
        out.append(f"Hi {fn}, Michael. A free idea: film one customer the moment they realize they chose right. 30 seconds, no script, one studio hour. It beats any ad. Want to shoot it?")
        out.append("Hi there, Michael from MWM. A free idea: film one customer the moment they realize they chose right. 30 seconds, one studio hour. Want to shoot it?")
    elif n == 3:
        out.append(f"Hi {fn}, Michael. I don't chase people, I chase stories, and yours is a good one. If this month is wrong, tell me which one is right. If it's now, two dates are yours.")
        out.append("Hi there, Michael from MWM. I don't chase people, I chase stories, and yours is a good one. If this month is wrong, say which one is right. If it's now, two dates are yours.")
    else:
        out.append(f"Hi {fn}, Michael. Last note from me. Someone in your market will tell their story on camera this year. I'd rather it were yours. The door stays open; reply when it's time.")
        out.append("Hi there, Michael from MWM. Last note from me. Someone in your market will tell their story on camera this year. I'd rather it were yours. The door stays open.")
    return out


def touch_sms(n, name, business="", must_understand=""):
    """The most specific variant (the app's fitter walks the rest)."""
    return touch_sms_variants(n, name, business, must_understand)[0]


def touch_email(n, name, business="", must_understand=""):
    """(subject, lines) — the app wraps lines with studio_visit._as_html. Short,
    one idea each, the way MWM talks: the story, not the sale."""
    fn, biz, mu = _fn(name), _biz(business), _mu(must_understand)
    about = biz or "your business"
    sig = ["", "Michael Moraes", "MWM Creations & Studios, Orlando"]
    if n == 1:
        subject = f"The story I keep thinking about, {fn}"
        lines = [f"Hi {fn},", "",
                 f"Michael here. Since we talked about {about} I keep coming back to one thing: "
                 + (f"you said people need to understand {mu}, and nobody learns that from a flyer. They learn it from a face and a story."
                    if mu else "your customers don't need another ad, they need to understand who they are dealing with before they call. That is a story, and stories get filmed."),
                 "If you want, I'll put the first one on paper for you: one scene, one message, one minute. No cost, no commitment. "
                 "Reply with a yes and I'll send it with two dates to film."] + sig
    elif n == 2:
        subject = f"One idea for {about}, free"
        lines = [f"Hi {fn},", "",
                 "A gift, no strings: film the moment a customer realizes they chose right. Not a testimonial read off a card, the real thing, "
                 "thirty seconds, one studio hour, and it does more for trust than any paid ad. We built the studio for moments like that.",
                 f"If that is the kind of video you want people to see about {about}, reply and I'll send two dates."] + sig
    elif n == 3:
        subject = f"{fn}, who tells your story if you don't?"
        lines = [f"Hi {fn},", "",
                 f"I don't chase people, I chase stories, and yours stayed with me. Right now the only version of {about} people can find online "
                 "is the one your competitors leave room for. The version where they see your face, hear your reason and understand what you do differently: "
                 "that one still needs to be filmed.",
                 "If this month is wrong, tell me which one is right and I'll come back then. If it's now, two dates are yours."] + sig
    else:
        subject = f"The door stays open, {fn}"
        lines = [f"Hi {fn},", "",
                 "Last note from me on this. Someone in your market will tell their story on camera this year, and I would rather it were yours.",
                 "When the moment comes, write back. We pick up exactly where we left off, and the first scene is already in my head."] + sig
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
