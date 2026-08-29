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


def normalize_email(value):
    if not value:
        return ""
    s = str(value).strip().lower()
    return s if "@" in s and "." in s.split("@")[-1] else ""


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
        e = normalize_email(rec.get("email"))
        if e:
            index["emails"].add(e)
        p = phone_key(rec.get("phone"))
        if p:
            index["phones"].add(p)
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

    return False, "no_match"
