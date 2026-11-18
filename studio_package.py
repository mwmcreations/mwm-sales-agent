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
import html as _html
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
# S8.6 (Michael, Jul 8): unused hours usable 30d past term end, then expire.
# STILL 30 for the trial and the one-off hour — nothing about those changed.
GRACE_DAYS = 30
# ── 21 Aug 2026 · Studio Package Terms v1.0 ──────────────────────────
# The 3-month package now gets NO grace. Terms v1.0 §4 is explicit:
# "The term itself is the window: any hours not used by the final day of the
# package expire, with no grace period and no carry-over."
#
# The code and the signed terms disagreed, and that is exactly the class of
# contradiction this whole piece of work exists to remove — the welcome email
# was promising 30 days of grace in writing while the terms about to be
# published said there was none.
#
# 🔴 NOT RETROACTIVE, AND IT DOES NOT NEED TO BE MADE SO. `package_term`
# computes `booking_deadline` at PURCHASE time and it is written into WP's
# `contract_end_date` there and then. Every existing client's deadline is
# already stored, so changing this number only reaches purchases from today
# forward. Michael's ruling — new packages only, nobody loses something they
# were told in writing — is satisfied by the existing architecture rather than
# by a migration.
PACKAGE_GRACE_DAYS = 0
PACKAGE_CYCLES = 3          # payments in the 3-month package
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

# PATCH #70 — AD_09's product. Created in Stripe by ROB on Aug 8 2026 (Michael's
# rule: ROB is the only agent who touches Stripe). Registered here because
# PACKAGES is keyed by price ID in CODE, not read from Stripe metadata — so a
# product can exist in Stripe, take real money, and provision NOTHING until
# this entry lands. That is exactly what happened between Rob creating it and
# this patch: package_for_session() returned None and the handler answered
# "other-product". Same failure #53 was written to prevent; it recurs for every
# new product until someone adds the row.
HOUR_ONEOFF_PRICE_ID = os.getenv("STUDIO_HOUR_ONEOFF_PRICE_ID",
                                 "price_1U2Gz7DAWlnEb9Rfhl5nA8t0")
HOUR_ONEOFF_NAME = "Studio Hour + Professional Editing"

# Keyed by Stripe price ID, because that is the one identifier the webhook can
# always see on a line item. `kind` mirrors the metadata set on the Stripe
# price and payment link, so a human reading either sees the same word.
PACKAGES = {
    STUDIO_PRICE_ID: {
        "kind": "studio_3mo",
        "name": PACKAGE_NAME,
        "hours": CONTRACT_HOURS,          # 12
        "term_days": CONTRACT_MONTHS * 30,  # 90
        "grace_days": PACKAGE_GRACE_DAYS,  # 0 → booking deadline IS the term end
        "cycles": PACKAGE_CYCLES,          # 3 payments of $1,200
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
    HOUR_ONEOFF_PRICE_ID: {
        "kind": "studio_hour_oneoff",
        "name": HOUR_ONEOFF_NAME,
        "hours": 1,
        # 30 days to use one hour is generous and matches the trial's shape, so
        # the portal's booking-window enforcement (S8.5) behaves identically.
        "term_days": 30,
        # ZERO, for the same reason as the trial: grace would silently double
        # the window the ad implied.
        "grace_days": 0,
        "recurring": False,
        # A $349 one-off must never inflate MRR. #53 was written because a
        # one-off was being counted as $1,200 of recurring revenue.
        "mrr": 0,
        "one_off": 349,
        "price_label": "$349 one-time",
        # Deliberately its own status. It must never merge with
        # "Client — Studio Trial (1 month)" — different product, different
        # price, different campaign.
        "sheet_status": "Client — Studio Hour (one-off)",
        "pace_note": "one hour, filmed and edited",
        # Editing is not an add-on here, it IS the offer. AD_09 says "we film
        # you, we edit it, you leave with video you can use" — the welcome
        # email is the written record the client keeps, so it says so.
        "includes_note": "Post-production editing is included",
        # Michael's ruling, Aug 8: "get the lead inside our room paying the
        # $349, and I can do the upsell over there." The upsell is deliberate
        # and happens in person. Nothing in this flow cross-sells, and no
        # credit toward a contract is invented here.
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


# ══════════════════════════════════════════════════════════════════════
# PATCH #278 · THE PLANS ON /book-studio
# ══════════════════════════════════════════════════════════════════════
# Michael, Mon 9 Nov 2026: "if you go to our website right now, we have 4
# different studio packages, and those packages need to be aligned with our
# sales system… make sure everything is aligned with what we have now."
#
# Before this patch only the three PACKAGES above provisioned anything. A
# client paying for AI Starter, AI Growth, AI Pro, an AI Wall Hour or a Full
# Immersion on the live page got NO portal account and NO welcome email (David
# was set up by hand). His rulings, same day:
#   · monthly plans: hours roll over, capped at 2 months' worth — each monthly
#     payment adds that month's hours up to the cap (AI Starter holds at most
#     4 h; Real Sets, AI Growth and AI Pro at most 8 h);
#   · one-time services: 1 studio hour per item, bookable for 60 days;
#   · Founding 10 annual prepay: the whole year (12 × monthly hours) loads at
#     once, bookable over 12 months (extended by hand if they pause).
# PLANS is its own table, not rows in PACKAGES: PACKAGES keeps its three
# entries and every email they send stays byte-for-byte the same.
PLAN_CAP_MONTHS = 2
PLAN_FIRST_WINDOW_DAYS = 60     # first month's hours: bookable this month and next
PLAN_TOPUP_WINDOW_DAYS = 30     # each renewal: bookable until 30 days past the next charge
ONEOFF_SERVICE_DAYS = 60
ANNUAL_TERM_DAYS = 365
PLAN_EDIT_NOTE = ("Editing is included: each hour gives you up to 10 edited short videos "
                  "or 1 podcast episode with 10 short cuts")
# PATCH #289 — the disclaimer, in Michael's words (18 Nov): the contract side lives
# here, once, in the welcome; the creative side never counts to 12.
PLAN_FOOTER_NOTE = ("This is a 3-month minimum agreement; after that your plan is recurring "
                    "month to month, and you can stop at any time with 30 days' notice.")
# Real Sets' Founding price IS STUDIO_PRICE_ID (ROB reused the $1,200 price for
# the website link). The old 3-month package keeps that price in PACKAGES; a
# checkout is Real Sets when it came through a Real Sets link or the
# subscription carries the link's sku.
REAL_SETS_SKUS = ("plan_studio_only_4h", "plan_real_sets")
REAL_SETS_LINKS = ("plink_1UR148DAWlnEb9RfffEDwxut",   # Founding $1,200
                   "plink_1UXJxUDAWlnEb9RfbgDk8pyU")   # regular $1,497


def _monthly_plan(kind, name, m, mrr, pace, includes, founding):
    cap = m * PLAN_CAP_MONTHS
    return {
        "kind": kind, "name": name, "hours": m, "monthly_hours": m, "cap_hours": cap,
        "term_days": PLAN_FIRST_WINDOW_DAYS, "grace_days": 0,
        "cycles": 12, "interval": "month", "recurring": True, "mrr": mrr, "one_off": 0,
        "price_label": f"${mrr:,}/month" + (" · Founding price" if founding else ""),
        "sheet_status": f"Client — {name}",
        "pace_note": pace, "includes_note": includes,
        "extra_notes": [PLAN_EDIT_NOTE,
                        # PATCH #289 — no total: "two months' worth", not "8 hours"
                        "Unused studio time rolls over to the next month (you can hold up "
                        "to two months' worth)"],
        "credits_toward_contract": False,
        "ongoing": True,
        "footer_note": PLAN_FOOTER_NOTE + (" Your Founding price stays locked while your "
                                           "plan is active." if founding else ""),
        "plan": "monthly", "founding": bool(founding),
    }


def _oneoff_service(kind, name, amount, includes):
    return {
        "kind": kind, "name": name, "hours": 1, "term_days": ONEOFF_SERVICE_DAYS,
        "grace_days": 0, "recurring": False, "mrr": 0, "one_off": amount,
        "price_label": f"${amount:,} one-time",
        "sheet_status": f"Client — {name}", "pace_note": "", "includes_note": includes,
        "credits_toward_contract": False, "plan": "oneoff", "per_unit": True,
    }


def _annual_plan(kind, name, m, amount, pace, includes):
    return {
        "kind": kind, "name": name, "hours": 12 * m, "monthly_hours": m,
        "term_days": ANNUAL_TERM_DAYS, "grace_days": 0,
        "recurring": False, "mrr": 0, "one_off": amount,
        "price_label": f"${amount:,} for 12 months (Founding 10)",
        "sheet_status": f"Client — {name}", "pace_note": pace, "includes_note": includes,
        "extra_notes": [PLAN_EDIT_NOTE],
        "credits_toward_contract": False, "plan": "annual", "founding": True,
    }


_P_REAL = "on our real sets"
_P_START = "1 on our real sets, 1 on the AI Wall"
_P_GROW = "up to 2 of them on the AI Wall"
_P_PRO = "all on the AI Wall"
_FI1 = "Your plan includes 1 Full Immersion video every month"      # PATCH #289 — Michael 18 Nov 10:46
_FI2 = "Your plan includes 2 Full Immersion videos every month"

_PLAN_ROWS = (
    # kind, name, monthly hours, pace, includes, founding price, $, regular price, $
    ("plan_real_sets", "Real Sets Plan", 4, _P_REAL, "",
     None, 1200, "price_1UXJwUDAWlnEb9RfLIi8E2ea", 1497),
    ("plan_ai_starter", "AI Starter Plan", 2, _P_START, _FI1,
     "price_1UR0ipDAWlnEb9RfSTYiE4VE", 1297, "price_1UXJwTDAWlnEb9RfgKs5wyxQ", 1497),
    ("plan_ai_growth", "AI Growth Plan", 4, _P_GROW, _FI1,
     "price_1UR13hDAWlnEb9Rfv3SarAEu", 1697, "price_1UXJwSDAWlnEb9Rfs9ZM5Xah", 1997),
    ("plan_ai_pro", "AI Pro Plan", 4, _P_PRO, _FI2,
     "price_1UR13kDAWlnEb9RfxUYIOCE0", 2497, "price_1UXJwTDAWlnEb9Rf3b0RwJQf", 2997),
)
PLANS = {}
for _k, _n, _m, _pace, _inc, _fp, _fa, _rp, _ra in _PLAN_ROWS:
    if _fp:
        PLANS[_fp] = _monthly_plan(_k, _n, _m, _fa, _pace, _inc, True)
    PLANS[_rp] = _monthly_plan(_k, _n, _m, _ra, _pace, _inc, False)
# Real Sets' Founding price is STUDIO_PRICE_ID (see above): reached via sku/link only.
REAL_SETS_FOUNDING = _monthly_plan("plan_real_sets", "Real Sets Plan", 4, 1200, _P_REAL, "", True)

PLANS.update({
    "price_1UR0ixDAWlnEb9Rfw5I1cFJX": _oneoff_service(
        "ai_wall_hour", "AI Wall Hour", 599,
        "Up to 3 AI worlds, editing included: up to 10 edited short videos or 1 podcast "
        "episode with 10 short cuts"),
    "price_1UR9slDAWlnEb9RfwuwNC0ac": _oneoff_service(
        "full_immersion", "Full Immersion", 997,
        "Each Full Immersion video: up to 30 seconds, up to 3 AI scenes, finished edit, "
        "1 revision round"),
    "price_1ULR8vDAWlnEb9RfJrE5OJcI": _oneoff_service(
        "full_immersion_pack", "Full Immersion Pack", 1497,
        "Four Full Immersion videos, planned together with Michael"),
    # Founding 10 annual prepay (ROB, Nov 8: "pay 9, get 12"). The agreement
    # calls the first one "Studio Only"; on the website it is Real Sets.
    "price_1UZaCHDAWlnEb9RfBQNh2P83": _annual_plan(
        "f10_real_sets", "Real Sets Plan · Founding Year", 4, 13473, _P_REAL, ""),
    "price_1UZaCEDAWlnEb9RfuTxbrbfW": _annual_plan(
        "f10_ai_starter", "AI Starter Plan · Founding Year", 2, 13473, _P_START, _FI1),
    "price_1UZaCCDAWlnEb9RfKpoeJTAI": _annual_plan(
        "f10_ai_growth", "AI Growth Plan · Founding Year", 4, 17973, _P_GROW, _FI1),
    "price_1UZaCGDAWlnEb9RfRvBAb8Vn": _annual_plan(
        "f10_ai_pro", "AI Pro Plan · Founding Year", 4, 26973, _P_PRO, _FI2),
})
PLAN_NAMES = tuple(sorted({sp_["name"] for sp_ in PLANS.values()}))


def resolve_spec(price_id, sku="", payment_link=""):
    """PATCH #278 — the spec for what was bought: a PACKAGE, a PLAN, or None.

    The one overlap is STUDIO_PRICE_ID, shared by the old 3-month package and
    the website's Real Sets Founding link: a Real Sets sku or link makes it the
    Real Sets plan; anything else keeps the package exactly as before."""
    pid = str(price_id or "").strip()
    if pid == STUDIO_PRICE_ID:
        # PATCH #287 — Michael, 18 Nov 09:47: the 3-month package is retired for
        # new purchases; every $1,200 checkout is the Real Sets plan, ongoing,
        # 3-month minimum, whatever link or sku it came through. PACKAGES keeps
        # the old spec for custom provisioning and the legacy emails.
        return REAL_SETS_FOUNDING
    return PACKAGES.get(pid) or PLANS.get(pid)


def _per_unit(spec, qty):
    """One studio hour per item for the one-time services (Full Immersion × 3 = 3 h)."""
    try:
        qty = int(qty or 1)
    except (TypeError, ValueError):
        qty = 1
    if not spec or not spec.get("per_unit") or qty <= 1:
        return spec
    out = dict(spec)
    out["quantity"] = qty
    out["hours"] = int(spec["hours"]) * qty
    out["one_off"] = int(spec.get("one_off") or 0) * qty
    out["price_label"] = f"{qty} × ${int(spec.get('one_off') or 0):,} one-time"
    return out


def spec_by_kind(kind):
    """PATCH #287 — a PACKAGE or PLAN spec by its kind ('studio_3mo', 'plan_ai_growth', …);
    founding prices first; Real Sets' founding spec is not in PLANS."""
    k = str(kind or "").strip()
    if not k:
        return None
    for s_ in PACKAGES.values():
        if s_["kind"] == k:
            return s_
    if REAL_SETS_FOUNDING["kind"] == k:
        return REAL_SETS_FOUNDING
    for s_ in sorted(PLANS.values(), key=lambda x: not x.get("founding")):
        if s_["kind"] == k:
            return s_
    return None


def plan_terms(spec):
    """How the team reads a plan's hours in Slack / the pipeline."""
    kind = (spec or {}).get("plan")
    if kind == "monthly":
        return (f"{spec['monthly_hours']}h/month, ongoing (rolls over, holds up to "
                f"{spec['cap_hours']}h)")
    if kind == "annual":
        return (f"{spec['hours']}h for the Founding year ({spec['monthly_hours']}h/month "
                f"× 12, all loaded now)")
    if kind == "oneoff":
        return f"{spec['hours']}h, bookable for {spec['term_days']} days"
    return f"{(spec or {}).get('hours')}h over {term_phrase(spec)}"


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


# ── 21 Aug 2026 · the billing footer ────────────────────────────────
# Michael, after reading ROB's spec: he did NOT want a checkout tick-box.
# "On Stripe you already have that very well made a sentence... I don't wanna
# create something that the client is gonna be feeling awkward having to check
# all of those things."
#
# He is right, and the evidence supports him: Iris — the client who disputed —
# had MORE disclosure than anyone else on the account. She ticked a consent box
# and Stripe rendered "$1,200.00 per month". The failure was never the
# checkout. It was that nothing MWM wrote said how package billing works.
#
# So the disclosure moves to the two places that cost the client nothing: the
# Terms, and a quiet footer on the welcome email. His words: "small lines at
# the bottom, something subtle there that kinda let them know that this is an
# automated charge. Once they do a package, of course."
#
# 🔴 THE DATES ARE THE WHOLE POINT. "The 18th of each month" is a description;
# "June 18, July 18, August 18" is a record. ROB's spec called that the single
# line that would have prevented the dispute, and it is the one thing here
# worth being fussy about.

STUDIO_TERMS_URL = os.getenv("STUDIO_TERMS_URL",
                             "https://mwmcreations.com/studio-terms")


def _add_calendar_month(d, n):
    """d plus n calendar months, clamped to the last valid day.

    Calendar months, NOT 30-day steps — Terms v1.0 §1 says "the same calendar
    day of each billing cycle", and Stripe bills that way too. A 31 Jan start
    bills 28 Feb; stepping by 30 days would say 2 March and be wrong on the
    client's statement.
    """
    y, m = d.year, d.month + n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    # Walk DOWN from the original day to the first one that exists in the
    # target month. Must start at d.day and go to 1 — an earlier version used
    # range(d.day, 27, -1), which is EMPTY for any day before the 28th, so
    # every ordinary date silently fell through to the 28th and a client
    # starting on 18 June was told they would be billed on the 28th. Caught by
    # running it on a real date rather than trusting the loop.
    for day in range(d.day, 0, -1):
        try:
            return d.replace(year=y, month=m, day=day)
        except ValueError:
            continue
    return d.replace(year=y, month=m, day=1)


def next_refresh_date(start):
    """PATCH #290 — the next monthly charge after `start` (same calendar day, clamped)."""
    d = start.date() if hasattr(start, "date") else start
    return _add_calendar_month(d, 1)


def billing_dates(spec, start):
    """Every date this package is charged on. Pure. [] for one-offs."""
    if not (spec or {}).get("recurring"):
        return []
    cycles = int((spec or {}).get("cycles") or 0)
    if cycles < 1:
        return []
    start_d = start.date() if hasattr(start, "date") else start
    # PATCH #269 — a weekly deal bills every 7 days from the day they paid.
    if str(spec.get("interval") or "month") == "week":
        return [start_d + timedelta(days=7 * i) for i in range(cycles)]
    return [_add_calendar_month(start_d, i) for i in range(cycles)]


def _dates_by_month(dates):
    """PATCH #269 — "November 6, 13, 20, 27; December 4, 11, 18, 25; January 1, 8"."""
    groups = []
    for d in dates:
        label = d.strftime("%B") if hasattr(d, "strftime") else str(d)
        day = str(d.day) if hasattr(d, "day") else ""
        if groups and groups[-1][0] == label:
            groups[-1][1].append(day)
        else:
            groups.append([label, [day]])
    return "; ".join(f"{m} {', '.join(ds)}" for m, ds in groups)


def billing_footer_html(spec, term):
    """The subtle billing line for the welcome email. "" for one-offs.

    Deliberately returns EMPTY for anything non-recurring. A $349 single hour
    is not on automatic billing and telling its buyer about recurring charges
    would be both wrong and alarming.
    """
    spec = spec or {}
    if not spec.get("recurring"):
        return ""
    dates = billing_dates(spec, (term or {}).get("start"))
    if not dates:
        return ""
    if str(spec.get("interval") or "month") == "week":
        # PATCH #269 — a weekly deal. The amount is the weekly charge, never
        # the MRR figure; the dates are still listed, grouped by month, because
        # the dates are the record (see the note above this function).
        w_amount = int(spec.get("cycle_amount") or 0)
        w_cycles = len(dates)
        w_total = w_amount * w_cycles
        return (
            '<p style="font-size:12px;line-height:1.6;color:#888;margin-top:22px;'
            'padding-top:14px;border-top:1px solid #e8e8e8;">'
            f'Your plan is <strong style="color:#666;">${w_amount:,}/week for '
            f'{w_cycles} weeks</strong> (${w_total:,} total), charged automatically to '
            f'the card on file every {dates[0].strftime("%A")} — '
            f'<strong style="color:#666;">{_dates_by_month(dates)}</strong>. '
            f'Hours can be used at any point during the term and expire at the end '
            f'of it, when we review the results together and decide the next step. '
            f'<a href="{STUDIO_TERMS_URL}" style="color:#888;">Studio Terms →</a>'
            '</p>')
    if spec.get("ongoing"):
        # PATCH #277 — an ongoing monthly plan (Michael, Mon 9 Nov 2026, on
        # David's welcome: "I want to make sure that clients understand this is
        # an ongoing project"). No "for N months", no total: the monthly price,
        # the day it is charged, the next charge, and the commitment in the
        # deal's own words.
        o_amount = int(spec.get("mrr") or 0)
        o_today = datetime.now(pytz.timezone("America/New_York")).date()
        # PATCH #278 — dates[0] is the day they paid; "next" is never that one.
        o_next = next((d for d in dates[1:] if d >= o_today), None)
        o_day = dates[0].day
        o_suffix = "th" if 11 <= o_day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(o_day % 10, "th")
        o_next_txt = (f" (next charge: <strong style=\"color:#666;\">"
                      f"{o_next.strftime('%B')} {o_next.day}</strong>)") if o_next else ""
        o_note = str(spec.get("footer_note") or "").strip()
        return (
            '<p style="font-size:12px;line-height:1.6;color:#888;margin-top:22px;'
            'padding-top:14px;border-top:1px solid #e8e8e8;">'
            f'Your plan is <strong style="color:#666;">${o_amount:,}/month</strong>, '
            f'charged automatically to the card on file on the {o_day}{o_suffix} of each '
            f'month{o_next_txt}. '
            + (f'{_html.escape(o_note)} ' if o_note else '') +
            f'<a href="{STUDIO_TERMS_URL}" style="color:#888;">Studio Package Terms →</a>'
            '</p>')
    amount = int(spec.get("mrr") or 0)
    cycles = len(dates)
    total = amount * cycles
    when = ", ".join(d.strftime("%B %-d") if hasattr(d, "strftime") else str(d)
                     for d in dates)
    return (
        '<p style="font-size:12px;line-height:1.6;color:#888;margin-top:22px;'
        'padding-top:14px;border-top:1px solid #e8e8e8;">'
        f'Your package is <strong style="color:#666;">${amount:,}/month for '
        f'{cycles} months</strong> (${total:,} total), charged automatically to '
        f'the card on file — <strong style="color:#666;">{when}</strong>. '
        f'Hours can be used at any point during the term and expire at the end '
        f'of it. '
        f'<a href="{STUDIO_TERMS_URL}" style="color:#888;">Studio Package Terms →</a>'
        '</p>')


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
    # PATCH #278 — the plans. Founding prices first, so a row reads at the
    # price most current clients pay; "AI Starter" matches "AI Starter Plan".
    for spec in sorted(PLANS.values(), key=lambda s_: not s_.get("founding")):
        n = spec["name"].strip().lower()
        if want in (n, n.replace(" plan", "", 1)):
            return spec
    if want in ("real sets", "real sets plan"):
        return REAL_SETS_FOUNDING
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
    # PATCH #269 — a deal may carry the exact words it was sold with
    # (13 weeks is "3 months" to the client, never "91 days").
    if spec.get("term_label"):
        return str(spec["term_label"])
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


def package_for_checkout(session: dict):
    """PATCH #278 — package_for_session, plus the plans and quantities.

    Reads the session's payment link and sku (Stripe copies a payment link's
    metadata onto its checkout sessions) so a Real Sets checkout on the shared
    $1,200 price is the Real Sets plan, and multiplies a one-time service by
    the quantity bought."""
    session = session or {}
    sid = str(session.get("id") or "")
    sku = str((session.get("metadata") or {}).get("sku") or "")
    link = session.get("payment_link") or ""
    if isinstance(link, dict):
        link = link.get("id") or ""
    try:
        items = _deps["stripe_get"](f"checkout/sessions/{sid}/line_items", {"limit": 20})
        for it in (items or {}).get("data", []):
            spec = resolve_spec((it.get("price") or {}).get("id"), sku, link)
            if spec:
                return _per_unit(spec, it.get("quantity"))
    except Exception as e:
        _report("studio.line_items", e, f"session={sid}")
    return None


def topup_portal_client(email: str, add_hours, cap_hours=0, end=None, ref: str = "",
                        package: str = "", monthly_hours=0, dry_run: bool = False,
                        next_refresh=None) -> dict:
    """PATCH #278 — add hours to an EXISTING portal client (WP snippet 15,
    action mwm_studio_topup_client). `cap_hours` > 0 caps what they can hold
    AVAILABLE afterwards (monthly roll-over: 2 months' worth); `end` only ever
    moves the last bookable day later; `ref` makes it apply once.
    Returns {'ok', 'found', 'duplicate', 'added', 'available', 'end_after', ...}."""
    payload = {"action": "mwm_studio_topup_client", "email": str(email or "").strip().lower(),
               "add_hours": str(add_hours), "cap_hours": str(cap_hours or 0),
               "ref": str(ref or "")[:120]}
    if end:
        payload["contract_end"] = end.strftime("%Y-%m-%d") if hasattr(end, "strftime") else str(end)
    if package:
        payload["package"] = package
    if monthly_hours:
        payload["monthly_hours"] = str(monthly_hours)
    if next_refresh:   # PATCH #290 — the portal's 'Refreshes on …' (snippet 15 v3)
        payload["next_refresh"] = next_refresh.strftime("%Y-%m-%d") if hasattr(next_refresh, "strftime") else str(next_refresh)
    if dry_run:
        payload["dry_run"] = "1"
    import time as _t
    last = ""
    for _attempt in range(3):   # safe to retry: WP applies a ref once
        try:
            r = http_requests.post(
                WP_PORTAL_PROVISION_URL, data=payload,
                headers={"X-MWM-Portal-Secret": WP_PORTAL_SECRET, "User-Agent": WP_UA}, timeout=20)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            data = body.get("data") or {}
            if body.get("success"):
                out = {"ok": True, "status": r.status_code}
                out.update({k: data.get(k) for k in (
                    "found", "duplicate", "added", "hours_before", "hours_after", "hours_used",
                    "available", "end_before", "end_after", "fresh_start", "client_id")})
                return out
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = repr(e)
        if _attempt < 2:
            _t.sleep(2 ** _attempt)
    _report("studio.topup_portal_client", last, f"email={email} ref={ref}")
    return {"ok": False, "found": None, "raw": last}


def _hours_added_email_html(first_name: str, spec: dict, term: dict, topup: dict) -> str:
    """PATCH #278 — an existing portal client bought again: no new code (they
    have one), just what was added and how to book it."""
    spec = spec or {}
    e = lambda v: _html.escape(str(v or ""))
    plan = spec.get("plan")
    avail = (topup or {}).get("available")
    try:
        avail_txt = f"{float(avail):g}"
    except (TypeError, ValueError):
        avail_txt = ""
    deadline = (term or {}).get("booking_deadline")
    if plan == "monthly":
        # PATCH #289 — monthly, never a quota headline
        lead = (f"Your <strong>{e(spec['name'])}</strong> is active: an ongoing creative "
                f"partnership with MWM Studios, renewed every month. This month's studio "
                f"time is already in your portal.")
    elif plan == "annual":
        lead = (f"Your <strong>{e(spec['name'])}</strong> is active: "
                f"{spec['monthly_hours']} hours every month for the next 12 months. All "
                f"{spec['hours']} hours of your year are already in your portal.")
    else:
        _h = int(spec.get("hours") or 1)
        lead = (f"Your <strong>{e(spec['name'])}</strong> is confirmed: we've added "
                f"{'1 studio hour' if _h == 1 else f'{_h} studio hours'} to your portal"
                + (f", bookable until <strong>{deadline.strftime('%A, %B %d, %Y')}</strong>"
                   if deadline else "") + ".")
    notes = [str(spec.get("includes_note") or "").strip()] + list(spec.get("extra_notes") or [])
    notes = [n for n in notes if n]
    return f"""
<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#222;">
  <div style="background:#111;padding:28px 32px;border-radius:12px 12px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:22px;">Your hours are ready 🎬</h1>
  </div>
  <div style="padding:28px 32px;background:#fafafa;border:1px solid #eee;border-top:none;
              border-radius:0 0 12px 12px;">
    <p style="font-size:16px;">Hi {e(first_name)},</p>
    <p style="font-size:15px;line-height:1.6;">{lead}</p>""" + (f"""
    <p style="font-size:15px;line-height:1.6;">You have <strong>{avail_txt} hours</strong> available to book right now.</p>""" if avail_txt else "") + f"""
    <p style="font-size:15px;line-height:1.6;">Log in at <a href="{PORTAL_URL}">{PORTAL_URL}</a>
    with this email address and the access code you already have, then pick a time on the
    booking calendar. Lost your code? Just reply to this email.</p>""" + ("""
    <ul style="font-size:15px;line-height:1.7;">""" + "".join(f"\n      <li>{n}</li>" for n in notes) + """
    </ul>""" if notes else "") + f"""
    <p style="font-size:15px;">— Michael &amp; the MWM Creations team<br>
    <span style="color:#888;font-size:13px;">Orlando, FL · mwmcreations.com</span></p>
    {billing_footer_html(spec, term)}
  </div>
</div>"""


def provision_portal_client(name: str, email: str, spec: dict = None,
                            dry_run: bool = False, start=None, rotate_code: bool = False,
                            next_refresh=None) -> dict:
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
    # PATCH #269 — `start` lets a by-hand provision run the term from the day
    # the client paid, not the day somebody got round to it.
    term = package_term(spec, start or datetime.now(et))
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
    if spec.get("plan") and spec.get("monthly_hours"):
        payload["monthly_hours"] = str(spec["monthly_hours"])   # PATCH #278
    # PATCH #290 — a monthly plan's next charge is the portal's 'Refreshes on …'.
    if next_refresh is None and spec.get("plan") == "monthly":
        next_refresh = next_refresh_date(term["start"])
    if next_refresh:
        payload["next_refresh"] = next_refresh.strftime("%Y-%m-%d") if hasattr(next_refresh, "strftime") else str(next_refresh)
    if dry_run:
        payload["dry_run"] = "1"
    if rotate_code:
        payload["rotate_code"] = "1"   # PATCH #287 — WP hands back a NEW code for an existing account
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
    # PATCH #269 — further lines a deal wants in the written record (referral
    # hours, say). Empty for every package, so their emails do not change by
    # a character.
    if spec.get("ongoing"):
        # PATCH #277 — an ongoing monthly plan speaks per month, never in
        # totals or end dates: the portal still holds a total and a last
        # bookable day (ROB tops it up), but the client reads a partnership.
        _m = int(spec.get("monthly_hours") or 0) or hours
        # PATCH #289 — Michael, 18 Nov 10:31: the creative side speaks monthly, never
        # in totals; the monthly figure appears once, as what the portal refreshes.
        headline = (f"Your <strong>{spec['name']}</strong> is active: an ongoing creative "
                    f"partnership with MWM Studios, renewed every month.")
        total_li = (f"Your monthly studio time: {_m} hours, refreshed every month"
                    + (f" ({_pace})" if _pace else ""))
        expiry_li = ("Your plan continues month after month, and your portal always "
                     "shows the studio time you have available to book")
        if _includes:
            expiry_li = f"{expiry_li}</li>\n      <li>{_includes}"
    if spec.get("plan") == "oneoff":
        # PATCH #278 — a one-time service: what they bought, and when to book it.
        _h = int(hours)
        _hw = "1 studio hour" if _h == 1 else f"{_h} studio hours"
        headline = (f"Your <strong>{spec['name']}</strong> is confirmed: {_hw} ready to "
                    f"book in your portal.")
        total_li = _hw + (f" ({_pace})" if _pace else "")
        expiry_li = (f"Book any time in the next {spec['term_days']} days"
                     + (f": the last day you can book is <strong>{deadline_str}</strong>"
                        if deadline_str else ""))
        if _includes:
            expiry_li = f"{expiry_li}</li>\n      <li>{_includes}"
    elif spec.get("plan") == "annual":
        # PATCH #278 — Founding 10 annual prepay: the whole year is loaded now.
        _m = int(spec.get("monthly_hours") or 0)
        headline = (f"Your <strong>{spec['name']}</strong> is active: {_m} hours of "
                    f"professional studio time every month for the next 12 months, at "
                    f"your Founding 10 rate.")
        total_li = (f"{_m} studio hours every month" + (f" ({_pace})" if _pace else ""))
        expiry_li = (f"All {hours} hours of your year are already in your portal, so you "
                     f"can book ahead"
                     + (f": the last day you can book is <strong>{deadline_str}</strong>"
                        if deadline_str else ""))
        if _includes:
            expiry_li = f"{expiry_li}</li>\n      <li>{_includes}"
    for _note in (spec.get("extra_notes") or []):
        _note = str(_note or "").strip()
        if _note:
            expiry_li = f"{expiry_li}</li>\n      <li>{_note}"
    _fs = spec.get("first_session") or None
    if _fs:
        return _welcome_email_body(first_name, access_code, headline, total_li,
                                   expiry_li, billing_footer_html(spec, term),
                                   highlight_html=_first_session_html(_fs),
                                   book_title="Book your next sessions",
                                   book_text=("Your first session is already on the "
                                              "calendar. For the next ones, log in, pick a "
                                              "time on the booking calendar, done. Your hours "
                                              "are tracked automatically."))
    return _welcome_email_body(first_name, access_code, headline, total_li,
                               expiry_li, billing_footer_html(spec, term))


def _first_session_html(fs):
    """PATCH #277 — the first session, already booked, as the most visible
    thing in the welcome email (Michael: "make it more visible visually")."""
    e = lambda v: _html.escape(str(v or "").strip())
    notes = [e(n) for n in (fs.get("notes") or []) if str(n or "").strip()]
    return (
        '<div style="margin:20px 0 24px;border:2px solid #C8A96E;border-radius:12px;'
        'background:#111;color:#fff;padding:20px 22px;">'
        '<div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;'
        f'color:#C8A96E;font-weight:bold;">&#128197; {e(fs.get("title")) or "Your first session is booked"}</div>'
        f'<div style="font-size:26px;font-weight:bold;margin:10px 0 2px;color:#fff;">{e(fs.get("when"))}</div>'
        f'<div style="font-size:21px;font-weight:bold;color:#E3C88E;margin-bottom:12px;">{e(fs.get("time"))}</div>'
        + (f'<div style="font-size:14px;color:#ccc;">&#128205; {e(fs.get("place"))}</div>' if fs.get("place") else "")
        + (f'<p style="font-size:14px;line-height:1.6;color:#ddd;margin:12px 0 0;">{"<br>".join(notes)}</p>' if notes else "")
        + '</div>')


def _welcome_email_body(first_name: str, access_code: str, headline: str,
                        total_li: str, expiry_li: str,
                        billing_footer: str = "", highlight_html: str = "",
                        book_title: str = "Book your first session",
                        book_text: str = ("All booking happens right in your portal —\n"
                                          "    log in, pick a time on the booking calendar, "
                                          "done. Your hours are tracked automatically.")) -> str:
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
    Here's everything you need:</p>{highlight_html}
    <h3 style="margin-bottom:6px;">1 · Your client portal</h3>
    <p style="font-size:15px;line-height:1.6;">Track your hours, see upcoming sessions, and
    manage bookings at<br><a href="{PORTAL_URL}">{PORTAL_URL}</a></p>
    <p style="font-size:15px;">Log in with this email address and your access code:</p>
    <p style="text-align:center;margin:18px 0;">{code_block}</p>
    <h3 style="margin-bottom:6px;">2 · {book_title}</h3>
    <p style="font-size:15px;line-height:1.6;">{book_text}</p>
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
    {billing_footer}
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
        _spec = package_for_checkout(obj)          # PATCH #278 — plans too
        if _spec is None:
            return {"handled": False, "reason": "other-product", "event": event_id}
        details = obj.get("customer_details") or {}
        email = (details.get("email") or obj.get("customer_email") or "").strip().lower()
        name = (details.get("name") or "").strip() or email.split("@")[0].title()
        if not email:
            _report("studio.purchase", "no email on checkout session", f"event={event_id}")
            return {"handled": False, "reason": "no-email", "event": event_id}
        if _spec.get("plan"):
            _mark_checkout(email, _spec["kind"])  # PATCH #278 — the invoice path defers to this
        _on_package_purchased(name, email, event_id, _spec)
        return {"handled": True, "event": event_id, "email": email,
                "package": _spec["kind"]}

    if etype == "invoice.paid":
        return _on_invoice_paid(obj, event_id)    # PATCH #278

    if etype in ("invoice.payment_failed", "customer.subscription.deleted"):
        details = ((obj.get("customer_details") or {}).get("email")
                   or obj.get("customer_email") or "unknown")
        _deps["post_slack"](_deps["matt_channel"],
            f"⚠️ *Stripe {etype}* for {details} — Studio Package billing needs attention. "
            f"ROB/Michael: check the Stripe dashboard.")
        return {"handled": True, "event": event_id, "alerted": etype}

    return {"handled": False, "reason": "ignored-type", "type": etype}


_CHECKOUT_KEY = "studio_plan_checkouts"


def _mark_checkout(email, kind):
    """PATCH #278 — remember that a checkout provisioned this plan, so an
    invoice for the same purchase (a subscription's first invoice, or a
    one-time invoice Stripe raises for a checkout) never provisions it twice."""
    try:
        with _processed_lock:
            seen = _deps["pg_load"](_CHECKOUT_KEY, {}) or {}
            seen[f"{email}|{kind}"] = datetime.utcnow().isoformat()
            if len(seen) > 300:
                for k in sorted(seen, key=seen.get)[:len(seen) - 300]:
                    seen.pop(k, None)
            _deps["pg_save"](_CHECKOUT_KEY, seen)
    except Exception as e:
        _report("studio.mark_checkout", e, f"email={email}")


def _checkout_recent(email, kind, minutes=60):
    try:
        seen = _deps["pg_load"](_CHECKOUT_KEY, {}) or {}
        at = seen.get(f"{email}|{kind}")
        return bool(at) and datetime.utcnow() - datetime.fromisoformat(at) < timedelta(minutes=minutes)
    except Exception:
        return False


def _invoice_lines(inv):
    """(price_id, quantity, period_end_epoch, period_start_epoch) per line, old and new API shapes."""
    out = []
    for ln in (((inv or {}).get("lines") or {}).get("data") or []):
        pr = ln.get("price")
        pid = pr.get("id") if isinstance(pr, dict) else pr
        if not pid:
            pid = ((ln.get("pricing") or {}).get("price_details") or {}).get("price")
        out.append((str(pid or ""), int(ln.get("quantity") or 1),
                    (ln.get("period") or {}).get("end"),
                    (ln.get("period") or {}).get("start")))   # PATCH #287
    return out


def _invoice_subscription(inv):
    """(subscription id, subscription metadata) — old and new API shapes."""
    inv = inv or {}
    sd = ((inv.get("parent") or {}).get("subscription_details") or {})
    sub = inv.get("subscription") or sd.get("subscription") or ""
    if isinstance(sub, dict):
        sub = sub.get("id") or ""
    meta = ((inv.get("subscription_details") or {}).get("metadata")
            or sd.get("metadata") or {})
    return str(sub), meta


def _prepaid_bucket_covers(email, period_start_epoch):
    """PATCH #287 — does a prepaid 3-month bucket on the lead record still cover
    this charge? -> {covered, until, until_iso, hours} · {convert, key, rec} · {}."""
    try:
        key, rec = _deps["lead_lookup_by_email"](email)
    except Exception:
        key, rec = None, None
    spr = rec.get("studio_package") if isinstance(rec, dict) else None
    if not isinstance(spr, dict) or spr.get("variant") != "studio_3mo" or not spr.get("booking_deadline"):
        return {}
    try:
        until = datetime.fromisoformat(str(spr["booking_deadline"])[:10]).date()
        tz = pytz.timezone(TIMEZONE)
        ps = (datetime.fromtimestamp(int(period_start_epoch), tz).date() if period_start_epoch
              else datetime.now(tz).date())
    except Exception:
        return {}
    if ps <= until:
        return {"covered": True, "until": until.strftime("%b %d, %Y"), "until_iso": until.isoformat(),
                "hours": spr.get("hours") or 12, "key": key, "rec": rec}
    return {"convert": True, "key": key, "rec": rec}


def _record_plan(email, spec):
    """PATCH #288 — the plan the client was GIVEN: a courtesy_plan on the lead
    record wins over the plan the Stripe price names (Camila pays Real Sets,
    holds AI Growth). Falls back to the price's spec."""
    try:
        _k, rec = _deps["lead_lookup_by_email"](email)
    except Exception:
        rec = None
    spr = rec.get("studio_package") if isinstance(rec, dict) else None
    court = spec_by_kind((spr or {}).get("courtesy_plan")) if isinstance(spr, dict) else None
    return court if (court and court.get("plan") == "monthly") else spec


def _convert_bucket_record(key, rec, spec):
    """PATCH #287 — the bucket is spent: from here on the record is the rolling plan."""
    try:
        old = dict(rec.get("studio_package") or {})
        # PATCH #288 — a courtesy upgrade rolls into the plan she was GIVEN, at the price she pays.
        court = spec_by_kind(old.get("courtesy_plan")) if old.get("courtesy_plan") else None
        plan = court if (court and court.get("plan") == "monthly") else spec
        rec["studio_package"] = dict(old, variant=plan["kind"], package_name=plan["name"],
                                     hours=plan["hours"], term_days=plan["term_days"], mrr=old.get("mrr", spec["mrr"]),
                                     model="rolling", converted_at=datetime.utcnow().isoformat(),
                                     bucket_deadline=old.get("booking_deadline", ""), booking_deadline="")
        rec["product"] = plan["name"]
        ld = _deps.get("lead_data")
        if isinstance(ld, dict) and key:
            ld[key] = rec
        _deps["post_slack"](_deps["matt_channel"],
                            f"🔁 *{rec.get('name') or key}*: prepaid 12-hour package finished — from this charge on "
                            f"the account is the rolling *{plan['name']}* ({plan['monthly_hours']}h a month, holds up to "
                            f"{plan['cap_hours']}h)"
                            + (f" — courtesy upgrade, pays the {spec['name']} price" if plan is not spec else "")
                            + ". (#287)")
    except Exception as e:
        _report("studio.convert_bucket", e, f"key={key}")


def _on_invoice_paid(inv: dict, event_id: str) -> dict:
    """PATCH #278 — invoice.paid for a plan.

    subscription_cycle → the monthly top-up (that month's hours, capped at
    2 months' worth available; last bookable day = 30 days past the next
    charge). subscription_create / manual → a purchase that did NOT come
    through a checkout (a subscription or invoice made by hand in Stripe):
    run the same purchase pipeline a checkout would. Anything bought through
    a payment link is the checkout handler's, never provisioned twice."""
    inv = inv or {}
    reason = str(inv.get("billing_reason") or "")
    inv_id = str(inv.get("id") or "")
    sub_id, meta = _invoice_subscription(inv)
    sku = str((meta or {}).get("sku") or "")
    spec, qty, pend, pstart = None, 1, None, None
    for pid, q, pe, ps in _invoice_lines(inv):
        s_ = resolve_spec(pid, sku, "")
        if s_ and s_.get("plan"):
            spec, qty, pend, pstart = s_, q, pe, ps
            break
    if not spec:
        return {"handled": False, "reason": "not-a-plan", "event": event_id}
    email = str(inv.get("customer_email") or "").strip().lower()
    name = str(inv.get("customer_name") or "").strip() or email.split("@")[0].title()
    if not email:
        _report("studio.invoice_paid", "no email on invoice", f"invoice={inv_id}")
        return {"handled": False, "reason": "no-email", "event": event_id}

    if reason == "subscription_cycle":
        if spec["plan"] != "monthly":
            return {"handled": False, "reason": "not-monthly", "event": event_id}
        if _already_processed(f"topup:{inv_id}"):
            return {"handled": False, "reason": "duplicate", "event": event_id}
        # PATCH #287 — a client who prepaid the old 3-month bucket (12 h loaded on day
        # one: Camila Silveira and Maria Josefa, 17 Nov) is covered until that bucket's
        # deadline — the Dec and Jan charges are the bucket's own, nothing is added — and
        # the first charge whose period starts after the deadline turns the account into
        # the rolling plan (WP starts fresh once the old window has closed).
        _cov = _prepaid_bucket_covers(email, pstart)
        if _cov.get("covered"):
            # PATCH #290 — no hours, but the portal's 'Refreshes on …' moves to the next charge.
            if pend:
                try:
                    topup_portal_client(email, 0, ref=f"refresh:{inv_id}",
                                        next_refresh=datetime.fromtimestamp(int(pend), pytz.timezone(TIMEZONE)).date())
                except Exception as _tx:
                    _report("studio.refresh_touch", _tx, f"invoice={inv_id}")
            line = (f"💳 *{spec['name']}* charge paid by *{name}* ({email}) — covered by their prepaid "
                    f"{_cov.get('hours')}-hour package until {_cov.get('until')}; no hours added. Rolling "
                    f"monthly hours start with the first charge after that date. (#287)")
            _deps["post_slack"](_deps["matt_channel"], line)
            return {"handled": True, "event": event_id, "covered_until": _cov.get("until_iso"),
                    "package": spec["kind"]}
        if _cov.get("convert"):
            _convert_bucket_record(_cov["key"], _cov["rec"], spec)
        spec = _record_plan(email, spec)   # PATCH #288 — a courtesy plan's hours, not the price's
        if pend:
            end = datetime.fromtimestamp(int(pend), pytz.timezone(TIMEZONE)).date() \
                + timedelta(days=PLAN_TOPUP_WINDOW_DAYS)
        else:
            end = datetime.now(pytz.timezone(TIMEZONE)).date() + timedelta(days=PLAN_FIRST_WINDOW_DAYS)
        _next = datetime.fromtimestamp(int(pend), pytz.timezone(TIMEZONE)).date() if pend else None   # PATCH #290
        res = topup_portal_client(email, spec["monthly_hours"] * qty,
                                  cap_hours=spec["cap_hours"] * qty, end=end,
                                  ref=f"invoice:{inv_id}", next_refresh=_next)
        if res.get("ok") and res.get("found"):
            line = (f"🔁 *{spec['name']}* renewed: *{name}* ({email}) · "
                    f"+{res.get('added')}h → {res.get('available')}h available "
                    f"(holds up to {spec['cap_hours'] * qty}h) · books until {res.get('end_after')}")
        elif res.get("ok"):
            line = (f"🚨 *{spec['name']}* renewal paid by *{name}* ({email}) but they have NO "
                    f"portal account. Create it in WP (or /admin/studio-provision-custom).")
        else:
            line = (f"🚨 *{spec['name']}* renewal paid by *{name}* ({email}): the portal top-up "
                    f"FAILED ({res.get('raw')}). Add {spec['monthly_hours'] * qty}h by hand.")
        _deps["post_slack"](_deps["lara_channel"], line)
        _deps["post_slack"](_deps["matt_channel"], line)
        return {"handled": True, "event": event_id, "topup": res, "package": spec["kind"]}

    if reason in ("subscription_create", "manual"):
        try:
            import time as _t
            _t.sleep(int(_deps.get("invoice_defer_seconds", 20)))  # let the checkout land first
        except Exception:
            pass
        if _checkout_recent(email, spec["kind"]):
            return {"handled": False, "reason": "checkout-handled", "event": event_id}
        if reason == "subscription_create" and sub_id:
            try:
                ss = _deps["stripe_get"]("checkout/sessions", {"subscription": sub_id, "limit": 1})
                if (ss or {}).get("data"):
                    return {"handled": False, "reason": "checkout-handled", "event": event_id}
            except Exception as e:
                _report("studio.invoice_paid", e, f"invoice={inv_id} (checkout lookup)")
                return {"handled": False, "reason": "lookup-failed", "event": event_id}
        if _already_processed(f"invoice:{inv_id}"):
            return {"handled": False, "reason": "duplicate", "event": event_id}
        spec = _per_unit(spec, qty)
        _on_package_purchased(name, email, f"invoice:{inv_id}", spec)
        return {"handled": True, "event": event_id, "email": email, "package": spec["kind"],
                "via": "invoice"}

    return {"handled": False, "reason": f"billing_reason={reason or '?'}", "event": event_id}


def _on_package_purchased(name: str, email: str, event_id: str, spec: dict = None,
                          start=None):
    """Full purchase pipeline: portal account -> welcome email -> lead update -> alerts.

    PATCH #53 — `spec` defaults to the 3-month package, so the existing path is
    byte-for-byte unchanged when nothing passes one.
    """
    spec = spec or PACKAGES[STUDIO_PRICE_ID]
    first = name.split()[0] if name else "there"

    # 1 · Portal account (idempotent by email on the WP side)
    prov = provision_portal_client(name, email, spec, start=start)
    code = prov.get("access_code")
    term = prov.get("term") or {}

    # PATCH #278 — an existing portal client buying a plan or a service: WP
    # hands back no code for an account that exists, so the welcome email
    # would say "your code is being generated". Add the hours instead and tell
    # them so; the code they already have still works.
    topup = None
    if spec.get("plan") and prov.get("ok") and prov.get("existing"):
        topup = topup_portal_client(
            email, spec["hours"],
            cap_hours=spec.get("cap_hours") or 0,
            end=term.get("booking_deadline"), ref=f"buy:{event_id}",
            package=spec["name"] if spec["plan"] in ("monthly", "annual") else "",
            monthly_hours=spec.get("monthly_hours") or 0,
            next_refresh=(next_refresh_date(term["start"]) if spec["plan"] == "monthly" and term.get("start") else None))   # PATCH #290

    # PATCH #287 — a plan bought on an account whose booking window had closed
    # (WP: fresh_start) belongs to someone who has not logged in for a while:
    # rotate the code and send the full welcome with it, not "use the code you
    # already have" (Camila Silveira, 17 Nov: her July code, no email, no login).
    if (topup is not None and topup.get("ok") and topup.get("found") and topup.get("fresh_start")
            and spec.get("plan") in ("monthly", "annual")):
        _rot = provision_portal_client(name, email, spec, start=start, rotate_code=True)
        if _rot.get("access_code"):
            code = _rot["access_code"]
            topup["code_rotated"] = True
            topup["welcome"] = True

    # 2 · Welcome email (send even if provisioning degraded — portal team can resend code)
    email_ok = False
    try:
        if topup is not None and not topup.get("welcome"):
            email_ok = bool(_deps["send_email"](
                email, f"MWM Studios — your {spec['name']} hours are in your portal 🎬",
                _hours_added_email_html(first, spec, term, topup)))
        else:
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
            # PATCH #288 — matched by name and no email on file: keep the payer's, so the
            # monthly charges find this record (Camila, 17 Nov: matched by name, email empty).
            if _matched_on == "name" and email and not str(rec.get("email") or "").strip():
                rec["email"] = email
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
                            context=f"{spec['price_label']} · "
                                    + (plan_terms(spec) if spec.get("plan") else
                                       f"{spec['hours']}h/{term_phrase(spec)}") + " · "
                                    f"portal={'ok' if prov.get('ok') else 'FAILED'} · "
                                    f"welcome_email={'sent' if email_ok else 'FAILED'}")
    prov_note = ("✅ portal account ready" if prov.get("ok")
                 else "🚨 PORTAL PROVISIONING FAILED — create the account manually in WP")
    if topup is not None:
        prov_note = (f"✅ existing portal client: +{topup.get('added')}h added, "
                     f"{topup.get('available')}h available" if topup.get("ok") and topup.get("found")
                     else "🚨 existing portal client but the HOURS TOP-UP FAILED — add them in WP")
    mail_note = "✅ welcome email sent" if email_ok else "🚨 welcome email FAILED — send manually"
    # PATCH #53 — a one-month trial is a DIFFERENT event to the team than a
    # three-month contract: it is not recurring revenue, and it has a date on
    # which the upsell either happens or the client walks. Say so.
    _trial_note = ""
    if not spec["recurring"] and not spec.get("plan"):
        _trial_note = (f"\n⚠️ *This is the 1-month trial, not the 3-month package.* "
                       f"One-time {spec['price_label']} — *not MRR*. "
                       + (f"Their {spec['hours']}h run out *{_deadline_str}*, which is the "
                          f"window to convert them to the package." if _deadline_str else ""))
    _deps["post_slack"](_deps["matt_channel"],
        f"💳 *{spec['name'].upper()} PURCHASED* — {lead_name} ({email})\n"
        f"{spec['price_label']} · "
        + (plan_terms(spec) if spec.get("plan") else f"{spec['hours']}h over {term_phrase(spec)}")
        + (f" · books until {_deadline_str}" if _deadline_str else "") + "\n"
        f"{prov_note} · {mail_note}{_trial_note}\n"
        f"_LARA — please set up production tracking; client books sessions in the portal ({PORTAL_URL})_")
    _deps["post_slack"](_deps["lara_channel"],
        f"💳 New *{spec['name']}* client: *{lead_name}* ({email}) — "
        + (plan_terms(spec) if spec.get("plan") else f"{spec['hours']}h over {term_phrase(spec)}")
        + (f", last bookable day {_deadline_str}" if _deadline_str else "")
        + f". Portal: {PORTAL_URL} · {prov_note}")
    # PATCH #269 — callers that run this by hand want to know what happened.
    return {"portal_ok": bool(prov.get("ok")), "existing": bool(prov.get("existing")),
            "code_issued": bool(code), "welcome_email": bool(email_ok),
            "topup": topup}


def custom_spec(label, hours, start, end, price_label="", term_label="",
                interval="none", cycle_amount=0, cycles=0, pace_note="",
                includes_note="", extra_notes=None, kind="custom",
                ongoing=False, monthly_hours=0, footer_note="", first_session=None):
    """PATCH #269 — a package spec for ONE client's deal, built from the deal's
    own terms and never written into PACKAGES. Michael, Sat 7 Nov 2026, on
    Shawnie Whitaker's $350-a-week partner plan: "pretty much a custom build…
    an exception… not something that I want to make fixed among the other
    plans" — but "everything related to his studio client portal stays the
    same as a regular studio client portal… the hours, the email automation".
    So the deal runs through the standard pipeline (portal account, the
    regular welcome email, lead record, alerts) on a spec that exists only for
    this call. Nothing here is a product: Maya never sees it, the webhook
    never matches it, the canvas counts it as whatever package_by_name says.

    `start`/`end` are dates; `end` is the portal's last bookable day. Billing:
    interval "week" | "month" with cycle_amount and cycles → the footer lists
    the dates; "none" → a one-off, no footer. Returns (spec, term)."""
    days = (end - start).days
    if days < 1:
        raise ValueError("end must be after start")
    hours = int(hours)
    if hours < 1:
        raise ValueError("hours must be at least 1")
    interval = str(interval or "none").lower()
    cycle_amount = int(cycle_amount or 0)
    cycles = int(cycles or 0)
    recurring = interval in ("week", "month") and cycle_amount > 0 and cycles > 0
    if interval == "week":
        mrr = int(round(cycle_amount * 52 / 12.0))
    elif interval == "month":
        mrr = cycle_amount
    else:
        mrr = 0
    label = " ".join(str(label or "").split()) or "Custom studio plan"
    spec = {
        "kind": str(kind or "custom"),
        "name": label,
        "hours": hours,
        "term_days": days,
        "term_label": str(term_label or "").strip(),
        "grace_days": 0,                 # `end` IS the last bookable day
        "cycles": cycles if recurring else 0,
        "interval": interval if recurring else "none",
        "cycle_amount": cycle_amount if recurring else 0,
        "recurring": recurring,
        "mrr": mrr if recurring else 0,
        "one_off": 0 if recurring else cycle_amount,
        "price_label": str(price_label or "").strip() or label,
        "sheet_status": f"Client — {label}",
        "pace_note": str(pace_note or "").strip(),
        "includes_note": str(includes_note or "").strip(),
        "extra_notes": [str(n).strip() for n in (extra_notes or []) if str(n).strip()],
        "credits_toward_contract": False,
        "custom": True,
    }
    # PATCH #277 — an ongoing monthly plan and an already-booked first session.
    # Absent unless asked for, so every earlier spec renders exactly as before.
    if ongoing:
        spec["ongoing"] = True
        spec["monthly_hours"] = int(monthly_hours or 0)
        spec["footer_note"] = str(footer_note or "").strip()
    if first_session and str((first_session or {}).get("when") or "").strip():
        spec["first_session"] = {k: first_session.get(k) for k in
                                 ("title", "when", "time", "place", "notes")}
    return spec, package_term(spec, start)


def provision_custom(name, email, hours, start, end, label="Custom studio plan",
                     price_label="", term_label="", interval="none", cycle_amount=0,
                     cycles=0, pace_note="", includes_note="", extra_notes=None,
                     apply=False, ongoing=False, monthly_hours=0, footer_note="",
                     first_session=None):
    """PATCH #269 — run the standard purchase pipeline for a client on a custom
    deal (see custom_spec). Dry by default: returns the spec, the dates, the
    subject and the welcome email as it would read, and asks WP whether the
    account exists — creates nothing, sends nothing. With apply=True it is
    exactly what the Stripe webhook does for a package, once per (email,
    start): a second apply is answered "duplicate", because WP hands back no
    code for an account that exists and the client would get a welcome email
    with no way in. `start`/`end` are YYYY-MM-DD; start = the day they paid."""
    email = str(email or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": False, "error": "email required"}
    name = " ".join(str(name or "").split()) or email
    try:
        start_d = datetime.strptime(str(start or "").strip(), "%Y-%m-%d").date()
        end_d = datetime.strptime(str(end or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return {"ok": False, "error": "start and end must be YYYY-MM-DD"}
    try:
        spec, term = custom_spec(label, hours, start_d, end_d, price_label=price_label,
                                 term_label=term_label, interval=interval,
                                 cycle_amount=cycle_amount, cycles=cycles,
                                 pace_note=pace_note, includes_note=includes_note,
                                 extra_notes=extra_notes, ongoing=ongoing,
                                 monthly_hours=monthly_hours, footer_note=footer_note,
                                 first_session=first_session)
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    first = name.split()[0] if name else "there"
    out = {"ok": True, "dry": not apply, "email": email, "name": name,
           "spec": {k: v for k, v in spec.items() if k not in ("extra_notes", "first_session")},
           "first_session": spec.get("first_session"),
           "extra_notes": spec["extra_notes"],
           "term_start": term["start"].isoformat(),
           "booking_deadline": term["booking_deadline"].isoformat(),
           "billing_dates": [d.isoformat() for d in billing_dates(spec, start_d)],
           "subject": f"Welcome to MWM Studios — your {spec['name']} is active 🎬"}
    if not apply:
        probe = provision_portal_client(name, email, spec, dry_run=True, start=start_d)
        out["wp"] = {"status": probe.get("status"), "existing": probe.get("existing"),
                     "raw": probe.get("raw")}
        out["welcome_html"] = _welcome_email_html(first, "XXXXXX", spec, term)
        return out
    marker = f"manual:{email}:{term['start'].isoformat()}"
    if _already_processed(marker):
        out.update(ok=False, error="duplicate", marker=marker)
        return out
    out["result"] = _on_package_purchased(name, email, marker, spec, start=start_d)
    out["marker"] = marker
    return out


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

# PATCH #280 — the three emails above describe ONE product: the 3-month Studio
# Package ($1,200/mo). Ayodele Pompey (12 Nov) was pitched AI Pro and the
# recap would have quoted him the wrong plan at midnight. The sequence now
# records what the report said was pitched, sends only for the package it
# was written for, keeps office hours, and can be held for a lead who asked
# for time. Copy for the AI plans is a separate, Michael-approved change.
PITCH_SEQ_KINDS_WITH_COPY = ("studio_3mo",)
PITCH_SEQ_SEND_HOURS = (9, 18)      # ET, Mon-Fri


def pitch_package_kind(service) -> str:
    """'Studio Package' / '$1,200' -> studio_3mo · 'AI Pro' -> ai_pro · '' -> ''
    (unknown/legacy) · anything else -> other. Never guesses a plan from silence."""
    s = str(service or "").strip().lower()
    if not s:
        return ""
    if "ai pro" in s:
        return "ai_pro"
    if "ai growth" in s:
        return "ai_growth"
    if "ai starter" in s:
        return "ai_starter"
    if "trial" in s:
        return "studio_trial_1mo"
    if "studio package" in s or "3-month" in s or "3 month" in s or "1,200" in s or "1200" in s:
        return "studio_3mo"
    return "other"


def _now_et():
    return datetime.now(pytz.timezone(TIMEZONE))


def pitch_seq_in_hours(now_et=None) -> bool:
    """Mon-Fri, 9:00-17:59 ET. A pitch recap at 00:06 reads as a robot."""
    t = now_et or _now_et()
    return t.weekday() < 5 and PITCH_SEQ_SEND_HOURS[0] <= t.hour < PITCH_SEQ_SEND_HOURS[1]


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


def start_pitch_sequence(lead_key: str, rec: dict, service=None):
    """Called when outcome=studio_package_pitched is recorded.
    PATCH #280: `service` is what the report says was pitched."""
    try:
        rec["studio_pitch"] = {
            "date": datetime.utcnow().isoformat(),
            "next_stage": 0,
            "done": False,
            "package": str(service or "").strip()[:120],
            "kind": pitch_package_kind(service),
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
            # PATCH #280 — only the package the copy was written for. A record
            # armed before this patch has no `kind` -> unknown -> halted too.
            _kind = sp.get("kind")
            if _kind is None:
                _kind = pitch_package_kind(sp.get("package"))
            if _kind not in PITCH_SEQ_KINDS_WITH_COPY:
                sp["done"] = True
                sp["halted"] = {"at": now.isoformat(), "why": "no copy for this package",
                                "package": sp.get("package") or "", "kind": _kind or "unknown"}
                _deps["post_slack"](_deps["matt_channel"],
                    f"\U0001F4E6 \u23F8 Studio pitch follow-up for *{rec.get('name', key)}* HALTED before "
                    f"the first email — the written sequence describes the 3-month Studio Package "
                    f"($1,200/mo) and the report says: {sp.get('package') or 'no package recorded'}. "
                    f"Nothing was sent. Michael: follow up personally, or ask DEV for copy for this plan.")
                continue
            _hold = sp.get("hold_until")
            if _hold:
                try:
                    if now < datetime.fromisoformat(str(_hold)):
                        continue
                except ValueError:
                    pass
            if not pitch_seq_in_hours():
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
