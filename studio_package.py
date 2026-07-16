"""studio_package.py — Studio Package automation (Phase 1, Jul 2026).

The Studio Package ($1,200/mo, 12h over 3 months) is a core Sales Machine
product. This module owns the machine side of the loop:

    studio visit -> Michael pitches -> [PACKAGE_PITCHED] -> follow-up sequence
                 -> Stripe purchase  -> [PACKAGE_PURCHASED] -> portal account
                 -> welcome email (access code + Calendly) -> LARA/#matt alert

Design notes:
  - Stripe webhook is signature-verified (STRIPE_WEBHOOK_SECRET) and
    idempotent on event.id (persisted via pg_store).
  - Portal provisioning calls the WP Code Snippets endpoint
    (action=mwm_studio_provision_client) with a shared secret header
    (WP_PORTAL_SECRET). Idempotent by email on the WP side.
  - Post-pitch follow-up sequence is EMAIL-FIRST (WABA billing incident
    Jul 5 blocks outbound WhatsApp templates; email sidesteps it).
  - Never raises into the caller; all failures go to the injected
    error reporter.

app.py injects dependencies via configure() — this module imports nothing
from app.py (no circulars).
"""
import os
import json
import hmac
import hashlib
import threading
import time
from datetime import datetime, timedelta

import requests as http_requests
import pytz

# ── Config ──────────────────────────────────────────────────────────────
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STUDIO_PRICE_ID = os.getenv("STUDIO_PACKAGE_PRICE_ID", "price_1ThGmlDAWlnEb9RfNApm1T2U")
WP_PORTAL_PROVISION_URL = os.getenv(
    "WP_PORTAL_PROVISION_URL", "https://mwmcreations.com/wp-admin/admin-ajax.php")
WP_PORTAL_SECRET = os.getenv("WP_PORTAL_SECRET", "")
PORTAL_URL = "https://mwmcreations.com/studio-portal/"
WP_UA = "MWM-SalesMachine/1.0 (+https://mwmcreations.com)"  # host mod_security rejects python-requests default UA
PACKAGE_LP_URL = "https://mwmcreations.com/studio-package/"
CALENDLY_URL = "https://calendly.com/mwmcreations/studio-package-session"
PACKAGE_NAME = "Studio Package"
PACKAGE_MRR = 1200          # $/month
CONTRACT_HOURS = 12         # per 3-month contract
CONTRACT_MONTHS = 3
GRACE_DAYS = 30             # S8.6: unused hours usable 30d past term end, then expire (Michael, Jul 8) — contract_end field = grace deadline
TIMEZONE = os.getenv("TIMEZONE", "US/Eastern")

# ── Injected dependencies (set by app.py at boot) ──────────────────────
_deps = {}


def configure(**kwargs):
    """app.py injects: report_error, post_slack(channel, text),
    pipeline_event(event_type, **kw), send_email(to, subject, html),
    stripe_get(endpoint, params), pg_load(key, default), pg_save(key, val),
    lead_lookup_by_email(email) -> (key, rec) | (None, None),
    update_sheet_status(name, status_text), heartbeat(name),
    matt_channel, lara_channel, dev_channel, lead_data (dict)."""
    _deps.update(kwargs)


def _report(ctx, exc, detail=""):
    fn = _deps.get("report_error")
    if fn:
        try:
            fn(ctx, exc, detail)
            return
        except Exception:
            pass
    print(f"[STUDIO] {ctx}: {exc} {detail}")


# ── Stripe signature verification (no SDK — raw HMAC per Stripe docs) ──
def webhook_secret() -> str:
    """STRIPE_WEBHOOK_SECRET env, falling back to pg_store key
    'stripe_webhook_secret' (written at provision time so the signing
    secret never has to transit chat/screens/env UIs)."""
    if STRIPE_WEBHOOK_SECRET:
        return STRIPE_WEBHOOK_SECRET
    try:
        return (_deps["pg_load"]("stripe_webhook_secret", "") or "").strip()
    except Exception:
        return ""


def webhook_secret_configured() -> bool:
    return bool(webhook_secret())


def verify_stripe_signature(payload: bytes, sig_header: str,
                            secret: str = None, tolerance: int = 300) -> bool:
    """Verify Stripe-Signature header. payload MUST be the raw request body."""
    secret = secret if secret is not None else webhook_secret()
    if not secret or not sig_header:
        return False
    try:
        ts = None
        v1s = []
        for part in sig_header.split(","):
            k, _, v = part.strip().partition("=")
            if k == "t":
                ts = int(v)
            elif k == "v1":
                v1s.append(v)
        if ts is None or not v1s:
            return False
        if abs(time.time() - ts) > tolerance:
            return False
        signed = f"{ts}.".encode() + payload
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, v1) for v1 in v1s)
    except Exception as e:
        _report("studio.verify_stripe_signature", e)
        return False


# ── Idempotency (pg-backed; survives deploys; Stripe retries webhooks) ──
_PROCESSED_KEY = "stripe_events_processed"
_processed_lock = threading.Lock()


def _already_processed(event_id: str) -> bool:
    try:
        with _processed_lock:
            seen = _deps["pg_load"](_PROCESSED_KEY, {}) or {}
            if event_id in seen:
                return True
            seen[event_id] = datetime.utcnow().isoformat()
            if len(seen) > 500:  # prune oldest
                for k in sorted(seen, key=seen.get)[:len(seen) - 500]:
                    seen.pop(k, None)
            _deps["pg_save"](_PROCESSED_KEY, seen)
            return False
    except Exception as e:
        _report("studio.idempotency", e, f"event={event_id}")
        return False  # fail-open: WP-side email idempotency is the backstop


# ── Purchase path ───────────────────────────────────────────────────────
def _session_bought_studio_package(session_id: str) -> bool:
    """Check the checkout session's line items for the Studio Package price."""
    try:
        items = _deps["stripe_get"](f"checkout/sessions/{session_id}/line_items",
                                    {"limit": 20})
        for it in (items or {}).get("data", []):
            if ((it.get("price") or {}).get("id")) == STUDIO_PRICE_ID:
                return True
    except Exception as e:
        _report("studio.line_items", e, f"session={session_id}")
    return False


def provision_portal_client(name: str, email: str, dry_run: bool = False) -> dict:
    """Create (or fetch) the portal account on WP page 1102's login store.
    Returns {'ok': bool, 'access_code': str|None, 'existing': bool, 'raw': ...}."""
    et = pytz.timezone(TIMEZONE)
    start = datetime.now(et)
    term_end = start + timedelta(days=CONTRACT_MONTHS * 30)
    # S8.6: contract_end = grace deadline (term end + 30d). WP enforces this
    # field as the booking hard stop (S8.5), so grace is automatic per client.
    end = term_end + timedelta(days=GRACE_DAYS)
    payload = {
        "action": "mwm_studio_provision_client",
        "name": name,
        "email": email,
        "package": PACKAGE_NAME,
        "contract_hours": str(CONTRACT_HOURS),
        "contract_start": start.strftime("%Y-%m-%d"),
        "contract_end": end.strftime("%Y-%m-%d"),
    }
    if dry_run:
        payload["dry_run"] = "1"
    # S22 gap #4: retry 3x with backoff — provisioning is idempotent by email
    # on the WP side, so a transient hiccup should not cost a manual account.
    import time as _t
    last_err = ""
    for _attempt in range(3):
        try:
            r = http_requests.post(
                WP_PORTAL_PROVISION_URL, data=payload,
                headers={"X-MWM-Portal-Secret": WP_PORTAL_SECRET, "User-Agent": WP_UA}, timeout=20)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            data = body.get("data") or body  # WP wp_send_json_success wraps in {success, data}
            ok = bool(body.get("success", r.status_code == 200))
            if ok or _attempt == 2:
                if not ok:
                    _report("studio.provision_portal_client",
                            f"HTTP {r.status_code} after 3 attempts", f"email={email}")
                return {"ok": ok,
                        "access_code": data.get("access_code"),
                        "existing": bool(data.get("existing")),
                        "raw": body, "status": r.status_code}
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = repr(e)
            if _attempt == 2:
                _report("studio.provision_portal_client", e, f"email={email}")
                return {"ok": False, "access_code": None, "existing": False, "raw": str(e)}
        _t.sleep(2 ** _attempt)
    return {"ok": False, "access_code": None, "existing": False, "raw": last_err}


def _welcome_email_html(first_name: str, access_code: str) -> str:
    code_block = (
        f'<div style="background:#111;color:#fff;font-size:28px;letter-spacing:6px;'
        f'padding:18px 24px;border-radius:10px;display:inline-block;font-family:monospace;">'
        f'{access_code}</div>' if access_code else
        f'<p style="font-size:15px;">Your access code is being generated — '
        f'you\'ll receive it in a separate email shortly.</p>')
    return f"""
<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#222;">
  <div style="background:#111;padding:28px 32px;border-radius:12px 12px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:22px;">Welcome to MWM Studios 🎬</h1>
  </div>
  <div style="padding:28px 32px;background:#fafafa;border:1px solid #eee;border-top:none;
              border-radius:0 0 12px 12px;">
    <p style="font-size:16px;">Hi {first_name},</p>
    <p style="font-size:15px;line-height:1.6;">Your <strong>Studio Package</strong> is active —
    {CONTRACT_HOURS} hours of professional studio time over the next {CONTRACT_MONTHS} months.
    Here's everything you need:</p>
    <h3 style="margin-bottom:6px;">1 · Your client portal</h3>
    <p style="font-size:15px;line-height:1.6;">Track your hours, see upcoming sessions, and
    manage bookings at<br><a href="{PORTAL_URL}">{PORTAL_URL}</a></p>
    <p style="font-size:15px;">Log in with this email address and your access code:</p>
    <p style="text-align:center;margin:18px 0;">{code_block}</p>
    <h3 style="margin-bottom:6px;">2 · Book your first session</h3>
    <p style="font-size:15px;line-height:1.6;">All booking happens right in your portal —
    log in, pick a time on the booking calendar, done. Your hours are tracked automatically.</p>
    <h3 style="margin-bottom:6px;">3 · How it works</h3>
    <ul style="font-size:15px;line-height:1.7;">
      <li>{CONTRACT_HOURS} hours total, use them across {CONTRACT_MONTHS} months (≈4h/month pace)</li>
      <li>Unused hours stay bookable for {GRACE_DAYS} days after your contract ends, then expire</li>
      <li>Book, reschedule, and cancel — all in your portal</li>
      <li><strong>Cancellations need at least 24 hours' notice.</strong> Sessions cancelled
          with less than 24h remaining are charged to your hours.</li>
      <li>Questions any time — just reply to this email or WhatsApp us</li>
    </ul>
    <p style="font-size:15px;line-height:1.6;">We can't wait to create with you.</p>
    <p style="font-size:15px;">— Michael &amp; the MWM Creations team<br>
    <span style="color:#888;font-size:13px;">Orlando, FL · mwmcreations.com</span></p>
  </div>
</div>"""


def handle_stripe_event(event: dict) -> dict:
    """Process a verified Stripe event. Returns a summary dict (for logs)."""
    etype = event.get("type", "")
    event_id = event.get("id", "")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        if _already_processed(event_id):
            return {"handled": False, "reason": "duplicate", "event": event_id}
        if not _session_bought_studio_package(obj.get("id", "")):
            return {"handled": False, "reason": "other-product", "event": event_id}
        details = obj.get("customer_details") or {}
        email = (details.get("email") or obj.get("customer_email") or "").strip().lower()
        name = (details.get("name") or "").strip() or email.split("@")[0].title()
        if not email:
            _report("studio.purchase", "no email on checkout session", f"event={event_id}")
            return {"handled": False, "reason": "no-email", "event": event_id}
        _on_package_purchased(name, email, event_id)
        return {"handled": True, "event": event_id, "email": email}

    if etype in ("invoice.payment_failed", "customer.subscription.deleted"):
        details = ((obj.get("customer_details") or {}).get("email")
                   or obj.get("customer_email") or "unknown")
        _deps["post_slack"](_deps["matt_channel"],
            f"⚠️ *Stripe {etype}* for {details} — Studio Package billing needs attention. "
            f"ROB/Michael: check the Stripe dashboard.")
        return {"handled": True, "event": event_id, "alerted": etype}

    return {"handled": False, "reason": "ignored-type", "type": etype}


def _on_package_purchased(name: str, email: str, event_id: str):
    """Full purchase pipeline: portal account -> welcome email -> lead update -> alerts."""
    first = name.split()[0] if name else "there"

    # 1 · Portal account (idempotent by email on the WP side)
    prov = provision_portal_client(name, email)
    code = prov.get("access_code")

    # 2 · Welcome email (send even if provisioning degraded — portal team can resend code)
    email_ok = False
    try:
        email_ok = bool(_deps["send_email"](
            email, "Welcome to MWM Studios — your Studio Package is active 🎬",
            _welcome_email_html(first, code)))
    except Exception as e:
        _report("studio.welcome_email", e, f"email={email}")

    # 3 · Lead record: -> Client, product=Studio Package
    lead_name = name
    try:
        key, rec = _deps["lead_lookup_by_email"](email)
        if key and rec is not None:
            rec["product"] = PACKAGE_NAME
            rec["outcome"] = "Won"
            rec["studio_package"] = {"purchased": datetime.utcnow().isoformat(),
                                     "stripe_event": event_id}
            lead_name = rec.get("name") or name
            _deps["update_sheet_status"](lead_name, "Client — Studio Package")
    except Exception as e:
        _report("studio.lead_update", e, f"email={email}")

    # 4 · Pipeline event + team alerts
    _deps["pipeline_event"]("PACKAGE_PURCHASED", lead_name=lead_name, source="Stripe",
                            new_stage="Client — Studio Package",
                            assigned_agents=["LARA", "ROB"],
                            context=f"${PACKAGE_MRR}/mo · {CONTRACT_HOURS}h/{CONTRACT_MONTHS}mo · "
                                    f"portal={'ok' if prov.get('ok') else 'FAILED'} · "
                                    f"welcome_email={'sent' if email_ok else 'FAILED'}")
    prov_note = ("✅ portal account ready" if prov.get("ok")
                 else "🚨 PORTAL PROVISIONING FAILED — create the account manually in WP")
    mail_note = "✅ welcome email sent" if email_ok else "🚨 welcome email FAILED — send manually"
    _deps["post_slack"](_deps["matt_channel"],
        f"💳 *STUDIO PACKAGE PURCHASED* — {lead_name} ({email})\n"
        f"{prov_note} · {mail_note}\n"
        f"_LARA — please set up production tracking; client books sessions in the portal ({PORTAL_URL})_")
    _deps["post_slack"](_deps["lara_channel"],
        f"💳 New Studio Package client: *{lead_name}* ({email}) — {CONTRACT_HOURS}h over "
        f"{CONTRACT_MONTHS} months. Portal: {PORTAL_URL} · {prov_note}")


# ── Post-pitch follow-up sequence (EMAIL-FIRST — WABA is down Jul 2026) ─
# Touch schedule after `studio_package_pitched` outcome:
#   T+1h   recap + portal LP link
#   T+2d   value/what's-included
#   T+6d   final nudge + Calendly link
_SEQ = [
    (timedelta(hours=1), "recap"),
    (timedelta(days=2), "value"),
    (timedelta(days=6), "nudge"),
]


def _seq_email(stage: str, first_name: str) -> tuple:
    if stage == "recap":
        return ("Great meeting you at MWM Studios 🎬", f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#222;">
<p>Hi {first_name},</p>
<p>Thank you for visiting MWM Studios today — it was great showing you the space and
talking about your project.</p>
<p>As promised, here's the <strong>Studio Package</strong> we discussed:
<strong>{CONTRACT_HOURS} hours of studio time over {CONTRACT_MONTHS} months for
${PACKAGE_MRR:,}/month</strong> — full details and checkout here:</p>
<p><a href="{PACKAGE_LP_URL}">{PACKAGE_LP_URL}</a></p>
<p>Any questions at all, just reply to this email.</p>
<p>— Michael, MWM Creations</p></div>""")
    if stage == "value":
        return ("What your Studio Package hours can do", f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#222;">
<p>Hi {first_name},</p>
<p>Quick follow-up on the Studio Package — clients typically use their
{CONTRACT_HOURS} hours for things like:</p>
<ul style="line-height:1.7;">
<li>Monthly content batches (podcast, reels, product shots) — ≈4h/month</li>
<li>A branded video series shot across multiple sessions</li>
<li>Consistent, professional content without booking hassle — your hours,
your schedule, tracked in your own client portal</li></ul>
<p>Details &amp; checkout: <a href="{PACKAGE_LP_URL}">{PACKAGE_LP_URL}</a></p>
<p>— Michael, MWM Creations</p></div>""")
    return ("Shall we reserve your studio dates?", f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#222;">
<p>Hi {first_name},</p>
<p>I'll keep this short — studio calendar slots for the coming month are filling up,
and I'd love to make sure you get the dates you want.</p>
<p>If the Studio Package still makes sense for you, you can start here:
<a href="{PACKAGE_LP_URL}">{PACKAGE_LP_URL}</a> — and your first session is bookable
the moment you're in.</p>
<p>If the timing isn't right, no pressure — just reply and tell me where you stand.</p>
<p>— Michael, MWM Creations</p></div>""")


def start_pitch_sequence(lead_key: str, rec: dict):
    """Called when outcome=studio_package_pitched is recorded."""
    try:
        rec["studio_pitch"] = {
            "date": datetime.utcnow().isoformat(),
            "next_stage": 0,
            "done": False,
        }
        _deps["pipeline_event"]("PACKAGE_PITCHED",
                                lead_name=rec.get("name", ""),
                                lead_phone=rec.get("phone", lead_key),
                                source=rec.get("source", ""),
                                new_stage="Studio Package — Pitched",
                                assigned_agents=["SUSAN", "MAYA"],
                                context="Post-visit pitch by Michael; email-first "
                                        "follow-up sequence armed (T+1h/T+2d/T+6d)")
    except Exception as e:
        _report("studio.start_pitch_sequence", e, f"lead={lead_key}")


_HONORIFICS = {"dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "prof", "prof.", "rev", "rev.", "pastor", "coach"}


def _first_name(name) -> str:
    """First usable name word, skipping honorifics ('Dr. Scott Robinson' -> 'Scott')."""
    for w in (name or "").split():
        if w.lower() not in _HONORIFICS:
            return w
    return "there"


def _sequence_pass():
    """One scan over lead_data: send any due sequence touches."""
    lead_data = _deps.get("lead_data") or {}
    now = datetime.utcnow()
    sent = 0
    for key, rec in list(lead_data.items()):
        try:
            sp = rec.get("studio_pitch")
            if not isinstance(sp, dict) or sp.get("done"):
                continue
            # Stop conditions: purchased, or lead became a client any other way
            if rec.get("product") == PACKAGE_NAME or rec.get("outcome") == "Won":
                sp["done"] = True
                continue
            stage_i = int(sp.get("next_stage", 0))
            if stage_i >= len(_SEQ):
                sp["done"] = True
                continue
            email = (rec.get("email") or "").strip()
            if not email:
                sp["done"] = True
                _deps["post_slack"](_deps["matt_channel"],
                    f"📦 Studio pitch follow-up for *{rec.get('name', key)}* has no email "
                    f"on file — sequence halted. Maya/Michael: follow up manually.")
                continue
            pitched = datetime.fromisoformat(sp["date"])
            delay, stage_name = _SEQ[stage_i]
            if now - pitched < delay:
                continue
            first = _first_name(rec.get("name"))
            subject, html = _seq_email(stage_name, first)
            if _deps["send_email"](email, subject, html):
                sp["next_stage"] = stage_i + 1
                sp[f"sent_{stage_name}"] = now.isoformat()
                sent += 1
                print(f"[STUDIO SEQ] {stage_name} -> {email}")
            else:
                _report("studio.sequence_send", f"send_email returned falsy",
                        f"lead={key} stage={stage_name}")
        except Exception as e:
            _report("studio.sequence_pass", e, f"lead={key}")
    return sent


def sequence_loop():
    """Background thread: hourly pass. Heartbeat name: studio_followup."""
    time.sleep(120)  # let boot restore finish
    while True:
        try:
            _sequence_pass()
            hb = _deps.get("heartbeat")
            if hb:
                hb("studio_followup")
        except Exception as e:
            _report("studio.sequence_loop", e)
        time.sleep(3600)


# ── WP portal ledger (S7.5 — read-only client+hours list) ──────────────
def wp_list_clients():
    """Fetch clients + hours from the WP portal ledger. Returns list or None."""
    if not WP_PORTAL_SECRET:
        return None
    try:
        r = http_requests.post(
            WP_PORTAL_PROVISION_URL, data={"action": "mwm_studio_list_clients"},
            headers={"X-MWM-Portal-Secret": WP_PORTAL_SECRET, "User-Agent": WP_UA}, timeout=15)
        body = r.json()
        if body.get("success"):
            return (body.get("data") or {}).get("clients") or []
    except Exception as e:
        _report("studio.wp_list_clients", e)
    return None


# ── Canvas stats block ──────────────────────────────────────────────────
def canvas_block(now_str: str) -> str:
    """Studio Package code-block for the pipeline canvas — per-client hours
    read live from the WP portal ledger (S7.5); falls back to lead_data."""
    lead_data = _deps.get("lead_data") or {}
    contracts = pitched = closed = expiring = 0
    et = pytz.timezone(TIMEZONE)
    now = datetime.now(et)
    for rec in lead_data.values():
        try:
            if rec.get("product") == PACKAGE_NAME:
                contracts += 1
                spd = (rec.get("studio_package") or {}).get("purchased")
                if spd:
                    pur = datetime.fromisoformat(spd)
                    end = pur + timedelta(days=CONTRACT_MONTHS * 30)
                    if 0 <= (end.replace(tzinfo=None) - now.replace(tzinfo=None)).days <= 30:
                        expiring += 1
            if isinstance(rec.get("studio_pitch"), dict):
                pitched += 1
                if rec.get("product") == PACKAGE_NAME:
                    closed += 1
        except Exception:
            pass
    conv = f"{closed}/{pitched} ({closed * 100 // pitched}%)" if pitched else "0/0 (—)"

    # S7.5: live portal ledger — authoritative for contracts + hours
    wp = wp_list_clients()
    if wp is not None:
        act = [c for c in wp if str(c.get("active", "1")) == "1"]
        contracts = len(act)
        expiring = 0
        lines = []
        used_t = tot_t = 0.0
        for c in act:
            try:
                used = float(c.get("hours_used") or 0)
                tot = float(c.get("contract_hours") or 0)
                used_t += used
                tot_t += tot
                end = str(c.get("contract_end_date") or "")[:10]
                try:
                    days = (datetime.strptime(end, "%Y-%m-%d") - datetime.utcnow()).days
                    if 0 <= days <= 30:
                        expiring += 1
                    end_note = f"ends {end}"
                except Exception:
                    end_note = ""
                lines.append(f"  {(c.get('name') or '?')[:22]:<24}{used:>5.1f}/{tot:.0f}h   {end_note}")
            except Exception:
                pass
        util = f"{used_t:.1f}/{tot_t:.0f}h ({used_t * 100 / tot_t:.0f}%)" if tot_t else "0/0h"
        return (
            f"Studio Contracts: {contracts} active | MRR: ${contracts * PACKAGE_MRR:,}\n"
            f"Hours (portal ledger): {util}\n"
            + ("\n".join(lines) + "\n" if lines else "")
            + f"Expiring <=30d: {expiring}\n"
            f"Pitch->Close: {conv}\n"
            f"Updated: {now_str} · source: portal ledger"
        )

    return (
        f"Studio Contracts: {contracts} active | MRR: ${contracts * PACKAGE_MRR:,}\n"
        f"Hours utilization: ~portal ledger unreachable (fallback: lead_data)\n"
        f"Expiring <=30d: {expiring}\n"
        f"Pitch->Close: {conv}\n"
        f"Updated: {now_str}"
    )
