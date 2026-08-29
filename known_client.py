"""
known_client.py — PATCH #110. A client is not a lead.

WHAT HAPPENED
─────────────
26 Aug 2026: Jaysee Soto of Altamonte Family Hearing bought a Studio Package —
$1,200/month, twelve hours, first shoot booked for 23 September. CLIENT WON.

29 Aug 2026, 11:56: the machine posted "PIPELINE: NEW LEAD — Bald Hearing Guy,
Altamonte Family Hearing, Instagram DM, Stage: New, Assigned: Maya, Eric."

He messaged us from Instagram. Instagram is a different sender key from the
WhatsApp number and the email his client record was built on, so `is_new_sender`
was true and the new-lead path ran exactly as designed. Nothing errored. The
machine simply had no way to know it had already sold to this person.

WHY THAT IS EXPENSIVE, NOT MERELY UNTIDY
────────────────────────────────────────
Left alone, a paying client walks the whole prospect path: Maya pitches him a
package he already owns, at 24h of silence he is added to the re-engagement
queue, at 48h he is marked Cold, and then he receives "still thinking about our
studio?" three days after paying $1,200. Eric may also spend retargeting budget
on him.

Patch #34 already settled the principle for the canvas — "being a client
outranks having an appointment". This extends the same principle across
CHANNELS: being a client outranks arriving on a new one.

THE BIAS OF THIS MODULE
───────────────────────
A false positive here is worse than the bug it fixes. Wrongly deciding a
genuine new lead is an existing client would drop a real prospect out of the
pipeline silently — the one failure mode nobody would notice. So every rule
below is deliberately strict:

  · business names match only on EXACT normalised equality, never substrings,
    and only when the name carries at least two meaningful words. "Studio" or
    "Hearing" alone can never match anything.
  · emails match exactly.
  · phones match on the last ten digits.
  · a person's name is NEVER a match on its own. There is more than one
    Michael.

And on a match the caller must not silently drop the lead — see
app.py, which posts an EXISTING_CLIENT event instead of NEW_LEAD. The card
still appears; it just says the true thing.
"""

import re

# Dropped from business names before comparison: legal form, not identity.
_LEGAL_SUFFIXES = {
    "llc", "l.l.c", "inc", "incorporated", "corp", "corporation", "co",
    "ltd", "limited", "pllc", "pc", "pa", "lp", "llp", "plc", "gmbh", "sa",
}
_NOISE = {"the", "and", "of", "a", "an", "&"}

# A normalised business name must carry at least this many meaningful words
# before it is allowed to identify anybody. One-word names are too collidable.
MIN_BUSINESS_TOKENS = 2


def normalize_business(value):
    """'Altamonte Family Hearing, LLC' -> 'altamonte family hearing'.

    Returns "" when the name is too thin to identify anyone — which callers
    must treat as "no match possible", never as a match against other ""."""
    if not value:
        return ""
    s = str(value).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split()
              if t and t not in _LEGAL_SUFFIXES and t not in _NOISE]
    if len(tokens) < MIN_BUSINESS_TOKENS:
        return ""
    return " ".join(tokens)


# Instagram profile names routinely carry the business after a location pin:
# "Bald Hearing Guy \U0001f4cdAltamonte Family Hearing". That is exactly the string
# the 29 Aug card printed, and the ONLY place the business appeared — there was
# no separate business field on the record. Without reading it, this whole
# module would have looked correct and matched nothing.
#
# The text after a pin is a place or a business, never a person's name, so
# reading it does not weaken the "never match on a name" rule. It still has to
# clear normalize_business()'s two-meaningful-word bar to identify anybody.
_PIN_MARKERS = ("\U0001f4cd", ":round_pushpin:", "\U0001f4cc")


def business_from_name(value):
    """Pull a business out of a display name that carries a location pin.
    Returns "" when there is no pin, or what follows it is too thin."""
    if not value:
        return ""
    s = str(value)
    for marker in _PIN_MARKERS:
        if marker in s:
            return normalize_business(s.split(marker, 1)[1])
    return ""


def normalize_email(value):
    if not value:
        return ""
    s = str(value).strip().lower()
    return s if "@" in s and "." in s.split("@")[-1] else ""


# Free/consumer mail providers. An address at one of these says nothing about
# which business a person belongs to, so its domain must never identify anyone.
_FREE_MAIL = {
    "gmail", "googlemail", "hotmail", "outlook", "live", "msn", "yahoo",
    "ymail", "icloud", "me", "mac", "aol", "proton", "protonmail", "gmx",
    "mail", "comcast", "verizon", "att", "sbcglobal", "bellsouth", "zoho",
}


def domain_key(email):
    """'jsoto@altamontefamilyhearing.com' -> 'altamontefamilyhearing'.

    The studio portal's client roster carries name, email and package — but
    not the company. For a business client the email domain usually IS the
    company, which is what lets a roster entry be matched against a business
    name seen somewhere else entirely. Returns "" for consumer providers and
    for anything too short to be distinctive."""
    e = normalize_email(email)
    if not e:
        return ""
    host = e.split("@")[-1]
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return ""
    # Drop the TLD (and a second-level country TLD such as .co.uk).
    if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) <= 3:
        stem = parts[-3]
    else:
        stem = parts[-2]
    if stem in _FREE_MAIL or len(stem) < 6:
        return ""
    return re.sub(r"[^a-z0-9]", "", stem)


def squash(normalized_business):
    """'altamonte family hearing' -> 'altamontefamilyhearing', so a business
    name can be compared against an email domain, which has no spaces."""
    return re.sub(r"[^a-z0-9]", "", normalized_business or "")


def phone_key(value):
    """Last ten digits — enough to match across +1 / no-country-code forms.
    Instagram-scoped ids are refused: they are not phone numbers."""
    if not value:
        return ""
    s = str(value)
    if s.lower().startswith("instagram:"):
        return ""
    digits = re.sub(r"\D", "", s.replace("whatsapp:", ""))
    return digits[-10:] if len(digits) >= 10 else ""


def is_client_record(rec):
    """The single definition of 'this record is a paying client'.

    Mirrors Patch #34's canvas rule so the two can never disagree: outcome
    Won, or a product on the record, or a status that already says client."""
    if not isinstance(rec, dict):
        return False
    if str(rec.get("outcome", "")).strip().lower() == "won":
        return True
    if str(rec.get("product", "")).strip():
        return True
    status = " ".join(str(rec.get(k, "")) for k in ("status", "stage", "wa_status"))
    return "client" in status.lower()


def build_client_index(records):
    """Index every paying client we hold, by the things that identify a
    person across channels. Records is any iterable of lead dicts."""
    index = {"businesses": set(), "emails": set(), "phones": set()}
    for rec in records or []:
        if not is_client_record(rec):
            continue
        b = normalize_business(rec.get("business"))
        if b:
            index["businesses"].add(b)
        pinned = business_from_name(rec.get("name"))
        if pinned:
            index["businesses"].add(pinned)
        e = normalize_email(rec.get("email"))
        if e:
            index["emails"].add(e)
        p = phone_key(rec.get("phone"))
        if p:
            index["phones"].add(p)
        # Squashed forms, so a spaced business name can meet an email domain.
        for form in (b, pinned):
            if form:
                index.setdefault("squashed", set()).add(squash(form))
        d = domain_key(rec.get("email"))
        if d:
            index.setdefault("squashed", set()).add(d)
    index.setdefault("squashed", set())
    return index


def match_known_client(candidate, index):
    """(matched, reason). Strongest, least ambiguous signal wins.

    Returns (False, "no_match") whenever anything is uncertain — an empty
    normalisation never matches, because "" is not evidence of sameness."""
    if not isinstance(candidate, dict) or not index:
        return False, "no_match"

    e = normalize_email(candidate.get("email"))
    if e and e in index.get("emails", ()):
        return True, "email"

    p = phone_key(candidate.get("phone"))
    if p and p in index.get("phones", ()):
        return True, "phone"

    b = normalize_business(candidate.get("business"))
    if b and b in index.get("businesses", ()):
        return True, "business:%s" % b

    # The business as written into an Instagram display name.
    pinned = business_from_name(candidate.get("name"))
    if pinned and pinned in index.get("businesses", ()):
        return True, "business_in_name:%s" % pinned

    # Last resort — and the one that makes the portal roster usable. The roster
    # carries an email but no company, so "Altamonte Family Hearing" seen on
    # Instagram is compared against the stem of jsoto@altamontefamilyhearing.com.
    # Both sides must still have cleared the two-meaningful-word bar to exist.
    squashed = index.get("squashed") or set()
    for form, label in ((b, "business_domain"), (pinned, "name_domain")):
        sq = squash(form)
        if sq and len(sq) >= 8 and sq in squashed:
            return True, "%s:%s" % (label, sq)

    d = domain_key(candidate.get("email"))
    if d and d in squashed:
        return True, "email_domain:%s" % d

    return False, "no_match"
