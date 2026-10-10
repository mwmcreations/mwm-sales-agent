"""
call_now.py — PATCH #156. Speed to a human: the CALL NOW alert.

ERIC, 9 Oct 2026 23:45 ET, on Michael's order ("the leak is lead -> chair,
not the ads"): every form lead that carries a phone number -> within five
minutes an SMS to Michael and the same line in #eric, both saying CALL NOW,
with the name, the business, the revenue band, the must-understand answer
and the number. A human returning a call to an inquiry needs no texting
consent, so this applies to every lead, consent box or not. Michael's rule
is first call inside the hour, 8 AM-8 PM; outside that window the SMS is
queued for 8 AM (the #eric line goes at once and says so). Maya's own first
touch is untouched — this is in addition, never instead.

PURE: the texts, the window, the queue arithmetic. app.py owns the sending
(operator_alert — SMS to the operator number + #eric, never WhatsApp) and
the pg_store queue.
"""
from datetime import datetime, timedelta

WINDOW_START_H = 8      # 08:00 ET — first text of the day
WINDOW_END_H = 20       # 20:00 ET — after this, queue for the morning
QUEUE_KEY = "call_now_queue"
MAX_QUEUE = 50          # a bug cannot grow the morning text into a novel


def in_window(now):
    """True when a CALL NOW text may go out right now (ET-aware caller)."""
    return WINDOW_START_H <= now.hour < WINDOW_END_H


def next_window_open(now):
    """The next 08:00 at or after `now` (same tz as `now`)."""
    today8 = now.replace(hour=WINDOW_START_H, minute=0, second=0, microsecond=0)
    if now.hour < WINDOW_START_H:
        return today8
    return today8 + timedelta(days=1)


def _clean(v, limit=80):
    s = " ".join(str(v or "").split())
    return s[:limit]


def compose(name, business, phone, revenue, role, must_understand, verdict,
            ad_label="", pretty=lambda v: v):
    """-> (sms_text, eric_text). Short enough for the operator SMS cap, and
    never a raw choice value: `pretty` turns owner_/_founder_/_partner into
    words (lead_form.pretty)."""
    nm = _clean(name, 60) or "no name"
    biz = _clean(business, 60)
    rev = _clean(pretty(revenue), 30)
    rl = _clean(pretty(role), 30)
    mu = _clean(must_understand, 140)
    ph = _clean(phone, 24)
    v = _clean(verdict, 16)
    lines = [f"CALL NOW - form lead ({v})", nm + (f" - {biz}" if biz else "")]
    band = " / ".join(x for x in (rev, rl) if x)
    if band:
        lines.append(band)
    if mu:
        lines.append(f"Must understand: {mu}")
    lines.append(ph)
    if ad_label:
        lines.append(f"ad {_clean(ad_label, 40)}")
    lines.append("First call inside the hour.")
    sms = "\n".join(lines)
    eric = (f":telephone_receiver: *CALL NOW — form lead* ({v}) · *{nm}*"
            + (f" · {biz}" if biz else "")
            + (f"\n{band}" if band else "")
            + (f"\nMust understand: _{mu}_" if mu else "")
            + f"\n`{ph}`" + (f" · ad {_clean(ad_label, 40)}" if ad_label else "")
            + "\n_Michael's rule: first call inside the hour (8 AM–8 PM ET)._")
    return sms, eric


def enqueue(queue, sms, eric, lead_key, now):
    """Return the queue with one entry added (newest last), capped."""
    q = list(queue or [])
    q.append({"sms": sms, "eric": eric, "lead_key": str(lead_key or ""),
              "queued_at": now.isoformat()})
    return q[-MAX_QUEUE:]


def due(queue, now):
    """(to_send, remaining): everything queued is due once the window is open."""
    q = list(queue or [])
    if not q or not in_window(now):
        return [], q
    return q, []


def queued_note(now):
    nxt = next_window_open(now)
    return f"text to Michael queued for {nxt.strftime('%-I:%M %p').replace(':00', '')} ET"
