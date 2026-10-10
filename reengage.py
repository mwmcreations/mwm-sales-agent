"""
reengage.py — PATCH #156/#158. The one-off "three studio visit slots this
week" push to the existing lead database (ERIC, 9 Oct 2026, item 3).

Tonight: the counts — who can be reached by email, who by SMS (marketing
consent), who has an open WhatsApp window, who is Orlando-area. Monday
10:00 AM ET: one send (email to everyone with an address; SMS only where
consent exists), tagged `source: reengage-oct12` so the scorecard keeps
them apart from ad leads.

PURE: classification and the summary. app.py supplies the record, the
consent record, the suppression answer and the clock.
"""
import re
from datetime import datetime, timedelta

ORLANDO_AREA_CODES = {"407", "321", "689"}          # Orlando metro
CENTRAL_FL_AREA_CODES = {"352", "386", "863", "772"}  # near enough to drive in
TAG = "reengage-oct12"

_CLIENT_REL = ("client", "existing_client", "new_client", "known")


def _digits(s):
    return re.sub(r"\D", "", str(s or ""))


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


def classify(key, rec, now, consent=None, email_suppressed=None, is_internal=None):
    """-> dict of flags for one lead record, or None when the lead is not a
    candidate at all (client, said no, do-not-contact, internal, test).

    consent: the sms_consent record for the phone ({} when none)
    email_suppressed(addr) -> (bool, reason)
    is_internal(phone) -> bool
    """
    rec = rec or {}
    k = str(key or "")
    if not isinstance(rec, dict):
        return None
    if rec.get("test_lead") or k.startswith("meta_lead_") and str(rec.get("name", "")).startswith("<test"):
        return None
    rel = str(rec.get("relationship") or "")
    if rel in _CLIENT_REL or rec.get("paid_at") or str(rec.get("outcome") or "").lower() in ("won", "client_won"):
        return None
    if isinstance(rec.get("disqualified"), dict) or rec.get("do_not_contact"):
        return None
    if str(rec.get("outcome") or "").lower() == "not_interested":
        return None
    phone = _digits(rec.get("phone") or (k if k.startswith("whatsapp:") else ""))
    if k.startswith("instagram:") or len(phone) >= 15:
        phone = _digits(rec.get("phone")) if len(_digits(rec.get("phone"))) in (10, 11) else ""
    if phone and len(phone) == 10:
        phone = "1" + phone
    if phone and is_internal and is_internal(phone):
        return None
    email = str(rec.get("email") or "").strip().lower()
    email_ok = bool(email and "@" in email)
    if email_ok and email_suppressed:
        try:
            sup, _ = email_suppressed(email)
            email_ok = not sup
        except Exception:
            email_ok = False
    us_mobile = bool(phone and len(phone) == 11 and phone.startswith("1"))
    c = consent or {}
    sms_ok = bool(us_mobile and str(c.get("status") or "").lower() == "yes"
                  and c.get("marketing") is not False and not rec.get("do_not_sms"))
    last = _aware(_parse(rec.get("last_message_time")), now)
    hours_since = ((now - last).total_seconds() / 3600.0) if last else None
    wa_open = bool(k.startswith("whatsapp:") and hours_since is not None and hours_since < 24)
    active_7d = bool(hours_since is not None and hours_since < 24 * 7)
    area = phone[1:4] if us_mobile else ""
    return {
        "key": k, "name": str(rec.get("name") or ""), "channel": (
            "whatsapp" if k.startswith("whatsapp:") else "instagram" if k.startswith("instagram:")
            else str(rec.get("channel") or rec.get("source") or "other")),
        "email": email_ok, "sms": sms_ok, "wa_open": wa_open, "active_7d": active_7d,
        "orlando": area in ORLANDO_AREA_CODES, "central_fl": area in CENTRAL_FL_AREA_CODES,
        "has_phone": us_mobile, "booked": bool(rec.get("booked")),
        "reachable": bool(email_ok or sms_ok),
    }


def summarize(rows):
    rows = [r for r in rows if r]
    n = len(rows)

    def c(flag):
        return sum(1 for r in rows if r.get(flag))

    return {
        "candidates": n,
        "with_email": c("email"),
        "with_sms_consent": c("sms"),
        "with_phone_no_consent": sum(1 for r in rows if r["has_phone"] and not r["sms"]),
        "open_whatsapp_window": c("wa_open"),
        "orlando_area": c("orlando"),
        "central_fl_outside_orlando": c("central_fl"),
        "email_or_sms": c("reachable"),
        "email_only": sum(1 for r in rows if r["email"] and not r["sms"]),
        "sms_only": sum(1 for r in rows if r["sms"] and not r["email"]),
        "both": sum(1 for r in rows if r["sms"] and r["email"]),
        "active_last_7d": c("active_7d"),
        "booked_flag": c("booked"),
        "orlando_reachable": sum(1 for r in rows if r["orlando"] and r["reachable"]),
        "by_channel": {ch: sum(1 for r in rows if r["channel"] == ch)
                       for ch in sorted({r["channel"] for r in rows})},
    }


# ── PATCH #158 — the send ────────────────────────────────────────────────────
# One email (and an SMS only where marketing consent exists) on Monday
# 12 Oct, 10:00 AM ET, after Michael OKs the copy. Michael's first person,
# no price, three named slots, reply or text Maya to book, "stop" honoured.

SEND_AT_KEY = "reengage_oct12_send_at"      # pg: ISO time the send is armed for
DONE_KEY = "reengage_oct12_done"            # pg: the summary once it ran
SUBJECT = "Three studio visit slots this week"
MAYA_WA = "+1 407-871-6473"


def _first(name):
    s = str(name or "").strip()
    if "@" in s:
        s = s.split("@", 1)[0]
    s = s.split()[0] if s.split() else ""
    s = re.sub(r"[^A-Za-zÀ-ɏ'\-]", "", s)
    return (s[:1].upper() + s[1:]) if s and len(s) <= 20 else "there"


def _slot_lines(slots):
    out = []
    for s in (slots or [])[:3]:
        d = s.get("display") if isinstance(s, dict) else str(s)
        if d:
            out.append(str(d).replace(" EST", "").replace(" EDT", ""))
    return out


def email_copy(name, slots):
    """(subject, html, text). The three slots are named at send time."""
    fn = _first(name)
    sl = _slot_lines(slots)
    slot_txt = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(sl)) if sl else "  (reply with a day that works)"
    slot_html = "".join(f"<li>{s}</li>" for s in sl) if sl else "<li>Reply with a day that works</li>"
    text = (
        f"Hi {fn},\n\n"
        f"Michael Moraes here, from MWM Creations & Studios in Orlando. You reached out to us a while "
        f"back, and I'd like to open the door again, simply: come and see the studio.\n\n"
        f"A studio visit is 30 minutes, free, and you leave with a clear plan for the videos your "
        f"customers need to see before they buy. No pitch deck.\n\n"
        f"I have three slots open this week:\n{slot_txt}\n\n"
        f"Reply to this email with the one you want, or text Maya on my team at {MAYA_WA}, "
        f"and she'll lock it in. If none of them work, send me a time that does.\n\n"
        f"If you'd rather not hear from us, just reply \"stop\" and that's the end of it.\n\n"
        f"Michael Moraes\n"
        f"MWM Creations & Studios\n"
        f"1500 Park Center Dr, Suite 230, Orlando, FL"
    )
    html = (
        f"<p>Hi {fn},</p>"
        f"<p>Michael Moraes here, from MWM Creations &amp; Studios in Orlando. You reached out to us a while "
        f"back, and I'd like to open the door again, simply: come and see the studio.</p>"
        f"<p>A studio visit is 30 minutes, free, and you leave with a clear plan for the videos your "
        f"customers need to see before they buy. No pitch deck.</p>"
        f"<p>I have three slots open this week:</p><ol>{slot_html}</ol>"
        f"<p>Reply to this email with the one you want, or text Maya on my team at "
        f"<b>{MAYA_WA}</b>, and she'll lock it in. If none of them work, send me a time that does.</p>"
        f"<p style=\"color:#666;font-size:13px\">If you'd rather not hear from us, just reply \"stop\" and that's the end of it.</p>"
        f"<p>Michael Moraes<br>MWM Creations &amp; Studios<br>1500 Park Center Dr, Suite 230, Orlando, FL</p>"
    )
    return SUBJECT, html, text


def sms_copy(name, slots):
    """Core of the marketing text (compose() wraps it with brand + STOP).
    Two slots at most, so it stays inside two segments."""
    fn = _first(name)
    sl = _slot_lines(slots)[:2]
    when = (" or ".join(sl)) if sl else "this week"
    return (f"Hi {fn}, Michael Moraes (MWM Studios). Three free studio-visit slots this week - "
            f"{when}. Reply with the one you want, or a time that works, and Maya books it.")


def is_due(send_at_iso, now):
    """True once `now` has reached the armed time (both tz-aware)."""
    if not send_at_iso:
        return False
    try:
        at = datetime.fromisoformat(str(send_at_iso))
    except Exception:
        return False
    if at.tzinfo is None and now.tzinfo is not None:
        at = at.replace(tzinfo=now.tzinfo)
    return now >= at
