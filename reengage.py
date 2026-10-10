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
