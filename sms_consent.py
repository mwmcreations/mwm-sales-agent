"""
sms_consent.py — PATCH #109. The bridge that was never built.

WHAT THIS EXISTS TO FIX
───────────────────────
On 27 Aug 2026 the A2P campaign was approved: five weeks, eight submissions,
four Twilio agents. The whole point of that fight was SMS re-engagement.

Then /health said would_send: false, and the reason was ours, not Twilio's.
The opt-in form at /sms-signup/ writes consent into a MySQL table on
WordPress. _sms_gates reads consent out of pg_store on Railway. Nothing
carried a row from one to the other, so every lead failed the consent gate —
the same gate we spent five weeks proving to Twilio that we honour. The
machine was built correctly and had nothing plugged into it.

This module is the policy half of that bridge: normalise a WordPress ledger
row into a consent record, decide which of two records wins, and decide
whether a given re-engagement touch is allowed to travel over SMS. It is pure
— no network, no pg_store, no Flask — so every rule below is testable without
a Twilio account or a WordPress install.

THE TWO RULES THAT MATTER MOST
──────────────────────────────
1. A REVOKE IS NEVER LOST. merge() will not let an older "yes" overwrite a
   newer "no" no matter which order the rows arrive in, and treats an
   unreadable timestamp on the incoming row as "do not overwrite". A missed
   opt-in costs us one lead. A missed opt-out costs us the brand.

2. RE-ENGAGEMENT IS MARKETING. The 7-touch sequence is promotional, so
   should_fallback_to_sms() requires the MARKETING checkbox, not merely the
   transactional one. A lead who ticked "appointment reminders" and nothing
   else has not agreed to be chased, and the fact that we hold a valid
   number for them does not change that.
"""

import calendar
import re
from datetime import datetime

# Reasons the primary channel is genuinely unreachable. SMS is a FALLBACK —
# it exists to keep a sequence alive when WhatsApp or Instagram has died, not
# to add a second message to a lead we can already reach. Anything not in this
# set means the primary channel still works, and SMS must stay out of it.
DEAD_PRIMARY = (
    "ig_window_expired",   # Instagram's 7-day messaging window closed
    "ig_403",              # Instagram refused the send, window closed
    "wa_invalid_phone",    # quarantined by S6.6 as not E.164-sendable
    "wa_send_failed",      # Meta accepted nothing after retries
)

_PLACEHOLDER_TS = ("", "0", "none", "null", "n/a")


# ── phone ──────────────────────────────────────────────────────────────────

def to_e164(raw):
    """'(407) 871-6473' -> '+14078716473'. None when it can never be a target.

    Mirrors maya_actions.normalize_wa_phone's rules deliberately — the two
    must agree or a lead is reachable on one channel and invisible on the
    other — but returns the leading '+', because that is what the Twilio
    Messages API and the pg_store consent key both use."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower().startswith("instagram:"):
        return None            # an IG-scoped id is not a phone number
    digits = re.sub(r"\D", "", s.replace("whatsapp:", ""))
    if len(digits) == 10:
        digits = "1" + digits  # bare US number
    if 11 <= len(digits) <= 14 and not digits.startswith("0"):
        return "+" + digits
    return None


# ── timestamps ─────────────────────────────────────────────────────────────

_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
)


def ts_epoch(value):
    """Tolerant timestamp -> epoch seconds, or None if it cannot be read.

    None is not a failure to paper over: merge() treats an unreadable
    incoming timestamp as a reason NOT to overwrite. Better a stale record
    than a wrong one."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s.lower() in _PLACEHOLDER_TS:
        return None
    s = s.replace("Z", "").split("+")[0].split(".")[0].strip()
    for fmt in _TS_FORMATS:
        try:
            # UTC, explicitly. The WordPress ledger stamps created_at with
            # gmdate(), and .timestamp() on a naive datetime would read it in
            # whatever timezone the container happens to run in — which is not
            # the app's TIMEZONE and not guaranteed to be UTC either. The
            # watermark we send back to WordPress is derived from these values,
            # so a silent offset here would skip a window of consents on every
            # poll and nobody would see it.
            return float(calendar.timegm(datetime.strptime(s, fmt).timetuple()))
        except ValueError:
            continue
    return None


# ── ledger row -> consent record ───────────────────────────────────────────

def row_to_record(row):
    """One row of wp_mwm_sms_consent -> the record _sms_gates reads.

    Returns None when the row cannot be trusted to mean anything: no usable
    phone, or no readable timestamp. Both are silent-corruption risks — a
    record with no time cannot be ordered against a revoke."""
    if not isinstance(row, dict):
        return None
    phone = to_e164(row.get("phone_e164") or row.get("phone")
                    or row.get("mwm_phone") or row.get("number"))
    if not phone:
        return None
    ts = ts_epoch(row.get("ts") or row.get("created_at") or row.get("time"))
    if ts is None:
        return None

    txn = _truthy(row.get("transactional", row.get("txn", row.get("mwm_txn", 0))))
    mkt = _truthy(row.get("marketing", row.get("mkt", row.get("mwm_mkt", 0))))
    revoked = _truthy(row.get("revoked", 0))

    # Neither box ticked is a real, recorded outcome: the reviewer's own test
    # case. It is an explicit "no", not a missing row.
    status = "yes" if (txn or mkt) and not revoked else "no"

    return {
        "phone": phone,
        "status": status,
        "marketing": bool(mkt) and not revoked,
        "transactional": bool(txn) and not revoked,
        "source": str(row.get("source") or "form")[:40],
        "context": str(row.get("source_url") or row.get("context") or "")[:300],
        "ts": ts,
    }


def _truthy(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


# ── which record wins ──────────────────────────────────────────────────────

def merge(existing, incoming):
    """Return the record that should be stored. Never loses a revoke.

    Ordering is by timestamp, not arrival: the WordPress ledger is polled, so
    rows can and do arrive out of order after an outage."""
    if not incoming:
        return existing
    if not existing:
        return incoming

    t_in = incoming.get("ts")
    t_ex = existing.get("ts")
    if t_in is None:
        return existing            # unreadable incoming never overwrites
    if t_ex is None:
        return incoming            # anything readable beats nothing
    if t_in > t_ex:
        return incoming
    if t_in < t_ex:
        return existing
    # Same instant, two rows. Prefer the more restrictive one — a "no" and a
    # "yes" stamped in the same second is not a tie we should resolve in our
    # own favour.
    return existing if existing.get("status") == "no" else incoming


# ── may this touch travel over SMS? ────────────────────────────────────────

def should_fallback_to_sms(primary_dead_reason, consent, sent_this_month,
                           monthly_cap):
    """(ok, reason). Deliberately hard to satisfy.

    Every refusal names itself so the checker can log a skip instead of an
    error — a lead we are not allowed to text is a normal outcome, not a
    fault, and must not reach the error bus."""
    if primary_dead_reason not in DEAD_PRIMARY:
        return False, "primary_channel_alive"
    if not consent:
        return False, "no_consent_record"
    if consent.get("status") != "yes":
        return False, "consent_not_yes"
    if not consent.get("marketing"):
        # Transactional-only consent. They agreed to hear about a booking
        # they made, not to be re-engaged.
        return False, "transactional_consent_only"
    try:
        if int(sent_this_month) >= int(monthly_cap):
            return False, "monthly_cap"
    except (TypeError, ValueError):
        return False, "monthly_cap_unreadable"   # fail closed
    return True, "ok"


# ═══════════════════════════════════════════════════════════════════════════
# PATCH #112 — a confirmation is not a promotion
# ═══════════════════════════════════════════════════════════════════════════
# Two public pages describe the same programme and they do not agree.
#
#   /sms-opt-in/  (12 Aug 2026, written for carrier review) collects TWO
#                 separate consents and caps only marketing at 4/month.
#   /terms/ §19   (last touched January 2026, before the A2P submission)
#                 bundles both into one sentence and caps EVERYTHING at 4.
#
# One studio booking is a confirmation plus a three-rung reminder ladder. Under
# §19 as written that is the entire month, so a client who books twice goes
# silent mid-ladder. Until §19 is corrected the machine obeys the STRICTER of
# the two: a public promise we break costs more than a text we withhold.
#
# This function is where that choice lives, and it is pure so the choice can
# be proven both ways without a Twilio account.

KIND_TRANSACTIONAL = "transactional"
KIND_MARKETING     = "marketing"


def policy(kind, split_live, cap_bundled, cap_marketing,
           quiet_marketing, quiet_transactional):
    """Rules for one kind of message.

    kind                 "transactional" | "marketing". ANYTHING ELSE IS
                         TREATED AS MARKETING — the stricter path. A caller
                         who mistypes a kind is refused, never over-permitted.
    split_live           True once /terms/ §19 matches /sms-opt-in/.
    cap_bundled          the single cap §19 promises today (4).
    cap_marketing        the marketing-only cap /sms-opt-in/ promises (4).
    quiet_*              (start_hour, end_hour) tuples.

    Returns {kind, consent_field, quiet_start, quiet_end, cap, counter_field,
             split_live}. cap None means uncapped, which is only ever reachable
    for transactional AND only once split_live is True.
    """
    if kind == KIND_TRANSACTIONAL:
        return {
            "kind": KIND_TRANSACTIONAL,
            "consent_field": "transactional",
            "quiet_start": int(quiet_transactional[0]),
            "quiet_end": int(quiet_transactional[1]),
            "cap": None if split_live else int(cap_bundled),
            # Split or not, the combined counter is always kept as well, so
            # flipping the flag can never hand anyone a fresh allowance.
            "counter_field": ("monthly_count_transactional" if split_live
                              else "monthly_count"),
            "split_live": bool(split_live),
        }
    return {
        "kind": KIND_MARKETING,
        "consent_field": "marketing",
        "quiet_start": int(quiet_marketing[0]),
        "quiet_end": int(quiet_marketing[1]),
        "cap": int(cap_marketing) if split_live else int(cap_bundled),
        "counter_field": ("monthly_count_marketing" if split_live
                          else "monthly_count"),
        "split_live": bool(split_live),
    }
