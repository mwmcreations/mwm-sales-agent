"""
meta_capi.py — PATCH #145. Three events back to Meta, nothing else.

ERIC's ask (26 Sep, item B4; 30 Sep, item 8): tell Meta when a lead is
QUALIFIED (`Lead`), when a visit is BOOKED (`Schedule`) and when money
arrives (`Purchase`), so the Leads-objective campaign optimises for people who
become clients rather than for anyone who will fill a form.

DARK UNTIL CONFIGURED. Two Railway variables switch it on:
    META_CAPI_DATASET_ID   the dataset (pixel) id from Events Manager
    META_CAPI_TOKEN        a Conversions API access token, generated in
                           Events Manager and pasted into Railway by Michael
                           (never through Slack or chat)
Optional: META_CAPI_TEST_CODE (Events Manager "Test events" code) — when
set, every event is tagged with it so it shows in the test tab and does not
count.

PURE where it matters: payload building and hashing are plain functions
with no network, so they are tested; `send()` is the only thing that talks
to Meta, and it never raises.
"""

import hashlib
import json
import os
import re
import time

GRAPH = "https://graph.facebook.com/v21.0"

EVENT_LEAD = "Lead"
EVENT_SCHEDULE = "Schedule"
EVENT_PURCHASE = "Purchase"

_STATS = {"sent": 0, "failed": 0, "skipped_unconfigured": 0, "last_error": "",
          "last_event": "", "last_at": ""}


def configured():
    return bool(os.getenv("META_CAPI_DATASET_ID", "").strip()
                and os.getenv("META_CAPI_TOKEN", "").strip())


def status():
    return {"configured": configured(),
            "dataset_id": os.getenv("META_CAPI_DATASET_ID", "").strip() or None,
            "test_code": bool(os.getenv("META_CAPI_TEST_CODE", "").strip()),
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
    qualified or a visit being booked; purchases from the website checkout
    use "website"."""
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
        return True, f"received {body.get('events_received', len(events))}"
    _STATS["failed"] += 1
    err = (body or {}).get("error") or {}
    msg = f"HTTP {code} {err.get('message', '') or json.dumps(body)[:200]}"
    _STATS["last_error"] = msg[:200]
    return False, msg


# ── the three events, as the app calls them ────────────────────────────────

def lead_event(name="", email="", phone="", lead_id="", ad_id="", qualified="",
               business="", event_id=None):
    fn, ln = split_name(name)
    return build_event(EVENT_LEAD,
                       user_data(email, phone, fn, ln, lead_id=lead_id),
                       custom={"lead_event_source": "MWM Sales Machine",
                               "event_source": "crm",
                               "qualified": qualified or "", "ad_id": ad_id or "",
                               "content_name": business or ""},
                       event_id=event_id or (f"lead-{lead_id}" if lead_id else None))


def schedule_event(name="", email="", phone="", lead_id="", when="", kind="studio_visit",
                   event_id=None):
    fn, ln = split_name(name)
    return build_event(EVENT_SCHEDULE,
                       user_data(email, phone, fn, ln, lead_id=lead_id),
                       custom={"content_name": kind, "scheduled_for": when or ""},
                       event_id=event_id)


def purchase_event(name="", email="", phone="", lead_id="", value=0.0, currency="USD",
                   product="", stripe_id="", event_id=None):
    fn, ln = split_name(name)
    return build_event(EVENT_PURCHASE,
                       user_data(email, phone, fn, ln, lead_id=lead_id),
                       action_source="website",
                       custom={"value": round(float(value or 0), 2),
                               "currency": currency or "USD",
                               "content_name": product or "",
                               "order_id": stripe_id or ""},
                       event_id=event_id or (f"purchase-{stripe_id}" if stripe_id else None))
