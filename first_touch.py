"""PATCH #267 — the first touch after a form lead: WhatsApp first, SMS as the
backstop, email as the written copy.

Michael, Tue 3 Nov 2026, after ERIC's assignment ("every booking since Oct 1
came out of a WhatsApp conversation; 0 replies to 19 chase texts/emails") and
his own instinct for SMS now that the form verifies the number: *do both, in
sequence.* The template goes to WhatsApp (held to the transactional window
like SMS); if WhatsApp does not show DELIVERED inside WA_WAIT_MIN the same
message goes as SMS; the email with the full details goes at intake either
way. Nobody is pinged twice at once.

Why the template is a UTILITY reply and not the sales line: Meta does not
deliver MARKETING templates to US numbers (wa_templates.usable() has refused
them since #250 for that reason), so the WhatsApp copy reads as the answer to
the lead's own request — times to confirm — and the SMS keeps Michael's
fuller "free 30-minute Studio Strategy Visit" wording.

Pure: no clock, no network, no app state. The app passes `now` in.
"""
from datetime import datetime, timedelta

# Meta name of the template (submitted 3 Nov 2026, UTILITY, en_US). The body
# on Meta's side is the contract; the app only fills {{1}} {{2}} {{3}}:
#   Hi {{1}}, this is Maya from Michael Moraes' team at MWM Creations. We
#   received your request about video for {{2}}. To schedule your studio
#   visit with Michael, these times are available: {{3}}. Reply 1 or 2 to
#   confirm, or VIDEO if you would prefer a 15-minute video call instead.
WA_TEMPLATE = "mwm_form_reply_times"
WA_LANG = "en_US"

# How long WhatsApp gets to show DELIVERED before the SMS goes.
WA_WAIT_MIN = 30
# A pending WhatsApp first touch that could not go (quiet hours, template not
# yet approved) is dropped after this many hours — the chase chain takes over.
WA_MAX_WAIT_H = 14

STATUS_DELIVERED = ("delivered", "read")
STATUS_FAILED = ("failed",)

REASON_WA_WAIT = "wa_wait"


def first_name(name, fallback="there"):
    parts = [p for p in str(name or "").replace(",", " ").split() if p]
    if not parts:
        return fallback
    fn = parts[0].strip(".,'\"")
    return fn if fn and fn.lower() not in ("unknown", "there", "n/a") else fallback


def _when_short(iso_or_display):
    """'Mon Nov 9 at 10:00 AM' from a slot id (ISO) — falls back to the
    display string the calendar gave us."""
    s = str(iso_or_display or "")
    try:
        d = datetime.fromisoformat(s)
        return (d.strftime("%a %b %d at %I:%M %p")
                .replace(" 0", " ").replace(" 0", " "))
    except Exception:
        return s


def times_text(slots):
    """{{3}}: '1) Mon Nov 9 at 10:00 AM 2) Tue Nov 10 at 3:00 PM'. One slot
    → '1) …'. No slot → a sentence that still reads with 'Reply 1 or 2'."""
    out = []
    for i, s in enumerate(list(slots or [])[:2]):
        if isinstance(s, dict):
            when = _when_short(s.get("id") or s.get("display"))
        else:
            when = _when_short(s)
        if when:
            out.append(f"{i + 1}) {when}")
    if not out:
        return "1) this week 2) next week - just tell me the day that suits you"
    return " ".join(out)


def wa_params(name, business, slots):
    """The three body parameters, in order. Never empty strings — Meta
    rejects an empty parameter and the sentence has to read either way."""
    biz = " ".join(str(business or "").split())
    return [first_name(name), biz or "your business", times_text(slots)]


def plan(base_plan, dialable, consent, wa_ready):
    """Rewrite lead_form.first_touch_plan()'s channels for the WhatsApp-first
    rule. `base_plan` is the list of (channel, why) it returned.

    - wa_ready (template approved on Meta) + dialable + consent → the 'sms'
      entry becomes 'whatsapp' (the SMS is armed as the fallback by the
      sender, not listed here).
    - otherwise the base plan stands, untouched.
    The same consent box gates both: a number we may not text, we do not
    WhatsApp either."""
    if not (wa_ready and dialable and consent):
        return list(base_plan or [])
    out = []
    for chan, why in base_plan or []:
        if chan == "sms":
            out.append(("whatsapp", "template approved + consented US mobile; "
                                    f"SMS follows in {WA_WAIT_MIN} min unless delivered"))
        else:
            out.append((chan, why))
    if not any(c == "whatsapp" for c, _ in out):
        out.insert(0, ("whatsapp", "template approved + consented US mobile"))
    return out


def sms_pending_after_wa(core, now, wamid):
    """The SMS fallback record, armed the moment the template is accepted."""
    return {"since": now.isoformat(), "core": core, "reason": REASON_WA_WAIT,
            "wamid": str(wamid or ""),
            "not_before": (now + timedelta(minutes=WA_WAIT_MIN)).isoformat()}


def sms_due(pending, wa_status, now):
    """('send'|'wait'|'drop', why) for a pending SMS that is waiting on
    WhatsApp. Any pending record that is NOT the wa_wait kind is 'send' —
    the caller's old rules (quiet hours, cap) still apply at send time."""
    if not isinstance(pending, dict) or pending.get("reason") != REASON_WA_WAIT:
        return "send", "not waiting on whatsapp"
    st = str(wa_status or "").lower()
    if st in STATUS_DELIVERED:
        return "drop", f"whatsapp {st}"
    if st in STATUS_FAILED:
        return "send", "whatsapp failed"
    try:
        nb = datetime.fromisoformat(str(pending.get("not_before") or ""))
    except Exception:
        return "send", "not_before unreadable"
    if now >= nb:
        return "send", f"whatsapp not delivered in {WA_WAIT_MIN} min"
    return "wait", "inside the whatsapp window"


def wamid_from_response(resp):
    try:
        return str(((resp or {}).get("messages") or [{}])[0].get("id") or "")
    except Exception:
        return ""


def note_status(rec, wamid, status, now):
    """Record a Meta status callback on the lead's first-touch WhatsApp. True
    when it was ours (wamid matches)."""
    ft = (rec or {}).get("first_touch_wa")
    if not isinstance(ft, dict) or not wamid or ft.get("wamid") != wamid:
        return False
    st = str(status or "").lower()
    order = {"sent": 1, "delivered": 2, "read": 3, "failed": 9}
    cur = str(ft.get("status") or "")
    # never let a late 'sent' overwrite 'delivered'
    if order.get(st, 0) >= order.get(cur, 0) or st == "failed":
        ft["status"] = st
        ft[f"{st}_at"] = now.isoformat()
    return True


def wa_pending(params, core, now):
    """A WhatsApp first touch that must wait (quiet hours)."""
    return {"since": now.isoformat(), "params": list(params), "core": core}


def wa_pending_expired(pending, now):
    try:
        since = datetime.fromisoformat(str(pending.get("since") or ""))
    except Exception:
        return True
    return (now - since).total_seconds() / 3600.0 > WA_MAX_WAIT_H


def in_window(now, start_h, end_h):
    return start_h <= now.hour < end_h


def summary(lead_data):
    """/health: how many first touches are mid-flight."""
    wa_pend = sms_wait = sent = delivered = 0
    for rec in (lead_data or {}).values():
        if not isinstance(rec, dict):
            continue
        if isinstance(rec.get("first_touch_wa_pending"), dict):
            wa_pend += 1
        p = rec.get("first_touch_sms_pending")
        if isinstance(p, dict) and p.get("reason") == REASON_WA_WAIT:
            sms_wait += 1
        ft = rec.get("first_touch_wa")
        if isinstance(ft, dict) and ft.get("wamid"):
            sent += 1
            if str(ft.get("status") or "") in STATUS_DELIVERED:
                delivered += 1
    return {"template": WA_TEMPLATE, "wa_pending_window": wa_pend,
            "sms_waiting_on_wa": sms_wait, "wa_sent": sent, "wa_delivered": delivered}
