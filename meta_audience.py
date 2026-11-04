"""PATCH #267 — who belongs in the Meta Custom Audience "MWM Cold Leads -
Retargeting (Sales Machine)" (120249187469750738), and how they are sent.

ERIC, Tue 3 Nov 2026: the audience shows last updated 2026-07-04. It was
never broken — only one path fed it (the WhatsApp re-engagement rail: T1–T7,
then REENGAGEMENT_COLD_DAYS, then farewell → push), and no lead has walked
that path since July. Form leads never enter it. So the audience starved
while the retargeting rebuild (AD_16) was planned on top of it.

This module decides membership from the record alone; the app runs it once a
day and on demand, hashes what Meta wants hashed, and posts the count.

Membership (any one of these, and none of the exclusions):
  * stage / temperature Cold, or the old "Cold" status strings
  * not booked and quiet for QUIET_DAYS (no inbound, no booking)
Exclusions: booked with an event, client (paid / won), do-not-contact, no
phone AND no email, internal/test records.

Removal: a lead that has been synced and then books or becomes a client is
taken OUT on the next run (Meta `DELETE /users` with the same hashes).

Pure: no clock, no network. Meta's hashing spec: SHA-256 of the normalised
value — phone as digits with country code, no plus; email lower-cased and
trimmed.
"""
import hashlib
import re
from datetime import datetime, timedelta

QUIET_DAYS = 14
SCHEMA = ["PHONE_SHA256", "EMAIL_SHA256"]
BATCH = 500
STAMP = "meta_audience_synced_at"
STAMP_REMOVED = "meta_audience_removed_at"

_COLD_WORDS = ("cold",)


def _lower(v):
    return str(v or "").strip().lower()


def normalize_phone(phone):
    d = re.sub(r"\D", "", str(phone or ""))
    if len(d) == 10:          # a bare US number
        d = "1" + d
    return d if 11 <= len(d) <= 15 else ""


def normalize_email(email):
    e = _lower(email)
    return e if "@" in e and "." in e.split("@")[-1] else ""


def sha256(v):
    return hashlib.sha256(str(v).encode("utf-8")).hexdigest() if v else ""


def row(phone, email):
    """One data row in SCHEMA order; None when nothing identifies the lead."""
    p, e = normalize_phone(phone), normalize_email(email)
    if not p and not e:
        return None
    return [sha256(p), sha256(e)]


def _parse(ts):
    try:
        d = datetime.fromisoformat(str(ts))
        return d
    except Exception:
        return None


def _is_cold(rec):
    for k in ("stage", "pipeline_stage", "lead_temperature", "temperature",
              "status", "whatsapp_status"):
        if any(w in _lower(rec.get(k)) for w in _COLD_WORDS):
            return True
    return False


def _last_activity(rec):
    best = None
    for k in ("last_message_time", "last_inbound_at", "sms_inbound_at",
              "booked_at", "created_at", "first_seen", "captured_at"):
        d = _parse(rec.get(k))
        if d is not None and (best is None or d > best):
            best = d
    return best


def _aware(d, tz):
    if d is None:
        return None
    if d.tzinfo is None:
        try:
            return tz.localize(d)
        except AttributeError:
            return d.replace(tzinfo=tz)
    return d


def decide(rec, now, is_client=False, is_booked=False, tz=None):
    """('add' | 'remove' | 'skip', why) for one record."""
    if not isinstance(rec, dict):
        return "skip", "not a record"
    if rec.get("test_lead") or rec.get("internal"):
        return "skip", "internal"
    synced = bool(rec.get(STAMP)) and not rec.get(STAMP_REMOVED)
    if is_client:
        return ("remove", "client") if synced else ("skip", "client")
    if is_booked and rec.get("event_id"):
        return ("remove", "booked") if synced else ("skip", "booked")
    if rec.get("do_not_contact") or rec.get("do_not_sms"):
        return ("remove", "do not contact") if synced else ("skip", "do not contact")
    if row(rec.get("phone"), rec.get("email")) is None:
        return "skip", "no phone or email"
    if _is_cold(rec):
        return "add", "cold"
    last = _last_activity(rec)
    if tz is not None:
        last = _aware(last, tz)
        now = _aware(now, tz)
    if last is None:
        return "skip", "no dates on the record"
    try:
        quiet_days = (now - last).total_seconds() / 86400.0
    except TypeError:
        return "skip", "dates not comparable"
    if quiet_days >= QUIET_DAYS:
        return "add", f"quiet {int(quiet_days)}d, not booked"
    return "skip", f"active {int(quiet_days)}d ago"


def plan(lead_data, now, is_client, is_booked, tz=None, force_all=False):
    """Walk the records → {'add': [(key, row, why)], 'remove': [...], 'skipped': {why: n}}.
    `force_all` re-sends every member (a backfill), otherwise a record that
    already carries the stamp is left alone."""
    out = {"add": [], "remove": [], "skipped": {}}
    for key, rec in list((lead_data or {}).items()):
        if not isinstance(rec, dict):
            out["skipped"]["not a record"] = out["skipped"].get("not a record", 0) + 1
            continue
        try:
            verdict, why = decide(rec, now, is_client=bool(is_client(key, rec)),
                                  is_booked=bool(is_booked(rec)), tz=tz)
        except Exception as e:  # one bad record never stops the sweep
            verdict, why = "skip", f"error {type(e).__name__}"
        if verdict == "add":
            if rec.get(STAMP) and not rec.get(STAMP_REMOVED) and not force_all:
                out["skipped"]["already synced"] = out["skipped"].get("already synced", 0) + 1
                continue
            out["add"].append((key, row(rec.get("phone"), rec.get("email")), why))
        elif verdict == "remove":
            out["remove"].append((key, row(rec.get("phone"), rec.get("email")), why))
        else:
            out["skipped"][why.split(" ")[0] if why.startswith(("active", "quiet")) else why] = \
                out["skipped"].get(why.split(" ")[0] if why.startswith(("active", "quiet")) else why, 0) + 1
    return out


def batches(rows, size=BATCH):
    rows = [r for r in rows if r]
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def payload(rows):
    """The JSON body Meta wants under the `payload` form field."""
    return {"schema": list(SCHEMA), "data": [list(r) for r in rows]}


def stamp(rec, now, removed=False):
    if removed:
        rec[STAMP_REMOVED] = now.isoformat()
    else:
        rec[STAMP] = now.isoformat()
        rec.pop(STAMP_REMOVED, None)
    return rec


def due_today(last_run_date, now, hour=7, minute=5):
    """Once a day, from HH:MM local. `last_run_date` is 'YYYY-MM-DD' or ''."""
    today = now.strftime("%Y-%m-%d")
    if last_run_date == today:
        return False
    return (now.hour, now.minute) >= (hour, minute)
