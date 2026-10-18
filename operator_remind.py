"""
operator_remind.py — PATCH #254. A text to Michael at a time he chose.

Michael, Sun 18 Oct 10:37: a form lead came in on a Sunday morning, he is
not calling on a Sunday, and he said yes to "a reminder text Monday at 9 AM
with the name and number". There was no way to do that: the operator alerts
(#149) fire at the moment of an event, and nothing in the machine could hold
a text for a chosen time. This holds it.

How it works
  - A reminder is one pg row `operator_text:<id>` = {id, body, at, created_by,
    created_at, sent_at, result}. `at` is an ISO time with offset (ET).
  - The app's `operator_remind` thread checks every minute; a row whose `at`
    has passed and that has no `sent_at` goes out through operator_alert
    (kind "reminder": SMS to MICHAEL_PHONE only, daily cap, dedupe) and is
    then stamped sent — or stamped failed with the reason, and left alone
    (it is not retried forever; the row says what happened).
  - POST /admin/operator-text {body, at?} creates one (no `at`, or a past
    `at`, sends now). GET /admin/operator-text lists them.

Pure here: building a row, deciding which rows are due, summarising. The
app supplies pg and the sender.
"""
import hashlib
import re
import time
from datetime import datetime, timezone, timedelta

KEY_PREFIX = "operator_text:"
BODY_MAX = 600            # operator_alert.SMS_MAX is 640
ET = timezone(timedelta(hours=-4))   # fallback only; the app passes real tz-aware times


def _epoch(value):
    """ISO string / datetime / epoch -> epoch seconds, or None."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=ET)
            return int(value.timestamp())
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip()
        if re.fullmatch(r"\d{9,11}(\.\d+)?", s):
            return int(float(s))
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        return int(dt.timestamp())
    except Exception:
        return None


def make(body, at=None, created_by="", now=None):
    """One reminder row. `at` None or past -> due now. Returns (row, error)."""
    text = re.sub(r"\s+", " ", str(body or "")).strip()
    if not text:
        return None, "body is required"
    if len(text) > BODY_MAX:
        return None, f"body is {len(text)} chars; max {BODY_MAX}"
    now_e = int(now or time.time())
    at_e = _epoch(at) if at not in (None, "") else now_e
    if at_e is None:
        return None, f"unreadable time: {at!r}"
    if at_e - now_e > 60 * 86400:
        return None, "more than 60 days out"
    rid = hashlib.sha256(f"{text}|{at_e}|{now_e}".encode("utf-8")).hexdigest()[:12]
    row = {"id": rid, "body": text, "at": at_e, "created_by": str(created_by or "")[:40],
           "created_at": now_e, "sent_at": None, "result": ""}
    return row, ""


def key(row_or_id):
    rid = row_or_id["id"] if isinstance(row_or_id, dict) else str(row_or_id)
    return KEY_PREFIX + rid


def due(rows, now=None):
    """Rows whose time has come and that were never attempted, oldest first."""
    now_e = int(now or time.time())
    out = [r for r in (rows or []) if isinstance(r, dict) and not r.get("sent_at")
           and not r.get("result") and _epoch(r.get("at")) is not None and _epoch(r.get("at")) <= now_e]
    out.sort(key=lambda r: _epoch(r.get("at")) or 0)
    return out


def mark(row, result, now=None):
    """Stamp the outcome of one attempt. 'sent' fills sent_at; anything else
    is the refusal/failure reason and the row is not tried again."""
    row = dict(row)
    now_e = int(now or time.time())
    row["result"] = str(result or "")[:80]
    row["sent_at"] = now_e if result == "sent" else None
    row["attempted_at"] = now_e
    return row


def fmt_at(row, tz=None):
    at = _epoch(row.get("at")) if isinstance(row, dict) else None
    if at is None:
        return ""
    dt = datetime.fromtimestamp(at, tz or ET)
    return dt.strftime("%a %b %-d, %-I:%M %p")


def summarize(rows, now=None):
    now_e = int(now or time.time())
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    pending = [r for r in rows if not r.get("sent_at") and not r.get("result")]
    sent = [r for r in rows if r.get("sent_at")]
    failed = [r for r in rows if r.get("result") and not r.get("sent_at")]
    nxt = min((_epoch(r.get("at")) for r in pending if _epoch(r.get("at")) is not None), default=None)
    return {"pending": len(pending), "sent": len(sent), "failed": len(failed),
            "next_at": (datetime.fromtimestamp(nxt, ET).isoformat() if nxt else None),
            "overdue": sum(1 for r in pending if (_epoch(r.get("at")) or now_e) <= now_e)}
