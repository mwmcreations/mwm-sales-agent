"""lead_reply.py — PATCH #262. A lead's answer by email is an answer.

WHAT HAPPENED (Mon 2 Nov 2026)
──────────────────────────────
Fri 30 Oct 08:54 — two "Moving our studio visit on Monday" emails went out
(Vicente Orellana, Shawnie Whitaker), each offering two dates and asking the
lead to reply with one. Nothing in the machine knew those emails existed.

  • Shawnie replied Mon 02:34: "Thursday, November 5 at 2:30 PM works
    perfectly for me!" The info@ watcher saw it at 02:37 and posted
    "Possible lead" in #dev. That was all. No event, no invite, no
    confirmation — the calendar stayed blank until Michael read the thread
    himself at 10:40 and asked why nothing had happened.
  • Vicente never saw his email. His Monday 10:00 event stayed on the
    calendar, so Saturday's T-48h WhatsApp reminder CONFIRMED Monday to him,
    he answered "Likewise", drove in from Tampa in the rain and found the
    door closed.

Michael: "no automation watched that email and put that day on the calendar
… do something to fix this for future communications with the same issue, so
we don't have anything out of place."

WHAT THIS MODULE IS
───────────────────
The pure half of the fix. Nothing here touches Gmail, the calendar, Slack or
the clock — app.py feeds it text and a `now`, it hands back a decision.

  parse_datetimes(text, now, tz)  the dates/times the lead wrote, resolved
  offers_from_text(text, now, tz) the options OUR email offered (a reply quotes
                                  them), so an email a human sent by hand works
  match_offer(text, offers, …)    which offer they picked — or "ambiguous",
                                  or a new time they proposed
  intent(text)                    choice / decline / later / question / ack / other
  body_text(gmail_message)        text/plain out of a Gmail `format="full"` body
  strip_quoted(text)              their words only — no quoted thread, no ">" lines
  reschedule_text / reschedule_email / confirmation_email — the copy

The reading of a message BODY happens in app.py on purpose: info_inbox.py is
contractually metadata-only (test_info_inbox greps it for format="full"), and
that contract stands. Only a message from a KNOWN LEAD gets its body read,
and only to act on it.
"""

import base64
import html as _html
import re
from datetime import datetime, timedelta, time as _time

MOVING_PROP = "mwm_moving"          # extendedProperties.private flag on an event
MOVING_PREFIX = "⏳ MOVING — "      # title prefix when an event is kept but moving

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WD_ABBR = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "weds": 2, "thu": 3, "thur": 3, "thurs": 3,
            "fri": 4, "sat": 5, "sun": 6}
_MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
           "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
           "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
           "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12}

_WD_RE = r"(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|weds?|thur?s?|fri|sat|sun)\.?"
_MON_RE = r"(?P<mon>january|february|march|april|may|june|july|august|september|sept|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\.?"
_DOM_RE = r"(?P<dom>\d{1,2})(?:st|nd|rd|th)?"
_TIME_RE = r"(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?|noon)?"
_AT = r"(?:\s*,?\s*(?:at|@|-|–)?\s*)"

# Order matters: the most specific shape first, so "Thursday, November 5 at
# 2:30 PM" is one match, not a weekday match plus a month match.
_PATTERNS = [
    # Thursday, November 5 at 2:30 PM · Nov 5 2:30pm · November 5th, 2 pm
    ("mon_dom_time", re.compile(
        r"(?:" + _WD_RE + r"\s*,?\s*)?" + _MON_RE + r"\s+" + _DOM_RE + r"(?:\s*,?\s*\d{4})?" + _AT + _TIME_RE + r"\b", re.I)),
    # 11/5 at 2:30 pm · 11/05 2pm
    ("num_date_time", re.compile(
        r"\b(?P<mn>\d{1,2})/(?P<dn>\d{1,2})(?:/(?:\d{2}|\d{4}))?" + _AT + _TIME_RE + r"\b", re.I)),
    # Wednesday the 4th 2 pm · Wednesday 4th at 2:00 · Thursday at 2:30 · Thursday 2:30 PM
    ("wd_dom_time", re.compile(
        _WD_RE + r"\s*,?\s*(?:the\s+)?(?:" + _DOM_RE + r")?" + _AT + _TIME_RE + r"\b", re.I)),
    # the 4th at 2pm · on the 5th 2:30
    ("dom_time", re.compile(
        r"\b(?:on\s+)?the\s+" + _DOM_RE + _AT + _TIME_RE + r"\b", re.I)),
    # Thursday, November 5 (no time) · Nov 5
    ("mon_dom", re.compile(
        r"(?:" + _WD_RE + r"\s*,?\s*)?" + _MON_RE + r"\s+" + _DOM_RE + r"\b", re.I)),
    # 11/5 (no time)
    ("num_date", re.compile(r"\b(?P<mn>\d{1,2})/(?P<dn>\d{1,2})(?:/(?:\d{2}|\d{4}))?\b")),
    # Thursday (alone) · Wednesday the 4th
    ("wd", re.compile(_WD_RE + r"(?:\s+the\s+" + _DOM_RE + r")?\b", re.I)),
    # 2:30 pm · 2pm (time alone — only meaningful against an offer)
    ("time", re.compile(r"\b(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))\s*(?P<ap>a\.?m\.?|p\.?m\.?)?\b|\b(?P<h2>\d{1,2})\s*(?P<ap2>a\.?m\.?|p\.?m\.?)\b", re.I)),
]

_NEG_RE = re.compile(r"(?i)\b(not|n't|cannot|can'?t|won'?t|unable|no|neither|instead of|rather than|doesn'?t|don'?t|isn'?t)\b")
# "Thursday doesn't work" — the no comes AFTER the day. A short look ahead.
_NEG_AFTER_RE = re.compile(r"(?i)^\s*(?:is\s+)?(doesn'?t|does not|won'?t|isn'?t|is not|not\b|no\b|can'?t|cannot|is out|is bad|is tough|is hard|would not|wouldn'?t)")
_ORD_RE = re.compile(r"(?i)(?:^|\b)(?P<pre>option\s*|#|number\s*|choice\s*)?(?P<n>[12])\b(?!\s*(?::|\d|pm|am|st|nd|rd|th|/))|\b(?P<w>first|second|1st|2nd|former|latter)\b(?:\s+(?:one|option|slot|time))?")
_QUOTE_HEADER_RE = re.compile(r"(?im)^[^\n]*\b(wrote|escreveu|escribió):\s*$|^(Date|Sent|Enviado|Fecha):[^\n]*$")


def _wd_index(word):
    w = (word or "").lower().rstrip(".")
    if w in _WEEKDAYS:
        return _WEEKDAYS.index(w)
    return _WD_ABBR.get(w)


def _hm(h, m, ap):
    """Hour/minute from the pieces; business-hours guess when am/pm is absent.
    A studio runs 9–5: 1–6 reads PM, 7–11 reads AM, 12 is noon."""
    try:
        h = int(h)
    except Exception:
        return None
    m = int(m) if m else 0
    if ap:
        a = ap.lower().replace(".", "")
        if a == "noon":
            return (12, 0)
        if a.startswith("p") and h != 12:
            h += 12
        if a.startswith("a") and h == 12:
            h = 0
    else:
        if 1 <= h <= 6:
            h += 12
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return (h, m)


def _next_weekday(now, wd, allow_today=True):
    d = now.date()
    delta = (wd - d.weekday()) % 7
    if delta == 0 and not allow_today:
        delta = 7
    return d + timedelta(days=delta)


def _date_for_dom(now, dom, month=None):
    """A day-of-month, in the named month or the nearest month ahead."""
    try:
        dom = int(dom)
    except Exception:
        return None
    if not (1 <= dom <= 31):
        return None
    y, mth = now.year, (month or now.month)
    if month is None and dom < now.day:
        mth += 1
    elif month is not None and (mth < now.month or (mth == now.month and dom < now.day)):
        y += 1
    if mth > 12:
        mth -= 12
        y += 1
    try:
        return datetime(y, mth, dom).date()
    except ValueError:
        return None


def parse_datetimes(text, now, tz=None):
    """Every date/time the text mentions, resolved against `now`.

    -> [{"date": date|None, "time": (h, m)|None, "dt": datetime|None,
         "text": <matched words>, "negated": bool, "kind": <pattern name>}]
    `dt` is set only when both a date and a time are known. Overlapping
    matches are collapsed: the earlier, longer pattern wins its span."""
    text = str(text or "")
    out, taken = [], []
    for name, rx in _PATTERNS:
        for mt in rx.finditer(text):
            s, e = mt.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            g = mt.groupdict()
            date = None
            hm = None
            if name in ("mon_dom_time", "mon_dom"):
                mon = _MONTHS.get((g.get("mon") or "").lower().rstrip("."))
                date = _date_for_dom(now, g.get("dom"), month=mon) if mon else None
                # a weekday written beside the date is the lead's words; the
                # date is what we trust, so a mismatch is not fatal
            elif name in ("num_date_time", "num_date"):
                try:
                    date = _date_for_dom(now, g.get("dn"), month=int(g.get("mn")))
                except Exception:
                    date = None
            elif name == "wd_dom_time":
                wd = _wd_index(g.get("wd"))
                if g.get("dom"):
                    date = _date_for_dom(now, g.get("dom"))
                    if date is not None and wd is not None and date.weekday() != wd:
                        # "Wednesday the 4th": the day-of-month wins when it is
                        # a real date; the weekday was a slip.
                        pass
                elif wd is not None:
                    date = _next_weekday(now, wd)
            elif name == "dom_time":
                date = _date_for_dom(now, g.get("dom"))
            elif name == "wd":
                wd = _wd_index(g.get("wd"))
                if g.get("dom"):
                    date = _date_for_dom(now, g.get("dom"))
                elif wd is not None:
                    date = _next_weekday(now, wd)
            if name in ("mon_dom_time", "num_date_time", "wd_dom_time", "dom_time"):
                hm = _hm(g.get("h"), g.get("m"), g.get("ap"))
                if hm is None:
                    continue
            elif name == "time":
                hm = _hm(g.get("h") or g.get("h2"), g.get("m"), g.get("ap") or g.get("ap2"))
                if hm is None:
                    continue
            if date is None and hm is None:
                continue
            # "Thursday at 2:30" with a weekday that already passed today still
            # means next week once the hour is gone.
            if date is not None and hm is not None and name in ("wd_dom_time", "wd") and not g.get("dom"):
                if date == now.date() and (hm[0], hm[1]) <= (now.hour, now.minute):
                    date = date + timedelta(days=7)
            dt = None
            if date is not None and hm is not None:
                dt = datetime.combine(date, _time(hm[0], hm[1]))
                if tz is not None:
                    try:
                        dt = tz.localize(dt)
                    except Exception:
                        dt = dt.replace(tzinfo=tz)
            # the negation has to be in THIS clause: "Thursday doesn't work,
            # Friday is fine" must not carry the no over the comma.
            lead_in = re.split(r"[,.;!?\n]|\bbut\b|\band\b|\bor\b", text[max(0, s - 28):s])[-1]
            follow = text[e:e + 24]
            out.append({"date": date, "time": hm, "dt": dt, "text": mt.group(0).strip(),
                        "negated": bool(_NEG_RE.search(lead_in) or _NEG_AFTER_RE.search(follow)),
                        "kind": name})
            taken.append((s, e))
    out.sort(key=lambda r: text.find(r["text"]))
    return out


def _slot_dt(slot, tz=None):
    """An offer's datetime from its ISO id (tz-aware when it carries an offset)."""
    sid = str((slot or {}).get("id") or (slot or {}).get("slot_id") or "")
    try:
        dt = datetime.fromisoformat(sid)
    except Exception:
        return None
    if dt.tzinfo is None and tz is not None:
        try:
            dt = tz.localize(dt)
        except Exception:
            dt = dt.replace(tzinfo=tz)
    return dt


def offers_from_text(text, now, tz=None, limit=4):
    """The options OUR email offered, read back out of the lead's reply (a reply
    quotes the message it answers). Only full date+time mentions count, so a
    stray "Thursday" in a sentence never becomes an offer.
    -> [{"id": ISO, "display": "Thursday, November 5 at 2:30 PM"}]"""
    out, seen = [], set()
    # the quote header ("On Fri, Oct 30, 2026 at 8:54 AM … wrote:") is a date
    # too — it is the date WE wrote, not an option.
    text = _QUOTE_HEADER_RE.sub(" ", str(text or ""))
    for c in parse_datetimes(text, now, tz):
        if c["dt"] is None:
            continue
        key = c["dt"].isoformat()
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": key, "display": c["dt"].strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")})
        if len(out) >= limit:
            break
    return out


def match_offer(text, offers, now, tz=None):
    """Which offered slot the lead picked.

    -> {"slot": offer|None, "via": "ordinal"|"datetime"|"date"|"time"|"weekday"|None,
        "ambiguous": bool, "proposed": datetime|None, "candidates": [...]}
    `proposed` is set when nothing offered matched but the lead named exactly
    one full date+time of their own (the Pineda shape: "can we do the 6th at
    3?"). The caller checks the calendar before booking a proposal."""
    text = str(text or "")
    offers = [o for o in (offers or []) if isinstance(o, dict)]
    res = {"slot": None, "via": None, "ambiguous": False, "proposed": None, "candidates": []}
    cands = [c for c in parse_datetimes(text, now, tz) if not c["negated"]]
    res["candidates"] = cands
    odt = [(_slot_dt(o, tz), o) for o in offers]
    odt = [(d, o) for d, o in odt if d is not None]

    # 1. exact date+time
    hits = []
    for c in cands:
        if c["dt"] is None:
            continue
        for d, o in odt:
            if d.date() == c["dt"].date() and (d.hour, d.minute) == (c["dt"].hour, c["dt"].minute):
                hits.append(o)
    hits = _dedupe(hits)
    if len(hits) == 1:
        res.update(slot=hits[0], via="datetime")
        return res
    if len(hits) > 1:
        res["ambiguous"] = True
        return res

    # 2. a date with no time, or a weekday — one offer that day
    hits = []
    for c in cands:
        if c["date"] is None or c["dt"] is not None:
            continue
        same = [o for d, o in odt if d.date() == c["date"]]
        if len(same) == 1:
            hits.append(same[0])
        elif len(same) > 1:
            # "Thursday" when both offers are Thursday: the time decides, if given
            if c["time"]:
                same_t = [o for d, o in odt if d.date() == c["date"] and (d.hour, d.minute) == c["time"]]
                if len(same_t) == 1:
                    hits.append(same_t[0])
                    continue
            res["ambiguous"] = True
            return res
    hits = _dedupe(hits)
    if len(hits) == 1:
        res.update(slot=hits[0], via="date")
        return res
    if len(hits) > 1:
        res["ambiguous"] = True
        return res

    # 3. a time alone — one offer at that time
    hits = []
    for c in cands:
        if c["time"] is None or c["date"] is not None:
            continue
        same = [o for d, o in odt if (d.hour, d.minute) == c["time"]]
        if len(same) == 1:
            hits.append(same[0])
        elif len(same) > 1:
            res["ambiguous"] = True
            return res
    hits = _dedupe(hits)
    if len(hits) == 1:
        res.update(slot=hits[0], via="time")
        return res
    if len(hits) > 1:
        res["ambiguous"] = True
        return res

    # 4. an ordinal — "option 2", "the first one", a bare "1"
    if offers and not cands:
        mt = _ORD_RE.search(text.strip())
        if mt:
            n = mt.group("n")
            w = (mt.group("w") or "").lower()
            idx = None
            # a bare digit is an answer only in a short reply ("2", "2 please",
            # "#2"); inside a sentence it is a number ("I'll bring 2 people")
            if n and not mt.group("pre") and len(text.strip()) > 20:
                n = None
            if n:
                idx = int(n) - 1
            elif w in ("first", "1st", "former"):
                idx = 0
            elif w in ("second", "2nd", "latter"):
                idx = 1
            if idx is not None and idx < len(offers):
                res.update(slot=offers[idx], via="ordinal")
                return res

    # 5. nothing offered matched — did they propose exactly one full time?
    full = _dedupe_dt([c["dt"] for c in cands if c["dt"] is not None])
    if len(full) == 1:
        res["proposed"] = full[0]
    elif len(full) > 1:
        res["ambiguous"] = True
    return res


def _dedupe(items):
    out, seen = [], set()
    for o in items:
        k = str(o.get("id") or o.get("slot_id") or o.get("display"))
        if k not in seen:
            seen.add(k)
            out.append(o)
    return out


def _dedupe_dt(dts):
    out, seen = [], set()
    for d in dts:
        k = d.isoformat()
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


_DECLINE_RE = re.compile(
    r"(?i)(not interested|no longer (interested|need)|cancel|won'?t be (able|coming|attending)|"
    r"can'?t make (it|this)|unsubscribe|remove me|stop (emailing|contacting)|"
    r"pass (for now|on this)|(went|going) (with|in) (another|a different)|no thank)")
_LATER_RE = re.compile(
    r"(?i)(\blater\b|next (month|year|quarter)|in a (few|couple of) (weeks|months)|"
    r"reach (out|back) (in|after)|circle back|after the holidays|not right now|"
    r"touch base (in|after)|follow up (in|after|next)|busy (this|next|until))")
_ACK_RE = re.compile(r"(?i)^\W*(thanks?( you)?|thank you|noted|ok(ay)?|got it|great|perfect|sounds good|"
                     r"awesome|see you (then|there)|will do|received|confirmed?)\b[\s\S]{0,60}$")

INTENT_CHOICE = "choice"
INTENT_DECLINE = "decline"
INTENT_LATER = "later"
INTENT_QUESTION = "question"
INTENT_ACK = "ack"
INTENT_OTHER = "other"


def intent(text, matched=None):
    """A coarse read of what the lead wants. `matched` is match_offer()'s result
    when the caller has one — a chosen slot is a choice whatever else is said."""
    t = str(text or "").strip()
    if matched and (matched.get("slot") or matched.get("proposed")):
        return INTENT_CHOICE
    if not t:
        return INTENT_OTHER
    if _DECLINE_RE.search(t):
        return INTENT_DECLINE
    if _LATER_RE.search(t):
        return INTENT_LATER
    if "?" in t:
        return INTENT_QUESTION
    if len(t) <= 160 and _ACK_RE.match(t):
        return INTENT_ACK
    return INTENT_OTHER


# ── reading a Gmail body ────────────────────────────────────────────────────

_QUOTE_CUT = re.compile(
    r"(?is)(\n|^)\s*(On\s[^\n]{0,220}?wrote:\s*\n|-{2,}\s*Original Message\s*-{2,}|"
    r"From:\s[^\n]{0,200}\n(?:Sent|Date):|_{10,}\s*\n\s*From:|"
    r"Em\s[^\n]{0,220}?escreveu:\s*\n|El\s[^\n]{0,220}?escribió:\s*\n)")
_SIG_CUT = re.compile(r"(?m)^\s*(--\s*$|Sent from my (iPhone|iPad|Galaxy|Android)|Get Outlook for)")


def strip_quoted(text):
    """The lead's own words: everything before the quoted thread, minus ">"
    lines and a trailing mobile signature. Never returns None."""
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    m = _QUOTE_CUT.search(t)
    if m:
        t = t[:m.start()]
    lines = [ln for ln in t.split("\n") if not ln.lstrip().startswith(">")]
    t = "\n".join(lines)
    m = _SIG_CUT.search(t)
    if m and m.start() > 0:
        t = t[:m.start()]
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _b64(data):
    try:
        s = str(data or "")
        s += "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s.encode("ascii")).decode("utf-8", "replace")
    except Exception:
        return ""


def _html_to_text(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", str(h or ""))
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", h)
    h = re.sub(r"(?i)<li[^>]*>", "• ", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = _html.unescape(h).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", h)


def body_text(message):
    """text/plain from a Gmail users.messages.get(format='full') resource;
    the HTML part flattened when there is no plain part; '' when neither."""
    payload = (message or {}).get("payload") or {}
    plain, rich = [], []

    def walk(p):
        mt = str(p.get("mimeType") or "").lower()
        data = ((p.get("body") or {}).get("data"))
        if mt == "text/plain" and data:
            plain.append(_b64(data))
        elif mt == "text/html" and data:
            rich.append(_b64(data))
        for sub in (p.get("parts") or []):
            walk(sub)

    walk(payload)
    if plain:
        return "\n".join(plain)
    if rich:
        return _html_to_text("\n".join(rich))
    return ""


# ── copy ────────────────────────────────────────────────────────────────────

def _fn(name):
    n = str(name or "").strip().split()
    return n[0].title() if n and n[0].isupper() else (n[0] if n else "there")


def _when(slot):
    d = _slot_dt(slot)
    if d is None:
        return str((slot or {}).get("display") or "")
    return d.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")


def reschedule_text(name, old_display, slots, who="Michael"):
    """SMS / WhatsApp: the options, numbered, one question. Plain ASCII."""
    fn = _fn(name)
    opts = [s for s in (slots or []) if isinstance(s, dict)][:2]
    if len(opts) == 2:
        ask = (f"Would {_when(opts[0])} or {_when(opts[1])} work instead? "
               f"Reply 1 or 2, or send a time that suits you.")
    elif len(opts) == 1:
        ask = f"Would {_when(opts[0])} work instead? Reply YES, or send a time that suits you."
    else:
        ask = "Which day this week or next would work instead? Send me a time."
    old = f" on {old_display}" if old_display else ""
    return (f"Hi {fn}, Maya from Michael Moraes' team. {who} has to move "
            f"your Studio Visit{old} - sorry about that. {ask}")


def reschedule_email(name, old_display, slots, address="", who="Michael"):
    """(subject, html, text) — the same offer by email, from info@."""
    fn = _fn(name)
    opts = [s for s in (slots or []) if isinstance(s, dict)][:3]
    subject = "Moving your studio visit" + (f" on {old_display.split(' at ')[0]}" if old_display else "")
    old = f" on {old_display}" if old_display else ""
    lines_txt = [f"Hi {fn},", "",
                 f"{who} has to move your Studio Visit{old} — sorry for the change.", ""]
    li = "".join(f"<li>{_html.escape(_when(s))}</li>" for s in opts)
    if opts:
        lines_txt.append("Would one of these work for you?")
        lines_txt += [f"  {i + 1}. {_when(s)}" for i, s in enumerate(opts)]
        lines_txt += ["", "Just reply with the one that suits you (or another time that works) and the updated invite goes out right away."]
        ask_html = (f"<p>Would one of these work for you?</p><ol>{li}</ol>"
                    f"<p>Just reply with the one that suits you (or another time that works) and the updated invite goes out right away.</p>")
    else:
        lines_txt += ["Which day this week or next would work for you? Reply with a time and the updated invite goes out right away."]
        ask_html = "<p>Which day this week or next would work for you? Reply with a time and the updated invite goes out right away.</p>"
    if address:
        lines_txt += ["", f"Studio: {address}"]
    lines_txt += ["", "Best,", "Maya", "MWM Creations & Studios", "info@mwmcreations.com"]
    html_body = (
        '<div style="font-family:Helvetica,Arial,sans-serif;font-size:15px;line-height:23px;color:#222222;max-width:560px">'
        f"<p>Hi {_html.escape(fn)},</p>"
        f"<p>{_html.escape(who)} has to move your Studio Visit{_html.escape(old)} — sorry for the change.</p>"
        + ask_html
        + (f'<p style="color:#555">Studio: {_html.escape(address)}</p>' if address else "")
        + '<p>Best,<br><strong>Maya</strong><br>MWM Creations &amp; Studios<br>'
          '<span style="color:#777777;font-size:13px">info@mwmcreations.com</span></p></div>')
    return subject, html_body, "\n".join(lines_txt)


def confirmation_email(name, when_display, address="", invite_sent=True, who="Michael"):
    """(subject, html, text) — 'booked, here is when', sent as a reply in the thread."""
    fn = _fn(name)
    subject = f"Confirmed: your Studio Visit — {when_display}"
    inv = ("The calendar invite is on its way to this address." if invite_sent
           else "A calendar invite follows shortly.")
    text = (f"Hi {fn},\n\nPerfect — you're booked for {when_display} with {who} at MWM Studios. {inv}\n"
            + (f"\nStudio: {address}\n" if address else "")
            + "\nIf anything changes, just reply here or text us.\n\nBest,\nMaya\nMWM Creations & Studios\ninfo@mwmcreations.com")
    html_body = (
        '<div style="font-family:Helvetica,Arial,sans-serif;font-size:15px;line-height:23px;color:#222222;max-width:560px">'
        f"<p>Hi {_html.escape(fn)},</p>"
        f"<p>Perfect — you're booked for <strong>{_html.escape(when_display)}</strong> with {_html.escape(who)} at MWM Studios. {inv}</p>"
        + (f'<p style="color:#555">Studio: {_html.escape(address)}</p>' if address else "")
        + "<p>If anything changes, just reply here or text us.</p>"
          '<p>Best,<br><strong>Maya</strong><br>MWM Creations &amp; Studios<br>'
          '<span style="color:#777777;font-size:13px">info@mwmcreations.com</span></p></div>')
    return subject, html_body, text


def escalation_sms(name, phone, snippet, kind="reply"):
    """The text to Michael when an email needs a human. Short, with the number."""
    nm = str(name or "A lead").strip() or "A lead"
    ph = str(phone or "").strip()
    what = {"reply": "replied by email and it is not a date pick",
            "ambiguous": "replied by email naming two times",
            "declined": "replied by email and is backing out",
            "later": "replied by email: not now, later",
            "taken": "replied by email asking for a time that is taken",
            "silent": "has not answered the reschedule options"}.get(kind, "replied by email")
    s = re.sub(r"\s+", " ", str(snippet or "")).strip()
    s = (s[:140] + "...") if len(s) > 143 else s
    tail = ("Maya keeps watching every channel for their answer."
            if kind == "silent" else "Maya has stopped the chase; the reply is yours.")
    return (f"{nm} {what}." + (f' "{s}"' if s else "")
            + (f" Call {ph}." if ph else "") + " " + tail)
