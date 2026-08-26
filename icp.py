#!/usr/bin/env python3
"""icp.py — S31. Who we are for, in one place.

MICHAEL, 25 AUGUST 2026
-----------------------
    "We have been receiving a lot of musicians, content creators that it's not
    the fit. We are one hundred percent aiming for small businesses. Let's put
    that as our rule. We wanna reach small business owners."

WHY THIS IS A MODULE AND NOT A SENTENCE IN A PROMPT
---------------------------------------------------
The rule already existed in three places and was enforced in none of them.
MAYA.md §51 carried it from 29 July — "declining the number is not enough, the
booking must not happen" — and lived only in an agent notebook that no code
reads, so for twelve days nothing enforced it. Patch #74 finally put a gate in
code after a hobbyist musician took a 10 AM studio hour.

Meanwhile the WhatsApp prompt says "business owners and entrepreneurs", the
shared knowledge says "not film sets or hobbyist creators", and the WEBSITE
prompt asks "What type of content are you looking to create?" — a question that
presupposes a creator and tells a plumber he is in the wrong place. Three
statements of the same policy, drifting apart, one of them recruiting exactly
the people the other two exclude.

So the rule lives here once, and every prompt imports it. A test asserts the
prompts contain it and do not contain the language that contradicts it. That is
the only way a policy survives contact with four prompts and a language model.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not classify anyone automatically. ERIC asked for a disqualification
reason that is REVERSIBLE, because Michael may change the rule. A model guessing
"not a business owner" from one message, and writing that verdict permanently
onto a lead, would be the confident-and-wrong failure this board keeps finding.
A human or an explicit statement marks it; anyone can unmark it.
"""

# ── the rule, as prompt text ────────────────────────────────────────────────

ICP_RULE = """
WHO WE ARE FOR — STANDING RULE, set by Michael on 25 August 2026.
MWM Creations & Studios sells to SMALL BUSINESS OWNERS: founders, owner-
operators, professionals and trades who need video to win customers.
Realtors, dentists, lawyers, contractors, clinics, restaurants, gyms, agencies,
local service businesses.

We are NOT for hobbyists, aspiring musicians, personal content creators or
people building a personal brand with no business behind it. They are not bad
people and they are not to be treated rudely — they are simply not who this
studio is built for.

HOW THIS CHANGES WHAT YOU SAY:
- Open on the BUSINESS, never on content. Your first substantive question is
  about what they do for a living and what they want more of.
- NEVER ask "what kind of content do you create?", "what type of content are
  you looking to create?", or any variant that assumes the person is a creator.
  That question tells a plumber he is in the wrong place and invites a hobbyist
  to stay. It is the single most expensive sentence in this conversation.
- If someone has no business — they are a hobbyist, a student, or building a
  personal brand — be warm, be brief, and do not offer a studio visit.
"""

# The question that replaces the creator-framed one. One line, does three jobs:
# assumes a business, disqualifies a hobbyist without insulting them, and
# returns routing intent. ERIC's wording, kept because it is good.
OPENING_QUESTION = (
    "What's your business, and what are you trying to get more of — "
    "customers, bookings, or people knowing you exist?"
)

# Language that must never appear in a prompt again. The guard test greps for
# these; that is what stops the rule quietly rotting back.
BANNED_OPENERS = (
    "what type of content are you looking to create",
    "what type of content do you help create",
    "what kind of content do you create",
    "what kind of content are you creating",
)

# ── disqualification, reversible by construction ────────────────────────────

REASON_NOT_TARGET_MARKET = "not_target_market"
REASON_BUDGET = "below_floor"
REASON_UNQUALIFIED_CALL = "unqualified_founder_call"
REASON_NOT_A_FIT = "not_a_fit"

DISQUALIFY_REASONS = (
    REASON_NOT_TARGET_MARKET,
    REASON_BUDGET,
    REASON_UNQUALIFIED_CALL,
    REASON_NOT_A_FIT,
)

REASON_LABELS = {
    REASON_NOT_TARGET_MARKET: "Not our target market (not a small business owner)",
    REASON_BUDGET: "Below the price floor",
    REASON_UNQUALIFIED_CALL: "Unqualified founder call",
    REASON_NOT_A_FIT: "Not a fit",
}


def mark_disqualified(lead, reason, at=None, by="", note=""):
    """Record WHY a lead was closed. Returns the mutated lead dict.

    Stored as a block rather than a boolean so it can be undone: clearing it
    restores the lead completely. ERIC asked for reversible and meant it —
    Michael may widen the rule again next month, and a permanent verdict
    written by a model on one message is exactly the mistake to avoid.
    """
    if lead is None or reason not in DISQUALIFY_REASONS:
        return lead
    lead["disqualified"] = {
        "reason": reason,
        "label": REASON_LABELS.get(reason, reason),
        "at": at,
        "by": by or "",
        "note": (note or "")[:500],
    }
    return lead


def clear_disqualified(lead):
    """Undo. The whole point of the block above."""
    if lead is not None:
        lead.pop("disqualified", None)
    return lead


def is_disqualified(lead, reason=None):
    d = (lead or {}).get("disqualified")
    if not isinstance(d, dict):
        return False
    return True if reason is None else d.get("reason") == reason


def disqualified_reason(lead):
    d = (lead or {}).get("disqualified")
    return d.get("reason") if isinstance(d, dict) else None


# ── the measurement ERIC actually needs ─────────────────────────────────────

def business_coverage(leads):
    """What fraction of leads we can even name the business of.

    ERIC: "I can price a conversation but not tell you what fraction were even
    the right kind of person." Cost per conversation cannot distinguish a
    working filter from a broken one — this can. Reported, not guessed.
    """
    total = named = disq = 0
    unnamed = []
    for key, lead in (leads or {}).items():
        total += 1
        if is_disqualified(lead):
            disq += 1
        if ((lead or {}).get("business") or "").strip():
            named += 1
        else:
            unnamed.append(key)
    return {
        "total": total,
        "with_business": named,
        "without_business": total - named,
        "disqualified": disq,
        "coverage_pct": round(100.0 * named / total, 1) if total else 0.0,
        "sample_unnamed": unnamed[:10],
    }
