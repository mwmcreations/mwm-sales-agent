"""info_inbox.py — the watcher on info@mwmcreations.com.

WHY THIS EXISTS
---------------
Aug 20 2026, Michael: a lead emailed info@ asking to change his studio visit.
He found it only because he happened to open a mailbox he does not normally
open, then handed it to Maya, who fixed it in minutes.

    "Those kind of emails can be there for days without me looking at it."

That is a client-facing channel with no rail on it, and its failure mode is
indistinguishable from a quiet inbox. Closing out that night he was explicit
about what he wanted instead:

    "I like the idea that the machine can take care of those emails and check
     those instead of having to wait for a human connection and rely on myself
     to check those emails. I trust much more on the machine to do that
     automatically."

Delegation and forwarding only move WHERE he has to look. This removes the
looking.

WHAT WAS ACTUALLY BLOCKING IT — AND WHAT WASN'T
----------------------------------------------
On the night of the 20th I told him the machine had send-only Gmail access and
that reading info@ needed an admin change. **That was wrong.** On the morning
of the 21st we opened the Admin console together and the service account
already carried gmail.readonly — it had for who knows how long. I had inferred
the GRANT from the CODE's requested scope, which is backwards, and it is the
second time that exact error has cost this project time (Patch #69 was the
same shape: DWD was granted all along and the code never used it).

So the only real blocker was one line: GMAIL_SCOPES asked for send only.

The other open question was whether info@ could be impersonated at all —
susan_gmail.py:46 asserts "info@ is a send-as alias, not a user account".
**Also false.** Michael logged into info@ on Aug 21: it has its own Inbox,
Sent, Drafts and settings. It is a real Workspace user, so DWD impersonation
is available.

READ-ONLY, AND WHY THAT IS NOT NEGOTIABLE HERE
----------------------------------------------
This mailbox is where clients write to the business. A reader that returns
nothing is an annoyance; a reader that marks mail read, archives it, or
replies is a business incident. Every fetch uses format="metadata" or
BODY-safe reads and nothing here calls modify, trash, send or batchModify.
test_info_inbox.py greps this file for those verbs and fails if one appears.

Reading a message never marks it seen: we never call users.messages.modify,
and Gmail only clears UNREAD when you ask it to.
"""

import os
import re

INFO_ADDRESS = os.getenv("INFO_INBOX_ADDRESS", "info@mwmcreations.com")

# ── who is NOT a person needing attention ───────────────────────────
# Calibrated against what actually lands in this mailbox (see §S90 in
# DEV.md and the calibration digest). The rule is deliberately asymmetric:
# a missed lead costs a booking, a false alert costs one line in Slack. When
# unsure, ALERT.
_INTERNAL_DOMAINS = ("mwmcreations.com", "mwmscreens.com", "mwmfilms.tv")

_ROBOT_SENDER_RE = re.compile(
    r"(?i)(no[-_.]?reply|do[-_.]?not[-_.]?reply|donotreply|notifications?@|"
    r"alerts?@|mailer|postmaster|bounce|automated|support@twilio\.zendesk|"
    r"@dsbackend\.com|@stripe\.com|@railway\.app|@wordpress|@sentry\.|"
    r"@google\.com|@accounts\.google|@calendar-notification|@docusign|"
    r"@intuit\.com|@quickbooks|@godaddy|@namecheap|@cloudflare|"
    # Added after the 21 Aug calibration run. It scored `ignore` live only
    # because the real address happens to contain "noreply"; the digest
    # truncated it and the test fixture guessed wrong. Naming TestFlight and
    # Apple's mailer explicitly makes that an intended rule rather than a
    # lucky one — developer noise is never client mail.
    r"via testflight|@email\.apple\.com|@testflight)")

_ROBOT_SUBJECT_RE = re.compile(
    r"(?i)(unsubscribe|newsletter|your receipt|payment (received|of)|"
    r"invoice #|security alert|sign-?in|verify your|password reset|"
    r"is now available|has been updated automatically|"
    r"player.{0,12}offline|deployment|build (failed|succeeded))")

# ── what makes an email URGENT rather than merely human ─────────────
# These are the words that appeared in the email that started all this.
# NOTE THE `(?:\w+\s+){0,3}` — it is there because the FOUNDING EXAMPLE failed
# without it. The lead wrote about changing his "studio visit", and a pattern
# requiring "change my visit" adjacent scored that as a routine enquiry. The
# one email this whole rail exists for must come out URGENT, and words get
# put between the verb and the noun constantly: "change my studio visit",
# "move our Thursday session", "cancel the podcast recording".
_URGENT_RE = re.compile(
    r"(?i)(\breschedul\w*|\bre-?schedule|"
    r"\b(change|move|switch|shift|push|swap)\s+(my|the|our)\s+(?:\w+\s+){0,3}"
    r"(booking|appointment|session|time|date|visit|slot|shoot|recording)|"
    r"\bcancel\w*|\bpostpone|can'?t make it|cannot make it|won'?t make it|"
    r"\brunning late|\bdouble[- ]book\w*|\brefund|\bcomplain\w*|"
    r"\burgent\b|\basap\b|\bemergency\b)")

_BOOKING_RE = re.compile(
    r"(?i)\b(book\w*|appointment|studio (visit|session|time)|availability|"
    r"available|schedule|quote|pricing|price|rate|how much|interested in|"
    r"consultation|shoot|record\w*|podcast)\b")


def is_internal(address):
    a = str(address or "").lower()
    return any(a.endswith("@" + d) or a.endswith("." + d) for d in _INTERNAL_DOMAINS)


def looks_automated(sender, subject):
    """True when this is a robot, not a person.

    Both the address and the subject get a vote, because plenty of robots
    write from a human-looking address and plenty of humans write from a
    shared one.
    """
    s = str(sender or "")
    if _ROBOT_SENDER_RE.search(s):
        return True
    if _ROBOT_SUBJECT_RE.search(str(subject or "")):
        return True
    return False


PRIORITY_URGENT = "urgent"     # a booking is moving, or somebody is unhappy
PRIORITY_LEAD = "lead"         # a person asking about work
PRIORITY_HUMAN = "human"       # a person, subject unclear
PRIORITY_IGNORE = "ignore"     # robot, or us

PRIORITY_ORDER = {PRIORITY_URGENT: 0, PRIORITY_LEAD: 1,
                  PRIORITY_HUMAN: 2, PRIORITY_IGNORE: 9}


def classify(sender, subject, snippet=""):
    """(priority, why). Pure — no network, no clock.

    ASYMMETRIC ON PURPOSE. Anything from a real person that is not obviously
    a robot comes back as at least PRIORITY_HUMAN, even when the subject says
    nothing useful. The email that started this said only "change my studio
    visit" — a keyword list tuned to catch exactly that and nothing else would
    have missed the next one, which will be worded differently.
    """
    addr = _address_of(sender)
    if is_internal(addr):
        return PRIORITY_IGNORE, "from our own domain"
    if looks_automated(sender, subject):
        return PRIORITY_IGNORE, "automated sender or notification subject"
    subj = str(subject or "")
    snip = str(snippet or "")

    # ── CALIBRATION, 21 Aug, off the real mailbox ────────────────
    # The first live run scored Whitney Aronoff's "Re: Thursday is postponed —
    # please stand down" as URGENT. Her actual message was "Noted. Thank you!"
    # — an acknowledgement. The word "postponed" was MICHAEL'S, echoed back in
    # the Re: subject.
    #
    # ⭐ On a reply, the subject line is OUR words, not theirs. So urgency on a
    # "Re:" is judged from the SNIPPET — what the client actually wrote. The
    # subject still counts for lead signals, because "Re: Confirming your
    # session" genuinely is about a booking; it just is not evidence that
    # anything is going wrong.
    _is_reply = bool(re.match(r"(?i)^\s*(re|fwd?|enc)\s*:", subj))
    _urgent_field = snip if _is_reply else ("%s %s" % (subj, snip))

    if _URGENT_RE.search(_urgent_field):
        return PRIORITY_URGENT, (
            "the client's own words mention a change, cancellation or complaint"
            if _is_reply else
            "mentions a booking change, cancellation or complaint")
    if _BOOKING_RE.search("%s %s" % (subj, snip)):
        return PRIORITY_LEAD, "about a booking, availability or pricing"
    return PRIORITY_HUMAN, "a person wrote to us and it is not obviously routine"


def _address_of(sender):
    """Pull the bare address out of a From header."""
    m = re.search(r"<([^>]+)>", str(sender or ""))
    return (m.group(1) if m else str(sender or "")).strip().lower()


def needs_attention(priority):
    return priority in (PRIORITY_URGENT, PRIORITY_LEAD, PRIORITY_HUMAN)


# ── reading the mailbox ─────────────────────────────────────────────
# Everything below touches the network. The classifier above does not, which
# is why the tests can exercise the judgement without a credential.

ERR_NOT_CONFIGURED = "not_configured"
ERR_AUTH = "auth_failed"
ERR_IMPERSONATION = "impersonation_refused"
ERR_SCOPE = "scope_missing"
ERR_UNKNOWN = "unknown"

MAX_FETCH = 25


def diagnose(exc):
    """(kind, sentence). The remedies share nothing, so neither should the
    diagnosis. 'unauthorized_client' means the DWD grant does not cover the
    scope we asked for; 'Precondition check failed' usually means the subject
    is not an impersonable user."""
    t = str(exc or "").lower()
    if "unauthorized_client" in t or "not authorized" in t:
        return ERR_SCOPE, (
            "Domain-wide delegation refused the scope. Check that the service "
            "account client carries gmail.readonly in Admin → Security → API "
            "controls → Domain-wide delegation, AND that GMAIL_SCOPES in the "
            "code actually asks for it — those are two different things, and "
            "confusing them has cost this project time twice.")
    if "precondition check failed" in t or "invalid_grant" in t:
        return ERR_IMPERSONATION, (
            f"Could not impersonate {INFO_ADDRESS}. That address must be a "
            f"real Workspace user, not a group or an alias.")
    if "insufficient" in t or "insufficientpermissions" in t:
        return ERR_SCOPE, "The token lacks read permission on this mailbox."
    return ERR_UNKNOWN, f"{type(exc).__name__}: {exc}"


def _header(payload, name):
    for h in (payload.get("headers") or []):
        if str(h.get("name", "")).lower() == name.lower():
            return h.get("value", "")
    return ""


def fetch_recent(service, limit=MAX_FETCH, query="in:inbox"):
    """Recent messages as light dicts. METADATA ONLY — never the body.

    format="metadata" is deliberate on two counts. It cannot mark anything
    read, and it keeps a client's private correspondence out of logs and out
    of an agent's context. The snippet Gmail returns is enough to classify;
    if a human needs the rest, they open the mail.
    """
    out = []
    listing = service.users().messages().list(
        userId="me", q=query, maxResults=int(limit)).execute()
    for ref in (listing.get("messages") or []):
        try:
            m = service.users().messages().get(
                userId="me", id=ref["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date", "To"]).execute()
        except Exception:
            continue          # one unreadable message must not stop the sweep
        p = m.get("payload") or {}
        out.append({
            "id": m.get("id"),
            "thread_id": m.get("threadId"),
            "from": _header(p, "From"),
            "to": _header(p, "To"),
            "subject": _header(p, "Subject"),
            "date": _header(p, "Date"),
            "snippet": m.get("snippet") or "",
            "unread": "UNREAD" in (m.get("labelIds") or []),
        })
    return out


def triage(messages):
    """Classify a batch and sort worst-first. Pure."""
    rows = []
    for m in (messages or []):
        pri, why = classify(m.get("from"), m.get("subject"), m.get("snippet"))
        r = dict(m)
        r["priority"] = pri
        r["why"] = why
        rows.append(r)
    rows.sort(key=lambda r: (PRIORITY_ORDER.get(r["priority"], 9),
                             r.get("date") or ""))
    return rows


def describe(row):
    """One Slack block for a single message. Pure."""
    badge = {PRIORITY_URGENT: "🔴 *NEEDS A REPLY NOW*",
             PRIORITY_LEAD: "🟡 *Possible lead*",
             PRIORITY_HUMAN: "⚪ *A person wrote in*"}.get(
                 row.get("priority"), "· ")
    return ("%s — %s\n*%s*\n_%s_\n`%s`"
            % (badge,
               (row.get("from") or "?")[:70],
               (row.get("subject") or "(no subject)")[:120],
               re.sub(r"\s+", " ", row.get("snippet") or "")[:220],
               row.get("why", "")))
