"""desk.py — PATCH #270 — MWM Desk, slice 1: SEE (slice 2 #271: ACT; slice 3 #273: MEASURE).

Michael, Sat 7 Nov 2026, 23:12: "We need to close that gap. That exactly what
makes me frustrated around our system. Go ahead and start now with the admin
page of our own. We have everything in our reach to build our own GHL."

The gap: the Sales Machine books the visits and nobody can see it work except
through Slack, a sheet and /health. This is the window — a board, an inbox and
a lead card over the SAME records Maya and the rails use. Slice 1 is read-only
on purpose: every number on the screen is the record, nothing is a copy.

What is here
  * A read model. Six months of patches left the lead record with several
    spellings for the same fact (status / whatsapp_status, temperature /
    lead_temperature, first_contact_time / lead_form_at…). `lead_view` turns
    one record into one clean shape; `stage_of` places it on the board from
    the facts the hooks actually write (the same fields meta_capi reads for
    the funnel). Pure: no Flask, no clock of its own, no network.
  * The door. Same model as Victory Intelligence: no passwords; a one-time
    link to an @mwmcreations.com address, a signed cookie, or the admin
    secret for the agents. Reuses victory_auth (pure) and victory_store (the
    link table and the session secret) so nothing new has to be trusted.
  * The routes, in `register(app, deps)`, and the page under desk_static/.

Stages on the board (activity order, not Meta's funnel):
  New → Contacted → Replied → Booked → Visited → Client   | Paused | Lost
"Qualified" is a badge, not a column: a form lead is qualified at intake,
before anyone has spoken to them.
"""
import os
import re
import json
import time
from datetime import datetime, timedelta

STAGES = ("New", "Contacted", "Replied", "Booked", "Visited", "Client", "Paused", "Lost")
SIDE_STAGES = ("Paused", "Lost")

# the visit outcomes the outcome rail writes (meta_capi counts the same ones as
# a completed visit); kept as a fallback so this module imports on its own —
# the live values come from meta_capi when it is there, and the test checks
# the two agree
try:
    from meta_capi import VISIT_OUTCOMES, QUALIFIED_VERDICTS  # noqa: F401
except Exception:  # pragma: no cover
    VISIT_OUTCOMES = ("completed", "follow_up", "studio_package_pitched", "client_won", "not_interested")
    QUALIFIED_VERDICTS = ("yes", "studio-hour")
LOST_STOPS = ("disqualified", "no", "declined", "dnc", "do_not_contact")
PAUSED_STOPS = ("not_now", "paused", "cold", "farewell")
QUIET_DAYS = 30          # nothing heard or sent for this long → Paused
VISIT_PASSED_GRACE_H = 12  # a booked slot this far in the past with no outcome → "outcome?"
BOOKING_STALE_DAYS = 14    # a booking with no slot time on record, older than this → treated as passed
ATTENTION_DAYS = 45        # a passed visit this recent with no outcome is on the "Needs me" list

COOKIE = "desk_session"
COOKIE_PATH = "/desk"
LINK_SUBJECT = "Your MWM Desk sign-in link"


# ── small helpers ───────────────────────────────────────────────────────────

def _first(*vals):
    for v in vals:
        if v not in (None, "", [], {}):
            return v
    return None


def _lower(v):
    return str(v or "").strip().lower()


def digits(s):
    return re.sub(r"\D", "", str(s or ""))


def parse_dt(v):
    """datetime | ISO string | epoch → aware-or-naive datetime, or None."""
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(v))
        except Exception:
            return None
    s = str(v).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def iso(v):
    d = parse_dt(v)
    return d.isoformat() if d else ""


def epoch(v):
    d = parse_dt(v)
    if d is None:
        return 0.0
    try:
        if d.tzinfo is None:
            return time.mktime(d.timetuple())
        return d.timestamp()
    except Exception:
        return 0.0


def latest(*vals):
    """The newest of several timestamps, as ISO, or ''."""
    best, best_e = "", 0.0
    for v in vals:
        e = epoch(v)
        if e > best_e:
            best, best_e = iso(v), e
    return best


def phone_key(key, rec):
    d = digits(key) if str(key or "").startswith(("whatsapp:", "sms:", "+")) else ""
    d = d or digits((rec or {}).get("phone"))
    if len(d) == 10:
        d = "1" + d
    return d


def is_test(rec):
    rec = rec or {}
    try:
        if rec.get("test_lead") or rec.get("internal"):
            return True
        try:
            from meta_capi import is_test_record  # Meta's Lead Ads Testing Tool dummies (#251b)
            return bool(is_test_record(rec))
        except ImportError:
            return str(rec.get("name") or "").strip().lower().startswith("<test lead")
    except Exception:
        return False      # a record that cannot even be read is handled (and marked) by the view


# ── conversations ───────────────────────────────────────────────────────────

def turns_for(key, rec, conversation_history, ig_history):
    """The conversation turns for a lead, wherever the app filed them.
    WhatsApp/SMS leads live under `whatsapp:+<digits>`; Instagram under
    `instagram:<igsid>`; a few old records under the bare key."""
    conv = conversation_history or {}
    igc = ig_history or {}
    out = None
    for k in (key, f"whatsapp:+{phone_key(key, rec)}" if phone_key(key, rec) else None,
              (rec or {}).get("ig_key"), (rec or {}).get("instagram_key")):
        if not k:
            continue
        t = conv.get(k)
        if t is None and str(k).startswith("instagram:"):
            t = igc.get(k)
        if t is None and str(k).startswith("@"):
            t = igc.get(k)
        if isinstance(t, list) and t:
            out = t
            break
    if out is None and str(key).startswith("instagram:"):
        out = igc.get(key) or []
    turns = []
    for t in (out or []):
        if not isinstance(t, dict):
            continue
        role = _lower(t.get("role"))
        if role not in ("user", "assistant"):
            continue
        content = t.get("content")
        if isinstance(content, list):      # multimodal shape: keep the text parts
            content = " ".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content)
        content = str(content or "").strip()
        if not content:
            continue
        who = "lead" if role == "user" else ("michael" if _lower(t.get("by")) == "michael" else "maya")
        turns.append({"role": who, "text": content, "at": iso(t.get("at") or t.get("ts") or t.get("time"))})
    return turns


def has_inbound(rec, turns):
    if any(t["role"] == "lead" for t in (turns or [])):
        return True
    return bool(_first(rec.get("last_inbound_at"), rec.get("sms_inbound_at"),
                       rec.get("first_inbound_at"), rec.get("replied_at"),
                       rec.get("email_reply_at")))


def has_outbound(rec, turns):
    if any(t["role"] in ("maya", "michael") for t in (turns or [])):
        return True
    ft = rec.get("first_touch_wa")
    if isinstance(ft, dict) and ft.get("wamid"):
        return True
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else {}
    if chase.get("sent"):
        return True
    return bool(_first(rec.get("first_touch_sms_at"), rec.get("first_touch_email_at"),
                       rec.get("reoffer_at"), rec.get("welcome_sent_at"),
                       rec.get("_email_notified")))


# ── the read model ──────────────────────────────────────────────────────────

def is_client(rec):
    if rec.get("paid_at") or rec.get("won_at"):
        return True
    if _lower(rec.get("outcome")) == "won" or _lower(rec.get("last_outcome")) == "client_won":
        return True
    if _lower(_first(rec.get("status"), rec.get("whatsapp_status"))).startswith("client"):
        return True
    if isinstance(rec.get("studio_package"), dict):
        return True
    return False


def is_qualified(rec):
    if _lower(rec.get("qualified")) in QUALIFIED_VERDICTS:
        return True
    return _lower(_first(rec.get("status"), rec.get("whatsapp_status"))) == "qualified"


def quiet_days(rec, turns=None, now=None):
    """Days since the last thing that happened on the record; None when the
    record carries no date at all (the oldest era)."""
    last = last_activity(rec, turns)
    if not last:
        return None
    e = epoch(last)
    if not e:
        return None
    n = (now.timestamp() if isinstance(now, datetime) and now.tzinfo else
         time.mktime(now.timetuple()) if isinstance(now, datetime) else time.time())
    return max(0.0, (n - e) / 86400.0)


SOFT_STAGES = ("New", "Contacted", "Replied", "Paused")
OVERRIDE_STAGES = ("Paused", "Lost")        # what a hand can set; Booked/Visited/Client come from facts


def _fact_time(rec):
    """When the record's last HARD fact happened (booking, visit outcome,
    payment, block) — a hand-set stage older than that no longer applies."""
    return latest(rec.get("booked_at"), rec.get("last_outcome_at"), rec.get("paid_at"),
                  rec.get("won_at"), rec.get("dnc_at"))


def stage_of(rec, turns=None, dnc=False, now=None):
    """Where the record sits on the board. A stage Michael set by hand
    (desk_stage, slice 2) wins over the soft stages, and over a hard fact only
    when it is newer than that fact — a booking made after he parked a lead
    un-parks it."""
    fact = _fact_stage(rec, turns, dnc=dnc, now=now)
    ov = rec.get("desk_stage") if isinstance(rec, dict) and isinstance(rec.get("desk_stage"), dict) else None
    if ov and ov.get("stage") in OVERRIDE_STAGES:
        if fact in SOFT_STAGES or epoch(ov.get("at")) > epoch(_fact_time(rec)):
            return ov["stage"]
    return fact


def _fact_stage(rec, turns=None, dnc=False, now=None):
    """The stage the facts alone say. Facts first (paid, blocked, visit
    outcome, a booking), then the chase's own verdicts, then time: a lead
    nobody has heard from in QUIET_DAYS is Paused, whatever Maya's
    temperature score says — the temperature is a read on the lead, not a
    stage, and it is shown as a badge instead (the first live board put 317
    of 385 leads in Paused by reading it as one)."""
    rec = rec or {}
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else {}
    stopped = _lower(chase.get("stopped"))
    if is_client(rec):
        return "Client"
    if dnc or rec.get("do_not_contact") or rec.get("do_not_sms"):
        return "Lost"
    if _lower(rec.get("last_outcome")) in ("not_interested",):
        return "Lost"
    if _lower(rec.get("last_outcome")) in VISIT_OUTCOMES:
        return "Visited"
    if rec.get("event_id"):
        return "Booked"
    if stopped in LOST_STOPS or _lower(rec.get("outcome")) in ("lost", "no", "declined"):
        return "Lost"
    if stopped in PAUSED_STOPS:
        return "Paused"
    active_chase = bool(chase) and not stopped
    inbound, outbound = has_inbound(rec, turns), has_outbound(rec, turns)
    q = quiet_days(rec, turns, now)
    if not active_chase:
        if q is not None and q >= QUIET_DAYS:
            return "Paused"               # whatever happened, it was a month ago or more
        if q is None and (inbound or outbound):
            return "Paused"               # a conversation with no date on it is an old one
    if inbound:
        return "Replied"
    if outbound:
        return "Contacted"
    return "New"


def display_name(rec, key=""):
    n = " ".join(str(rec.get("name") or "").split())
    if n and _lower(n) not in ("unknown", "n/a", "none"):
        return n
    b = " ".join(str(rec.get("business") or "").split())
    if b:
        return b
    d = phone_key(key, rec)
    if d:
        return "…" + d[-4:]
    if str(key).startswith("instagram:"):
        return "Instagram lead"
    return str(key)[:24] or "Lead"


_SOURCE_LABELS = {"instagram dm": "Instagram DM", "instagram": "Instagram", "whatsapp": "WhatsApp",
                  "meta lead ad": "Meta Lead Ad", "website chat": "Website chat", "lead form": "Lead form",
                  "sms": "SMS", "email": "Email"}


def source_of(rec, key=""):
    s = " ".join(str(rec.get("source") or "").split())
    if s:
        return _SOURCE_LABELS.get(s.lower(), s)
    ch = _lower(rec.get("channel"))
    if ch:
        return ch.title()
    if str(key).startswith("instagram:") or str(key).startswith("@"):
        return "Instagram"
    if str(key).startswith("whatsapp:"):
        return "WhatsApp"
    return "—"


def channel_of(rec, key=""):
    if str(key).startswith("instagram:") or str(key).startswith("@"):
        return "instagram"
    ch = _lower(rec.get("channel"))
    if ch in ("instagram", "ig", "ig dm"):
        return "instagram"
    if ch in ("sms", "text"):
        return "sms"
    if ch in ("email", "lead form", "form", "website"):
        return "email"
    return "whatsapp"


def last_activity(rec, turns=None):
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else {}
    sent = chase.get("sent") if isinstance(chase.get("sent"), dict) else {}
    ft = rec.get("first_touch_wa") if isinstance(rec.get("first_touch_wa"), dict) else {}
    cands = [rec.get("last_message_time"), rec.get("last_inbound_at"), rec.get("sms_inbound_at"),
             rec.get("booked_at"), rec.get("last_outcome_at"), rec.get("first_touch_sms_at"),
             rec.get("reoffer_at"), rec.get("lead_form_at"), rec.get("first_contact_time"),
             rec.get("paid_at"), rec.get("won_at"), rec.get("updated_at"), ft.get("sent_at"),
             ft.get("delivered_at"), ft.get("read_at")]
    cands += list(sent.values())
    cands += [t.get("at") for t in (turns or []) if t.get("at")]
    return latest(*cands)


def first_seen(rec):
    return iso(_first(rec.get("lead_form_at"), rec.get("first_contact_time"),
                      rec.get("created_at"), rec.get("first_seen"), rec.get("captured_at")))


def flags_for(rec, turns, stage, manual=False, now=None):
    out = []
    if manual:
        out.append("michael")              # Michael took the conversation over
    if turns and turns[-1]["role"] == "lead" and stage not in ("Client", "Lost") and not manual:
        out.append("awaiting_reply")
    if is_qualified(rec):
        out.append("qualified")
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else {}
    if chase and not chase.get("stopped") and stage not in ("Booked", "Visited", "Client", "Lost"):
        out.append("chasing")
    if isinstance(rec.get("first_touch_wa_pending"), dict) or isinstance(rec.get("first_touch_sms_pending"), dict):
        out.append("first_touch_pending")
    if _lower(rec.get("last_outcome")) in ("no_show", "noshow", "no-show"):
        out.append("no_show")
    bk = booking_of(rec, now)
    if bk and bk.get("passed") and stage == "Booked" and not rec.get("last_outcome"):
        # the visit is behind us and nobody said what happened: recent ones are on the
        # "Needs me" list, the older backlog is only marked
        age = quiet_days({"booked_at": bk.get("slot_at") or bk.get("at")}, None, now)
        out.append("visit_passed" if (age is not None and age <= ATTENTION_DAYS) else "outcome_missing")
    if rec.get("offered_slots") and stage not in ("Booked", "Visited", "Client"):
        out.append("times_offered")
    return out


def slot_display(iso_or_text):
    """'Tue Nov 10 at 10:00 AM' from the slot's ISO time (booked_slot_id, #262);
    anything that is not a date comes back as it was."""
    d = parse_dt(iso_or_text)
    if d is None:
        return str(iso_or_text or "")
    s = d.strftime("%a %b %d at %I:%M %p")
    return s.replace(" 0", " ")


def booking_of(rec, now=None):
    if not rec.get("event_id"):
        return None
    slot = _first(rec.get("booked_slot_id"), rec.get("booked_slot"), rec.get("slot_id"))
    slot_dt = parse_dt(slot)
    when = str(_first(rec.get("booked_display"), rec.get("booking_display"), "") or "") or (slot_display(slot) if slot_dt else "")
    passed = False
    if slot_dt is None:
        # bookings before #262 carry no slot time; after two weeks the visit is behind us either way
        bq = quiet_days({"booked_at": rec.get("booked_at")}, None, now) if rec.get("booked_at") else None
        passed = bool(bq is not None and bq >= BOOKING_STALE_DAYS)
    if slot_dt is not None:
        n = now or datetime.now(slot_dt.tzinfo) if slot_dt.tzinfo else (now or datetime.now())
        try:
            if slot_dt.tzinfo and n.tzinfo is None:
                n = n.replace(tzinfo=slot_dt.tzinfo)
            elif slot_dt.tzinfo is None and n.tzinfo is not None:
                n = n.replace(tzinfo=None)
            passed = (n - slot_dt).total_seconds() > VISIT_PASSED_GRACE_H * 3600
        except Exception:
            passed = False
    return {"event_id": str(rec.get("event_id")),
            "when": when,
            "slot_at": slot_dt.isoformat() if slot_dt else "",
            "passed": passed,
            "at": iso(_first(rec.get("booked_at"), rec.get("last_outcome_at"))),
            "kind": str(_first(rec.get("booking_kind"), rec.get("visit_type"), "studio_visit") or ""),
            "link": str(rec.get("event_link") or rec.get("calendar_link") or "")}


def chase_of(rec):
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else None
    if not chase:
        return None
    sent = chase.get("sent") if isinstance(chase.get("sent"), dict) else {}
    return {"kind": str(chase.get("kind") or ""), "armed_at": iso(chase.get("armed_at")),
            "sent": len(sent), "last_sent_at": latest(*sent.values()) if sent else "",
            "stopped": str(chase.get("stopped") or ""),
            "channels": list(chase.get("channels") or [])}


def first_touch_of(rec):
    ft = rec.get("first_touch_wa") if isinstance(rec.get("first_touch_wa"), dict) else {}
    out = {}
    if ft.get("wamid"):
        out["whatsapp"] = {"status": str(ft.get("status") or "sent"),
                           "at": iso(_first(ft.get("sent_at"), ft.get("at")))}
    if rec.get("first_touch_sms_at"):
        out["sms"] = {"at": iso(rec.get("first_touch_sms_at"))}
    if rec.get("first_touch_email_at"):   # #273 (the email waits for 7 AM since #272)
        out["email"] = {"at": iso(rec.get("first_touch_email_at"))}
    if isinstance(rec.get("first_touch_email_pending"), dict):
        out["email_pending"] = {"since": iso(rec["first_touch_email_pending"].get("since"))}
    if isinstance(rec.get("first_touch_sms_pending"), dict):
        out["sms_pending"] = {"reason": str(rec["first_touch_sms_pending"].get("reason") or ""),
                              "not_before": iso(rec["first_touch_sms_pending"].get("not_before"))}
    if isinstance(rec.get("first_touch_wa_pending"), dict):
        out["whatsapp_pending"] = {"since": iso(rec["first_touch_wa_pending"].get("since"))}
    return out or None


def consent_of(rec):
    out = {}
    if "sms_consent_form" in rec:
        out["form"] = bool(rec.get("sms_consent_form"))
    for k in ("sms_consent", "consent", "text_ok", "sms_consent_at"):
        if rec.get(k) not in (None, "", False):
            out[k] = rec.get(k) if not isinstance(rec.get(k), (dict, list)) else "yes"
    if rec.get("do_not_sms"):
        out["do_not_sms"] = True
    if rec.get("do_not_contact"):
        out["do_not_contact"] = True
    return out


def lead_view(key, rec, turns=None, manual=False, dnc=False, now=None):
    """One record → one clean shape for the board, the inbox and the card."""
    rec = rec if isinstance(rec, dict) else {}
    turns = turns or []
    stage = stage_of(rec, turns, dnc=dnc, now=now)
    last = last_activity(rec, turns)
    snippet = turns[-1]["text"] if turns else ""
    view = {
        "key": str(key),
        "name": display_name(rec, key),
        "business": str(rec.get("business") or "").strip(),
        "phone": phone_key(key, rec),
        "email": _lower(rec.get("email")),
        "source": source_of(rec, key),
        "channel": channel_of(rec, key),
        "stage": stage,
        "qualified": is_qualified(rec),
        "temperature": _lower(_first(rec.get("temperature"), rec.get("lead_temperature"))),
        "score": rec.get("lead_score"),
        "first_seen": first_seen(rec),
        "last_activity": last,
        "last_turn_role": turns[-1]["role"] if turns else "",
        "snippet": snippet[:160],
        "turns": len(turns),
        "flags": flags_for(rec, turns, stage, manual=manual, now=now),
        "booking": booking_of(rec, now),
        "quiet_days": (lambda q: round(q, 1) if q is not None else None)(quiet_days(rec, turns, now)),
        "outcome": {"last": str(rec.get("last_outcome") or ""), "at": iso(rec.get("last_outcome_at"))}
                   if rec.get("last_outcome") else None,
        "chase": chase_of(rec),
        "first_touch": first_touch_of(rec),
        "offers": {"slots": list(rec.get("offered_slots") or []), "at": iso(rec.get("reoffer_at"))}
                  if rec.get("offered_slots") or rec.get("reoffer_at") else None,
        "consent": consent_of(rec),
        "product": str(rec.get("product") or ""),
        "paid": {"at": iso(_first(rec.get("paid_at"), rec.get("won_at"))),
                 "product": str(_first(rec.get("paid_product"), rec.get("product"), "") or ""),
                 "value": rec.get("paid_value")} if (rec.get("paid_at") or rec.get("won_at")) else None,
        "desk_stage": rec.get("desk_stage") if isinstance(rec.get("desk_stage"), dict) else None,
        "desk_log": [e for e in (rec.get("desk_log") or []) if isinstance(e, dict)][-20:]
                    if isinstance(rec.get("desk_log"), list) else [],
        "manual_until": iso(rec.get("manual_until")) if rec.get("manual_until") else "",
        "notes": [n for n in (rec.get("notes") or []) if isinstance(n, (str, dict))][-20:]
                 if isinstance(rec.get("notes"), list) else ([str(rec.get("notes"))] if rec.get("notes") else []),
        "form": {k: rec.get(k) for k in ("role_raw", "revenue_raw", "must_understand", "website",
                                         "qualified", "qualified_reason", "track", "ad_name",
                                         "utm_campaign") if rec.get(k) not in (None, "")},
        "test": is_test(rec),
    }
    return view


def timeline(view, rec, turns):
    """Dated events from the record (newest last) + the conversation turns.
    Old turns carry no time (the app never stamped them); they are shown in
    order after the dated events, and new turns will carry `at` from #271."""
    rec = rec if isinstance(rec, dict) else {}
    ev = []

    def add(kind, at, text, **extra):
        at_i = iso(at)
        e = {"kind": kind, "at": at_i, "text": text}
        e.update(extra)
        ev.append(e)

    fs = _first(rec.get("lead_form_at"), rec.get("first_contact_time"))
    if fs:
        add("captured", fs, f"Captured via {view['source']}")
    ft = view.get("first_touch") or {}
    if ft.get("whatsapp"):
        add("first_touch", ft["whatsapp"]["at"], f"First touch on WhatsApp — {ft['whatsapp']['status']}")
    if ft.get("sms"):
        add("first_touch", ft["sms"]["at"], "First touch by SMS")
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else {}
    for k, at in sorted((chase.get("sent") or {}).items(), key=lambda kv: epoch(kv[1])):
        add("chase", at, f"Chase · {k}")
    if chase.get("stopped"):
        add("chase_stop", None, f"Chase stopped — {chase['stopped']}")
    if view.get("offers"):
        slots = view["offers"]["slots"]
        shown = ", ".join(str(s.get("display") if isinstance(s, dict) else s) for s in slots[:3])
        add("offer", view["offers"]["at"], f"Times offered: {shown}" if shown else "Times offered")
    if view.get("booking"):
        b = view["booking"]
        add("booked", b["at"], f"Booked — {b['when'] or 'see calendar'}" + (" · the slot has passed, no outcome recorded" if b.get("passed") and not view.get("outcome") else ""))
    if view.get("outcome"):
        add("outcome", view["outcome"]["at"], f"Visit outcome — {view['outcome']['last']}")
    if view.get("paid"):
        p = view["paid"]
        add("paid", p["at"], f"Paid — {p['product'] or 'package'}" + (f" (${p['value']})" if p.get("value") else ""))
    for e in (view.get("desk_log") or []):
        add(str(e.get("kind") or "desk"), e.get("at"), str(e.get("text") or ""), by=str(e.get("by") or ""))
    ev.sort(key=lambda e: epoch(e["at"]) if e["at"] else float("inf"))
    return {"events": ev, "turns": turns}


# ── collections ─────────────────────────────────────────────────────────────

def _views(lead_data, conversation_history, ig_history, manual_keys=None, dnc_keys=None,
           include_test=False, now=None):
    manual_keys = set(manual_keys or [])
    dnc_keys = set(dnc_keys or [])
    out = []
    for key, rec in list((lead_data or {}).items()):
        if not isinstance(rec, dict):
            continue
        if not include_test and is_test(rec):
            continue
        try:
            turns = turns_for(key, rec, conversation_history, ig_history)
            pk = phone_key(key, rec)
            v = lead_view(key, rec, turns, manual=(key in manual_keys or (pk and pk in manual_keys)),
                          dnc=(key in dnc_keys or (pk and pk in dnc_keys)), now=now)
        except Exception as e:   # one bad record never blanks the board
            v = {"key": str(key), "name": str(key), "stage": "New", "flags": ["error"],
                 "last_activity": "", "error": type(e).__name__, "turns": 0, "snippet": "",
                 "source": "—", "channel": "whatsapp", "business": "", "phone": "", "email": ""}
        out.append(v)
    return out


def _card(v):
    keep = ("key", "name", "business", "phone", "email", "source", "channel", "stage", "qualified",
            "temperature", "first_seen", "last_activity", "last_turn_role", "snippet", "turns",
            "flags", "booking", "outcome", "chase", "product", "test", "quiet_days")
    return {k: v.get(k) for k in keep}


def board(lead_data, conversation_history, ig_history, manual_keys=None, dnc_keys=None,
          per_column=150, now=None):
    views = _views(lead_data, conversation_history, ig_history, manual_keys, dnc_keys, now=now)
    cols = {s: [] for s in STAGES}
    for v in views:
        cols.setdefault(v["stage"], []).append(_card(v))
    for s in cols:
        if s == "Booked":
            def _bk(c):
                b = c.get("booking") or {}
                sa = epoch(b.get("slot_at"))
                # upcoming first (soonest on top), then bookings without a time, then passed ones
                return (1 if b.get("passed") else 0, sa if sa else float("inf")) if not b.get("passed") else (1, -sa)
            cols[s].sort(key=_bk)
        else:
            cols[s].sort(key=lambda c: epoch(c.get("last_activity")), reverse=True)
    counts = {s: len(cols[s]) for s in cols}
    attention = sum(1 for v in views if "awaiting_reply" in v.get("flags", []))
    return {"stages": list(STAGES), "columns": {s: cols[s][:per_column] for s in cols},
            "counts": counts, "total": len(views), "awaiting_reply": attention,
            "as_of": (now or datetime.now()).isoformat()}


def inbox(lead_data, conversation_history, ig_history, manual_keys=None, dnc_keys=None,
          limit=200, only=None, now=None):
    views = _views(lead_data, conversation_history, ig_history, manual_keys, dnc_keys, now=now)
    rows = [v for v in views if v.get("turns") or v.get("last_activity")]
    if only == "attention":   # what needs a human: a reply owed, Michael driving, a visit with no outcome
        rows = [v for v in rows if any(f in v["flags"] for f in ("awaiting_reply", "michael", "visit_passed"))]
    elif only == "conversations":
        rows = [v for v in rows if v.get("turns")]
    rows.sort(key=lambda v: epoch(v.get("last_activity")), reverse=True)
    return {"rows": [_card(v) for v in rows[:limit]], "total": len(rows),
            "as_of": (now or datetime.now()).isoformat()}


def search(lead_data, conversation_history, ig_history, q, limit=30, manual_keys=None, dnc_keys=None):
    q = str(q or "").strip().lower()
    if not q:
        return {"rows": [], "q": q}
    qd = digits(q)
    views = _views(lead_data, conversation_history, ig_history, manual_keys, dnc_keys)
    hits = []
    for v in views:
        hay = " ".join([v.get("name", ""), v.get("business", ""), v.get("email", ""),
                        v.get("source", ""), v.get("key", "")]).lower()
        if q in hay or (qd and len(qd) >= 4 and qd in (v.get("phone") or "")):
            hits.append(v)
    hits.sort(key=lambda v: epoch(v.get("last_activity")), reverse=True)
    return {"rows": [_card(v) for v in hits[:limit]], "q": q, "total": len(hits)}


def one(lead_data, conversation_history, ig_history, key, manual_keys=None, dnc_keys=None, now=None):
    rec = (lead_data or {}).get(key)
    if not isinstance(rec, dict):
        # a phone typed by hand → the whatsapp key
        d = digits(key)
        if d:
            if len(d) == 10:
                d = "1" + d
            for cand in (f"whatsapp:+{d}", f"sms:+{d}", d, f"+{d}"):
                if isinstance((lead_data or {}).get(cand), dict):
                    key, rec = cand, lead_data[cand]
                    break
    if not isinstance(rec, dict):
        return None
    turns = turns_for(key, rec, conversation_history, ig_history)
    mk, dk = set(manual_keys or []), set(dnc_keys or [])
    pk = phone_key(key, rec)
    v = lead_view(key, rec, turns, manual=(key in mk or (pk and pk in mk)),
                  dnc=(key in dk or (pk and pk in dk)), now=now)
    v["timeline"] = timeline(v, rec, turns)
    return v


def status(lead_data, conversation_history, ig_history):
    """For /health: a line, not the board."""
    try:
        b = board(lead_data, conversation_history, ig_history, per_column=0)
        return {"leads": b["total"], "counts": b["counts"], "awaiting_reply": b["awaiting_reply"]}
    except Exception as e:
        return {"error": type(e).__name__}


# ── the door (pure parts) ───────────────────────────────────────────────────

def session_ok(cookie_value, secret, admin_secret_given="", admin_ok=None, now=None):
    """Who is at the door: ('mwm', email) for a signed-in MWM session,
    ('admin', '') for the admin secret, (None, '') otherwise."""
    try:
        import victory_auth as va
    except Exception:
        va = None
    if admin_secret_given and callable(admin_ok):
        try:
            if admin_ok(admin_secret_given):
                return ("admin", "")
        except Exception:
            pass
    if va is not None and cookie_value and secret:
        s = va.verify_session(cookie_value, secret, now=now)
        if s and s.get("role") == va.ROLE_MWM and _lower(s.get("email")).endswith("@" + va.HOME_DOMAIN):
            return ("mwm", _lower(s.get("email")))
    return (None, "")


def may_request_link(email):
    """Only our own domain gets a Desk link. Nothing else, ever."""
    try:
        import victory_auth as va
        e = va.normalize_email(email)
        return bool(e) and va.domain_of(e) == va.HOME_DOMAIN
    except Exception:
        return False


def link_email_html(url, minutes=15):
    return f"""
<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#222;">
  <div style="background:#111;padding:22px 28px;border-radius:12px 12px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:20px;">MWM Desk</h1>
  </div>
  <div style="padding:24px 28px;background:#fafafa;border:1px solid #eee;border-top:none;border-radius:0 0 12px 12px;">
    <p style="font-size:15px;line-height:1.6;">Tap to sign in. The link works once and for {minutes} minutes.</p>
    <p style="text-align:center;margin:22px 0;"><a href="{url}" style="background:#111;color:#fff;text-decoration:none;
       padding:14px 22px;border-radius:10px;font-size:16px;display:inline-block;">Open the Desk</a></p>
    <p style="font-size:12px;color:#888;">If you did not ask for this, ignore it — nothing happens without the tap.</p>
  </div>
</div>"""


def link_email_text(url, minutes=15):
    return f"MWM Desk — tap to sign in (works once, {minutes} minutes):\n{url}\n"


DOOR_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>MWM Desk</title>
<style>
:root{color-scheme:dark}body{margin:0;background:#0f0f10;color:#f3f3f1;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px;box-sizing:border-box}
.card{width:100%;max-width:380px;background:#17171a;border:1px solid #26262b;border-radius:18px;padding:28px}
h1{font-size:22px;margin:0 0 4px;letter-spacing:.2px}p{color:#a7a7ad;font-size:14px;line-height:1.5;margin:0 0 18px}
input{width:100%;box-sizing:border-box;background:#0f0f10;border:1px solid #2d2d33;color:#fff;border-radius:12px;padding:14px;font-size:16px}
button{width:100%;margin-top:12px;background:#f5a524;color:#111;border:0;border-radius:12px;padding:14px;font-size:16px;font-weight:600}
.msg{background:#1f2a1f;border:1px solid #2f4a2f;color:#cde9c9;padding:12px;border-radius:12px;font-size:14px;margin-bottom:14px}
.err{background:#2a1f1f;border-color:#4a2f2f;color:#e9c9c9}.foot{margin-top:18px;color:#6e6e75;font-size:12px}
</style></head><body><div class="card">
<h1>MWM Desk</h1><p>The window on the Sales Machine. Sign in with your MWM address and we'll email you a one-tap link.</p>
__MESSAGE__
<form method="post" action="/desk/login"><input type="email" name="email" placeholder="you@mwmcreations.com" autocomplete="email" required autofocus>
<button type="submit">Email me the link</button></form>
<div class="foot">No passwords. The link works once, for 15 minutes.</div>
</div></body></html>"""


def door_html(message="", sent=False, error=False):
    m = ""
    if sent:
        m = '<div class="msg">If that address is one of ours, a link is on its way. Check your email.</div>'
    elif message:
        m = f'<div class="msg{" err" if error else ""}">{message}</div>'
    return DOOR_HTML.replace("__MESSAGE__", m)


# ── actions (slice 2) — pure: they change the record and say what they did ──
#
# Michael, Sun 8 Nov 00:46: "Let's move to slice 2." Every action writes the
# record the rails already read (chase.stopped, do_not_contact, notes…) plus a
# line in desk_log, so the machine and the screen never disagree. Nothing here
# sends anything: the sends go through the app's own senders (register()).

LOG_MAX = 50
MANUAL_DEFAULT_HOURS = 2


def _log(rec, kind, text, by, now, **extra):
    e = {"kind": kind, "text": text, "by": by or "desk", "at": now.isoformat()}
    e.update(extra)
    log = rec.get("desk_log") if isinstance(rec.get("desk_log"), list) else []
    log.append(e)
    rec["desk_log"] = log[-LOG_MAX:]
    return e


def apply_note(rec, text, by, now):
    text = " ".join(str(text or "").split())
    if not text:
        return {"ok": False, "error": "empty note"}
    notes = rec.get("notes") if isinstance(rec.get("notes"), list) else ([str(rec["notes"])] if rec.get("notes") else [])
    notes.append({"text": text[:2000], "by": by, "at": now.isoformat()})
    rec["notes"] = notes[-100:]
    _log(rec, "note", text[:140], by, now)
    return {"ok": True, "notes": len(rec["notes"])}


def apply_stage(rec, stage, by, now, reason="", turns=None):
    """Park (Paused), close (Lost) or reopen a lead by hand. Booked, Visited and
    Client are facts, not opinions: they come from a booking, a report or a
    payment, never from this button."""
    before = stage_of(rec, turns, now=now)
    stage = str(stage or "").strip().title()
    if stage in ("Reopen", "Open", "Active"):
        rec.pop("desk_stage", None)
        chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else None
        if chase and chase.get("stopped") in ("manual", "manual_lost", "manual_paused"):
            chase["stopped"] = ""
        after = stage_of(rec, turns, now=now)
        _log(rec, "stage", f"Reopened ({before} → {after})" + (f" — {reason}" if reason else ""), by, now)
        return {"ok": True, "before": before, "after": after}
    if stage not in OVERRIDE_STAGES:
        return {"ok": False, "error": f"a hand can set {', '.join(OVERRIDE_STAGES)} or Reopen; "
                                      f"Booked, Visited and Client come from a booking, a report or a payment"}
    rec["desk_stage"] = {"stage": stage, "by": by, "at": now.isoformat(), "reason": str(reason or "")[:300]}
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else None
    if chase and not chase.get("stopped"):
        chase["stopped"] = "manual_lost" if stage == "Lost" else "manual_paused"
    after = stage_of(rec, turns, now=now)
    _log(rec, "stage", f"{before} → {after}" + (f" — {reason}" if reason else ""), by, now)
    return {"ok": True, "before": before, "after": after}


def apply_chase(rec, action, by, now):
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else None
    if not chase:
        return {"ok": False, "error": "no chase on this lead"}
    action = _lower(action)
    if action in ("pause", "stop"):
        if chase.get("stopped"):
            return {"ok": True, "stopped": chase["stopped"], "changed": False}
        chase["stopped"] = "manual"
        _log(rec, "chase", "Chase paused", by, now)
        return {"ok": True, "stopped": "manual", "changed": True}
    if action in ("resume", "start"):
        if chase.get("stopped") and chase["stopped"] not in ("manual", "manual_paused"):
            return {"ok": False, "error": f"the chase ended on its own ({chase['stopped']}); re-offer instead"}
        chase["stopped"] = ""
        _log(rec, "chase", "Chase resumed", by, now)
        return {"ok": True, "stopped": "", "changed": True}
    return {"ok": False, "error": "action must be pause or resume"}


def apply_dnc(rec, on, by, now):
    on = bool(on)
    rec["do_not_contact"] = on
    if on:
        rec["dnc_at"] = now.isoformat()
        chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else None
        if chase and not chase.get("stopped"):
            chase["stopped"] = "dnc"
        _log(rec, "dnc", "Do not contact — set", by, now)
    else:
        rec.pop("dnc_at", None)
        _log(rec, "dnc", "Do not contact — lifted", by, now)
    return {"ok": True, "do_not_contact": on}


def send_plan(key, rec, text, as_who="maya"):
    """Which sender, to whom, for a message typed in the Desk. The channel is
    the lead's own: Instagram leads get a DM, phone leads WhatsApp; SMS only
    when the record says the WhatsApp side is not usable or it is an SMS lead."""
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "empty message"}
    if len(text) > 4000:
        return {"ok": False, "error": "message too long"}
    as_who = "michael" if _lower(as_who) == "michael" else "maya"
    k = str(key or "")
    if k.startswith("instagram:"):
        return {"ok": True, "channel": "instagram", "to": k.split(":", 1)[1], "as": as_who, "text": text}
    d = phone_key(k, rec)
    if not d:
        return {"ok": False, "error": "no phone or Instagram id on this lead"}
    ch = _lower((rec or {}).get("channel"))
    if ch in ("sms", "text") or (rec or {}).get("wa_unreachable"):
        return {"ok": True, "channel": "sms", "to": f"+{d}", "as": as_who, "text": text}
    return {"ok": True, "channel": "whatsapp", "to": f"whatsapp:+{d}", "as": as_who, "text": text}


def _until_iso(epoch_s):
    """An epoch from the app's manual-mode switch → ISO, '' when it is not a sane time."""
    try:
        e = float(epoch_s or 0)
        if e <= 0:
            return ""
        return datetime.fromtimestamp(e).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def turn(role, content, by=None, now=None):
    """A conversation turn with a clock on it (and who typed it, for a human
    send). The API-bound copy is made with api_safe()."""
    t = {"role": role, "content": content, "at": (now or datetime.now()).isoformat()}
    if by:
        t["by"] = by
    return t


def api_safe(messages):
    """Only role + content go to the model — extra keys are refused there."""
    out = []
    for m in messages or []:
        if isinstance(m, dict) and "role" in m and "content" in m:
            out.append({"role": m["role"], "content": m["content"]})
        else:
            out.append(m)
    return out


# ── routes ──────────────────────────────────────────────────────────────────

# ── slice 3 (PATCH #273): visits, clients, stats ────────────────────────────
# Michael, Sun 8 Nov 23:44: "do the slice-3 list". Three more windows over the
# same records (nothing here writes): the visits calendar, the clients' hours
# ledger (the WP portal, read live and cached five minutes), and the numbers.
# Plus the Today strip learns the difference between a studio visit and
# "📚 Michael Jr.": his personal calendar is read for the report, so an event
# from it is shown only when it names a lead or sounds like studio business.

VISIT_WORDS = ("studio", "visit", "strategy", "meeting", "consult", "call", "shoot", "record",
               "recording", "podcast", "session", "client", "mwm", "zoom", "meet", "filming",
               "interview", "tour", "walkthrough", "discovery", "onboarding", "presentation")
PORTAL_CACHE_S = 300
EXPIRING_DAYS = 14
_PORTAL_CACHE = {"at": 0.0, "rows": None, "error": ""}


def _name_tokens(name):
    toks = [t for t in re.split(r"[^a-z0-9]+", _lower(name)) if len(t) >= 3]
    return toks


def _lead_names(lead_data):
    """Token lists for every named lead (and their business) — the match set
    for calendar titles. Two tokens or more: a single word ("Michael") would
    claim half the calendar."""
    out = []
    for key, rec in list((lead_data or {}).items()):
        if not isinstance(rec, dict) or is_test(rec):
            continue
        for n in (rec.get("name"), rec.get("business")):
            toks = _name_tokens(n)
            if len(toks) >= 2 and _lower(n) not in ("unknown", "n/a", "none"):
                out.append((toks, str(key)))
    return out


def event_matches_lead(summary, names):
    """The lead key when a calendar title carries two words of a lead's (or
    their business's) name as whole words — else ''."""
    s = " " + re.sub(r"[^a-z0-9]+", " ", _lower(summary)) + " "
    if not s.strip():
        return ""
    for toks, key in names:
        if sum(1 for t in toks if (" " + t + " ") in s) >= 2:
            return key
    return ""


def is_studio_event(summary):
    s = _lower(summary)
    return any(w in s for w in VISIT_WORDS)


def calendar_filter(meetings, lead_data, show_all=False):
    """Keep every event from the MWM calendar; from Michael's own calendar
    keep only what names a lead or sounds like studio business. Each kept
    event learns `lead_key` when a lead matched. Returns (kept, hidden)."""
    names = _lead_names(lead_data)
    kept, hidden = [], 0
    for m in (meetings or []):
        if not isinstance(m, dict):
            continue
        title = str(m.get("summary") or "") or " ".join(filter(None, [m.get("name"), m.get("business")]))
        lk = event_matches_lead(title, names)
        m = dict(m)
        m["lead_key"] = lk
        personal = _lower(m.get("calendar")) == "personal"
        if show_all or not personal or lk or is_studio_event(title):
            kept.append(m)
        else:
            hidden += 1
    return kept, hidden


def _days_between(a_iso, now):
    e = epoch(a_iso)
    if not e:
        return None
    n = now.timestamp() if isinstance(now, datetime) and now.tzinfo else (
        time.mktime(now.timetuple()) if isinstance(now, datetime) else time.time())
    return (e - n) / 86400.0


def twin_losers(views):
    """PATCH #276 — one visit, two records (#256 twins share the calendar event).
    Returns the keys to leave out when counting visits: for each event the
    record that carries the outcome wins, else the one with a conversation."""
    best = {}
    for v in views:
        ev = ((v.get("booking") or {}).get("event_id") or "").strip()
        if not ev:
            continue
        rank = (1 if v.get("outcome") else 0, 1 if v.get("turns") else 0)
        if ev not in best or rank > best[ev][0]:
            best[ev] = (rank, v["key"])
    losers = set()
    for v in views:
        ev = ((v.get("booking") or {}).get("event_id") or "").strip()
        if ev and best[ev][1] != v["key"]:
            losers.add(v["key"])
    return losers


def visits(lead_data, conversation_history, ig_history, manual_keys=None, dnc_keys=None,
           now=None, days_ahead=30, days_back=14):
    """The visits calendar from the records: what is coming, what passed
    without an outcome, and the outcomes of the last two weeks."""
    now = now or datetime.now()
    views = _views(lead_data, conversation_history, ig_history, manual_keys, dnc_keys, now=now)
    upcoming, needs, recent, undated = [], [], [], []
    _losers = twin_losers(views)   # PATCH #276
    for v in views:
        if v["key"] in _losers:
            continue   # the twin carries this visit
        b = v.get("booking")
        oc = v.get("outcome")
        if b:
            d = _days_between(b.get("slot_at") or b.get("at"), now)
            if b.get("slot_at") and not b.get("passed") and d is not None and 0 - (VISIT_PASSED_GRACE_H / 24.0) <= d <= days_ahead:
                upcoming.append(_card(v))
            elif b.get("passed") and not oc and v.get("stage") == "Booked":
                needs.append(_card(v))
            elif not b.get("slot_at") and not b.get("passed") and not oc and v.get("stage") == "Booked":
                undated.append(_card(v))           # a booking with no time (and no date) on record — pre-#262
        if oc and oc.get("at"):
            d = _days_between(oc["at"], now)
            if d is not None and -days_back <= d <= 0.5:
                recent.append(_card(v))
    upcoming.sort(key=lambda c: epoch((c.get("booking") or {}).get("slot_at")) or float("inf"))
    needs.sort(key=lambda c: epoch((c.get("booking") or {}).get("slot_at") or (c.get("booking") or {}).get("at")), reverse=True)
    recent.sort(key=lambda c: epoch((c.get("outcome") or {}).get("at")), reverse=True)
    undated.sort(key=lambda c: epoch(c.get("last_activity")), reverse=True)
    by_day = {}
    for c in upcoming:
        d = parse_dt((c.get("booking") or {}).get("slot_at"))
        label = d.strftime("%a %b %d").replace(" 0", " ") if d else "Time not on record"
        by_day.setdefault(label, []).append(c)
    return {"upcoming": upcoming, "upcoming_by_day": [{"day": k, "cards": v} for k, v in by_day.items()],
            "needs_outcome": needs, "recent": recent, "undated": undated,
            "counts": {"upcoming": len(upcoming), "needs_outcome": len(needs), "recent": len(recent), "undated": len(undated)},
            "as_of": now.isoformat()}


def portal_rows(fetch, force=False, now_s=None):
    """The WP ledger, cached PORTAL_CACHE_S seconds — a tab refresh every 30 s
    must not hit WordPress every time. `fetch()` is the app's wp_list_clients."""
    now_s = now_s if now_s is not None else time.time()
    c = _PORTAL_CACHE
    if not force and c["rows"] is not None and now_s - c["at"] < PORTAL_CACHE_S:
        return c["rows"], True, c["error"]
    rows, err = None, ""
    try:
        rows = fetch() if callable(fetch) else None
    except Exception as e:
        err = repr(e)
    if rows is None:
        if c["rows"] is not None:
            return c["rows"], True, err or "portal unreachable; showing the last read"
        return None, False, err or "portal unreachable"
    c.update(at=now_s, rows=rows, error="")
    return rows, False, ""


def _mask_match(masked, email):
    """'cam…@gmail.com' matches 'camila@gmail.com'."""
    m, e = _lower(masked), _lower(email)
    if not m or not e or "@" not in m or "@" not in e:
        return False
    if "…" not in m:
        return m == e
    head, dom = m.split("@", 1)
    head = head.replace("…", "")
    eh, ed = e.split("@", 1)
    return ed == dom and eh.startswith(head)


def _client_money(rec):
    """Monthly value of a client record: the deal's own number when the
    purchase wrote one (studio_package.mrr — a $350/week plan is $1,517, not
    $1,200), else None (the caller falls back to the package name)."""
    sp = rec.get("studio_package") if isinstance(rec, dict) and isinstance(rec.get("studio_package"), dict) else None
    if sp and sp.get("recurring") is False:
        return 0, int(sp.get("one_off") or 0)
    if sp and sp.get("mrr") not in (None, ""):
        try:
            return int(sp["mrr"]), 0
        except Exception:
            pass
    return None, None


def clients(rows, lead_data, now=None, package_lookup=None, default_mrr=1200):
    """The ledger merged with the lead records. `rows` come from the portal
    (name, masked email, package_name, contract_hours, hours_used, dates,
    active). A row's end date is the truth: the portal never flips `active`.
    `package_lookup(name)` → spec with recurring/mrr/one_off, or None."""
    now = now or datetime.now()
    today = now.date() if isinstance(now, datetime) else now
    leads = [(k, r) for k, r in list((lead_data or {}).items()) if isinstance(r, dict) and not is_test(r)]
    out = []
    mrr_active = 0
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        name = " ".join(str(row.get("name") or "").split())
        if _lower(name).startswith("qa test"):
            continue
        key, rec = "", None
        for k, r in leads:
            if _lower(r.get("name")) == _lower(name) or _mask_match(row.get("email"), r.get("email")):
                key, rec = str(k), r
                break
        try:
            hours = float(row.get("contract_hours") or 0)
        except Exception:
            hours = 0.0
        try:
            used = float(row.get("hours_used") or 0)
        except Exception:
            used = 0.0
        end = parse_dt(row.get("contract_end_date"))
        start = parse_dt(row.get("contract_start_date"))
        days_left = (end.date() - today).days if end else None
        if days_left is None:
            status = "unknown"
        elif days_left < 0:
            status = "ended"
        elif days_left <= EXPIRING_DAYS:
            status = "expiring"
        else:
            status = "active"
        mrr, one_off = _client_money(rec) if rec else (None, None)
        if mrr is None:
            spec = package_lookup(row.get("package_name")) if callable(package_lookup) else None
            if spec:
                mrr = int(spec.get("mrr") or 0) if spec.get("recurring") else 0
                one_off = 0 if spec.get("recurring") else int(spec.get("one_off") or 0)
            else:
                mrr, one_off = default_mrr, 0
        if status in ("active", "expiring"):
            mrr_active += int(mrr or 0)
        out.append({"name": name, "email": str(row.get("email") or ""), "package": str(row.get("package_name") or ""),
                    "hours": hours, "used": used, "left": max(0.0, hours - used),
                    "pct": (min(100, round(used / hours * 100)) if hours else 0),
                    "start": start.date().isoformat() if start else "", "end": end.date().isoformat() if end else "",
                    "days_left": days_left, "status": status, "mrr": int(mrr or 0), "one_off": int(one_off or 0),
                    "key": key, "lead_stage": (stage_of(rec) if rec else "")})
    order = {"expiring": 0, "active": 1, "unknown": 2, "ended": 3}
    # live contracts: soonest end first; ended ones: the most recently ended first
    out.sort(key=lambda c: (order.get(c["status"], 9),
                            (-(c["days_left"]) if c["status"] == "ended" else c["days_left"]) if c["days_left"] is not None else 9999))
    active = [c for c in out if c["status"] in ("active", "expiring")]
    return {"rows": out,
            "summary": {"active": len(active), "expiring": sum(1 for c in out if c["status"] == "expiring"),
                        "ended": sum(1 for c in out if c["status"] == "ended"),
                        "mrr": mrr_active, "hours_left": round(sum(c["left"] for c in active), 1),
                        "hours_bought": round(sum(c["hours"] for c in active), 1)},
            "as_of": now.isoformat() if isinstance(now, datetime) else str(now)}


def _in_window(at, start_e, end_e):
    e = epoch(at)
    return bool(e and start_e <= e <= end_e)


def stats(lead_data, conversation_history, ig_history, manual_keys=None, dnc_keys=None,
          days=30, now=None, ledger_summary=None):
    """The numbers for one window: the cohort that arrived in it (by source,
    how the first touch went, who replied, who booked), the events that
    happened in it (bookings, visits by outcome, wins), the chase, and the
    board as it stands now."""
    now = now or datetime.now()
    try:
        days = int(days) if days not in (None, "") else 30
    except Exception:
        days = 30
    days = max(1, min(365, days))
    end_e = now.timestamp() if now.tzinfo else time.mktime(now.timetuple())
    start_e = end_e - days * 86400
    views = _views(lead_data, conversation_history, ig_history, manual_keys, dnc_keys, now=now)
    recs = lead_data or {}
    by_source, cohort = {}, []
    ft = {"email": 0, "sms": 0, "whatsapp": 0, "waiting": 0, "none": 0, "form_leads": 0}
    contacted = replied = booked_c = visited_c = won_c = 0
    booked_ev = 0
    visits_by = {}
    won_ev = 0
    chase_sent = 0
    chase_active = 0
    chase_stops = {}
    first_touch_minutes = []
    stage_counts = {s: 0 for s in STAGES}
    awaiting = 0
    _losers = twin_losers(views)   # PATCH #276: a visit is counted once
    for v in views:
        rec = recs.get(v["key"]) if isinstance(recs.get(v["key"]), dict) else {}
        _twin_loser = v["key"] in _losers
        stage_counts[v["stage"]] = stage_counts.get(v["stage"], 0) + 1
        if "awaiting_reply" in (v.get("flags") or []):
            awaiting += 1
        ch = rec.get("chase") if isinstance(rec.get("chase"), dict) else {}
        if ch:
            if ch.get("stopped"):
                if _in_window(ch.get("stopped_at"), start_e, end_e):
                    chase_stops[str(ch["stopped"])] = chase_stops.get(str(ch["stopped"]), 0) + 1
            elif ch.get("armed_at"):
                chase_active += 1
            for at in (ch.get("sent") or {}).values():
                if _in_window(at, start_e, end_e):
                    chase_sent += 1
        b = v.get("booking") or {}
        if b and not _twin_loser and _in_window(b.get("at"), start_e, end_e):
            booked_ev += 1
        oc = v.get("outcome") or {}
        if oc and not _twin_loser and _in_window(oc.get("at"), start_e, end_e):
            visits_by[oc["last"]] = visits_by.get(oc["last"], 0) + 1
        p = v.get("paid") or {}
        if (p and _in_window(p.get("at"), start_e, end_e)) or (oc and not _twin_loser and oc.get("last") == "client_won" and _in_window(oc.get("at"), start_e, end_e)):
            won_ev += 1
        if not _in_window(v.get("first_seen"), start_e, end_e):
            continue
        cohort.append(v)
        src = v.get("source") or "—"
        by_source[src] = by_source.get(src, 0) + 1
        turns = turns_for(v["key"], rec, conversation_history, ig_history)
        out_ = has_outbound(rec, turns)
        in_ = has_inbound(rec, turns) or (_lower(ch.get("stopped")) == "replied")
        if out_:
            contacted += 1
        if in_:
            replied += 1
        if b:
            booked_c += 1
        if oc:
            visited_c += 1
        if v.get("stage") == "Client":
            won_c += 1
        if rec.get("meta_lead_ad") or _lower(rec.get("source")) == "meta lead ad":
            ft["form_leads"] += 1
            wa = rec.get("first_touch_wa") if isinstance(rec.get("first_touch_wa"), dict) else {}
            if wa.get("wamid") and _lower(wa.get("status")) in ("delivered", "read", "sent"):
                ft["whatsapp"] += 1
            if rec.get("first_touch_sms_at"):
                ft["sms"] += 1
            if rec.get("first_touch_email_at"):
                ft["email"] += 1
            if isinstance(rec.get("first_touch_sms_pending"), dict) or isinstance(rec.get("first_touch_wa_pending"), dict) \
                    or isinstance(rec.get("first_touch_email_pending"), dict):
                ft["waiting"] += 1
            if not (wa.get("wamid") or rec.get("first_touch_sms_at") or rec.get("first_touch_email_at")):
                ft["none"] += 1
            t0 = epoch(rec.get("lead_form_at"))
            t1 = min([e for e in (epoch(rec.get("first_touch_email_at")), epoch(rec.get("first_touch_sms_at")),
                                  epoch(wa.get("sent_at"))) if e] or [0])
            if t0 and t1 and t1 >= t0:
                first_touch_minutes.append((t1 - t0) / 60.0)
    src_rows = sorted(by_source.items(), key=lambda kv: -kv[1])
    n = len(cohort)
    med = sorted(first_touch_minutes)[len(first_touch_minutes) // 2] if first_touch_minutes else None
    return {
        "days": days, "as_of": now.isoformat(),
        "cohort": {"new": n, "contacted": contacted, "replied": replied, "booked": booked_c,
                   "visited": visited_c, "won": won_c,
                   "reply_rate": (round(replied / contacted * 100) if contacted else None),
                   "book_rate": (round(booked_c / n * 100) if n else None)},
        "by_source": [{"source": s, "n": c} for s, c in src_rows],
        "first_touch": dict(ft, median_minutes=(round(med, 1) if med is not None else None)),
        "events": {"booked": booked_ev, "visits": sum(visits_by.values()), "visits_by_outcome": visits_by, "won": won_ev},
        "chase": {"active": chase_active, "sent": chase_sent, "stopped": chase_stops},
        "now": {"stages": stage_counts, "awaiting_reply": awaiting, "leads": len(views)},
        "clients": ledger_summary or None,
    }


def register(app, admin_ok, lead_data, conversation_history, ig_history, pg=None,
             send_email=None, report_error=None, notify=None, static_dir=None,
             manual_keys=None, dnc_keys=None, actions=None):
    """Mount the Desk on the Flask app. `lead_data` / histories are the live
    dicts (read only here); `manual_keys()` and `dnc_keys()` are callables that
    return the lead keys Michael took over and the do-not-contact keys.
    `actions` (slice 2) is a dict of the app's own callables the Desk acts
    through: pipeline_event(event_type, **kw), send_whatsapp(to, body),
    send_instagram(igsid, body), send_sms(phone, body), manual_set(digits,
    hours) → until_epoch, manual_clear(digits), save() (persist now)."""
    from flask import request, jsonify, make_response, redirect, send_from_directory, Response
    try:
        import victory_auth as va
        import victory_store as vs
    except Exception as e:  # the door needs them; the app must still boot
        print(f"[DESK] auth modules missing: {e!r}")
        va = vs = None

    here = static_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "desk_static")
    limiter = va.RateLimiter() if va else None

    def _err(where, exc, ctx=""):
        print(f"[DESK] {where}: {exc!r} {ctx}")
        if report_error:
            try:
                report_error(f"desk.{where}", exc, ctx)
            except Exception:
                pass

    def _secret():
        try:
            return vs.session_secret() if vs else ""
        except Exception as e:
            _err("session_secret", e)
            return ""

    def _who():
        return session_ok(request.cookies.get(COOKIE, ""), _secret() if vs else "",
                          request.values.get("secret", "") or request.headers.get("X-Admin-Secret", ""),
                          admin_ok)

    def _base_url():
        root = request.url_root.rstrip("/")
        if request.headers.get("X-Forwarded-Proto", "").startswith("https"):
            root = "https://" + root.split("://", 1)[-1]
        return root

    def _ip():
        xf = request.headers.get("X-Forwarded-For", "")
        return (xf.split(",")[0].strip() if xf else request.remote_addr) or ""

    def _manual():
        try:
            return set(manual_keys() if callable(manual_keys) else (manual_keys or []))
        except Exception:
            return set()

    def _dnc():
        try:
            return set(dnc_keys() if callable(dnc_keys) else (dnc_keys or []))
        except Exception:
            return set()

    def _need_auth():
        role, _ = _who()
        if role:
            return None
        return jsonify({"ok": False, "error": "sign in at /desk/"}), 401

    @app.route("/desk", methods=["GET"])
    def desk_root_redirect():
        return redirect("/desk/")

    @app.route("/desk/", methods=["GET"])
    def desk_home():
        role, email = _who()
        if not role:
            return Response(door_html(), mimetype="text/html")
        try:
            with open(os.path.join(here, "desk.html"), encoding="utf-8") as f:
                html = f.read()
        except Exception as e:
            _err("page", e)
            return Response("Desk page missing", status=500)
        resp = make_response(html)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/desk/static/<path:fname>", methods=["GET"])
    def desk_static(fname):
        resp = make_response(send_from_directory(here, fname))
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/desk/login", methods=["POST"])
    def desk_login():
        try:
            if va is None or vs is None:
                return Response(door_html("Sign-in is unavailable right now.", error=True), mimetype="text/html"), 503
            email = va.normalize_email(request.form.get("email", "")
                                       or (request.get_json(silent=True) or {}).get("email", ""))
            ok_ip = limiter.allow("desk:ip:" + _ip(), va.LINK_MAX_PER_IP) if limiter else True
            ok_em = limiter.allow("desk:em:" + email, va.LINK_MAX_PER_EMAIL) if (limiter and email) else True
            if email and may_request_link(email) and ok_ip and ok_em:
                token, token_hash = va.new_token()
                if vs.create_link(token_hash, email, _ip()):
                    url = f"{_base_url()}/desk/auth?token={token}"
                    sent = False
                    if send_email:
                        try:
                            sent = bool(send_email(email, LINK_SUBJECT, link_email_text(url),
                                                   link_email_html(url)))
                        except Exception as sx:
                            _err("login.send", sx, email)
                    print(f"[DESK] sign-in link {'sent to' if sent else 'created but NOT emailed for'} {email}")
                    if not sent and notify:
                        try:
                            notify(f":warning: MWM Desk could not email a sign-in link to {email}.")
                        except Exception:
                            pass
            elif email and not may_request_link(email):
                print("[DESK] refused a link for an address off our domain")
            return Response(door_html(sent=True), mimetype="text/html")
        except Exception as e:
            _err("login", e)
            return Response(door_html(sent=True), mimetype="text/html")

    @app.route("/desk/auth", methods=["GET"])
    def desk_auth():
        try:
            if va is None or vs is None:
                return Response(door_html("Sign-in is unavailable right now.", error=True), mimetype="text/html"), 503
            token = request.args.get("token", "")
            secret = vs.session_secret()
            if not secret:
                return Response(door_html("Sign-in is unavailable right now.", error=True), mimetype="text/html"), 503
            claimed = vs.consume_link(va.hash_token(token)) if token else None
            if not claimed:
                return Response(door_html("That link has already been used, or it is not valid. Ask for a new one.",
                                          error=True), mimetype="text/html"), 400
            email, issued_at = claimed
            if va.link_expired(issued_at):
                return Response(door_html("That link has expired. Ask for a new one.", error=True),
                                mimetype="text/html"), 400
            if not may_request_link(email):
                return Response(door_html("The Desk is for MWM addresses only.", error=True),
                                mimetype="text/html"), 403
            value = va.sign_session(email, va.ROLE_MWM, "", secret)
            if not value:
                return Response(door_html("Sign-in failed. Try again.", error=True), mimetype="text/html"), 500
            resp = make_response(redirect("/desk/"))
            resp.set_cookie(COOKIE, value, max_age=va.SESSION_TTL_SECONDS, httponly=True, samesite="Lax",
                            secure=request.headers.get("X-Forwarded-Proto", "").startswith("https"),
                            path=COOKIE_PATH)
            print(f"[DESK] signed in {email}")
            return resp
        except Exception as e:
            _err("auth", e)
            return Response(door_html("Sign-in failed. Try again.", error=True), mimetype="text/html"), 500

    @app.route("/desk/logout", methods=["GET", "POST"])
    def desk_logout():
        resp = make_response(redirect("/desk/"))
        resp.set_cookie(COOKIE, "", max_age=0, path=COOKIE_PATH)
        return resp

    # ── JSON ──
    @app.route("/desk/api/me", methods=["GET"])
    def desk_api_me():
        role, email = _who()
        if not role:
            return jsonify({"ok": False, "signed_in": False}), 401
        return jsonify({"ok": True, "signed_in": True, "role": role, "email": email})

    @app.route("/desk/api/board", methods=["GET"])
    def desk_api_board():
        bad = _need_auth()
        if bad:
            return bad
        try:
            return jsonify(dict(ok=True, **board(lead_data, conversation_history, ig_history,
                                                 manual_keys=_manual(), dnc_keys=_dnc())))
        except Exception as e:
            _err("board", e)
            return jsonify({"ok": False, "error": repr(e)}), 500

    @app.route("/desk/api/inbox", methods=["GET"])
    def desk_api_inbox():
        bad = _need_auth()
        if bad:
            return bad
        try:
            only = request.args.get("only") or None
            lim = min(500, max(1, int(request.args.get("limit") or 200)))
            return jsonify(dict(ok=True, **inbox(lead_data, conversation_history, ig_history,
                                                 manual_keys=_manual(), dnc_keys=_dnc(), limit=lim, only=only)))
        except Exception as e:
            _err("inbox", e)
            return jsonify({"ok": False, "error": repr(e)}), 500

    @app.route("/desk/api/search", methods=["GET"])
    def desk_api_search():
        bad = _need_auth()
        if bad:
            return bad
        try:
            return jsonify(dict(ok=True, **search(lead_data, conversation_history, ig_history,
                                                  request.args.get("q", ""), manual_keys=_manual(), dnc_keys=_dnc())))
        except Exception as e:
            _err("search", e)
            return jsonify({"ok": False, "error": repr(e)}), 500

    @app.route("/desk/api/lead/<path:key>", methods=["GET"])
    def desk_api_lead(key):
        bad = _need_auth()
        if bad:
            return bad
        try:
            v = one(lead_data, conversation_history, ig_history, key, manual_keys=_manual(), dnc_keys=_dnc())
            if v is None:
                return jsonify({"ok": False, "error": "no such lead"}), 404
            return jsonify(dict(ok=True, lead=v))
        except Exception as e:
            _err("lead", e, key)
            return jsonify({"ok": False, "error": repr(e)}), 500

    # ── actions (slice 2) ──
    acts = actions or {}

    def _rec_for(key):
        rec = (lead_data or {}).get(key)
        if isinstance(rec, dict):
            return key, rec
        d = digits(key)
        if d:
            if len(d) == 10:
                d = "1" + d
            for cand in (f"whatsapp:+{d}", f"sms:+{d}"):
                if isinstance((lead_data or {}).get(cand), dict):
                    return cand, lead_data[cand]
        return None, None

    def _by():
        role, email = _who()
        return (email.split("@")[0] if email else ("agent" if role == "admin" else "desk"))

    def _act(fn):
        try:
            fn()
        except Exception as e:
            _err("after_action", e)

    def _json_body():
        return request.get_json(silent=True) or request.form.to_dict() or {}

    def _done(key, rec, extra=None):
        _act(lambda: acts.get("save") and acts["save"]())
        v = one(lead_data, conversation_history, ig_history, key, manual_keys=_manual(), dnc_keys=_dnc())
        out = {"ok": True, "lead": v}
        if extra:
            out.update(extra)
        return jsonify(out)

    @app.route("/desk/api/lead/<path:key>/note", methods=["POST"])
    def desk_api_note(key):
        bad = _need_auth()
        if bad:
            return bad
        k, rec = _rec_for(key)
        if rec is None:
            return jsonify({"ok": False, "error": "no such lead"}), 404
        r = apply_note(rec, _json_body().get("text"), _by(), datetime.now())
        if not r.get("ok"):
            return jsonify(r), 400
        return _done(k, rec, r)

    @app.route("/desk/api/lead/<path:key>/stage", methods=["POST"])
    def desk_api_stage(key):
        bad = _need_auth()
        if bad:
            return bad
        k, rec = _rec_for(key)
        if rec is None:
            return jsonify({"ok": False, "error": "no such lead"}), 404
        body = _json_body()
        turns = turns_for(k, rec, conversation_history, ig_history)
        r = apply_stage(rec, body.get("stage"), _by(), datetime.now(), reason=body.get("reason", ""), turns=turns)
        if not r.get("ok"):
            return jsonify(r), 400
        if r["before"] != r["after"] and acts.get("pipeline_event"):
            _act(lambda: acts["pipeline_event"]("STAGE_CHANGE", lead_name=display_name(rec, k),
                                                lead_phone=phone_key(k, rec), source=source_of(rec, k),
                                                old_stage=r["before"], new_stage=r["after"],
                                                context=f"by {_by()} via Desk" + (f": {body.get('reason')}" if body.get("reason") else "")))
        return _done(k, rec, r)

    @app.route("/desk/api/lead/<path:key>/chase", methods=["POST"])
    def desk_api_chase(key):
        bad = _need_auth()
        if bad:
            return bad
        k, rec = _rec_for(key)
        if rec is None:
            return jsonify({"ok": False, "error": "no such lead"}), 404
        r = apply_chase(rec, _json_body().get("action"), _by(), datetime.now())
        if not r.get("ok"):
            return jsonify(r), 400
        return _done(k, rec, r)

    @app.route("/desk/api/lead/<path:key>/dnc", methods=["POST"])
    def desk_api_dnc(key):
        bad = _need_auth()
        if bad:
            return bad
        k, rec = _rec_for(key)
        if rec is None:
            return jsonify({"ok": False, "error": "no such lead"}), 404
        on = str(_json_body().get("on", "1")).lower() in ("1", "true", "yes", "on")
        r = apply_dnc(rec, on, _by(), datetime.now())
        if acts.get("dnc_sms"):
            _act(lambda: acts["dnc_sms"](phone_key(k, rec), on))
        return _done(k, rec, r)

    @app.route("/desk/api/lead/<path:key>/takeover", methods=["POST"])
    def desk_api_takeover(key):
        bad = _need_auth()
        if bad:
            return bad
        k, rec = _rec_for(key)
        if rec is None:
            return jsonify({"ok": False, "error": "no such lead"}), 404
        body = _json_body()
        d = phone_key(k, rec)
        if not d:
            return jsonify({"ok": False, "error": "take-over works on phone leads (Maya holds WhatsApp/SMS replies)"}), 400
        action = _lower(body.get("action") or "take")
        now = datetime.now()
        if action in ("take", "takeover", "hold"):
            try:
                hours = float(body.get("hours") or MANUAL_DEFAULT_HOURS)
            except (TypeError, ValueError):
                hours = MANUAL_DEFAULT_HOURS
            hours = min(max(hours, 0.25), 72)
            until = acts["manual_set"](d, hours) if acts.get("manual_set") else None
            rec["manual_until"] = _until_iso(until) or (now + timedelta(hours=hours)).isoformat()
            _log(rec, "takeover", f"{_by()} took the conversation (Maya holds for {hours:g} h)", _by(), now)
        else:
            if acts.get("manual_clear"):
                acts["manual_clear"](d)
            rec.pop("manual_until", None)
            _log(rec, "takeover", "Handed back to Maya", _by(), now)
        return _done(k, rec, {"action": action})

    @app.route("/desk/api/lead/<path:key>/send", methods=["POST"])
    def desk_api_send(key):
        bad = _need_auth()
        if bad:
            return bad
        k, rec = _rec_for(key)
        if rec is None:
            return jsonify({"ok": False, "error": "no such lead"}), 404
        body = _json_body()
        plan = send_plan(k, rec, body.get("text"), body.get("as") or "maya")
        if not plan.get("ok"):
            return jsonify(plan), 400
        if rec.get("do_not_contact"):
            return jsonify({"ok": False, "error": "this lead is marked do-not-contact"}), 400
        sender = acts.get("send_" + plan["channel"])
        if not sender:
            return jsonify({"ok": False, "error": f"no sender wired for {plan['channel']}"}), 500
        now = datetime.now()
        try:
            res = sender(plan["to"], plan["text"])
        except Exception as e:
            _err("send", e, k)
            return jsonify({"ok": False, "error": f"{plan['channel']} send failed: {e!r}"}), 502
        if isinstance(res, dict) and (res.get("error") or res.get("ok") is False):
            return jsonify({"ok": False, "error": str(res.get("reason") or res.get("error") or "refused"), "channel": plan["channel"]}), 400
        # the turn goes into the history the rails read, with a clock and a signature
        hist = ig_history if plan["channel"] == "instagram" else conversation_history
        hk = k if plan["channel"] == "instagram" else f"whatsapp:+{phone_key(k, rec)}"
        hist.setdefault(hk, []).append(turn("assistant", plan["text"], by=plan["as"], now=now))
        rec["last_message_time"] = now.isoformat()
        if plan["as"] == "michael" and acts.get("manual_set") and plan["channel"] != "instagram":
            # a human is talking: Maya holds this thread for a while
            until = acts["manual_set"](phone_key(k, rec), MANUAL_DEFAULT_HOURS)
            if _until_iso(until):
                rec["manual_until"] = _until_iso(until)
        _log(rec, "send", f"{plan['as'].title()} sent on {plan['channel']}: {plan['text'][:120]}", _by(), now)
        return _done(k, rec, {"sent": {"channel": plan["channel"], "as": plan["as"]}})

    # ── the Daily Event Report, under the Desk's own path ──
    # The desk_session cookie is scoped to /desk, so a call to /meeting-report/*
    # never carries it (the first live morning: a 401 → reload loop). The Desk
    # proxies the two report calls here, with its own door, and hands the
    # request to the app's unchanged handlers.
    @app.route("/desk/api/report/meetings", methods=["GET"])
    def desk_report_meetings():
        bad = _need_auth()
        if bad:
            return bad
        fn = acts.get("report_meetings")
        if not fn:
            return jsonify({"ok": False, "error": "report not wired"}), 500
        try:
            resp = fn()
            # PATCH #273 — the report reads Michael's own calendar too; the Desk shows a
            # personal event only when it names a lead or sounds like studio business
            r0, status = (resp[0], resp[1]) if isinstance(resp, tuple) else (resp, 200)
            body = None
            try:
                body = r0.get_json(silent=True) if hasattr(r0, "get_json") else None
            except Exception:
                body = None
            if status == 200 and isinstance(body, dict) and body.get("ok"):
                kept, hidden = calendar_filter(body.get("meetings") or [], lead_data,
                                               show_all=str(request.args.get("all") or "") in ("1", "true"))
                return jsonify(dict(body, meetings=kept, hidden=hidden))
            return resp
        except Exception as e:
            _err("report_meetings", e)
            return jsonify({"ok": False, "error": repr(e)}), 500

    @app.route("/desk/api/report/submit", methods=["POST"])
    def desk_report_submit():
        bad = _need_auth()
        if bad:
            return bad
        fn = acts.get("report_submit")
        if not fn:
            return jsonify({"ok": False, "error": "report not wired"}), 500
        try:
            return fn()
        except Exception as e:
            _err("report_submit", e)
            return jsonify({"ok": False, "error": repr(e)}), 500

    # ── slice 3 (PATCH #273): visits · clients · stats ──
    def _lookup_pkg(name):
        fn = acts.get("package_by_name")
        try:
            return fn(name) if callable(fn) else None
        except Exception:
            return None

    def _ledger(force=False):
        rows, cached, err = portal_rows(acts.get("portal_clients"), force=force)
        if rows is None:
            return None, err
        return clients(rows, lead_data, package_lookup=_lookup_pkg), err

    @app.route("/desk/api/visits", methods=["GET"])
    def desk_api_visits():
        bad = _need_auth()
        if bad:
            return bad
        try:
            return jsonify(dict(ok=True, **visits(lead_data, conversation_history, ig_history,
                                                  manual_keys=_manual(), dnc_keys=_dnc())))
        except Exception as e:
            _err("visits", e)
            return jsonify({"ok": False, "error": repr(e)}), 500

    @app.route("/desk/api/clients", methods=["GET"])
    def desk_api_clients():
        bad = _need_auth()
        if bad:
            return bad
        try:
            led, err = _ledger(force=str(request.args.get("refresh") or "") in ("1", "true"))
            if led is None:
                return jsonify({"ok": False, "error": err or "portal ledger unreachable"}), 502
            led["note"] = err
            return jsonify(dict(ok=True, **led))
        except Exception as e:
            _err("clients", e)
            return jsonify({"ok": False, "error": repr(e)}), 500

    @app.route("/desk/api/stats", methods=["GET"])
    def desk_api_stats():
        bad = _need_auth()
        if bad:
            return bad
        try:
            days = int(request.args.get("days") or 30)
        except Exception:
            days = 30
        try:
            led, _ = _ledger()
            return jsonify(dict(ok=True, **stats(lead_data, conversation_history, ig_history,
                                                 manual_keys=_manual(), dnc_keys=_dnc(), days=days,
                                                 ledger_summary=(led or {}).get("summary") if led else None)))
        except Exception as e:
            _err("stats", e)
            return jsonify({"ok": False, "error": repr(e)}), 500

    print("[DESK] mounted at /desk/ (slice 3: see + act + measure)")
    return True
