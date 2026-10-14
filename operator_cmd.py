"""
operator_cmd.py — PATCH #161. Michael texting the line back.

The operator alert (#149/#157) texts Michael "unconfirmed: {name} {time} …
Call or text them now." On 14 Oct he answered the same number "He is
confirmed" and "Good morning" and nothing came back: the SMS path treated
him as a lead (Maya drafted a sales reply, the quiet-hours gate refused it
at 6:31). On WhatsApp his number has had Command Mode since day one.

PURE: recognising a confirmation in his words and picking which alert it
answers. app.py owns the pg list of recent alerts, the mark and the reply.
"""
import re
from datetime import datetime, timedelta

CONFIRM_WORDS = re.compile(
    r"\b(confirmed|confirm|confirmado|confirmada|is coming|are coming|will be there|he's in|she's in|they're in|all good|good to go)\b",
    re.I)
NEGATION = re.compile(r"\b(not|no|never|un-?confirmed|cancel+ed|cancel|isn'?t|won'?t|didn'?t|hasn'?t)\b", re.I)
ALL_WORDS = re.compile(r"\b(all|both|everyone|every one|the series|all three|all 3)\b", re.I)
RECENT_H = 24          # an alert older than this is not what he is answering


def is_confirmation(text):
    """True when the text says someone IS confirmed (and does not negate it)."""
    t = str(text or "").strip()
    if not t or len(t) > 200:
        return False
    return bool(CONFIRM_WORDS.search(t)) and not NEGATION.search(t)


def targets(text, alerts, now):
    """Which recent unconfirmed alerts the text answers. `alerts` is the pg
    list of {event_id, name, time, date, at (iso)}; newest last. One target
    (the most recent inside RECENT_H) unless the text says "all"/"both",
    then every alert inside the window. A name in the text narrows it."""
    t = str(text or "").lower()
    live = []
    for a in alerts or []:
        try:
            at = datetime.fromisoformat(str(a.get("at")))
        except Exception:
            continue
        if at.tzinfo is None and now.tzinfo is not None:
            at = at.replace(tzinfo=now.tzinfo)
        if now - at <= timedelta(hours=RECENT_H):
            live.append(a)
    if not live:
        return []
    named = [a for a in live if any(tok and len(tok) > 2 and tok in t
                                    for tok in str(a.get("name") or "").lower().split())]
    if named:
        return named if ALL_WORDS.search(t) else [named[-1]]
    if ALL_WORDS.search(t):
        return live
    return [live[-1]]


def reply_for(marked):
    """What Maya texts back once the mark is written."""
    if not marked:
        return ""
    if len(marked) == 1:
        a = marked[0]
        return (f"Got it - {a.get('name') or 'the visit'} at {a.get('time')} ({a.get('date')}) is marked confirmed. "
                f"No more nudges for that one.")
    names = "; ".join(f"{a.get('name') or 'visit'} {a.get('time')} ({a.get('date')})" for a in marked)
    return f"Got it - marked confirmed: {names}. No more nudges for those."


def split_sms(text, limit=450):
    """Chunks of at most `limit` characters on sentence/space boundaries."""
    s = " ".join(str(text or "").split())
    out = []
    while len(s) > limit:
        cut = max(s.rfind(". ", 0, limit), s.rfind(" ", 0, limit))
        if cut < limit // 2:
            cut = limit
        out.append(s[:cut + 1].strip() if s[cut:cut + 1] == "." else s[:cut].strip())
        s = s[cut + 1:].strip() if s[cut:cut + 1] in (".", " ") else s[cut:].strip()
    if s:
        out.append(s)
    return out
