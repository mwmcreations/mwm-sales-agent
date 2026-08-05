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

# ══════════════════════════════════════════════════════════════════════
# PATCH #53 · MORE THAN ONE PACKAGE
# ══════════════════════════════════════════════════════════════════════
# A client wanted one month before committing to the three-month package, at
# $1,400 instead of $1,200/mo, and gave the green light before any of this
# existed. There was no link to send them, and nothing here could have handled
# the payment if there had been:
#
#   · Detection was `price_id == STUDIO_PRICE_ID`, a bare bool. A different
#     price returns "other-product" and provisions NOTHING — the money lands,
#     no portal account is made, no email is sent, and the only trace is a log
#     line saying it was ignored. Silent, in the expensive direction.
#   · The term was three module constants, so every client got 12h/3mo.
#   · The welcome email hard-coded "12 hours over the next 3 months".
#
# The trap worth naming: the 3-month path sends WP a `contract_end` of term end
# PLUS 30 days of grace, because WP enforces that one field as the booking hard
# stop. Copying that shape for a 30-day package would have given this client
# SIXTY days of booking — double what Michael quoted him. So grace is per
# variant and this one is zero.
TRIAL_PRICE_ID = os.getenv("STUDIO_TRIAL_PRICE_ID",
                           "price_1U15xuDAWlnEb9RfH6w5jYIf")
TRIAL_NAME = "Studio Trial — 1 Month"

# Keyed by Stripe price ID, because that is the one identifier the webhook can
# always see on a line item. `kind` mirrors the metadata set on the Stripe
# price and payment link, so a human reading either sees the same word.
PACKAGES = {
    STUDIO_PRICE_ID: {
        "kind": "studio_3mo",
        "name": PACKAGE_NAME,
        "hours": CONTRACT_HOURS,          # 12
        "term_days": CONTRACT_MONTHS * 30,  # 90
        "grace_days": GRACE_DAYS,         # 30 → booking deadline at 120d
        "recurring": True,
        "mrr": PACKAGE_MRR,               # counts toward MRR
        "one_off": 0,
        "price_label": "$1,200/mo × 3 months",
        "sheet_status": "Client — Studio Package",
        "pace_note": "≈4h/month pace",
        # Empty on purpose. The 3-month welcome email has never listed
        # deliverables, and adding a line to a live client-facing template
        # nobody asked me to change is not a free action.
        "includes_note": "",
        "credits_toward_contract": False,
    },
    TRIAL_PRICE_ID: {
        "kind": "studio_trial_1mo",
        "name": TRIAL_NAME,
        "hours": 4,
        "term_days": 30,
        # ZERO. Michael told the client 30 days; grace would silently make it 60.
        "grace_days": 0,
        "recurring": False,
        "mrr": 0,                         # a one-off must never inflate MRR
        "one_off": 1400,
        "price_label": "$1,400 one-time",
        "sheet_status": "Client — Studio Trial (1 month)",
        "pace_note": "one 4-hour session, or split it across shorter ones",
        # PATCH #54 — Michael confirmed editing IS included in the trial. It is
        # stated in the welcome email because that email is the written record
        # the client keeps; if what was included is ever in question, this is
        # the artifact. Deliberately not enumerating short cuts, captions or
        # logo animation — he said "editing", and inventing the rest of the
        # package's deliverables would be promising work nobody agreed to.
        "includes_note": "Post-production editing is included",
        # No credit toward a 3-month contract. Recorded here so a future upsell
        # sequence cannot quietly invent one: if they go to the package it is a
        # fresh $1,200/mo × 3, and the $1,400 stays spent on the trial.
        "credits_toward_contract": False,
    },
}

# Every product name that means "this lead has bought something". Used to stop
# the cold pitch sequence: a trial client is a client, and pitching them the
# package they just declined to commit to would read as not listening.
PACKAGE_NAMES = tuple(spec["name"] for spec in PACKAGES.values())


def package_for_price(price_id):
    """The package spec for a Stripe price ID, or None."""
    return PACKAGES.get(str(price_id or "").strip())


def package_term(spec, start):
    """Work out the dates ONCE, so the portal and the email cannot disagree.

    Returns {"start", "term_end", "booking_deadline"} as date objects.

    `booking_deadline` is what goes into WP's `contract_end_date`, which the
    portal enforces as the hard stop on booking (S8.5). For the 3-month package
    that is deliberately later than the term end — 30 days of grace to use
    hours already paid for. For the trial it IS the term end, because 30 days
    is the whole offer.
    """
    spec = spec or {}
    days = int(spec.get("term_days") or 0)
    grace = int(spec.get("grace_days") or 0)
    start_d = start.date() if hasattr(start, "date") else start
    term_end = start_d + timedelta(days=days)
    return {"start": start_d, "term_end": term_end,
            "booking_deadline": term_end + timedelta(days=grace)}


def package_by_name(name):
    """The spec for a package NAME, or None.

    The portal ledger reports `package_name`, not a price ID, so this is how a
    live client row gets classified for revenue reporting.
    """
    want = str(name or "").strip().lower()
    if not want:
        return None
    for spec in PACKAGES.values():
        if spec["name"].strip().lower() == want:
            return spec
    return None


def revenue_split(clients):
    """Split active portal clients into recurring vs one-off, with the money.

    PATCH #53. The canvas said `MRR: ${contracts * PACKAGE_MRR}` — every active
    portal client multiplied by $1,200. A $1,400 one-month trial would have
    been reported as $1,200 of RECURRING revenue, which is wrong twice: wrong
    amount, and wrong kind. Overstating MRR is the sort of number that gets
    repeated in a decision later.

    An unrecognised package_name counts as the 3-month package, because every
    client predating this patch is on it and the historical figure must not
    move. Returns (recurring_count, mrr, oneoff_count, oneoff_total).
    """
    default = PACKAGES[STUDIO_PRICE_ID]
    rec_n = one_n = 0
    mrr = one_total = 0
    for c in (clients or []):
        if not isinstance(c, dict):
            continue
        spec = package_by_name(c.get("package_name")) or default
        if spec["recurring"]:
            rec_n += 1
            mrr += int(spec["mrr"] or 0)
        else:
            one_n += 1
            one_total += int(spec.get("one_off") or 0)
    return rec_n, mrr, one_n, one_total


def term_phrase(spec):
    """How to describe the term to the client, in their words not ours."""
    spec = spec or {}
    days = int(spec.get("term_days") or 0)
    if days and days % 30 == 0 and days >= 60:
        months = days // 30
        return f"{months} months"
    return f"{days} days"

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
def package_for_session(session_id: str):
    """WHICH package this checkout session bought, or None.

    PATCH #53 — was `_session_bought_studio_package`, returning a bool against
    one price ID. That is why a second product could not exist: any other price
    came back False and the handler answered "other-product", so the payment
    landed and nothing at all was provisioned.

    Returns the spec dict so every downstream step reads the same source of
    truth for hours, term and grace instead of module constants.
    """
    try:
        items = _deps["stripe_get"](f"checkout/sessions/{session_id}/line_items",
                                    {"limit": 20})
        for it in (items or {}).get("data", []):
            spec = package_for_price((it.get("price") or {}).get("id"))
            if spec:
                return spec
    except Exception as e:
        _report("studio.line_items", e, f"session={session_id}")
    return None


def _session_bought_studio_package(session_id: str) -> bool:
    """Back-compat shim. Prefer package_for_session()."""
    return package_for_session(session_id) is not None


def provision_portal_client(name: str, email: str, spec: dict = None,
                            dry_run: bool = False) -> dict:
    """Create (or fetch) the portal account on WP page 1102's login store.

    Returns {'ok', 'access_code', 'existing', 'raw', 'status', 'term'} where
    `term` is the dict from package_term() — the dates ACTUALLY sent to WP.
    The welcome email is written from that, so it can never promise a deadline
    the portal will not honour.

    PATCH #53 — `spec` defaults to the 3-month package so every existing caller
    behaves exactly as before.
    """
    spec = spec or PACKAGES[STUDIO_PRICE_ID]
    et = pytz.timezone(TIMEZONE)
    term = package_term(spec, datetime.now(et))
    payload = {
        "action": "mwm_studio_provision_client",
        "name": name,
        "email": email,
        "package": spec["name"],
        "contract_hours": str(spec["hours"]),
        "contract_start": term["start"].strftime("%Y-%m-%d"),
        # WP enforces contract_end as the booking hard stop, so this carries
        # the grace period for packages that have one and nothing extra for
        # the ones that do not.
        "contract_end": term["booking_deadline"].strftime("%Y-%m-%d"),
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
                        "raw": body, "status": r.status_code, "term": term}
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = repr(e)
            if _attempt == 2:
                _report("studio.provision_portal_client", e, f"email={email}")
                return {"ok": False, "access_code": None, "existing": False,
                        "raw": str(e), "term": term}
        _t.sleep(2 ** _attempt)
    return {"ok": False, "access_code": None, "existing": False,
            "raw": last_err, "term": term}


def _welcome_email_html(first_name: str, access_code: str,
                        spec: dict = None, term: dict = None) -> str:
    """PATCH #53 — the copy is now written from the package spec.

    It used to hard-code "12 hours over the next 3 months" and "unused hours
    stay bookable for 30 days after your contract ends". Sent to a 4-hour
    trial client that would have been three wrong facts in one paragraph, and
    the last one would have promised 30 days of grace the portal does not give
    them.

    `term` comes back from provision_portal_client, so the date in this email
    is literally the date written into WP. When it is missing we say nothing
    about a deadline rather than guessing one — a reminder with the wrong date
    is worse than no date, because the client writes it down.
    """
    spec = spec or PACKAGES[STUDIO_PRICE_ID]
    hours = spec["hours"]
    deadline = (term or {}).get("booking_deadline")
    deadline_str = deadline.strftime("%A, %B %d, %Y") if deadline else ""

    if spec.get("grace_days"):
        expiry_li = (f"Unused hours stay bookable for {spec['grace_days']} days after "
                     f"your term ends, then expire")
    else:
        expiry_li = (f"All {hours} hours must be used within {term_phrase(spec)}"
                     + (f" — the last day you can book is <strong>{deadline_str}</strong>"
                        if deadline_str else ""))
    headline = (f"Your <strong>{spec['name']}</strong> is active — {hours} hours of "
                f"professional studio time to use over the next {term_phrase(spec)}.")
    _includes = str(spec.get("includes_note") or "").strip()
    _pace = str(spec.get("pace_note") or "").strip()
    total_li = (f"{hours} hours total across {term_phrase(spec)}"
                + (f" ({_pace})" if _pace else ""))
    if _includes:
        # Appended to the hours line rather than added as a new bullet, so the
        # 3-month email's list length does not change at all.
        expiry_li = f"{expiry_li}</li>\n      <li>{_includes}"
    return _welcome_email_body(first_name, access_code, headline, total_li, expiry_li)


def _welcome_email_body(first_name: str, access_code: str, headline: str,
                        total_li: str, expiry_li: str) -> str:
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
    <p style="font-size:15px;line-height:1.6;">{headline}
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
      <li>{total_li}</li>
      <li>{expiry_li}</li>
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
        _spec = package_for_session(obj.get("id", ""))
        if _spec is None:
            return {"handled": False, "reason": "other-product", "event": event_id}
        details = obj.get("customer_details") or {}
        email = (details.get("email") or obj.get("customer_email") or "").strip().lower()
        name = (details.get("name") or "").strip() or email.split("@")[0].title()
        if not email:
            _report("studio.purchase", "no email on checkout session", f"event={event_id}")
            return {"handled": False, "reason": "no-email", "event": event_id}
        _on_package_purchased(name, email, event_id, _spec)
        return {"handled": True, "event": event_id, "email": email,
                "package": _spec["kind"]}

    if etype in ("invoice.payment_failed", "customer.subscription.deleted"):
        details = ((obj.get("customer_details") or {}).get("email")
                   or obj.get("customer_email") or "unknown")
        _deps["post_slack"](_deps["matt_channel"],
            f"⚠️ *Stripe {etype}* for {details} — Studio Package billing needs attention. "
            f"ROB/Michael: check the Stripe dashboard.")
        return {"handled": True, "event": event_id, "alerted": etype}

    return {"handled": False, "reason": "ignored-type", "type": etype}


def _on_package_purchased(name: str, email: str, event_id: str, spec: dict = None):
    """Full purchase pipeline: portal account -> welcome email -> lead update -> alerts.

    PATCH #53 — `spec` defaults to the 3-month package, so the existing path is
    byte-for-byte unchanged when nothing passes one.
    """
    spec = spec or PACKAGES[STUDIO_PRICE_ID]
    first = name.split()[0] if name else "there"

    # 1 · Portal account (idempotent by email on the WP side)
    prov = provision_portal_client(name, email, spec)
    code = prov.get("access_code")
    term = prov.get("term") or {}

    # 2 · Welcome email (send even if provisioning degraded — portal team can resend code)
    email_ok = False
    try:
        email_ok = bool(_deps["send_email"](
            email, f"Welcome to MWM Studios — your {spec['name']} is active 🎬",
            _welcome_email_html(first, code, spec, term)))
    except Exception as e:
        _report("studio.welcome_email", e, f"email={email}")

    # 3 · Lead record: -> Client, product=Studio Package
    #
    # PATCH #34 — this block used to be a SILENT NO-OP on a lookup miss.
    # `if key and rec is not None:` with no else branch: when the payer's Stripe
    # email did not match a lead record, the product/outcome/sheet-status writes
    # were all skipped and NOTHING was reported. The try/except only fires on an
    # exception, and "not found" is not an exception.
    #
    # That is the same failure family as everything else in this rail: not a
    # crash, a quiet wrong answer. A client pays, the money lands, and the
    # pipeline still shows them as a lead — with no error anywhere to explain it.
    #
    # Now: email -> phone -> name, in that order, and if all three miss we
    # report LOUDLY with the payment details so a human can link it by hand.
    # A payment that cannot find its lead is a named assignment, never a
    # skipped line.
    lead_name = name
    try:
        key, rec = _deps["lead_lookup_by_email"](email)
        _matched_on = "email" if key else None

        if not key:
            # Fallback: name. (Phone is deliberately NOT attempted — this
            # handler only receives name/email/event_id from the Stripe webhook,
            # so there is no phone to match on. Pretending otherwise would be a
            # lookup that silently never fires.)
            finder = _deps.get("lead_lookup_by_name")
            if callable(finder) and name:
                try:
                    key, rec = finder(name)
                    if key:
                        _matched_on = "name"
                except Exception as fe:
                    _report("studio.lead_lookup_fallback", fe, "via=name")

        if key and rec is not None:
            rec["product"] = spec["name"]
            rec["outcome"] = "Won"
            # PATCH #53 — record WHICH package and WHEN it runs out. Without the
            # variant and the deadline on the record, nothing downstream can
            # tell a $1,400 one-month trial from a $3,600 three-month contract,
            # and the upsell conversation has no date attached to it.
            rec["studio_package"] = {
                "purchased": datetime.utcnow().isoformat(),
                "stripe_event": event_id,
                "variant": spec["kind"],
                "package_name": spec["name"],
                "hours": spec["hours"],
                "term_days": spec["term_days"],
                "recurring": bool(spec["recurring"]),
                "mrr": spec["mrr"],
                "one_off": spec.get("one_off", 0),
                "booking_deadline": (term.get("booking_deadline").isoformat()
                                     if term.get("booking_deadline") else ""),
            }
            lead_name = rec.get("name") or name
            _deps["update_sheet_status"](lead_name, spec["sheet_status"])
            if _matched_on != "email":
                _deps["post_slack"](_deps["matt_channel"],
                    f"ℹ️ Studio Package payment matched to a lead by *{_matched_on}*, "
                    f"not email — *{lead_name}* ({email}). Worth checking the lead's "
                    f"email field; a mismatch here is what silently strands payments.")
        else:
            # NEVER silent. The money arrived; the record did not.
            _report("studio.lead_not_found",
                    "paid customer could not be matched to any lead record",
                    f"email={email} name={name!r} stripe_event={event_id}")
            _deps["post_slack"](_deps["matt_channel"],
                f"🔴 *PAID CLIENT NOT LINKED TO A LEAD* — {name} ({email})\n"
                f"Studio Package purchased (Stripe `{event_id}`) but no lead record "
                f"matched by email, phone or name. *Their stage will stay wrong until "
                f"someone links it.*\n"
                f"*MICHAEL:* confirm which lead record is theirs, or that they are new.\n"
                f"_This used to fail silently — the payment landed and the pipeline "
                f"simply never noticed._")
    except Exception as e:
        _report("studio.lead_update", e, f"email={email}")

    # 4 · Pipeline event + team alerts
    _deadline_str = ""
    if term.get("booking_deadline"):
        _deadline_str = term["booking_deadline"].strftime("%b %d, %Y")
    _deps["pipeline_event"]("PACKAGE_PURCHASED", lead_name=lead_name, source="Stripe",
                            new_stage=spec["sheet_status"],
                            assigned_agents=["LARA", "ROB"],
                            context=f"{spec['price_label']} · {spec['hours']}h/"
                                    f"{term_phrase(spec)} · "
                                    f"portal={'ok' if prov.get('ok') else 'FAILED'} · "
                                    f"welcome_email={'sent' if email_ok else 'FAILED'}")
    prov_note = ("✅ portal account ready" if prov.get("ok")
                 else "🚨 PORTAL PROVISIONING FAILED — create the account manually in WP")
    mail_note = "✅ welcome email sent" if email_ok else "🚨 welcome email FAILED — send manually"
    # PATCH #53 — a one-month trial is a DIFFERENT event to the team than a
    # three-month contract: it is not recurring revenue, and it has a date on
    # which the upsell either happens or the client walks. Say so.
    _trial_note = ""
    if not spec["recurring"]:
        _trial_note = (f"\n⚠️ *This is the 1-month trial, not the 3-month package.* "
                       f"One-time {spec['price_label']} — *not MRR*. "
                       + (f"Their {spec['hours']}h run out *{_deadline_str}*, which is the "
                          f"window to convert them to the package." if _deadline_str else ""))
    _deps["post_slack"](_deps["matt_channel"],
        f"💳 *{spec['name'].upper()} PURCHASED* — {lead_name} ({email})\n"
        f"{spec['price_label']} · {spec['hours']}h over {term_phrase(spec)}"
        + (f" · books until {_deadline_str}" if _deadline_str else "") + "\n"
        f"{prov_note} · {mail_note}{_trial_note}\n"
        f"_LARA — please set up production tracking; client books sessions in the portal ({PORTAL_URL})_")
    _deps["post_slack"](_deps["lara_channel"],
        f"💳 New *{spec['name']}* client: *{lead_name}* ({email}) — {spec['hours']}h over "
        f"{term_phrase(spec)}"
        + (f", last bookable day {_deadline_str}" if _deadline_str else "")
        + f". Portal: {PORTAL_URL} · {prov_note}")


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
            # PATCH #53 — any package, not just the 3-month one. A trial client
            # has bought; pitching them the package they deliberately did not
            # commit to would read as not having listened. The upsell is a
            # separate, later conversation with a date on it.
            if rec.get("product") in PACKAGE_NAMES or rec.get("outcome") == "Won":
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
            if rec.get("product") in PACKAGE_NAMES:
                contracts += 1
                _rsp = rec.get("studio_package") or {}
                spd = _rsp.get("purchased")
                if spd:
                    pur = datetime.fromisoformat(spd)
                    # PATCH #53 — per-record term. Using CONTRACT_MONTHS here
                    # dated a 30-day trial as if it ran for 90.
                    _td = int(_rsp.get("term_days") or (CONTRACT_MONTHS * 30))
                    end = pur + timedelta(days=_td)
                    if 0 <= (end.replace(tzinfo=None) - now.replace(tzinfo=None)).days <= 30:
                        expiring += 1
            if isinstance(rec.get("studio_pitch"), dict):
                pitched += 1
                if rec.get("product") in PACKAGE_NAMES:
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
        _rec_n, _mrr, _one_n, _one_total = revenue_split(act)
        _rev = f"{contracts} active | MRR: ${_mrr:,}"
        if _one_n:
            _rev += (f"  (+{_one_n} one-month trial"
                     + ("s" if _one_n != 1 else "")
                     + f" · ${_one_total:,} one-off, NOT MRR)")
        return (
            f"Studio Contracts: {_rev}\n"
            f"Hours (portal ledger): {util}\n"
            + ("\n".join(lines) + "\n" if lines else "")
            + f"Expiring <=30d: {expiring}\n"
            f"Pitch->Close: {conv}\n"
            f"Updated: {now_str} · source: portal ledger"
        )

    _fb_rec = _fb_mrr = _fb_one = _fb_one_total = 0
    for _r in lead_data.values():
        try:
            _sp = _r.get("studio_package") or {}
            _spec = package_by_name(_r.get("product"))
            if _spec is None:
                continue
            if _spec["recurring"]:
                _fb_rec += 1
                _fb_mrr += int(_sp.get("mrr", _spec["mrr"]) or 0)
            else:
                _fb_one += 1
                _fb_one_total += int(_sp.get("one_off", _spec.get("one_off", 0)) or 0)
        except Exception:
            pass
    _fb = f"{contracts} active | MRR: ${_fb_mrr:,}"
    if _fb_one:
        _fb += (f"  (+{_fb_one} one-month trial"
                + ("s" if _fb_one != 1 else "")
                + f" · ${_fb_one_total:,} one-off, NOT MRR)")
    return (
        f"Studio Contracts: {_fb}\n"
        f"Hours utilization: ~portal ledger unreachable (fallback: lead_data)\n"
        f"Expiring <=30d: {expiring}\n"
        f"Pitch->Close: {conv}\n"
        f"Updated: {now_str}"
    )
