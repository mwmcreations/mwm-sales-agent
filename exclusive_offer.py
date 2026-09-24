"""PATCH #132 — Exclusive Video Offer: the $2,497 one-time purchase, end to end.

Michael, 24 Sep 2026: /exclusive-offer stops sending people to WhatsApp and
takes payment on the page (Stripe payment link owned by ROB,
plink_1UJEPeDAWlnEb9Rf4lAvkFH5, metadata sku=exclusive_video_offer).

The Stripe confirmation screen promises "Our team will contact you within 1
business day to plan your shoot." Before this patch the webhook classified the
payment as "other-product" and dropped it: the money would land and nobody on
the team would know a sale had happened. ROB's ruling: "This is not optional."

On checkout.session.completed with metadata.sku == exclusive_video_offer:
  1. Alert #lara and #rob, tagging Michael, with name, company, email, phone,
     amount and payment link. LARA owns the 1-business-day scheduling call.
  2. Mark the lead record a client (outcome Won, product, status client,
     relationship new_client, booked) — matched by email, then phone, then
     exact full name. Those are the fields every sales/follow-up guard in the
     machine already reads, so the cold-lead, re-engagement and studio-pitch
     rails stop touching this person. A payer with no record gets one, so a
     later DM from them is recognised as a client, not a new lead.
  3. Nothing else: no subscription, no portal account, no studio hours.

Idempotent on the Stripe event id. The idempotency stamp is written only
after the team alert went out, so a Stripe retry can self-heal a failed post.

Also here: maya_offer_context(page_url) — what Maya may say about the offer
when the visitor is chatting from the offer page (Michael: "teach Maya").
"""

import re
from datetime import datetime, timedelta

SKU = "exclusive_video_offer"
PRODUCT_NAME = "Exclusive Video Offer"
PRICE_LABEL = "$2,497 one-time"
SHEET_STATUS = "Client — Exclusive Video Offer"
OFFER_PATH = "/exclusive-offer"
MICHAEL_SLACK = "<@U01N06A8VE1>"

_deps = {}


def configure(**kw):
    """report_error, post_slack, pg_load, pg_save, lead_data,
    lead_lookup_by_email, lead_lookup_by_phone, lead_lookup_by_name,
    update_sheet_status(name, status, notes, service, next_steps),
    pipeline_event, lara_channel, rob_channel, dev_channel, now (optional)."""
    _deps.update(kw)


def _now():
    fn = _deps.get("now")
    return fn() if callable(fn) else datetime.now().astimezone()


def _report(where, err, ctx=""):
    fn = _deps.get("report_error")
    if callable(fn):
        try:
            fn(where, err, ctx)
        except Exception:
            pass


def is_offer_session(session):
    meta = (session or {}).get("metadata") or {}
    return str(meta.get("sku", "")).strip() == SKU


def next_business_day(d):
    """The day the 1-business-day promise falls due (Mon–Fri; no holiday list)."""
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def buyer_from_session(session):
    """Name, company, email, phone as Stripe collected them.

    The link collects individual name (required) and business name (optional)
    via name_collection. Depending on API version those arrive on
    customer_details or on collected_information — read both."""
    s = session or {}
    cd = s.get("customer_details") or {}
    ci = s.get("collected_information") or {}
    name = (cd.get("individual_name") or ci.get("individual_name")
            or cd.get("name") or "").strip()
    company = (cd.get("business_name") or ci.get("business_name") or "").strip()
    email = (cd.get("email") or s.get("customer_email") or "").strip().lower()
    phone = (cd.get("phone") or "").strip()
    if not name and email:
        name = email.split("@")[0].title()
    return {"name": name, "company": company, "email": email, "phone": phone}


def _match_lead(buyer):
    """(key, rec, via). Email first, then phone, then exact full name."""
    for via, dep, val in (("email", "lead_lookup_by_email", buyer["email"]),
                          ("phone", "lead_lookup_by_phone", buyer["phone"]),
                          ("name", "lead_lookup_by_name", buyer["name"])):
        fn = _deps.get(dep)
        if not val or not callable(fn):
            continue
        try:
            key, rec = fn(val)
        except Exception as e:
            _report("exclusive_offer.lead_lookup", e, f"via={via}")
            continue
        if key and rec is not None:
            return key, rec, via
    return None, None, None


def _mark_client(rec, buyer, box, when):
    rec["outcome"] = "Won"
    rec["product"] = PRODUCT_NAME
    rec["status"] = "client"
    rec["relationship"] = "new_client"      # sales rail OFF (#52)
    rec["booked"] = True                    # cold-lead checker skips booked
    rec["booked_at"] = when.isoformat()
    rec["outcome_date"] = when.strftime("%Y-%m-%d")
    rec["deal_value"] = box["amount"]
    rec["service"] = PRODUCT_NAME
    rec["exclusive_offer"] = box
    for f in ("name", "email", "phone"):
        if buyer.get(f) and not str(rec.get(f) or "").strip():
            rec[f] = buyer[f]
    if buyer.get("company") and not str(rec.get("business") or "").strip():
        rec["business"] = buyer["company"]


def handle_offer_paid(event):
    """Returns None when the event is not an Exclusive Offer checkout (the
    caller carries on routing), otherwise a summary dict (event is owned)."""
    if (event or {}).get("type") != "checkout.session.completed":
        return None
    session = ((event.get("data") or {}).get("object")) or {}
    if not is_offer_session(session):
        return None

    event_id = event.get("id", "")
    idem = f"exclusive_offer_evt:{event_id}"
    try:
        if _deps["pg_load"](idem, False):
            return {"handled": True, "duplicate": True, "event": event_id}
    except Exception as e:
        _report("exclusive_offer.idem_load", e, idem)

    buyer = buyer_from_session(session)
    when = _now()
    amount_cents = int(session.get("amount_total") or 0)
    amount = amount_cents / 100.0
    paid = session.get("payment_status") == "paid"
    plink = session.get("payment_link") or ""
    box = {
        "purchased": when.isoformat(),
        "stripe_event": event_id,
        "checkout_session": session.get("id", ""),
        "payment_link": plink,
        "amount": amount,
        "paid": paid,
        "company": buyer["company"],
    }

    # 2 · Lead record
    lead_note = ""
    lead_name = buyer["name"]
    if paid:
        try:
            key, rec, via = _match_lead(buyer)
            if rec is not None:
                _mark_client(rec, buyer, box, when)
                lead_name = rec.get("name") or lead_name
                lead_note = f"lead record updated (matched by {via}) → Won"
            else:
                ld = _deps.get("lead_data")
                new_key = re.sub(r"\D", "", buyer["phone"]) or buyer["email"]
                if ld is not None and new_key:
                    ld[new_key] = {"name": buyer["name"], "email": buyer["email"],
                                   "phone": re.sub(r"\D", "", buyer["phone"]),
                                   "business": buyer["company"],
                                   "source": "Stripe — Exclusive Offer page",
                                   "first_contact_time": when,
                                   "last_message_time": when}
                    # Re-fetch: LeadData wraps on __setitem__ (#56) — mutate
                    # the stored object, never the dict we passed in.
                    _mark_client(ld[new_key], buyer, box, when)
                    lead_note = "no earlier lead record — new client record created"
                else:
                    lead_note = "⚠️ no lead record and none created (no email/phone)"
            try:
                _deps["update_sheet_status"](
                    lead_name, SHEET_STATUS,
                    f"{PRODUCT_NAME} — {PRICE_LABEL}, paid {when.strftime('%b %d, %Y')}",
                    PRODUCT_NAME,
                    "LARA calls within 1 business day to schedule the shoot")
            except Exception as e:
                _report("exclusive_offer.sheet", e, f"name={lead_name!r}")
        except Exception as e:
            _report("exclusive_offer.lead_update", e, f"email={buyer['email']}")
            lead_note = "🚨 lead update FAILED — see #dev"

    # 1 · Team alert (#lara + #rob, Michael tagged)
    due = next_business_day(when).strftime("%a %b %d")
    if paid:
        head = (f"💳 *EXCLUSIVE VIDEO OFFER — PAID* {MICHAEL_SLACK}\n"
                f"*{lead_name or '?'}*" + (f" · {buyer['company']}" if buyer["company"] else ""))
        todo = (f"*LARA:* call to schedule the shoot by *{due}* — the checkout "
                f"promised contact within 1 business day.")
    else:
        head = (f"⏳ *EXCLUSIVE VIDEO OFFER — CHECKOUT DONE, PAYMENT NOT SETTLED* "
                f"{MICHAEL_SLACK}\n*{lead_name or '?'}*"
                + (f" · {buyer['company']}" if buyer["company"] else ""))
        todo = ("*Do not schedule yet* — Stripe reports the payment as not settled "
                "(delayed method). ROB: confirm in Stripe before anyone calls.")
    text = (f"{head}\n"
            f"✉️ {buyer['email'] or '—'} · 📞 {buyer['phone'] or '—'}\n"
            f"${amount:,.2f} · link `{plink or '—'}` · session `{session.get('id', '')}`\n"
            + (f"{lead_note}\n" if lead_note else "")
            + todo)
    posted = 0
    for ch in (_deps.get("lara_channel"), _deps.get("rob_channel")):
        if not ch:
            continue
        try:
            _deps["post_slack"](ch, text)
            posted += 1
        except Exception as e:
            _report("exclusive_offer.slack", e, f"channel={ch}")

    if paid:
        try:
            fn = _deps.get("pipeline_event")
            if callable(fn):
                fn("CLIENT_WON", lead_name=lead_name, lead_phone=buyer["phone"],
                   source="Stripe — Exclusive Offer page", new_stage=SHEET_STATUS,
                   assigned_agents=["LARA", "ROB"],
                   context=f"{PRODUCT_NAME} · {PRICE_LABEL} · schedule by {due}")
        except Exception as e:
            _report("exclusive_offer.pipeline", e, "")

    if posted:
        try:
            _deps["pg_save"](idem, True)
        except Exception as e:
            _report("exclusive_offer.idem_save", e, idem)
    else:
        _report("exclusive_offer.no_alert",
                "sale alert did not reach Slack — not marking processed so Stripe retries",
                f"event={event_id}")
    return {"handled": True, "event": event_id, "paid": paid, "alerts": posted,
            "lead": lead_note, "email": buyer["email"]}


MAYA_OFFER_CONTEXT = """

EXCLUSIVE VIDEO OFFER — the visitor is chatting from this offer's page. Facts you may use (do not add to them):
- Price: $2,497, one-time payment (listed total value $6,885). No monthly fee, no contract.
- Included: 1 film shoot with our pro crew · up to 6 hours on set · a 2–3 minute professionally edited video · logo animation · 30 days of support.
- How to buy: the "Claim This Offer — Pay Now" button on this page opens a secure Stripe checkout. After payment our team contacts them within 1 business day to plan and schedule the shoot.
- Terms (mwmcreations.com/terms/#20): the shoot happens within 90 days of purchase; travel included within 30 miles of the Orlando studio (beyond that a travel fee, confirmed in writing first); one free reschedule with 72+ hours notice; full refund before a shoot date is confirmed, non-refundable after; two rounds of revisions included. For anything else about the terms, point them to that page.
- Rules: never offer a discount, coupon or payment plan on this offer. Do not promise anything not listed (extra videos, raw footage, dates, locations) — say the team plans those details on the scheduling call.
- If they want to talk before paying, offer a studio visit / consultation with Michael (use the booking tools as usual).
- If they need something bigger or recurring, mention the monthly video production plans (start at $1,997/month) and suggest the studio visit."""


def maya_offer_context(page_url):
    """The extra system-prompt block for a chat started on the offer page."""
    if page_url and OFFER_PATH in str(page_url).lower():
        return MAYA_OFFER_CONTEXT
    return ""
