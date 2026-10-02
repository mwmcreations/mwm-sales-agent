"""
operator_alert.py — PATCH #149. Michael's operator alerts go by SMS + #eric.
Never WhatsApp.

Why this exists
  On 1 Oct the first real booked visit from the ad form (Michael Sessa,
  Tue 6 Oct 3 PM) was announced to Michael over WhatsApp. Meta refused it:
  more than 24 h had passed since Michael last wrote to Maya's number
  (131047 / window_expired). The send was prevented, and Michael never heard.
  The same thing happened twice more that day. An owner's alert must not
  depend on him having chatted with his own bot in the last 24 hours.

Rules
  1. ONE recipient: the operator number (MICHAEL_PHONE). Callers never pass a
     number, so this path can never text a lead.
  2. Transactional SMS over the Twilio Messaging Service. There is no lead
     consent gate, because he is the operator, not a lead. A do_not_sms mark
     on his number is still honoured (in the app-side sender), and a daily cap
     stops a bug from flooding his phone.
  3. Booking and lead alerts also post the same line to #eric (ERIC's ask,
     2 Oct 07:57). The line says whether the text went out, so a failed SMS is
     never a silent alert.
  4. WhatsApp is never used on this path.
  5. Every SMS failure goes to the error rail. The Slack line still lands.
"""
import hashlib
import re
import threading
import time
from datetime import datetime

KINDS = {
    "booking":  {"eric": True},
    "cancel":   {"eric": True},
    "lead":     {"eric": True},
    "expo":     {"eric": True},
    "briefing": {"eric": False},   # 1-h pre-visit brief, for Michael only
    "test":     {"eric": False},
}
SMS_MAX = 640              # ~4-5 segments; enough for a booking or a brief
DAILY_CAP_DEFAULT = 40
DEDUPE_S = 600             # the same alert twice in 10 min is a retry, not news
CAP_KEY = "operator_sms_day"

_lock = threading.Lock()
_recent = {}
_cfg = {}
_STATUS = {"sent": 0, "failed": 0, "refused": 0, "deduped": 0, "eric_posted": 0,
           "last_at": None, "last_kind": "", "last_sms": "", "channel": "sms+#eric",
           "configured": False}
_mem_day = {"day": "", "count": 0}

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍←-⇿⬀-⯿]")


def configure(*, sms_post, post_slack, report_error, operator_phone,
              eric_channel, daily_cap=DAILY_CAP_DEFAULT,
              pg_load=None, pg_save=None, today=None):
    """sms_post(to, body) -> {"ok": bool, "reason"/"sid"}; operator_phone() -> str."""
    _cfg.update(sms_post=sms_post, post_slack=post_slack, report_error=report_error,
                operator_phone=operator_phone, eric_channel=eric_channel,
                daily_cap=int(daily_cap), pg_load=pg_load, pg_save=pg_save,
                today=today or (lambda: datetime.now().strftime("%Y-%m-%d")))
    _STATUS["configured"] = True


def normalize(phone):
    """'whatsapp:+1 (813) 503-1224' / '8135031224' -> '+18135031224'; '' if unusable."""
    d = re.sub(r"\D", "", str(phone or ""))
    if len(d) == 10:
        d = "1" + d
    return "+" + d if len(d) >= 11 else ""


def plain(text):
    """Slack/WhatsApp markup -> a clean SMS. No emoji (they force UCS-2 and
    triple the segment count), no *bold*/_italic_/`code`, no blank-line runs."""
    s = _EMOJI.sub("", str(text or ""))
    s = re.sub(r"[*_`~]", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.strip()
    if len(s) > SMS_MAX:
        s = s[:SMS_MAX - 1].rstrip() + "…"
    return s


def _cap_take():
    """Count one send against today's cap. True if allowed."""
    day = _cfg["today"]()
    load, save = _cfg.get("pg_load"), _cfg.get("pg_save")
    st = None
    if load and save:
        try:
            st = load(CAP_KEY, {}) or {}
        except Exception:
            st = None
    if st is None:
        st = _mem_day
    if st.get("day") != day:
        st = {"day": day, "count": 0}
    if int(st.get("count", 0)) >= _cfg["daily_cap"]:
        return False
    st["count"] = int(st.get("count", 0)) + 1
    if load and save:
        try:
            save(CAP_KEY, st)
        except Exception:
            pass
    _mem_day.update(st)
    return True


def alert(kind, sms_text, eric_text=None):
    """Send one operator alert. Returns {"sms": "sent"|reason, "eric": bool}."""
    if kind not in KINDS:
        kind = "test"
    out = {"sms": "not_configured", "eric": False}
    if not _cfg:
        return out
    body = plain(sms_text)
    key = hashlib.sha256(f"{kind}|{body}".encode("utf-8")).hexdigest()[:16]
    now = time.time()
    with _lock:
        for k in [k for k, t in _recent.items() if now - t > DEDUPE_S]:
            _recent.pop(k, None)
        if key in _recent:
            _STATUS["deduped"] += 1
            out["sms"] = "deduped"
            return out
        _recent[key] = now

    # 1. the text to Michael
    to = normalize(_cfg["operator_phone"]())
    if not body:
        out["sms"] = "empty"
    elif not to:
        out["sms"] = "no_operator_phone"
    else:
        with _lock:
            allowed = _cap_take()
        if not allowed:
            out["sms"] = "daily_cap"
        else:
            try:
                res = _cfg["sms_post"](to, body) or {}
            except Exception as exc:
                res = {"ok": False, "reason": f"exception: {exc}"}
            out["sms"] = "sent" if res.get("ok") else str(res.get("reason") or "failed")
    if out["sms"] != "sent":
        with _lock:
            _recent.pop(key, None)   # a failed alert may be retried at once
    with _lock:
        if out["sms"] == "sent":
            _STATUS["sent"] += 1
        elif out["sms"] in ("daily_cap", "no_operator_phone", "empty", "do_not_sms",
                            "twilio_env_missing"):
            _STATUS["refused"] += 1
        else:
            _STATUS["failed"] += 1
        _STATUS.update(last_at=datetime.now().isoformat(timespec="seconds"),
                       last_kind=kind, last_sms=out["sms"])
    if out["sms"] != "sent":
        try:
            _cfg["report_error"](f"operator_sms_{out['sms'][:40]}",
                                 f"operator {kind} alert NOT texted to Michael",
                                 "the #eric line still went out" if KINDS[kind]["eric"] else "")
        except Exception:
            pass

    # 2. the same line in #eric, with the delivery outcome on it
    if KINDS[kind]["eric"]:
        line = (eric_text or sms_text or "").strip()
        tag = ("text to Michael: sent" if out["sms"] == "sent"
               else f"text to Michael: NOT sent ({out['sms']})")
        try:
            _cfg["post_slack"](_cfg["eric_channel"], f"{line}\n_{tag}_")
            out["eric"] = True
            with _lock:
                _STATUS["eric_posted"] += 1
        except Exception as exc:
            try:
                _cfg["report_error"]("operator_alert_eric", exc, kind)
            except Exception:
                pass
    return out


def status():
    with _lock:
        s = dict(_STATUS)
        s["today"] = dict(_mem_day)
        s["daily_cap"] = _cfg.get("daily_cap", DAILY_CAP_DEFAULT)
    return s
