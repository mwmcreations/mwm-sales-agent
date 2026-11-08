"""desk.py — PATCH #270 — MWM Desk, slice 1: SEE.

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
    return bool((rec or {}).get("test_lead") or (rec or {}).get("internal"))


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
        turns.append({"role": "lead" if role == "user" else "maya",
                      "text": content, "at": iso(t.get("at") or t.get("ts") or t.get("time"))})
    return turns


def has_inbound(rec, turns):
    if any(t["role"] == "lead" for t in (turns or [])):
        return True
    return bool(_first(rec.get("last_inbound_at"), rec.get("sms_inbound_at"),
                       rec.get("first_inbound_at"), rec.get("replied_at"),
                       rec.get("email_reply_at")))


def has_outbound(rec, turns):
    if any(t["role"] == "maya" for t in (turns or [])):
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


def stage_of(rec, turns=None, dnc=False):
    rec = rec or {}
    chase = rec.get("chase") if isinstance(rec.get("chase"), dict) else {}
    stopped = _lower(chase.get("stopped"))
    if is_client(rec):
        return "Client"
    if dnc or rec.get("do_not_contact") or rec.get("do_not_sms"):
        return "Lost"
    if _lower(rec.get("last_outcome")) in VISIT_OUTCOMES:
        return "Visited"
    if rec.get("event_id"):
        return "Booked"
    if stopped in LOST_STOPS or _lower(rec.get("outcome")) in ("lost", "no", "declined"):
        return "Lost"
    temp = _lower(_first(rec.get("temperature"), rec.get("lead_temperature")))
    if stopped in PAUSED_STOPS or rec.get("cold_fired") or rec.get("farewell_sent_at") \
            or temp == "cold" or _lower(rec.get("whatsapp_status")) == "cold":
        return "Paused"
    if has_inbound(rec, turns):
        return "Replied"
    if has_outbound(rec, turns):
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


def source_of(rec, key=""):
    s = str(rec.get("source") or "").strip()
    if s:
        return s
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
    if rec.get("offered_slots") and stage not in ("Booked", "Visited", "Client"):
        out.append("times_offered")
    return out


def booking_of(rec):
    if not rec.get("event_id"):
        return None
    return {"event_id": str(rec.get("event_id")),
            "when": str(_first(rec.get("booked_display"), rec.get("booking_display"), "") or ""),
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
    stage = stage_of(rec, turns, dnc=dnc)
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
        "booking": booking_of(rec),
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
        add("booked", view["booking"]["at"], f"Booked — {view['booking']['when'] or 'see calendar'}")
    if view.get("outcome"):
        add("outcome", view["outcome"]["at"], f"Visit outcome — {view['outcome']['last']}")
    if view.get("paid"):
        p = view["paid"]
        add("paid", p["at"], f"Paid — {p['product'] or 'package'}" + (f" (${p['value']})" if p.get("value") else ""))
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
            "flags", "booking", "outcome", "chase", "product", "test")
    return {k: v.get(k) for k in keep}


def board(lead_data, conversation_history, ig_history, manual_keys=None, dnc_keys=None,
          per_column=150, now=None):
    views = _views(lead_data, conversation_history, ig_history, manual_keys, dnc_keys, now=now)
    cols = {s: [] for s in STAGES}
    for v in views:
        cols.setdefault(v["stage"], []).append(_card(v))
    for s in cols:
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
    if only == "attention":
        rows = [v for v in rows if "awaiting_reply" in v["flags"] or "michael" in v["flags"]]
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


# ── routes ──────────────────────────────────────────────────────────────────

def register(app, admin_ok, lead_data, conversation_history, ig_history, pg=None,
             send_email=None, report_error=None, notify=None, static_dir=None,
             manual_keys=None, dnc_keys=None):
    """Mount the Desk on the Flask app. `lead_data` / histories are the live
    dicts (read only here); `manual_keys()` and `dnc_keys()` are callables that
    return the lead keys Michael took over and the do-not-contact keys."""
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

    print("[DESK] mounted at /desk/ (slice 1: see)")
    return True
