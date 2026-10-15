"""
meta_capi.py — PATCH #145 (three events), reshaped by PATCH #251 into the five
CRM lead stages Meta's "Conversion Leads" optimisation wants.

ERIC's ask (26 Sep, item B4; 30 Sep, item 8; 15 Oct, patch request): tell Meta
what happens to a lead AFTER the form, so the Leads-objective campaign can
optimise for owners who book and buy, not for anyone who will fill a form.

THE FIVE STAGES (one event per stage change, per lead — ERIC, 15 Oct):
    Lead                   the form was captured (mirrors Meta's own Lead)
    Qualified              passed the role + revenue gate (verdict yes/review)
    StudioVisitBooked      a calendar event exists for the visit
    StudioVisitCompleted   the visit happened (any report outcome but no_show)
    Converted              money arrived (Stripe) or Michael reported client_won

HOW A STAGE IS KEYED
    event_id   = "<lead_key>:<Stage>"   — Meta de-duplicates on it, and the
                 app's ledger (pg `capi_sent:<lead_key>:<Stage>`) never sends
                 a stage twice. A lead key may itself contain colons
                 ("whatsapp:+1407…"), so the stage is the LAST colon-field.
    user_data  lead_id = the Instant Form leadgen id when the lead came from a
                 Meta form (the match key Conversion Leads keys on), plus
                 SHA-256 em / ph / fn / ln as the fallback for IG / WhatsApp /
                 web leads that never touched a form.
    custom_data {"event_source": "crm", "lead_event_source": "MWM Sales Machine",
                 "stage": <Stage>} on EVERY event, plus whatever the hook knows
                 (ad_id, qualified verdict, value/currency, content_name).
    action_source "system_generated" — the documented value for CRM events.

THE 7-DAY RULE
    Meta refuses an event whose event_time is more than 7 days old. A stage
    that happened earlier (the Oct 1+ backfill) is therefore stamped at send
    time and carries the real moment in custom_data.stage_time, with
    custom_data.stage_time_clamped = true. The lead_id match window is 28
    days, which is what the optimisation actually needs.

DARK UNTIL CONFIGURED. Two Railway variables switch it on:
    META_CAPI_DATASET_ID   the dataset id from Events Manager (658880878344916)
    META_CAPI_TOKEN        a Conversions API access token, generated in
                           Events Manager and pasted into Railway by Michael
                           (never through Slack or chat)
Optional: META_CAPI_TEST_CODE (Events Manager "Test events" code) — when set,
every event is tagged with it so it shows in the test tab and does not count.
While dark, nothing is marked sent, so the backfill route can send every
stage once the token exists.

PURE where it matters: payload building, hashing, time clamping, the
stage-from-record derivation and the backfill plan are plain functions with
no network, so they are tested; `send()` is the only thing that talks to
Meta, and it never raises.
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone

GRAPH = "https://graph.facebook.com/v21.0"

# ── the five stages, in funnel order ─────────────────────────────────────────
STAGE_LEAD = "Lead"
STAGE_QUALIFIED = "Qualified"
STAGE_BOOKED = "StudioVisitBooked"
STAGE_COMPLETED = "StudioVisitCompleted"
STAGE_CONVERTED = "Converted"
STAGES = (STAGE_LEAD, STAGE_QUALIFIED, STAGE_BOOKED, STAGE_COMPLETED, STAGE_CONVERTED)
STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}

# Form verdicts that count as Qualified (lead_form.Q_YES / Q_REVIEW — review
# runs the same opener, visit offer and chain, flagged for a human read).
# Q_NO and the sub-$50K studio-hour track are not Qualified.
QUALIFIED_VERDICTS = ("yes", "review")

# Daily Event Report outcomes that mean the visit HAPPENED.
VISIT_OUTCOMES = ("completed", "follow_up", "studio_package_pitched", "client_won", "not_interested")

# PATCH #251b — Meta's Lead Ads Testing Tool dummies are not people. The one
# the rail has seen (30 Sep proof run) is listed by id; any record whose name
# is the tool's "<test lead: …>" placeholder is caught the same way.
TEST_LEADGEN_IDS = ("4593113990973865",)


def is_test_record(rec):
    """True for anything that must never reach Meta as a stage: the rail's
    own test leads (test_lead), the Testing Tool dummies, placeholder names."""
    rec = rec or {}
    if rec.get("test_lead"):
        return True
    if str(rec.get("leadgen_id") or "") in TEST_LEADGEN_IDS:
        return True
    if str(rec.get("name") or "").strip().lower().startswith("<test"):
        return True
    return False


def is_form_lead(rec):
    """A lead that came through a Meta Instant Form. The live rail writes
    leadgen_id; a record rebuilt from the sheet (#153 restore) has only
    meta_lead_ad — it still gets Lead/Qualified, matched by hashed email/phone."""
    rec = rec or {}
    return bool(rec.get("leadgen_id") or rec.get("meta_lead_ad"))

CUSTOM_BASE = {"event_source": "crm", "lead_event_source": "MWM Sales Machine"}

# Meta: event_time must be within the last 7 days. Keep an hour of slack.
MAX_EVENT_AGE_S = 7 * 86400 - 3600

_STATS = {"sent": 0, "failed": 0, "skipped_unconfigured": 0, "last_error": "",
          "last_event": "", "last_at": "", "by_stage": {}}


def configured():
    return bool(os.getenv("META_CAPI_DATASET_ID", "").strip()
                and os.getenv("META_CAPI_TOKEN", "").strip())


def status():
    return {"configured": configured(),
            "dataset_id": os.getenv("META_CAPI_DATASET_ID", "").strip() or None,
            "test_code": bool(os.getenv("META_CAPI_TEST_CODE", "").strip()),
            "stages": list(STAGES),
            **_STATS}


# ── hashing (Meta: lowercase, trimmed, SHA-256 hex) ────────────────────────

def _sha(value):
    v = (value or "").strip().lower()
    if not v:
        return None
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


def norm_email(email):
    e = str(email or "").strip().lower()
    return e if ("@" in e and "." in e.split("@")[-1]) else ""


def norm_phone(phone):
    """Digits only with country code, no plus: '+1 (407) 555-1234' -> '14075551234'."""
    d = re.sub(r"\D", "", str(phone or "").replace("whatsapp:", ""))
    if len(d) == 10:
        d = "1" + d
    return d if 11 <= len(d) <= 15 else ""


def user_data(email="", phone="", first_name="", last_name="", lead_id="",
              fbc="", fbp="", external_id=""):
    """Hashed user_data block. Every field is optional; empty ones are dropped.
    `lead_id` (the Meta leadgen id) is the strongest key for form leads —
    Meta matches it directly, no hashing, and it is what "Conversion Leads"
    optimisation keys on."""
    ud = {}
    e = norm_email(email)
    if e:
        ud["em"] = [_sha(e)]
    p = norm_phone(phone)
    if p:
        ud["ph"] = [_sha(p)]
    if first_name:
        ud["fn"] = [_sha(first_name)]
    if last_name:
        ud["ln"] = [_sha(last_name)]
    if lead_id and str(lead_id).isdigit():
        ud["lead_id"] = int(lead_id)
    if external_id:
        ud["external_id"] = [_sha(str(external_id))]
    if fbc:
        ud["fbc"] = fbc
    if fbp:
        ud["fbp"] = fbp
    return ud


def build_event(event_name, ud, event_time=None, source_url="", action_source="system_generated",
                custom=None, event_id=None):
    """One event in Meta's shape. action_source "system_generated" is the
    documented value for CRM/offline-style events like a lead becoming
    qualified or a visit being booked."""
    ev = {
        "event_name": event_name,
        "event_time": int(event_time or time.time()),
        "action_source": action_source,
        "user_data": ud,
    }
    if source_url:
        ev["event_source_url"] = source_url
    if event_id:
        ev["event_id"] = str(event_id)
    if custom:
        ev["custom_data"] = dict(custom)
    return ev


def split_name(name):
    parts = str(name or "").strip().split()
    if not parts:
        return "", ""
    return parts[0], (parts[-1] if len(parts) > 1 else "")


# ── time ─────────────────────────────────────────────────────────────────────

def to_epoch(value):
    """datetime (aware or naive-as-UTC), ISO string, int/float epoch, or
    None -> epoch seconds or None. Never raises."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return int(value.timestamp())
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip()
        if re.fullmatch(r"\d{9,11}(\.\d+)?", s):
            return int(float(s))
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def clamp_time(stage_time, now=None):
    """(event_time, clamped). A stage older than Meta's 7-day window is
    stamped `now`; a stage in the future is stamped `now` too (clocks)."""
    now = int(now or time.time())
    st = to_epoch(stage_time)
    if st is None:
        return now, False
    if st > now:
        return now, True
    if now - st > MAX_EVENT_AGE_S:
        return now, True
    return st, False


# ── ids ──────────────────────────────────────────────────────────────────────

def event_id_for(lead_key, stage):
    return f"{lead_key}:{stage}"


def ledger_key(lead_key, stage):
    return f"capi_sent:{lead_key}:{stage}"


def parse_event_id(event_id):
    """'whatsapp:+14075551234:StudioVisitBooked' -> ('whatsapp:+14075551234',
    'StudioVisitBooked'); anything that does not end in a known stage ->
    (None, None). The stage is always the LAST colon-field."""
    s = str(event_id or "")
    if ":" not in s:
        return None, None
    key, stage = s.rsplit(":", 1)
    if stage not in STAGE_ORDER or not key:
        return None, None
    return key, stage


# ── the stage event ──────────────────────────────────────────────────────────

def stage_event(stage, lead_key, name="", email="", phone="", lead_id="",
                stage_time=None, now=None, extra=None):
    """One CRM stage for one lead, in Meta's shape, keyed for de-duplication."""
    if stage not in STAGE_ORDER:
        raise ValueError(f"unknown stage {stage!r}")
    fn, ln = split_name(name)
    ud = user_data(email, phone, fn, ln, lead_id=lead_id)
    et, clamped = clamp_time(stage_time, now)
    custom = dict(CUSTOM_BASE)
    custom["stage"] = stage
    if clamped:
        st = to_epoch(stage_time)
        if st is not None:
            custom["stage_time"] = datetime.fromtimestamp(st, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        custom["stage_time_clamped"] = True
    for k, v in (extra or {}).items():
        if v in (None, ""):
            continue
        custom[k] = v
    return build_event(stage, ud, event_time=et, custom=custom,
                       event_id=event_id_for(lead_key, stage))


# ── what a lead record says happened (for the backfill) ─────────────────────

def _first(*vals):
    for v in vals:
        if v not in (None, ""):
            return v
    return None


def stages_from_record(rec):
    """[(stage, stage_time_or_None, extra), ...] in funnel order, derived from
    the fields the hooks write. A booking counts only with an event_id (S30:
    the flag alone is not a booking). Lead/Qualified come only from a form
    (leadgen_id); the other three apply to any lead."""
    rec = rec or {}
    out = []
    captured = _first(rec.get("lead_form_at"), rec.get("first_contact_time"))
    if is_form_lead(rec):
        out.append((STAGE_LEAD, captured,
                    {"ad_id": str(rec.get("ad_id") or ""), "qualified": str(rec.get("qualified") or ""),
                     "content_name": str(rec.get("business") or "")}))
        if str(rec.get("qualified") or "") in QUALIFIED_VERDICTS:
            out.append((STAGE_QUALIFIED, captured,
                        {"ad_id": str(rec.get("ad_id") or ""), "qualified": str(rec.get("qualified") or "")}))
    if rec.get("event_id"):
        out.append((STAGE_BOOKED, _first(rec.get("booked_at"), rec.get("last_outcome_at")),
                    {"content_name": "studio_visit"}))
    if str(rec.get("last_outcome") or "") in VISIT_OUTCOMES:
        out.append((STAGE_COMPLETED, rec.get("last_outcome_at"),
                    {"content_name": str(rec.get("last_outcome") or "")}))
    if rec.get("paid_at") or rec.get("won_at"):
        extra = {"content_name": str(rec.get("paid_product") or rec.get("product") or "")}
        try:
            v = float(rec.get("paid_value") or 0)
            if v:
                extra["value"] = round(v, 2)
                extra["currency"] = "USD"
        except Exception:
            pass
        out.append((STAGE_CONVERTED, _first(rec.get("paid_at"), rec.get("won_at")), extra))
    return out


def backfill_plan(leads, already_sent, since=None, now=None, meta_only=True):
    """Which (lead_key, stage, stage_time, extra) still need sending.

    `leads` is {key: record}; `already_sent(key, stage)` is the ledger; `since`
    (epoch or ISO) keeps the plan to leads first seen at or after it; with
    `meta_only` only form leads (leadgen_id or meta_lead_ad) are considered
    (ERIC: the Oct 1+ Meta leads). Pure. Test records are never planned."""
    since_e = to_epoch(since) if since not in (None, "") else None
    plan = []
    for key, rec in (leads or {}).items():
        if not isinstance(rec, dict) or is_test_record(rec):
            continue
        if meta_only and not is_form_lead(rec):
            continue
        seen = to_epoch(_first(rec.get("lead_form_at"), rec.get("first_contact_time")))
        if since_e is not None and (seen is None or seen < since_e):
            continue
        for stage, st, extra in stages_from_record(rec):
            if already_sent(key, stage):
                continue
            plan.append({"lead_key": key, "stage": stage, "stage_time": st, "extra": extra,
                         "lead_id": str(rec.get("leadgen_id") or ""),
                         "name": rec.get("name") or "", "email": rec.get("email") or "",
                         "phone": rec.get("phone") or ""})
    plan.sort(key=lambda p: (to_epoch(p["stage_time"]) or 0, STAGE_ORDER[p["stage"]]))
    return plan


# ── the wire ─────────────────────────────────────────────────────────────────

def send(events, post=None, dataset_id=None, token=None, test_code=None):
    """POST the events. Returns (ok, detail). Never raises.

    `post` is injectable for tests: post(url, json) -> (status_code, body_dict)."""
    dataset_id = dataset_id or os.getenv("META_CAPI_DATASET_ID", "").strip()
    token = token or os.getenv("META_CAPI_TOKEN", "").strip()
    test_code = test_code if test_code is not None else os.getenv("META_CAPI_TEST_CODE", "").strip()
    if not events:
        return False, "no events"
    if not (dataset_id and token):
        _STATS["skipped_unconfigured"] += 1
        return False, "unconfigured"
    payload = {"data": list(events), "access_token": token}
    if test_code:
        payload["test_event_code"] = test_code
    try:
        if post is None:
            import requests as _rq
            r = _rq.post(f"{GRAPH}/{dataset_id}/events", json=payload, timeout=15)
            try:
                body = r.json()
            except Exception:
                body = {"raw": (r.text or "")[:300]}
            code = r.status_code
        else:
            code, body = post(f"{GRAPH}/{dataset_id}/events", payload)
    except Exception as exc:
        _STATS["failed"] += 1
        _STATS["last_error"] = str(exc)[:200]
        return False, f"exception: {str(exc)[:120]}"
    _STATS["last_event"] = ",".join(e.get("event_name", "?") for e in events)
    _STATS["last_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if code == 200 and not (body or {}).get("error"):
        _STATS["sent"] += len(events)
        for e in events:
            n = str(e.get("event_name", "?"))
            _STATS["by_stage"][n] = _STATS["by_stage"].get(n, 0) + 1
        return True, f"received {body.get('events_received', len(events))}"
    _STATS["failed"] += 1
    err = (body or {}).get("error") or {}
    msg = f"HTTP {code} {err.get('message', '') or json.dumps(body)[:200]}"
    _STATS["last_error"] = msg[:200]
    return False, msg
