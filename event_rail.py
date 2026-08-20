"""
event_rail.py — Event Confirmation Rail (Patch #30: S-1, S-2, and the S-6 refusal half)

Spec: Memory/Event_Confirmation_Rail_Spec.md

WHY THIS MODULE EXISTS
----------------------
Four separate code paths create calendar events, and each one configured
reminders differently (or not at all):

    A  app.py  book_appointment()              — Maya studio visits / strategy calls
    B  app.py  handle_tool_call/create_calendar_event — Maya command path
    C  app.py  /webhook/studio-booking         — WP portal, PAID bookings
    D  ana_calendar.py  create_event()         — ANA

Path C had no reminders, no location and no attendee at all — the client's
email lived in description text only, so no calendar mail could reach him even
in principle (Todd Berger, portal booking #56, Jul 27).

Rather than patch four write-sites four different ways, every path now funnels
its event body through ONE gate: harden_event_body(). Fix the gate, fix all four.

This module deliberately has no imports from app.py. app.py and ana_calendar.py
both import it; putting the helpers in app.py would create a circular import.

DESIGN NOTES THAT ARE EASY TO GET WRONG
---------------------------------------
* An Instagram-scoped ID (IGSID) is 16-17 digits and is NOT a phone number.
  Meta rejects it with error 131009. It must never reach the WhatsApp API.
  Historically it did, because it was written into the phone field with a "+1"
  bolted on (`+1046947537903616`) and everything downstream trusted it.

* The source channel must be resolved from the IDENTIFIER, never from a label
  and never from a default parameter value. `book_appointment` used to carry
  `booked_via="WhatsApp"` as a default, so every caller that omitted the
  argument stamped "WhatsApp" on the event regardless of the real thread.
  Spec §2.4 forbids exactly this. When identifier and label disagree, the
  identifier wins.

* strict=True REJECTS. It is intended only for the LARA production-shoot path.
  Paid portal bookings and live Maya conversations create-and-report instead:
  refusing a booking a client has already paid for, over an unparseable
  address, is the worse outcome. Every issue is reported either way — strict
  only decides whether we also stop.
"""

import os
import re
import unicodedata
# Patch #58 needs real datetime parsing for approval slots. Stdlib only —
# this module still imports nothing from app.py, which is the rule that
# keeps it testable and free of circular imports.
from datetime import datetime

import pytz


# ══════════════════════════════════════════════════════════════════════
# PATCH #60 — THE CLOCK. One definition of "now", in the studio's timezone.
#
# Rodolfo Silva is a booked client. At 07:55 ET on Aug 6 he was sent
# "checking in … if the timing isn't right, tell me and I'll stop following
# up." His T+2d step was due at 11:47 ET. It fired at 11:55 UTC — 3h52m
# early, which is exactly the offset.
#
# The cause is that TWO clocks were in play and nobody had ever put them
# side by side:
#
#   * `armed_at` is written offset-aware, in LOCAL time  ("…T11:47-04:00")
#   * `outcome_sender._pass()` took `datetime.now()` — naive, and on Railway
#     the container runs UTC, so that is a naive UTC wall clock.
#
# The sender then did `armed.replace(tzinfo=None)`, which THROWS THE OFFSET
# AWAY rather than converting, leaving a naive LOCAL time. Subtracting a
# naive local time from a naive UTC time silently adds four hours to every
# elapsed-time calculation. Every timed client send in this system has been
# landing up to four hours early.
#
# The same naive-UTC `now` was handed to within_send_window(), so the 8 AM
# floor that exists specifically to stop pre-breakfast client sends was
# comparing 11 (UTC) against 8 and passing. At 07:55 ET. The guard was not
# merely bypassed — it was reading a different clock than the one it was
# written to protect.
#
# The tell that this went unnoticed for so long: /admin/lead-seq computes
# elapsed correctly (aware, `pytz.timezone(TIMEZONE)`), so the DIAGNOSTIC and
# the SENDER have been quietly disagreeing. The diagnostic said "due 11:47
# AM ET" and it was right. Any check that reads the diagnostic will keep
# saying the rail is healthy while the rail messages people at dawn.
#
# So: one clock, defined here, in the module both the sender and the rail
# already import. Naive-local is kept as the wire format because every
# stored `sent[].at` and every test in the suite is naive — converting the
# stored records would be a migration, and this is a timing bug, not a
# schema one.
# ══════════════════════════════════════════════════════════════════════

LOCAL_TZ_NAME = os.getenv("TIMEZONE", "America/New_York")   # Orlando, Florida
try:
    LOCAL_TZ = pytz.timezone(LOCAL_TZ_NAME)
except Exception:                                            # pragma: no cover
    LOCAL_TZ = pytz.timezone("America/New_York")


def to_local_naive(dt):
    """Any datetime → the same INSTANT as a naive wall clock in LOCAL_TZ.

    An offset-aware value is CONVERTED, not stripped. `.replace(tzinfo=None)`
    on an aware datetime keeps the digits and discards the meaning, which is
    the exact move that made a UTC-stored timestamp read as a local one.

    A naive value is passed through unchanged: it is already on the wire
    format this module uses, and guessing that it "must be UTC" would break
    every stored record written before this patch.
    """
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.astimezone(LOCAL_TZ)
    return dt.replace(tzinfo=None)


def local_now():
    """Wall-clock time in the studio's timezone, naive.

    Use this instead of `datetime.now()` anywhere a client-facing decision
    is made. On a UTC host `datetime.now()` is a UTC wall clock wearing no
    label, which is indistinguishable from a local one until it messages
    somebody at 4 AM.
    """
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)

# ── S-2 · the standard reminder block ────────────────────────────────
# Every client-facing event gets all three, set at creation, on every path.
STANDARD_REMINDERS = [
    {"method": "email", "minutes": 1440},   # T-24h
    {"method": "email", "minutes": 60},     # T-60m
    {"method": "popup", "minutes": 30},     # T-30m
]

# Channel constants — use these, do not retype the strings.
CH_INSTAGRAM = "Instagram"
CH_WHATSAPP = "WhatsApp"
CH_WEB = "Website Chat"
CH_EMAIL = "Email"
CH_UNKNOWN = "Unknown"

# E.164 allows at most 15 digits. An IGSID is 16-17. That gap is the whole test.
_E164_MAX_DIGITS = 15
_IGSID_MIN_DIGITS = 16


class EventRailRejected(Exception):
    """Raised by harden_event_body(strict=True) when an event fails validation."""

    def __init__(self, issues, context=""):
        self.issues = list(issues)
        self.context = context
        super().__init__(f"event rejected [{context}]: " + "; ".join(self.issues))


# ── identifier shape ─────────────────────────────────────────────────

def digits_of(identifier):
    """Every digit in the identifier, prefixes and punctuation removed."""
    if identifier is None:
        return ""
    s = str(identifier)
    for prefix in ("instagram:", "whatsapp:", "ig:", "web:"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    return re.sub(r"\D", "", s)


def is_ig_scoped(identifier):
    """True if this identifier is an Instagram-scoped ID, not a phone number.

    Two ways to be sure:
      1. it carries an explicit instagram:/ig:/@ marker, or
      2. it has more digits than E.164 permits (>15).

    The digit-count test is what catches the legacy `+1046947537903616`
    records, where the prefix had already been stripped and a "+1" added,
    making an IGSID look like a US phone number to anything doing a naive
    string check.
    """
    if identifier is None:
        return False
    s = str(identifier).strip()
    if not s:
        return False
    low = s.lower()
    if low.startswith("instagram:") or low.startswith("ig:") or s.startswith("@"):
        return True
    return len(digits_of(s)) >= _IGSID_MIN_DIGITS


def is_dialable(identifier):
    """True if this identifier can plausibly be an E.164 destination.

    Deliberately permissive on the low end (short test numbers exist) and
    hard on the high end, because the high end is where the IGSID bug lives.
    """
    if identifier is None:
        return False
    if is_ig_scoped(identifier):
        return False
    d = digits_of(identifier)
    return 7 <= len(d) <= _E164_MAX_DIGITS


# PATCH #46B — CH_WEB's display value is "Website Chat", which is correct as
# a SOURCE ("this lead arrived via the website chat") and wrong as a
# DESTINATION. The rail uses CH_WEB for the EMAIL delivery path, so the armed
# line in Michael's report read "T+2d nudge via Website Chat" for a touch that
# is an email to the client's inbox. We do not operate a website chat widget.
# Source labels and delivery labels are different things; keep them apart.
_DELIVERY_LABELS = {
    CH_WEB: "email",
    CH_EMAIL: "email",
    CH_WHATSAPP: "WhatsApp",
    CH_INSTAGRAM: "Instagram DM",
    CH_UNKNOWN: "a named human (no automated channel)",
}


def delivery_label(channel):
    """How to describe where a step will ACTUALLY land, for a human reader."""
    return _DELIVERY_LABELS.get(channel, str(channel))


def resolve_channel(identifier, hint=None):
    """Resolve the true source channel FROM THE IDENTIFIER.

    `hint` is whatever the caller believed the channel was. It is used only
    when the identifier is uninformative. When identifier and hint disagree,
    THE IDENTIFIER WINS — that is the entire point of spec §2.4.
    """
    if identifier is not None:
        s = str(identifier).strip()
        low = s.lower()
        if low.startswith("web:"):
            return CH_WEB
        if is_ig_scoped(s):
            return CH_INSTAGRAM
        if is_dialable(s):
            return CH_WHATSAPP
        if "@" in s:
            return CH_EMAIL
    if hint:
        return str(hint)
    return CH_UNKNOWN


REMINDER_CHANNELS = {
    "email":    "Email — always works, and it is what carries the calendar invite",
    "whatsapp": "WhatsApp — only if you know they actually use it",
}


def reminder_channel_for(identifier, email=None, stated=None):
    """Which rail can actually reach this person? Returns (channel, why).

    channel is one of "whatsapp" / "instagram" / "email" / None.
    None means UNREMINDABLE — that is a hard S-1 failure, not a warning.

    🔑 S85 — A STATED CHANNEL BEATS THE INFERENCE, ALWAYS.
    `is_dialable()` answers "could this number be phoned." It was being read
    as "this person is on WhatsApp." For a lead who ARRIVED on WhatsApp that
    is sound — they messaged us there, so we have proof. For a booking
    Michael typed into /book it is a guess, and on Aug 11 it guessed wrong:
    Shelley Roxanne's US mobile made the rail write "Reminder channel:
    whatsapp" for a client who is email and SMS only.

    Evidence beats inference. When somebody who knows the client says which
    rail to use, that answer wins outright — but only if the rail can
    actually carry it, so a stated email with no address on file still falls
    through to the honest answer rather than promising a send we cannot make.
    """
    if stated:
        st = str(stated).strip().lower()
        if st == "whatsapp" and is_dialable(identifier):
            return "whatsapp", "stated by the person who booked it"
        if st == "email" and email and ascii_email(email)[1]:
            return "email", "stated by the person who booked it"
        # a stated channel we cannot actually carry falls through to the
        # resolver below rather than being asserted and silently failing

    if is_dialable(identifier):
        return "whatsapp", "dialable E.164 identifier"
    if is_ig_scoped(identifier):
        if email and ascii_email(email)[1]:
            return "email", "IG-scoped identifier — WhatsApp impossible, falling back to email"
        return None, ("IG-scoped identifier with no email on file — "
                      "structurally unremindable (Meta rejects IGSID with 131009)")
    if email and ascii_email(email)[1]:
        return "email", "no usable phone identifier, email on file"
    return None, "no resolvable reminder channel"


# ══════════════════════════════════════════════════════════════════════
# PATCH #61 — ONE KEY FOR THE PHONE COLUMN
#
# MATT's finding, Aug 6: Instagram has produced 90 active leads, four
# calendar-verified bookings, and ZERO rows that ever read "Booked" — in the
# entire history of this pipeline — while WhatsApp books and renders
# correctly on the same night.
#
# It is not the canvas and it is not a backlog. Six functions match a lead
# against the sheet's Phone column, and they do NOT agree on what a match is:
#
#   log_new_contact_to_sheets   row[4] == clean_phone          exact
#   log_lead_to_sheets          row[4] == clean_phone          exact
#   update_booking_in_sheets    row[4] == clean_phone          exact
#   lookup_lead_in_sheets       endswith, >= 7 digits          suffix
#   update_lead_columns         re.sub(\\D,'',row) == clean     DIGITS
#
# For an Instagram thread `sender` is "instagram:<IGSID>", and that whole
# string — prefix included — is what gets written into the Phone cell. The
# exact matchers therefore work: name, business and email all land, which is
# why IG leads look present and healthy on the canvas.
#
# update_lead_columns strips the digits out of the CELL and compares them to
# the UNSTRIPPED sender. "1586517099782001" == "instagram:1586517099782001"
# is false, every time, for every Instagram lead that has ever existed. It
# then finds no row and returns SILENTLY.
#
# And update_lead_columns is the only writer of exactly four columns:
#
#       Status · WhatsApp Status · Appointment Booked · Lead Temperature
#
# `Appointment Booked` is what the canvas reads to decide `stage = "Booked"`.
# So an Instagram lead can be booked on the calendar, confirmed, reminded,
# and sat in the studio, and the pipeline will still say "Contacted" —
# because the one function that would have said otherwise could not find her
# row and said nothing about it.
#
# The fix is one comparison, defined once, applied to BOTH SIDES of every
# match. It deliberately does NOT change what is written into the cell: the
# "instagram:" prefix is the only thing in the sheet that stops a 16-digit
# IGSID being read by a human as a phone number, and Meta rejects an IGSID
# sent to WhatsApp with error 131009.
# ══════════════════════════════════════════════════════════════════════

_SHEET_KEY_PREFIXES = ("whatsapp:", "instagram:", "messenger:", "ig:", "fb:")


def sheet_row_key(value):
    """Normalise EITHER a sender key OR a Phone cell to one comparable form.

    Must be applied to both sides of a comparison. Applying it to one side
    only is the bug this function exists to end.

    Returns "" for anything that cannot identify a row — a blank cell, a
    stray label, a digit residue too short to be real. An empty key must
    never match, because a Phone cell that was merely empty once matched
    every caller alive (the Prime Vacation identity contamination, S24).
    """
    s = str(value or "").strip().lower()
    for _p in _SHEET_KEY_PREFIXES:
        if s.startswith(_p):
            s = s[len(_p):]
            break
    s = s.lstrip("+").strip()
    if s.startswith("web:"):
        # Web-chat leads are keyed by email address, not by digits. Stripping
        # to digits would collapse every one of them to "" — i.e. to each other.
        return "web:" + s[4:].strip()
    if "@" in s:
        return s
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) >= 7 else ""


# ══════════════════════════════════════════════════════════════════════
# PATCH #63 — A BLOCK MUST CARRY THE MARK USED TO FIND IT AGAIN
#
# The pipeline canvas has 362 duplicate "Active Leads" blocks, ~16M
# characters, growing by roughly one block every 28-minute sync. MATT could
# not read it in one call this morning. It has been diagnosed twice as a
# missing "S54-ACTIVE-LEADS" anchor. That anchor never existed. Here is what
# actually happened.
#
# `_replace_table_section()` is a DELETE-then-INSERT cycle, and it has been
# correct since S5.6:
#
#     for sid in _canvas_lookup_ids(_CANVAS_FINGERPRINTS[name]):
#         delete sid
#     insert fresh block after the header
#
# The delete half depends entirely on a fingerprint — a literal string that
# Slack's `canvases.sections.lookup` searches for — matching text inside the
# block that was inserted last cycle. For Active Leads that fingerprint is:
#
#     "active_leads": "Days in Stage"
#
# Patch #34 renamed that column. Its own comment explains why, and it was the
# right call: the number was never days-in-stage, it was the lead's age, and
# the wrong header made a healthy pipeline look stuck. The header became
# "Lead Age (d)".
#
# Nothing linked the header to the fingerprint. They are 600 lines apart, in
# different functions, and no test crossed them. So from Patch #34 onward the
# lookup matched ZERO sections, the delete loop deleted nothing, and the
# insert ran anyway — every 28 minutes, forever. Delete-then-insert quietly
# degraded into append.
#
# The other four sections are fine, and that is the corroboration: their
# fingerprints still appear in their payloads, and only Active Leads
# duplicates. One renamed string, 362 blocks.
#
# The fix is not "correct the string" — that repairs this instance and leaves
# the trap armed for the next person who improves a column header. The fix is
# that the block CARRIES ITS OWN MARK: `_replace_table_section` stamps every
# block it inserts, and looks for that stamp when deleting. The mark is
# generated from the section name, so it cannot drift from the payload — the
# same function produces both.
#
# Legacy fingerprints are still swept, or the 362 orphans already on the
# canvas would be unreachable forever.
# ══════════════════════════════════════════════════════════════════════

CANVAS_SYNC_PREFIX = "sync-id:"


def canvas_sync_mark(name):
    """The stamp that identifies a synced canvas block, from its section name.

    Plain text on purpose, and underscores are folded to hyphens. Slack's
    `contains_text` search matches the RENDERED text of a section, so
    anything markdown might eat — a backtick, a bracket, an underscore that
    pairs with another one into emphasis — is a fingerprint that works until
    it doesn't. This whole patch exists because a fingerprint stopped
    matching and nothing said so; the replacement is not going to depend on
    how a renderer feels about punctuation.
    """
    return f"{CANVAS_SYNC_PREFIX} {str(name or '').strip().replace('_', '-')}"


def canvas_stamp_block(name, markdown):
    """Return `markdown` guaranteed to contain its own section's mark.

    Idempotent: stamping twice does not double-stamp. For a fenced code block
    the mark goes INSIDE the fence, because a section lookup has to find it in
    the same node that gets deleted — a mark outside the fence identifies a
    different section from the one being cleaned up, which is a subtler
    version of the exact bug this patch exists to end.
    """
    mark = canvas_sync_mark(name)
    md = markdown if isinstance(markdown, str) else str(markdown or "")
    if mark in md:
        return md
    stripped = md.rstrip()
    if stripped.endswith("```"):
        return stripped[:-3].rstrip("\n") + "\n" + mark + "\n```"
    return stripped + "\n" + mark


def canvas_block_is_findable(name, markdown):
    """True when a block can be found again by the mark used to delete it.

    This is the invariant Patch #34 broke without anyone noticing. Inserting
    a block you cannot later look up is not a cosmetic problem — it is an
    unbounded append, and it has cost this canvas 16 million characters.
    """
    return canvas_sync_mark(name) in (markdown or "")


# ══════════════════════════════════════════════════════════════════════
# PATCH #66 — THE MACHINE COULD NOT TELL MICHAEL ANYTHING BY EMAIL
#
# Patch #58 built an out-of-hours approval door: when a lead asks for a time
# outside business hours, Maya files a real request and EMAILS Michael one tap
# per option. Email was chosen deliberately — #matt has never carried a human
# message from him, and WhatsApp to his own number bounces on expired windows.
#
# It has never delivered a single approval. Not once.
#
# `email_is_suppressed()` (Patch #38/#44A) reads:
#
#     if e in INTERNAL_EMAILS or e.endswith("@mwmcreations.com"):
#         return True, "internal address"
#
# and `MICHAEL_EMAIL` is `michael@mwmcreations.com`. So every approval email
# was refused before it was sent, `email_ok()` correctly returned False, and
# the alarm fired — every ten minutes, six times an hour, all night. Andrea
# Battis has been waiting three days for an answer to a request that was filed
# correctly and could never reach anybody.
#
# 🔴 THE GUARD ITSELF IS RIGHT AND MUST NOT BE WEAKENED. It exists because
# MATT asked a yes/no on Aug 1 — could the scheduler email Michael's daughter
# as a lead? — and the answer was yes. That must stay impossible.
#
# So this is NOT a bypass. It is a separate, ALLOW-LISTED channel: operator
# notifications may go to a fixed, tiny set of addresses and to nobody else.
# A lead cannot be reached through it even if a caller passes a lead's address,
# because the address must be on the list rather than merely absent from a
# blocklist. Deny-by-default, not allow-by-default — the difference between
# the two is this entire patch.
#
# DNC still outranks the allow-list. Yasmin Moraes is on INTERNAL_EMAILS *and*
# on EMAIL_DNC as a test lead; if a future edit ever widens the operator set to
# INTERNAL_EMAILS, DNC has to be what stops her being emailed anyway.
# ══════════════════════════════════════════════════════════════════════


def operator_allowed(addr, operators, dnc=None):
    """(allowed: bool, reason: str) — may an OPERATOR notification go here?

    Deny by default. An address must appear in `operators` to be reachable.

    Order matters and is deliberate:
      1. unparseable  → refuse (fail closed, same posture as the lead guard)
      2. on DNC       → refuse EVEN IF on the operator list. Do-not-contact is
                        a promise to a person; an internal label never overrides
                        it. This is the line that keeps a test lead who is also
                        an "internal" address unreachable.
      3. not on the operator list → refuse. This is what makes the channel safe
                        to exempt from the @mwmcreations.com rule at all.
    """
    e = str(addr or "").strip().lower()
    if not e or "@" not in e:
        return False, "unparseable address"
    _ops = {str(o or "").strip().lower() for o in (operators or []) if str(o or "").strip()}
    _dnc = {str(d or "").strip().lower() for d in (dnc or []) if str(d or "").strip()}
    if e in _dnc:
        return False, "on do-not-contact — DNC outranks the operator list"
    if e not in _ops:
        return False, "not an operator address (allow-list is deny-by-default)"
    return True, ""


# ══════════════════════════════════════════════════════════════════════
# PATCH #69 — A CLIENT IS NOT A LEAD, AND DNC WAS ANSWERING BOTH QUESTIONS
#
# Marcia Cardim booked a studio session through the portal on Aug 7. She is a
# paying client with an event on Aug 12. Her booking reminders — T-168h,
# T-48h, T-24h, T-2h — route through `_email_send`, which calls
# `email_is_suppressed`, and `ediasm@icloud.com` is on EMAIL_DNC.
#
# She was put there for a good reason: she became a client and must not
# receive LEAD follow-ups. But one list is now answering two questions:
#
#     "may the machine market to this person?"        → correctly NO
#     "may the machine confirm the booking they made?" → wrongly NO
#
# This is the third time in two days that suppression has conflated distinct
# audiences. #66/#68 was lead-mail vs OPERATOR mail. This is lead-mail vs
# CLIENT TRANSACTIONAL mail. The pattern is the lesson: a blocklist that
# cannot say WHY it is blocking will eventually block the wrong thing.
#
# Same remedy as #68 — an explicit allow-list, deny by default, and a hard
# never-contact tier that outranks everything. Yasmin Moraes is a TEST lead
# on EMAIL_DNC; she must remain unreachable by every path including this one.
# Marcia is a client with a real booking; she must get her reminders.
# ══════════════════════════════════════════════════════════════════════


def transactional_allowed(addr, allowed, never_contact=None):
    """(decision, reason) for CLIENT TRANSACTIONAL mail — confirmations and
    reminders for something the person actually booked.

    Returns one of three decisions, and the three-way answer is the point:

      "allow"   — explicitly on the transactional allow-list. Send it even if
                  the lead-DNC list would otherwise refuse.
      "block"   — unparseable, or on the hard never-contact tier. Never send,
                  no matter which flag the caller passed.
      "default" — nothing special about this address; fall through to the
                  ORDINARY suppression check. Most clients land here, and
                  that is correct: the allow-list is an exception mechanism,
                  not a replacement for the guard.

    Deliberately NOT a boolean. A two-way answer would force every caller to
    decide what "no" meant, and "never contact" and "not special, ask the
    normal rules" are answers that must not be confused.
    """
    e = str(addr or "").strip().lower()
    if not e or "@" not in e:
        return "block", "unparseable address"
    _never = {str(n or "").strip().lower() for n in (never_contact or []) if str(n or "").strip()}
    _ok = {str(a or "").strip().lower() for a in (allowed or []) if str(a or "").strip()}
    if e in _never:
        return "block", "on the never-contact tier — outranks every allow-list"
    if e in _ok:
        return "allow", "client transactional allow-list"
    return "default", "no transactional exception — ordinary suppression applies"


# ── attendee address ─────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def ascii_email(addr):
    """Return (ascii_form, ok, note).

    Google Calendar's attendee field rejects non-ASCII local parts. The live
    case was `andersonbritobáez@gmail.com` — the invite silently failed and the
    lead got no calendar mail.

    We fold the accent (NFKD, drop combining marks) to produce a deliverable
    ASCII form, and the caller records BOTH forms on the event so the original
    is never lost.
    """
    if not addr:
        return "", False, "no email"
    raw = str(addr).strip().strip("<>").strip()
    folded = unicodedata.normalize("NFKD", raw)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    try:
        folded.encode("ascii")
    except UnicodeEncodeError:
        folded = folded.encode("ascii", "ignore").decode("ascii")
    if not _EMAIL_RE.match(folded):
        return folded, False, f"not a valid address after ASCII folding: {raw!r}"
    if folded != raw:
        return folded, True, f"non-ASCII folded: {raw!r} -> {folded!r}"
    return folded, True, ""


# ── location ─────────────────────────────────────────────────────────

def looks_like_address(location):
    """Cheap postal-address sanity check.

    Not a geocoder — we are catching EMPTY and catching "TBD", not validating
    deliverability. Five for five of the events audited on Jul 29 (Anderson,
    Ehmcke, Rafael, Dondrique, Berger) had a completely empty location, so the
    bar here only has to be above zero to be worth having.
    """
    if not location:
        return False
    s = str(location).strip()
    if len(s) < 8:
        return False
    if s.lower() in {"tbd", "n/a", "na", "none", "-", "--", "tba", "online", "remote"}:
        return False
    has_digit = any(c.isdigit() for c in s)
    has_words = len([t for t in re.split(r"[\s,]+", s) if t]) >= 2
    return has_digit and has_words


# ── S-1 · the one gate ───────────────────────────────────────────────

def harden_event_body(body, source_identifier=None, attendee_email=None,
                      context="", strict=False, reporter=None,
                      default_location=None, channel_hint=None,
                      require_attendee=True, require_postal=True, stated_reminder_channel=None):
    """Validate and repair a Google Calendar event body in place.

    Returns (body, issues). `issues` is a list of human-readable strings; an
    empty list means the event passed clean.

    What it enforces (spec S-1):
      * a non-empty, plausible `location`
      * an ASCII-safe attendee address, actually present in `attendees` —
        not merely mentioned in the description
      * a resolvable reminder channel
      * a source channel read from the identifier, never a label or a default

    What it repairs (spec S-2):
      * the standard reminder block, unless the caller set one explicitly

    strict=True raises EventRailRejected instead of returning issues.
    reporter, if given, is called as reporter(context, summary, detail) so the
    caller's existing #dev error bus carries the report. A rail that cannot
    report its own failure is worse than no rail.
    """
    body = dict(body or {})
    issues = []
    notes = []

    # ── source channel, resolved from the identifier ──
    channel = resolve_channel(source_identifier, hint=channel_hint)
    if channel_hint and channel != CH_UNKNOWN and str(channel_hint) != channel:
        notes.append(f"source channel corrected: label said {channel_hint!r}, "
                     f"identifier says {channel!r}")
    if channel == CH_UNKNOWN:
        issues.append("source channel could not be resolved from the identifier")

    # ── location ──
    loc = (body.get("location") or "").strip()
    if not loc and default_location:
        loc = str(default_location).strip()
        notes.append(f"location defaulted to {loc!r}")
    if not loc:
        issues.append("location is empty")
    elif require_postal and not looks_like_address(loc):
        # require_postal=False is for events that genuinely have no street
        # address — a phone strategy call, a video call. Those still need a
        # non-empty location saying so; they just must not be measured against
        # a postal-address shape. Flagging every phone call forever would be
        # the cry-wolf failure this rail exists to avoid.
        issues.append(f"location does not look like a postal address: {loc!r}")
    if loc:
        body["location"] = loc

    # ── attendee ──
    if attendee_email:
        ascii_form, ok, note = ascii_email(attendee_email)
        if not ok:
            issues.append(f"attendee address unusable: {note}")
        else:
            if note:
                notes.append(note)
            existing = body.get("attendees") or []
            have = {str(a.get("email", "")).lower() for a in existing if isinstance(a, dict)}
            if ascii_form.lower() not in have:
                existing.append({"email": ascii_form})
            body["attendees"] = existing
            if str(attendee_email).strip() != ascii_form:
                # Keep the original visible; the folded form is what Google gets.
                notes.append(f"original attendee address preserved in description: "
                             f"{str(attendee_email).strip()}")
    elif require_attendee:
        issues.append("no attendee address supplied — "
                      "a client not on the attendee list cannot be reached by calendar mail")

    # ── reminder channel ──
    rchan, rwhy = reminder_channel_for(source_identifier, attendee_email,
                                       stated=stated_reminder_channel)
    if rchan is None:
        issues.append(f"no resolvable reminder channel: {rwhy}")
    elif rchan != "whatsapp":
        notes.append(f"reminder channel = {rchan} ({rwhy})")

    # ── S-2 reminder block ──
    rem = body.get("reminders")
    if not isinstance(rem, dict) or rem.get("useDefault") or not rem.get("overrides"):
        body["reminders"] = {"useDefault": False, "overrides": [dict(r) for r in STANDARD_REMINDERS]}
        if isinstance(rem, dict) and rem.get("overrides"):
            notes.append("reminder block replaced with the standard block")

    # ── stamp what we resolved — PRIVATELY ──
    # S87: this block used to be appended to the description, which Google
    # renders in full to every guest. Michael found `Sales rail: OFF` and a
    # list of creation issues sitting in a client's invite. Nothing has ever
    # read this stamp back — it is write-only diagnostics — so it moves to
    # extendedProperties.private, where our own reads still see it and the
    # attendee never does.
    _priv = (body.get("extendedProperties") or {}).get("private") or {}
    _priv["source_channel"] = str(channel)[:300]
    _priv["reminder_channel"] = str(rchan or "NONE — UNREMINDABLE")[:300]
    _priv["reminder_why"] = str(rwhy or "")[:300]
    if notes:
        _priv["rail_notes"] = "; ".join(notes)[:300]
    if issues:
        _priv["rail_issues"] = "; ".join(issues)[:300]
    body.setdefault("extendedProperties", {})["private"] = _priv

    # ── report ──
    if issues and reporter:
        try:
            reporter(
                f"event_rail.{context or 'unknown'}",
                f"{len(issues)} validation issue(s) on event {body.get('summary', '(no title)')!r}",
                " | ".join(issues),
            )
        except Exception:
            pass   # a failing reporter must never block a booking

    if issues and strict:
        raise EventRailRejected(issues, context=context)

    return body, issues


# ── Patch #31 · S-3/S-5 · EVENT CLASSIFICATION ───────────────────────
# The Jul 29 backfill dry run scanned 69 future events and flagged all 69.
# Only 16 were client events. The other 53 were TREINO EMS gym sessions,
# BLOQUEADO travel blocks and VICTORY TV admin reminders — flagged by the
# same rules, but not client events at all.
#
# That is why REPAIR and NUDGE need a filter and AUDIT does not:
#   audit everything      -> over-auditing is noise
#   repair only clients   -> over-repairing is DATA CORRUPTION
# Running ?apply=1 without this would have stamped the studio's postal
# address onto 53 of Michael's gym sessions and personal blocks.
#
# The asymmetry is deliberate and anything ambiguous is SKIPPED, NEVER GUESSED.

KIND_STUDIO_VISIT = "studio_visit"
KIND_STRATEGY_CALL = "strategy_call"
KIND_PRODUCTION_SHOOT = "production_shoot"
KIND_PORTAL_BOOKING = "portal_booking"
# Patch #33 — two kinds the Jul 29 backfill proved were missing.
KIND_STUDIO_PRODUCTION = "studio_production"   # a SHOOT, but at OUR studio
KIND_CLIENT_CALL = "client_call"               # Zoom/Calendly client meeting
KIND_INTERNAL = "internal"
KIND_UNKNOWN = "unknown"

# Client-event titles, as actually written by the four creation paths AND as
# Michael types them by hand.
#
# PATCH #33 — WHY THIS LIST GREW. The Jul 29 backfill repaired 10 of 69 events
# and skipped 6 as AMBIGUOUS. Skipping was the correct behaviour given what the
# classifier knew — but two of those six were PAYING CLIENTS sitting off the
# reminder rail entirely:
#     "STUDIO RECORDING | Dr. Luiz Bolfer — Educational Videos"   Sat Aug 15
#     "STUDIO SHOOT - NO LINES with Dr. Scott Robinson"           Thu Aug 20
# Robinson is a $1,200/mo Studio Package client. Bolfer is a $2,497 client.
# Neither title matched anything, so neither gets a confirmation or a reminder.
#
# The fix is MORE POSITIVE SIGNALS, never a looser rule. Skip-rather-than-guess
# stays exactly as it is; we are teaching the classifier to recognise real
# client events, not lowering the bar for what counts as one.
_TITLE_PATTERNS = [
    (KIND_STUDIO_VISIT, re.compile(r"^\s*studio visit\s*[—\-]", re.I)),
    (KIND_STRATEGY_CALL, re.compile(r"^\s*strategy call\s*[—\-]", re.I)),
    (KIND_PORTAL_BOOKING, re.compile(r"studio:\s", re.I)),
    # A shoot AT our studio. Distinct from a production shoot on location:
    # same crew+client confirmation needs, but the venue IS our address.
    # Matches "STUDIO RECORDING | …", "STUDIO SHOOT - …", "Studio Session w/ …".
    (KIND_STUDIO_PRODUCTION,
     re.compile(r"^\s*studio\s+(recording|shoot|session|filming)\b", re.I)),
    # PATCH #50C — `gravação` was missing, and its absence had a name.
    # Michael books in two languages; `filmagem` and `depoimento` were already
    # here, so the omission read as deliberate when it was just incomplete.
    # "GRAVAÇÃO Natalia Tavares" (Aug 5, 5–7 PM) matched nothing, classified
    # `unknown`, and sat in the unclassified bucket where no rail could see it
    # — a real client-facing booking, invisible for exactly one missing word.
    # Accent-folded so `gravacao` typed without the cedilla matches too, and
    # `film shoot` added because that is what he actually types.
    (KIND_PRODUCTION_SHOOT,
     re.compile(r"(video shoot|film shoot|filmagem|grava[çc][ãa]o|production shoot"
                r"|depoimento|on[- ]location|external shoot)", re.I)),
    # Client calls. "Zoom call …" is typed by hand; "<Name> and Michael Moraes"
    # is Calendly's default event title, which is how the ROADMAP calls land.
    (KIND_CLIENT_CALL, re.compile(r"^\s*(zoom|google meet|meet|teams)\b.*\bcall\b", re.I)),
    (KIND_CLIENT_CALL, re.compile(r"^\s*zoom call\b", re.I)),
    (KIND_CLIENT_CALL, re.compile(r"\band\s+michael\s+moraes\s*$", re.I)),
]

# Recurring personal / admin blocks. These are NEVER client events and must
# never be repaired. Matched anywhere in the title, case-insensitive.
# Patch #33: a Brazilian court case number (0844538-85.2024.8.19.0002) is a
# LEGAL matter on Michael's own calendar, not a client booking. It was landing
# in AMBIGUOUS because it has two external attendees — which meant every
# backfill and every S-5 nudge had to re-consider it. Naming it explicitly
# stops the rail from ever nudging a court clerk for an RSVP.
_LEGAL_CASE_RE = re.compile(r"\b\d{6,7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")

_INTERNAL_MARKERS = [
    "treino", "ems", "bloqueado", "send weekly update", "victory tv",
    "campeonato", "aniversário", "aniversario", "férias", "ferias",
    "holiday", "dentist", "medico", "médico", "self-test",
]

# Addresses that belong to us, not to a client.
_INTERNAL_EMAIL_DOMAINS = ("mwmcreations.com", "mwmscreens.com")


def classify_event(ev):
    """Classify a calendar event. Returns (kind, is_client, why).

    is_client is True ONLY when we are confident. Ambiguous events come back
    False with a reason — the caller must skip them rather than guess.
    """
    summary = str(ev.get("summary") or "")
    desc = str(ev.get("description") or "")
    low = summary.lower()

    if _LEGAL_CASE_RE.search(summary):
        return KIND_INTERNAL, False, "legal case number — Michael's own matter, not a client booking"

    for marker in _INTERNAL_MARKERS:
        if marker in low:
            return KIND_INTERNAL, False, f"internal/recurring block (matched {marker!r})"

    for kind, pat in _TITLE_PATTERNS:
        if pat.search(summary):
            return kind, True, f"title matches {kind}"

    # Created by one of our own paths? The rail stamps this at creation.
    if "Booked by: Maya" in desc or "Studio Package portal booking" in desc:
        return KIND_PORTAL_BOOKING, True, "created by a known machine write-path"

    # An external attendee is suggestive but NOT sufficient on its own —
    # Michael's court hearing has two external attendees and is not a client.
    ext = [a.get("email", "") for a in (ev.get("attendees") or [])
           if isinstance(a, dict) and a.get("email")
           and not str(a["email"]).lower().endswith(_INTERNAL_EMAIL_DOMAINS)]
    if ext:
        return KIND_UNKNOWN, False, (
            f"has {len(ext)} external attendee(s) but no recognised client-event title — "
            f"AMBIGUOUS, skipped rather than guessed")

    return KIND_UNKNOWN, False, "no client-event signal"


def is_client_event(ev):
    """True only for events we are confident are client-facing."""
    return classify_event(ev)[1]


# ── Patch #31 · S-3 · what each event type is owed ───────────────────
# Spec S-3: production shoots get crew T-48 hard yes/no, client T-24 explicit
# yes, and T-2h day-of to all. Studio visits keep the rail that already works.
# "Do not build a second reminder system for shoots" — this is the same job,
# made event-type aware.
# PATCH #45A — the 7-day and 48-hour CLIENT tiers are new here, and they are
# the ones Michael actually asked for after the no-shows. They previously
# "existed" only as Google Calendar overrideReminders, which are private to
# whoever wrote them and reached no client (see instrumentation_gaps below).
# These go out on the rail that genuinely delivers: WhatsApp first, email
# fallback, a named human when neither works.
#
# Deliberately NOT uniform. A 3-hour studio production earns a week's notice;
# a 30-minute strategy call does not, and a reminder nobody needs is how a
# useful rail teaches people to ignore it.
CONFIRMATION_PLAN = {
    KIND_STUDIO_VISIT:     [("client", 168), ("client", 48), ("client", 24), ("client", 2)],
    KIND_PORTAL_BOOKING:   [("client", 168), ("client", 48), ("client", 24), ("client", 2)],
    KIND_STRATEGY_CALL:    [("client", 48), ("client", 24), ("client", 2)],
    KIND_CLIENT_CALL:      [("client", 48), ("client", 24), ("client", 2)],
    # A studio production needs the SAME crew rail as an on-location shoot —
    # Robinson's podcast has guests and an audience, Bolfer's is a 3h session.
    # Only the venue differs, not the confirmation obligation.
    KIND_STUDIO_PRODUCTION: [("client", 168), ("crew", 48), ("client", 48),
                             ("client", 24), ("client", 2), ("crew", 2)],
    KIND_PRODUCTION_SHOOT:  [("client", 168), ("crew", 48), ("client", 48),
                             ("client", 24), ("client", 2), ("crew", 2)],
}


# ── Patch #32 · WHERE does each event kind actually happen? ──────────
# The #31 repair path wrote STUDIO_ADDRESS into ANY empty client location.
# That is wrong, and wrong in the dangerous direction:
#
#   · a PRODUCTION SHOOT happens at the CLIENT's site. Rafael Madeira's was at
#     FastLine Group, 5047 W Colonial Dr. Stamping the studio address on it
#     would have sent the crew to the wrong side of Orlando on shoot day.
#   · a STRATEGY CALL is a phone call. There is no address. Stamping the studio
#     on it tells a client to drive across town for a phone call.
#     (Jorge Pabon Aug 5, Carolina Rodriguez Aug 6 — both empty, both calls.)
#
# An empty location is OBVIOUSLY missing and someone asks. A WRONG location is
# confidently misleading and someone drives to it. Wrong beats empty only in
# the sense that it is worse.
#
# So the repair defaults a location ONLY where we actually know the answer.
# Where we do not, we REFUSE TO GUESS and hand it to a human by name.

VENUE_STUDIO = "studio"      # happens at our address — safe to auto-fill
VENUE_VIRTUAL = "virtual"    # phone/video — safe to fill with a non-postal note
VENUE_CLIENT_SITE = "client" # only Michael/LARA know where — NEVER guess

EVENT_VENUE = {
    KIND_STUDIO_VISIT:      VENUE_STUDIO,
    KIND_PORTAL_BOOKING:    VENUE_STUDIO,
    KIND_STUDIO_PRODUCTION: VENUE_STUDIO,     # a shoot, but at OUR address
    KIND_STRATEGY_CALL:     VENUE_VIRTUAL,
    KIND_CLIENT_CALL:       VENUE_VIRTUAL,
    KIND_PRODUCTION_SHOOT:  VENUE_CLIENT_SITE,
}


def venue_of(kind):
    """Where this kind of event happens. Unknown kinds are treated as
    client-site, i.e. never auto-filled — the conservative default."""
    return EVENT_VENUE.get(kind, VENUE_CLIENT_SITE)


def location_repair_for(kind, studio_address, virtual_note):
    """What may the backfill safely write into an empty location?

    Returns (value_or_None, reason). None means DO NOT WRITE — report it to a
    human instead. This is the same skip-rather-than-guess rule the client
    filter uses, applied one level deeper: it is not enough to know the event
    is a client event, we also have to know where it happens.
    """
    v = venue_of(kind)
    if v == VENUE_STUDIO:
        return studio_address, "studio-based event — our own address is correct"
    if v == VENUE_VIRTUAL:
        return virtual_note, "virtual event — non-postal note, not a street address"
    return None, ("event happens at the CLIENT's site — only a human knows the "
                  "address. Guessing here would send the crew to the wrong place.")


# ══════════════════════════════════════════════════════════════════════
# PATCH #50 · DIRECT BOOKINGS — the intake form's vocabulary
# ══════════════════════════════════════════════════════════════════════
# Referrals phone Michael directly. He books them by hand in Google Calendar,
# and every hand-typed title is a coin flip on whether any rail can see the
# event. Two live examples, both his, both from this week:
#
#   "FILM SHOOT — ENZO AUTO SERVICE (On Location)"  classified fine, but had
#       no attendee and no address, so it sat on the CRITICAL list unreachable.
#   "GRAVAÇÃO Natalia Tavares"                      matched nothing at all and
#       fell into the unclassified bucket, invisible to every rail.
#
# The fix is NOT a naming convention he has to remember. In his own words: "I
# might not remember how to do it anymore, I just have too many things in my
# head." A convention that depends on recall is a convention that fails on the
# busy week — which is exactly the week the booking matters.
#
# So the title is COMPUTED here from a picked type, and never typed. The form
# asks questions; this module turns the answers into the shape the rail
# already understands. Nothing downstream changes: these titles are chosen to
# match the EXISTING `_TITLE_PATTERNS` and therefore the existing ladders in
# CONFIRMATION_PLAN. Verified against classify_event, not assumed.

BOOKING_TYPES = {
    "studio_visit": {
        "label": "Studio Visit",
        "hint": "They come to the studio — tour, consultation, a look at the space.",
        "kind": KIND_STUDIO_VISIT,
        "title": "Studio Visit - {name}",
        "default_minutes": 60,
        "billable": False,
    },
    "strategy_call": {
        "label": "Strategy Call",
        "hint": "Phone or video. No address needed.",
        "kind": KIND_STRATEGY_CALL,
        "title": "Strategy Call - {name}",
        "default_minutes": 30,
        "billable": False,
    },
    "studio_recording": {
        "label": "Studio Recording / Shoot",
        "hint": "Filming at OUR studio. Crew get their own 48h and 2h confirmations.",
        "kind": KIND_STUDIO_PRODUCTION,
        "title": "Studio Recording - {name}",
        "default_minutes": 120,
        "billable": True,
    },
    "location_shoot": {
        "label": "Film Shoot — On Location",
        "hint": "Filming at THEIR site. The address is where the crew drives, so it is required.",
        "kind": KIND_PRODUCTION_SHOOT,
        "title": "Film Shoot (On Location) - {name}",
        "default_minutes": 180,
        "billable": True,
    },
}

# Ordered for display. dicts preserve insertion order, but the form's meaning
# should not depend on that quietly.
BOOKING_TYPE_ORDER = ["studio_visit", "strategy_call",
                      "studio_recording", "location_shoot"]

# ── who is this person to us? ────────────────────────────────────────
# This is the bucket the machine has never had, and its absence has a cost
# with a name. The 24h auto-outcome marks ANY unreported meeting `follow_up`
# and hands the person to Maya's nurture. For a referral that is correct. For
# Enzo Auto Service — an active client — it is selling to someone who already
# bought. For Natalia — an editor owed $500, taking it in studio time — it is
# a "checking in to see where things stand" email to a person we owe money to.
#
# `sells` gates the SALES rail only. Every relationship still gets the full
# confirmation ladder: a partner shoot needs its reminders exactly as much as
# a paid one, because not turning up costs the same either way.
# PATCH #52 — Michael asked whether "Paid" could stand in for "existing
# client", and the answer is no: money and relationship are different
# questions, and only one of them decides whether we chase someone. But the
# second half of his question found a real hole — "maybe a lead that paid me
# on the spot when they called."
#
# That person had no correct answer. `new_lead` created their record and then
# nurtured them about becoming a client they had already become. And
# `existing_client` correctly stayed silent but created NO RECORD, because the
# submit path only ever created one for `new_lead` — so a client who happened
# not to be in the pipeline yet stayed invisible to it.
#
# Two flags now, because they were always two ideas wearing one label:
#   sells    — may the SALES rail chase this person?
#   pipeline — should a lead record exist for them at all?
# A vendor and a partner are real people we book real rooms for; they are just
# not prospects, and putting them in the sales pipeline would be a lie about
# what they are.
RELATIONSHIPS = {
    "new_lead":        {"label": "New lead / referral", "sells": True,
                        "pipeline": True, "converted": False,
                        "hint": "Hasn't bought yet. Goes in the pipeline and gets followed up."},
    "new_client":      {"label": "New client — already paid", "sells": False,
                        "pipeline": True, "converted": True,
                        "hint": "Paid on the call, or booked and paid up front. Goes in the pipeline, never pitched again."},
    "existing_client": {"label": "Existing client", "sells": False,
                        "pipeline": True, "converted": True,
                        "hint": "Already a client. Remind them, never pitch them."},
    "partner":         {"label": "Partner / collaboration", "sells": False,
                        "pipeline": False, "converted": False,
                        "hint": "A trade or joint project, not a sale."},
    "vendor":          {"label": "Vendor / internal", "sells": False,
                        "pipeline": False, "converted": False,
                        "hint": "Crew, editor, contractor. Owed time or paid by us."},
}

RELATIONSHIP_ORDER = ["new_lead", "new_client", "existing_client",
                      "partner", "vendor"]


def relationship_in_pipeline(rel):
    """Should this person have a lead record? Unknown: no.

    PATCH #52. Fails closed in the direction of NOT inventing pipeline
    entries — a missing record is visible the moment someone looks for the
    lead, whereas a spurious one quietly inflates every count on the board.
    """
    return bool((RELATIONSHIPS.get(str(rel or "").strip()) or {}).get("pipeline"))


def relationship_converted(rel):
    """Has this person already bought? Unknown: no."""
    return bool((RELATIONSHIPS.get(str(rel or "").strip()) or {}).get("converted"))

# PATCH #51 — Michael hit this on his first real use of the form and he was
# right: "on number four, paid or not — a studio visit, people don't need to
# pay to come for a visit." Asking whether a free sales meeting is paid is a
# category error, and none of the four answers fitted, so the form was forcing
# a wrong one.
#
# He also named where that information actually belongs: "I just put that
# information after on my event report about the payment situation, because
# I'm gonna be reporting what kind of package did I offer." Correct — at
# booking time there is no price yet, only an intention to quote one. The
# money is an OUTCOME of the meeting, and the Daily Event Report already
# captures it.
#
# So the question is now asked only of work being delivered.
BILLING = {
    "no_charge":   "No charge — sales meeting",
    "paid":        "Paid",
    "partnership": "Unpaid — partnership / collaboration",
    "trade":       "Unpaid — trade or time already owed",
    "internal":    "Unpaid — internal / our own cost",
}

BILLING_ORDER = ["paid", "partnership", "trade", "internal"]

# What a consultation is allowed to be: exactly one thing, so the form can
# answer for him instead of asking.
BILLING_CONSULTATION = ["no_charge"]


def billing_options_for(type_key):
    """Which billing answers make sense for this booking type.

    A studio visit or a strategy call is how a lead becomes a client — the fee
    does not exist yet, so the only honest answer is "no charge", and the form
    fills it in rather than making him choose a wrong one. A shoot or a studio
    session is delivered work and genuinely can be paid, a partnership, a
    trade, or on our own cost.

    An unknown type gets the full list, which is the permissive default — but
    validate_booking still refuses an unknown type outright, so this never
    becomes a way in.
    """
    spec = BOOKING_TYPES.get(type_key)
    if spec is None:
        return list(BILLING_ORDER)
    return list(BILLING_ORDER) if spec.get("billable") else list(BILLING_CONSULTATION)


def billing_is_asked(type_key):
    """False when there is only one honest answer, so the form should not ask."""
    return len(billing_options_for(type_key)) > 1


def booking_kind(type_key):
    """Which classify_event KIND this booking type will become."""
    return (BOOKING_TYPES.get(type_key) or {}).get("kind", KIND_UNKNOWN)


def booking_title(type_key, name):
    """The event title. COMPUTED, never typed.

    The whole patch turns on this function. Each template is chosen so that
    classify_event() recognises the result and CONFIRMATION_PLAN therefore has
    a ladder for it. test_booking_form.py asserts that round trip for every
    type — if someone edits a template into something the classifier no longer
    recognises, the suite fails rather than production going quiet.
    """
    spec = BOOKING_TYPES.get(type_key)
    if not spec:
        return ""
    clean = " ".join(str(name or "").split()).strip(" -—")
    if not clean:
        return ""
    return spec["title"].format(name=clean)


def booking_needs_address(type_key):
    """True when only a human can know where this happens.

    Reuses venue_of() rather than restating it. A studio booking fills from our
    own address, a call has no address, and a location shoot is the one case
    where guessing sends the crew to the wrong side of Orlando — Patch #32's
    lesson, applied at intake instead of at repair time.
    """
    return venue_of(booking_kind(type_key)) == VENUE_CLIENT_SITE


def booking_location(type_key, custom, studio_address, virtual_note):
    """The location this event MUST carry. Never returns empty for a valid type.

    PATCH #50. `instrumentation_gaps` counts an empty location as a gap, so an
    event created without one is degraded from birth — which is how the Enzo
    shoot ended up on the CRITICAL list with "no location and no meeting link"
    alongside its missing attendee.

    Delegates to `location_repair_for` rather than restating the venue rules,
    so the form and the backfill can never drift apart on where an event kind
    happens. The one case that helper refuses to answer — a shoot at the
    client's site — is exactly the case the form makes a required field, so
    the human supplies what the machine must not guess.
    """
    kind = booking_kind(type_key)
    supplied = str(custom or "").strip()
    if venue_of(kind) == VENUE_CLIENT_SITE:
        return supplied          # required by validate_booking; never invented
    auto, _why = location_repair_for(kind, studio_address, virtual_note)
    # A location Michael typed beats our default — he may be using the second
    # room, or a client's conference line.
    return supplied or (auto or "")


def relationship_sells(rel):
    """May the SALES rail act on this person? Unknown relationships: no.

    Fails closed on purpose. A missed nurture is a follow-up Michael can send
    by hand; an unwanted pitch to a paying client is a relationship problem he
    cannot unsend.
    """
    return bool((RELATIONSHIPS.get(str(rel or "").strip()) or {}).get("sells"))


def relationship_from_description(desc):
    """Read the Relationship: line back off an event. '' when absent.

    Absent means the event predates this patch or was hand-made, and the
    caller must treat it as unknown rather than assuming new_lead.
    """
    for line in str(desc or "").split("\n"):
        s = line.strip()
        if s.lower().startswith("relationship:"):
            val = s.split(":", 1)[1].strip().lower()
            return val if val in RELATIONSHIPS else ""
    return ""


def booking_description(name, email, phone="", business="",
                        type_key="", relationship="", billing="",
                        amount="", notes=""):
    """The description an ATTENDEE will read. Nothing else belongs here.

    🔴 S87 — Michael, Aug 11, after seeing Shelley Roxanne's invite:
    *"once she receives the invitation all of those notes that are on the
    invitation she is also going to be able to read... this is not fine."*
    He is right, and it had been true of every invite this system has ever
    sent. A calendar description is rendered in full to every guest, and we
    were printing `Relationship: existing_client`, `Sales rail: OFF — existing
    client is not a sales prospect`, `Billing: No charge — sales meeting`,
    `Booked by: Michael (Direct Booking form)` and a block of rail
    diagnostics onto a document we then emailed to the client.

    🔑 The rule this establishes: **an event description is client-facing
    copy, not a record.** Internal state goes in `extendedProperties.private`,
    which Google shows only to our own copy of the event.

    `Lead:` and `Email:` STAY. They are the client's own name and address —
    nothing to hide — and six readers depend on them, including the one that
    decides whether a reminder can greet her by name instead of "there".
    """
    spec = BOOKING_TYPES.get(type_key) or {}
    lines = []

    label = spec.get("label") or "Meeting"
    lines.append("{} with Michael Moraes — MWM Creations & Studios".format(label))

    if notes:
        lines.append("")
        lines.append(str(notes).strip())

    lines.append("")
    lines.append("Lead: {}".format(" ".join(str(name or "").split())))
    if email:
        lines.append("Email: {}".format(str(email).strip()))
    return "\n".join(lines)


# Keys we keep ON the event but OUT of the client's view. Google renders
# extendedProperties to nobody; they come back on our own reads.
def booking_private_props(phone="", business="", type_key="", relationship="",
                          billing="", amount="", booked_by="Direct Booking form"):
    """The internal record that used to sit in the client-facing description.

    Values are truncated to Google's 300-character limit per property.
    """
    props = {}

    def put(k, v):
        v = str(v or "").strip()
        if v:
            props[k] = v[:300]

    put("phone", phone)
    put("business", business)
    put("booking_type", type_key)
    put("booked_by", booked_by)
    if relationship in RELATIONSHIPS:
        put("relationship", relationship)
        put("sales_rail", "on" if relationship_sells(relationship) else "off")
    if billing in BILLING:
        bill = BILLING[billing]
        if billing == "paid" and str(amount or "").strip():
            bill = "{} — {}".format(bill, str(amount).strip())
        put("billing", bill)
        if billing == "no_charge":
            put("pricing", "decided at the meeting — Daily Event Report, not the booking")
    return props


def relationship_of_event(event):
    """The relationship for an event, private props first, description second.

    The description fallback is not legacy cruft — every event created before
    S87 carries it there, and they are still on the calendar.
    """
    try:
        priv = ((event or {}).get("extendedProperties") or {}).get("private") or {}
        val = str(priv.get("relationship") or "").strip().lower()
        if val in RELATIONSHIPS:
            return val
    except Exception:
        pass
    return relationship_from_description((event or {}).get("description", ""))


def _hhmm_to_min(v):
    """'14:30' -> 870. '24:00' -> 1440. Anything unparseable -> None.

    "24:00" is not a typo: /studio-availability serialises a block running to
    or past midnight that way on purpose (S15.1). A block that ended "00:00"
    collapsed to zero length and got discarded, and a convention showed as
    open for four days before Michael spotted it. Whatever reads those blocks
    has to speak the same dialect.
    """
    try:
        h, _, m = str(v).strip().partition(":")
        h, m = int(h), int(m or 0)
    except (ValueError, AttributeError):
        return None
    if not (0 <= h <= 24 and 0 <= m < 60):
        return None
    return h * 60 + m


def slot_conflicts(start_hhmm, minutes, blocks):
    """Which existing blocks does this proposed slot collide with?

    PATCH #50D. Michael is on the phone and the client asks for Thursday at
    two. Until now the answer came from him remembering, or from switching to
    the Google Calendar app mid-call — which is the exact habit this form was
    built to replace. A form that lets him book a double-booking has just moved
    the mistake, not removed it.

    Touching is NOT overlapping: a 09:00–12:00 shoot does not conflict with a
    12:00 start. Strict inequality on both sides, so back-to-back bookings stay
    legal — he does them constantly.

    Pure. `blocks` is whatever the availability feed returned; anything
    malformed is skipped rather than guessed at, because a block we cannot
    parse must not silently become "free".
    """
    s0 = _hhmm_to_min(start_hhmm)
    try:
        dur = int(minutes)
    except (TypeError, ValueError):
        return []
    if s0 is None or dur <= 0:
        return []
    s1 = s0 + dur
    hits = []
    for b in (blocks or []):
        if not isinstance(b, dict):
            continue
        b0 = _hhmm_to_min(b.get("start"))
        b1 = _hhmm_to_min(b.get("end"))
        if b0 is None or b1 is None or b1 <= b0:
            continue
        if s0 < b1 and b0 < s1:      # strict: touching endpoints do not collide
            hits.append(b)
    return hits


# PATCH #50E — turnaround between bookings.
# Michael asked for this after seeing the calendar, and it corrects an
# assumption I had defended: I built "back-to-back is not a clash" on the
# reasoning that he books that way constantly. He does — but a gear change
# between a shoot and the next client is physical, and a form that calls
# 09:00 clear when a shoot ends at 09:00 is technically right and practically
# useless. 30 minutes is his number.
#
# It is a WARNING, never a refusal. Sometimes back-to-back is exactly what he
# wants — a second client in a different room, or a call he takes from the
# car. A form that blocks it teaches him to work around the form.
BOOKING_BUFFER_MIN = 30


def slot_buffer_warnings(start_hhmm, minutes, blocks, buffer_min=None):
    """Bookings that do not OVERLAP but sit inside the turnaround window.

    Returns a list of {"block", "gap", "side"} — side is "before" when the
    existing booking ends just before this one starts, "after" when it begins
    just after this one ends. Anything that genuinely overlaps is excluded and
    left to `slot_conflicts`, so the two never double-report the same booking.

    Pure. A block that cannot be parsed is skipped rather than assumed clear —
    same rule as slot_conflicts, for the same reason.
    """
    buf = BOOKING_BUFFER_MIN if buffer_min is None else buffer_min
    s0 = _hhmm_to_min(start_hhmm)
    try:
        dur, buf = int(minutes), int(buf)
    except (TypeError, ValueError):
        return []
    if s0 is None or dur <= 0 or buf <= 0:
        return []
    s1 = s0 + dur
    out = []
    for b in (blocks or []):
        if not isinstance(b, dict):
            continue
        b0 = _hhmm_to_min(b.get("start"))
        b1 = _hhmm_to_min(b.get("end"))
        if b0 is None or b1 is None or b1 <= b0:
            continue
        if s0 < b1 and b0 < s1:
            continue                      # a real overlap — not a buffer case
        if b1 <= s0:
            gap = s0 - b1
            side = "before"
        else:
            gap = b0 - s1
            side = "after"
        if 0 <= gap < buf:
            out.append({"block": b, "gap": gap, "side": side})
    out.sort(key=lambda w: w["gap"])
    return out


def slot_runs_past_midnight(start_hhmm, minutes):
    """True when this slot spills into the next day.

    PATCH #50D. `slot_conflicts` is scoped to ONE day's blocks, so a 23:00
    start running three hours is checked against nothing after midnight and
    would report CLEAR while colliding with an 01:00 booking. Rather than
    silently under-checking, the caller surfaces this and says so — an honest
    "I did not check the other side of midnight" beats a confident wrong CLEAR.
    """
    s0 = _hhmm_to_min(start_hhmm)
    try:
        dur = int(minutes)
    except (TypeError, ValueError):
        return False
    return s0 is not None and dur > 0 and (s0 + dur) > 24 * 60


def day_is_free(blocks):
    """True when nothing real is on the day."""
    return not [b for b in (blocks or [])
                if isinstance(b, dict)
                and _hhmm_to_min(b.get("start")) is not None
                and _hhmm_to_min(b.get("end")) is not None]


def validate_booking(payload):
    """Pure gate on a form submission. Returns (errors, clean).

    Deliberately strict about the four things that have actually gone wrong on
    this calendar — no type, no name, no address to reach the person, no
    address for the crew — and silent about everything else. A form that
    nags about optional fields gets filled with junk to make it stop.
    """
    p = payload or {}
    get = lambda k: str(p.get(k) or "").strip()
    errors = []

    type_key = get("type")
    if type_key not in BOOKING_TYPES:
        errors.append("pick what kind of booking this is")

    name = " ".join(get("name").split())
    if len(name) < 2:
        errors.append("the client's name is required — it is what reminders greet them by")

    email = get("email")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        errors.append("a real email address is required — without one no reminder "
                      "can reach them and no RSVP can be read")

    date = get("date")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        errors.append("pick a date")
    start = get("start")
    if not re.match(r"^\d{2}:\d{2}$", start):
        errors.append("pick a start time")

    try:
        minutes = int(float(get("minutes") or 0))
    except ValueError:
        minutes = 0
    if minutes <= 0:
        minutes = (BOOKING_TYPES.get(type_key) or {}).get("default_minutes", 60)
    if minutes > 12 * 60:
        errors.append("that is longer than 12 hours — check the duration")

    location = get("location")
    if type_key and booking_needs_address(type_key) and not location:
        errors.append("an on-location shoot needs the full street address — "
                      "it is where the crew drives on the day, and nobody but "
                      "you knows it")

    rel = get("relationship")
    if rel not in RELATIONSHIPS:
        errors.append("say who this person is to us — it decides whether the "
                      "sales rail is allowed to touch them")

    # PATCH #51 — two different behaviours here, on purpose.
    #
    # A consultation is COERCED: there is exactly one honest answer, so the
    # form does not ask and the server fills it. Anything else that arrives —
    # a stale tab, a hand-rolled POST — is overwritten rather than rejected,
    # because "Paid — $2,400" on a free studio visit must never be stored, and
    # there is no ambiguity about what it should have said.
    #
    # A billable type is REFUSED: if a shoot arrives marked "no charge" we
    # genuinely do not know whether it is a partnership, a trade, or an
    # oversight, and guessing would put a wrong number next to real work.
    billing = get("billing")
    _allowed = billing_options_for(type_key) if type_key in BOOKING_TYPES else []
    if type_key in BOOKING_TYPES and not billing_is_asked(type_key):
        billing = _allowed[0]
    elif billing not in BILLING:
        errors.append("say whether this is paid")
    elif _allowed and billing not in _allowed:
        errors.append("{!r} is not a valid answer for a {} — pricing for a sales "
                      "meeting belongs in the event report, not here"
                      .format(BILLING.get(billing, billing),
                              BOOKING_TYPES[type_key]["label"]))

    # S85 — ask, do not infer. Default EMAIL: it is the only channel this form
    # has actually verified (the address is required and it is what carries the
    # invite). WhatsApp is offered because much of Michael's book is on it, but
    # it must be a choice, never a deduction from a phone number's shape.
    reminder = (get("reminder") or "email").strip().lower()
    if reminder not in REMINDER_CHANNELS:
        reminder = "email"

    clean = {
        "reminder": reminder,
        "type": type_key, "name": name, "email": email,
        "phone": get("phone"), "business": get("business"),
        "date": date, "start": start, "minutes": minutes,
        "location": location, "relationship": rel,
        "billing": billing, "amount": get("amount"),
        "notes": get("notes"),
    }
    return errors, clean


def stage_horizon_phrase(stage_h):
    """How to describe the gap, in the client's words, at this stage.

    PATCH #45B. The confirmation body said "your session tomorrow" for EVERY
    stage at or above 24h. With #45A adding 48h and 168h tiers that sentence
    becomes a lie twice over — and a reminder that states the wrong day is
    worse than none, because the client trusts it and writes down the wrong
    date.
    """
    try:
        h = float(stage_h)
    except (TypeError, ValueError):
        return "coming up"
    if h >= 144:
        return "a week from now"
    if h >= 36:
        return "in a couple of days"
    if h >= 12:
        return "tomorrow"
    return "today"


def confirmation_copy(stage_h, first_name, when_long, time_str, location=""):
    """(whatsapp_body, email_subject, email_html) for one client tier.

    Pure on purpose: copy is the part most likely to be wrong and the part
    nobody notices is wrong, so it belongs where a test can read it.

    Early tiers CARRY THE DATE. "Tomorrow at 10" is unambiguous; "in a couple
    of days at 10" is not, and a client reading it a week out has nothing to
    write in a calendar.
    """
    fn = greeting_name(first_name)
    phrase = stage_horizon_phrase(stage_h)
    try:
        h = float(stage_h)
    except (TypeError, ValueError):
        h = 24.0

    if h < 12:
        wa = (f"Hi {fn}! See you soon — your session with MWM Creations starts "
              f"at {time_str} today. Reply here if you need anything!")
        subject = f"Today at {time_str} — MWM Creations & Studios"
    else:
        wa = (f"Hi {fn}! Maya from MWM Creations here 😊 Reminder about your "
              f"session {phrase} — {when_long} at {time_str}. Could you reply "
              f"YES to confirm? Reply here if you need to reschedule.")
        subject = f"Confirming your session — {when_long}"

    html = (f"<p>Hi {fn},</p>"
            f"<p>Confirming your session with MWM Creations &amp; Studios "
            f"<b>{phrase}</b> — {when_long} at {time_str}.</p>"
            + (f"<p>Location: {location}</p>" if location else "")
            + f"<p>Could you reply to confirm you're coming? If you need to "
              f"move it, just tell me and I'll find another time.</p>"
              f"<p>— MWM Creations &amp; Studios</p>")
    return wa, subject, html


def due_stages(kind, hours_until, tolerance=1.0):
    """Which confirmation stages are due right now for this event?

    Returns a list of (audience, hours_before) tuples. Tolerance is half the
    poll window — the caller de-duplicates with a persistent marker, so a
    generous window is safe and a narrow one silently misses sends.
    """
    out = []
    for audience, h in CONFIRMATION_PLAN.get(kind, []):
        if (h - tolerance) <= hours_until <= (h + tolerance):
            out.append((audience, h))
    return out


def audit_event(ev):
    """Read-only check of an EXISTING Google Calendar event.

    Used by /admin/event-rail-backfill. Returns a list of issue strings.
    Never mutates, never writes, never deletes.
    """
    issues = []
    if not (ev.get("location") or "").strip():
        issues.append("empty location")
    elif not looks_like_address(ev.get("location")):
        issues.append("location not address-shaped")

    attendees = ev.get("attendees") or []
    emails = [str(a.get("email", "")) for a in attendees if isinstance(a, dict)]
    if not emails:
        issues.append("no attendees on event")
    else:
        for e in emails:
            _f, ok, note = ascii_email(e)
            if not ok:
                issues.append(f"unusable attendee address ({note})")

    rem = ev.get("reminders") or {}
    if rem.get("useDefault") or not rem.get("overrides"):
        issues.append("no overrideReminders — default popup only")
    else:
        mins = {(o.get("method"), o.get("minutes")) for o in rem.get("overrides") or []}
        for want in STANDARD_REMINDERS:
            if (want["method"], want["minutes"]) not in mins:
                issues.append(f"missing reminder {want['method']}@{want['minutes']}m")

    for a in attendees:
        if isinstance(a, dict) and a.get("responseStatus") == "needsAction":
            issues.append(f"attendee {a.get('email', '?')} still needsAction")

    desc = ev.get("description") or ""
    m = re.search(r"(?:Booked via|Source channel)\s*:\s*([^\n]+)", desc)
    if m and "instagram" in m.group(1).lower():
        issues.append("IG-sourced — verify reminder channel is not WhatsApp")

    return issues


# ══════════════════════════════════════════════════════════════════════════
# PATCH #39 · OUTCOME AUTOMATION POLICY
#
# Michael, Aug 3 2026: "I would love all buttons, instead of Not interested,
# to do an automated task so it goes together with our sales system nicely."
#
# Three findings shaped this, and none of them were guesses:
#
#  1. EMAIL IS OUR NARROWEST CHANNEL, NOT OUR WIDEST. Measured across 365
#     dated CRM rows: only 62 carry an email address — 17%. Instagram 29%,
#     WhatsApp 27%. An email-only design would reach one lead in six.
#     So: reply on the channel they ARRIVED on (100% coverage by
#     construction), and treat getting an email as the sequence's first job.
#
#  2. INSTAGRAM HAS A DOOR THAT SHUTS. Meta permits a DM only within 24h of
#     the lead's last inbound message; after that it is a hard 403. A day-2
#     touch on an IG lead CANNOT SEND. Any plan that ignores this produces
#     the silent failure we watched fire four times on Aug 2-3.
#     Email is the only channel that stays open, which is exactly why
#     capture matters more than channel preference.
#
#  3. NOTHING EVER ENDED. Ezechiel Garcon took four emails across six weeks
#     because no sequence knew how to stop. Every plan below carries a
#     close_after_days. A sequence without an ending is a nag with a
#     schedule.
#
# This module is PURE: no I/O, no sends, no clock. It answers one question —
# "given this outcome and what we know about reaching this person, what
# should happen and when should it stop?" The caller does the sending.
# ══════════════════════════════════════════════════════════════════════════

# what each step is FOR — the caller maps these to copy
STEP_NUDGE        = "nudge"          # short "still interested?" touch
STEP_EMAIL_ASK    = "email_capture"  # ask for an email address, nothing else
STEP_RECAP        = "recap"          # what we discussed + link
STEP_VALUE        = "value"          # what the package/hours can do
STEP_REBOOK       = "rebook"         # offer new times after a no-show
STEP_REVIEW       = "review"         # ask for a review/testimonial
STEP_HUMAN        = "human"          # S-4: named assignment, no automation

IG_DM_WINDOW_HOURS = 24


def ig_window_open(hours_since_inbound):
    """Can we still DM this Instagram lead? None = unknown -> assume CLOSED.

    Unknown must mean closed. Assuming open produces a 403 and a lead who
    silently never hears from us; assuming closed produces an email or a
    named human, both of which actually reach someone.
    """
    if hours_since_inbound is None:
        return False
    try:
        return float(hours_since_inbound) < IG_DM_WINDOW_HOURS
    except (TypeError, ValueError):
        return False


def outcome_plan(outcome, channel=CH_UNKNOWN, has_email=False,
                 hours_since_inbound=None):
    """The whole policy, in one testable place.

    Returns a dict:
      steps            [(after_hours, channel, step_kind), ...] in order
      close_after_days when to stop chasing and mark closed, or None
      suppress         True -> add to do-not-contact, send NOTHING, ever
      editing          True -> always route to the editing pipeline
      internal_only    True -> no client-facing automation at all
      owner            who picks it up if automation cannot reach them
      why              one line explaining the shape, for the #matt post
    """
    plan = {"steps": [], "close_after_days": None, "suppress": False,
            "editing": False, "internal_only": False, "owner": None, "why": ""}

    # ── NOT INTERESTED — the one Michael explicitly exempted, and correctly.
    # They said no. Any outreach after a no costs brand and earns complaints.
    # But it IS automated: the automation is STOPPING, not sending.
    if outcome == "not_interested":
        plan["suppress"] = True
        plan["why"] = ("said no — suppressed from all sequences, digests and "
                       "re-engagement. No further contact is sent, ever.")
        return plan

    # ── CLIENT WON — automate hard on the INSIDE, stay human on the outside.
    # A signed client deserves Michael's voice, not a template. The machine
    # does the paperwork.
    if outcome == "client_won":
        plan["internal_only"] = True
        plan["editing"] = True
        plan["owner"] = "LARA"
        plan["why"] = ("internal onboarding armed (tracker, production record, "
                       "invoice). No automated client email — this one is "
                       "Michael's to send.")
        return plan

    # ── COMPLETED — Michael, Aug 3: "all our shoots require editing."
    # The old rule only routed when the notes happened to contain the word
    # "edit". Written "went great"? It silently never routed. That is a
    # keyword match pretending to be a rule.
    if outcome == "completed":
        plan["editing"] = True
        plan["owner"] = "LARA"
        plan["close_after_days"] = 14
        plan["steps"] = [(24 * 7, _reachable(channel, has_email, hours_since_inbound),
                          STEP_REVIEW)]
        plan["why"] = ("shoot complete -> editing pipeline ALWAYS (no keyword "
                       "test), plus one review ask at day 7.")
        return plan

    # ── NO-SHOW — the proven-broken one. Ezechiel no-showed Jul 22; the
    # button said "Maya, please reach out" and nothing happened for 8 days.
    # Speed is the whole value here: a same-day rebook offer converts, a
    # day-3 one does not.
    if outcome == "no_show":
        plan["close_after_days"] = 5
        plan["owner"] = "MAYA"
        native = _reachable(channel, has_email, hours_since_inbound)
        plan["steps"] = [(0, native, STEP_REBOOK)]
        if has_email:
            plan["steps"].append((48, CH_WEB, STEP_REBOOK))
        elif native != CH_WEB:
            plan["steps"].append((48, native, STEP_EMAIL_ASK))
        plan["why"] = ("same-day rebook offer, one more at 48h, closed at day 5. "
                       "Speed is the value — a same-day offer rebooks, a day-3 "
                       "offer does not.")
        return plan

    # ── FOLLOW-UP — softer and slower than the pitch. Michael talked to them
    # but did NOT put the package in front of them, so this must not read as
    # a chase.
    if outcome == "follow_up":
        plan["close_after_days"] = 14
        plan["owner"] = "MAYA"
        native = _reachable(channel, has_email, hours_since_inbound)
        plan["steps"] = [(48, native, STEP_NUDGE)]
        if has_email:
            plan["steps"].append((24 * 7, CH_WEB, STEP_VALUE))
        elif native != CH_WEB:
            plan["steps"].append((24 * 7, native, STEP_EMAIL_ASK))
        plan["why"] = ("soft nudge at 48h on their own channel, one value note "
                       "at day 7, closed at day 14.")
        return plan

    # ── PACKAGE PITCHED — the existing 3-email rail already works and is
    # NOT rebuilt here. The only change: it finally has an ENDING.
    if outcome == "studio_package_pitched":
        plan["close_after_days"] = 10
        plan["owner"] = "SUSAN"
        if has_email:
            plan["steps"] = [(1, CH_WEB, STEP_RECAP),
                             (24 * 2, CH_WEB, STEP_VALUE),
                             (24 * 6, CH_WEB, STEP_NUDGE)]
            plan["why"] = ("existing T+1h / T+2d / T+6d email rail, now with a "
                           "close condition at day 10.")
        else:
            # 83% of leads have no email. Pitching one of them and then
            # arming an email sequence is how a pitch evaporates in silence.
            native = _reachable(channel, has_email, hours_since_inbound)
            plan["steps"] = [(1, native, STEP_EMAIL_ASK)]
            plan["why"] = ("PITCHED BUT NO EMAIL ON FILE — the email rail cannot "
                           "run. Asking for an address on their own channel "
                           "first; the pitch sequence arms once we have one.")
        return plan

    plan["why"] = f"no automation defined for outcome {outcome!r}"
    return plan


def _reachable(channel, has_email, hours_since_inbound):
    """Which channel can ACTUALLY deliver right now — never which we'd prefer.

    Instagram is the trap: outside the 24h window a DM is a guaranteed 403,
    so we fall to email, and to a named human if there is no email. An
    unreachable step that looks scheduled is worse than one that never armed.
    """
    if channel == CH_INSTAGRAM:
        if ig_window_open(hours_since_inbound):
            return CH_INSTAGRAM
        return CH_WEB if has_email else CH_UNKNOWN
    if channel == CH_WHATSAPP:
        return CH_WHATSAPP
    if has_email:
        return CH_WEB
    return CH_UNKNOWN


def plan_is_deliverable(plan):
    """False when every step lands on CH_UNKNOWN — i.e. we have armed nothing
    that can actually reach a human. The caller must escalate (S-4) rather
    than report a sequence as armed."""
    steps = plan.get("steps") or []
    if not steps:
        return True          # nothing armed on purpose (suppress / internal)
    return any(ch != CH_UNKNOWN for _h, ch, _k in steps)


# ══════════════════════════════════════════════════════════════════════════
# PATCH #42 · ONE RECORD, TWO PEOPLE
#
# Live case, Aug 3 2026 — Krista Neeley. She and her husband booked a studio
# visit together, so Maya wrote ONE lead record holding BOTH of them:
#
#   name  : "Krista Neeley (with Michael Neeley)"
#   email : "Kristasky@gmail.com / Michael@michaelneeley.com"
#
# The calendar invite carries just `kristasky@gmail.com`. Every lookup we own
# compares the WHOLE stored field for exact equality, so:
#   · email lookup: "kristasky@gmail.com" != "Kristasky@gmail.com / Michael@..."
#   · name  lookup: "Krista Neeley"       != "Krista Neeley (with Michael Neeley)"
# Both missed. She became invisible to the pitch sequence, to Susan's digest,
# and — the expensive one — to the STRIPE PAYER MATCH, which is the exact
# shape of the Robinson defect: money arrives, no lead is found, the stage
# stays wrong and nobody is told why.
#
# A joint booking is not an edge case in this business. Couples, partners and
# co-founders book studio time together constantly.
# ══════════════════════════════════════════════════════════════════════════

_EMAIL_SPLIT_RE = re.compile(r"[\s,;/|]+")


def emails_in_field(value):
    """Every address in a CRM email cell. Handles 'a@b.com / c@d.com'.

    Returns a lower-cased list, order preserved. Anything without an '@' is
    dropped rather than guessed at.
    """
    out = []
    for tok in _EMAIL_SPLIT_RE.split(str(value or "")):
        tok = tok.strip().strip("<>").strip()
        if "@" in tok and "." in tok.split("@")[-1]:
            low = tok.lower()
            if low not in out:
                out.append(low)
    return out


def email_field_matches(stored_field, wanted):
    """True when `wanted` is ANY of the addresses in a (possibly multi-value)
    stored field. Exact address comparison — never a substring test, which
    would make 'ana@x.com' match 'susana@x.com'."""
    w = str(wanted or "").strip().lower()
    return bool(w) and w in emails_in_field(stored_field)


def name_variants(value):
    """Comparable forms of a stored or submitted name.

    "Krista Neeley (with Michael Neeley)" -> ["krista neeley (with michael neeley)",
                                              "krista neeley"]
    The trailing bracket is dropped ONLY when something remains in front of it,
    so "(Acme)" is never reduced to nothing.
    """
    raw = str(value or "").strip()
    if not raw:
        return []
    out = [raw.lower()]
    before, inside = _split_trailing_parens_er(raw)
    if inside and before and before.lower() not in out:
        out.append(before.lower())
    return out


def names_match(stored, wanted):
    """True when the two names agree on any comparable form."""
    a, b = name_variants(stored), name_variants(wanted)
    return bool(a) and bool(b) and bool(set(a) & set(b))


def _split_trailing_parens_er(s):
    """Balanced trailing (...) split — same rule as meeting_report_utils, kept
    here so event_rail stays import-free of the app's helpers."""
    s = (s or "").rstrip()
    if not s.endswith(")"):
        return s, ""
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                before, inside = s[:i].rstrip(), s[i + 1:-1].strip()
                return (before, inside) if (before and inside) else (s, "")
    return s, ""


# ══════════════════════════════════════════════════════════════════════════
# PATCH #43 · THE REMINDER SYSTEM, MADE STRONG
#
# Michael, Aug 3 2026, after Gema Hiatt cancelled THREE MINUTES before her
# call: "We are having no-show situations, we have clients not coming. Make
# sure this reminder system really does work and that is strong."
#
# What the Robinson trace found, and what it generalises to:
#
#   The rail resolves the client by scraping `Lead:` / `Phone:` lines out of
#   the event DESCRIPTION. Events Maya books carry those lines. Events typed
#   onto the calendar BY HAND do not — so Dr. Robinson, our largest shoot,
#   was set to be greeted "Hi there" at T-24 and T-2, with WhatsApp skipped
#   entirely because no phone could be scraped.
#
#   Coach Fly was the same root cause one layer up: no attendee at all, so
#   invisible to every rail. Robinson is VISIBLE BUT ANONYMOUS — and that is
#   the harder failure, because nothing errors and nothing alerts.
#
# A description is a note somebody typed. An attendee is a real key. Prefer
# the key.
# ══════════════════════════════════════════════════════════════════════════

RSVP_TIERS_HOURS = (72, 24)      # #43: 72h added — at 24h the only move left
                                 # is eating the slot; at 72h LARA can still
                                 # call, rebook, or release the studio.
RSVP_TIER_TOLERANCE = 1.5        # poll runs every 15 min; ±1.5h never misses


def due_rsvp_tier(hours_until):
    """Which RSVP tier is due right now, or None. Highest tier first so a
    single pass can never fire two."""
    try:
        h = float(hours_until)
    except (TypeError, ValueError):
        return None
    for tier in RSVP_TIERS_HOURS:
        if abs(h - tier) <= RSVP_TIER_TOLERANCE:
            return tier
    return None


# The reminder job must see far enough ahead to reach its own earliest tier.
# Robinson exposed this: the horizon was 50h and the crew stage fires at 48h,
# so the entire margin on our largest shoot was TWO HOURS. One restart inside
# that window and the crew tier is missed in silence.
# PATCH #45C — was 80, which made the new 168h client tier unreachable: the
# scan never saw an event a week out, so the tier could never fire. 180 = the
# 168h tier plus half a day of slack.
#
# Safe to widen. due_stages() matches a WINDOW (h ± tolerance), not a
# threshold, so raising the horizon does NOT retro-fire the new tiers for
# events already closer than 168h — only events that pass THROUGH the window
# from now on will trigger them. No blast on deploy.
REMINDER_HORIZON_HOURS = 180     # 168h client tier + 12h of slack


def instrumentation_gaps(ev, resolved_name=None):
    """What is missing on a FUTURE client event, in plain language.

    PATCH #45D — CORRECTED, and the correction matters more than the original.

    The #43 version scored an event on its `overrideReminders` and called a
    missing EMAIL override a critical, client-unreachable failure. That was
    exactly backwards. Google Calendar reminders are private to the
    authenticated user — Google's words:

        "Reminders are private information, specific to an authenticated
         user; they're not shared across multiple users."

    An override our service account writes is a reminder FOR THE SERVICE
    ACCOUNT. No client has ever received one. There is no mechanism in the API
    for an organiser to set a reminder that reaches an attendee.

    Demonstrated on our own calendar rather than merely read: the first live
    sweep (Aug 4, 07:00) reported "NO REMINDERS AT ALL" for precisely the
    events whose reminders MICHAEL set in his own UI, and reported nothing
    about reminders on precisely the events our service account had written the
    night before. The service account can only see its own. That is the
    per-user model, proved on production data.

    So this function no longer measures reminders at all. It measures what the
    REAL rail needs in order to reach a human: an attendee address to send to,
    a name to greet them by, an answered RSVP, and somewhere to go. The rail
    itself is `_lead_reminder_thread` — WhatsApp first, email fallback, named
    human last.

    Read-only. Returns [] when the event is fully instrumented.
    """
    gaps = []
    attendees = [a for a in (ev.get("attendees") or [])
                 if isinstance(a, dict)]
    external = [a for a in attendees
                if a.get("email")
                and not str(a["email"]).lower().endswith(
                    ("mwmcreations.com", "mwmscreens.com"))
                and "group.calendar.google.com" not in str(a["email"]).lower()]

    # ── the Coach Fly failure: nobody was ever invited ──
    if not external:
        gaps.append("NO ATTENDEE — no invite was ever sent, no RSVP is possible, "
                    "and the RSVP watcher filters on attendees so it can never "
                    "see this event")

    # ── the Robinson failure: reachable, but anonymous ──
    desc = str(ev.get("description") or "")
    has_lead_line = any(l.strip().lower().startswith("lead:")
                        for l in desc.split("\n"))
    if not has_lead_line and not resolved_name:
        gaps.append("ANONYMOUS — no 'Lead:' line in the description and no lead "
                    "record matched the attendee, so reminders greet the client "
                    "as 'there'")

    # ── PATCH #45D — the reminder checks that used to live here are GONE.
    # They asked whether the event carried an email override at 1440 minutes.
    # That field is private to whoever wrote it and has never reached a
    # client, so an event could pass this check and still be completely
    # un-remindable. Scoring on it did not merely fail to help — it produced
    # false confidence, which is why the ladder went unquestioned for a week.
    # What replaces it is the attendee check above (that address is what the
    # email rail actually sends to) and the RSVP check below.

    # ── RSVP ──
    pending = [a.get("email", "?") for a in external
               if a.get("responseStatus") == "needsAction"]
    if pending:
        gaps.append("RSVP unanswered: " + ", ".join(pending))

    if not (ev.get("location") or "").strip() and not ev.get("conferenceUrl"):
        gaps.append("no location and no meeting link")

    return gaps


def gap_severity(gaps):
    """'critical' when the event cannot reach the client at all, 'warn' when
    it can but is degraded, 'ok' when clean. Drives whether a sweep pages or
    merely lists."""
    if not gaps:
        return "ok"
    # PATCH #45D — only NO ATTENDEE is critical now.
    #
    # "NO REMINDERS AT ALL" is gone entirely: it measured a field that reaches
    # nobody. ANONYMOUS is a WARN, not a critical — a client greeted as "there"
    # still receives the message, which is a quality defect, not an outage.
    # Calling both critical is how the first live sweep produced 18 criticals
    # and buried the one that mattered.
    for g in gaps:
        if g.startswith("NO ATTENDEE"):
            return "critical"
    return "warn"


# ══════════════════════════════════════════════════════════════════════════
# PATCH #44B · EXECUTING THE PLAN THAT #39 ARMED
#
# Patch #39 computed `outcome_plan()` and stored the result on the lead record
# as `outcome_seq`. It said, in a comment, that "the sender (Patch #40)" would
# consume it. Patch #40 turned out to be the lead-resolution fix. Nobody built
# the sender.
#
# Verified Aug 3, 2026: `outcome_seq` is WRITTEN in exactly one place
# (app.py:16797) and READ in zero. Every outcome except studio_package_pitched
# — which has its own sender in studio_package.py — armed a sequence that was
# described in Slack, saved to the record, and then never executed. Follow-up
# nudges, no-show rebooks, the day-7 review ask, and every email-capture step
# have been dead since #39 shipped on Aug 3.
#
# This section is the pure, testable half of the fix: given a stored sequence
# and a clock, which step is due, and when does the whole thing stop. The
# sending lives in outcome_sender.py, which imports these and nothing else.
# ══════════════════════════════════════════════════════════════════════════

# A step whose delay elapsed more than this long ago is not "due" — it is
# stale. Firing a same-day no-show rebook four days late is worse than not
# firing it: it reads as a machine that lost track, and #39's own reasoning
# was that speed IS the value. Stale steps are skipped and reported.
STEP_STALE_AFTER_HOURS = 72


def booked_after(rec, armed_at):
    """True only when this record's booking provably POSTDATES the sequence.

    PATCH #49B. `booked` is set at booking creation and never cleared, so on
    its own it means "booked at some point in history" — including the very
    meeting whose follow-up we just armed. #48B treated it as "has a
    commitment, leave them alone" and cancelled Rodolfo Silva's Thursday nudge
    in production within ten minutes of shipping.

    No `booked_at` means NO STOP. That is deliberate. Legacy records have no
    timestamp, and the two failure modes are not symmetrical: a wrongly SENT
    nudge is one warm email that says "checking in", while a wrongly STOPPED
    sequence is permanent, silent, and indistinguishable from the automation
    never having existed. When we cannot tell, keep the rail running.
    """
    at = str((rec or {}).get("booked_at") or "").strip()
    if not at or not armed_at:
        return False
    try:
        return at > str(armed_at)
    except Exception:
        return False


def seq_stop_reason(rec, seq=None):
    """Why this sequence must stop NOW, or "" to continue.

    Checked before any timing. A lead who booked, paid, replied or asked to be
    left alone must never receive the next scheduled touch — that is the
    failure everyone actually notices.
    """
    rec = rec or {}
    seq = seq if seq is not None else (rec.get("outcome_seq") or {})
    if not isinstance(seq, dict):
        return "sequence record is malformed"
    if seq.get("done"):
        return "already finished"
    if rec.get("do_not_contact"):
        return "lead is on do-not-contact"
    if rec.get("outcome") == "Won" or rec.get("product"):
        return "lead converted"
    # PATCH #49B — was `if rec.get("booked")`, which stopped the sequence for
    # anyone who had EVER booked. Since a follow_up sequence is armed straight
    # after a meeting the lead booked, that condition is true almost by
    # definition, and it fails silently. Now it must be a booking made SINCE
    # the sequence was armed.
    if rec.get("booked") and booked_after(rec, seq.get("armed_at")):
        return "lead booked again after this sequence was armed"
    # A reply is the loudest possible stop signal: the sequence exists to
    # provoke one, so continuing after it arrives is talking over the answer.
    if seq.get("armed_at") and rec.get("last_message_time"):
        try:
            if str(rec["last_message_time"]) > str(seq["armed_at"]):
                return "lead replied after the sequence was armed"
        except Exception:
            pass
    return ""


def sibling_stop_reason(rec, siblings, armed_at=None):
    """Why a DIFFERENT record for the same human should stop this sequence.

    PATCH #48B. `seq_stop_reason` reads the record the sequence sits on, which
    is correct right up until the same person exists twice.

    Live case, Aug 4 2026: /admin/lead-seq returned two Rodolfo Silva records.
    One carries the business name and `booked: true`. The other is thinner and
    carries the armed sequence, and it says `booked: false`. So the booking is
    invisible to the sequence, and he could book on the 7th and still be asked
    on the 11th where things stand.

    Deduplicating the store is a separate, riskier job. Reading across the
    duplicates costs nothing and closes the failure today.

    `siblings` is every OTHER record that plausibly refers to the same person.
    The caller decides that — this stays pure.
    """
    for sib in (siblings or []):
        if not isinstance(sib, dict) or sib is rec:
            continue
        if sib.get("do_not_contact"):
            return "a duplicate record for this person is on do-not-contact"
        if sib.get("outcome") == "Won" or sib.get("product"):
            return "a duplicate record for this person has already converted"
        # PATCH #49B — this line, as written in #48B, cancelled Rodolfo Silva's
        # Thursday nudge. His twin record carries `booked: true` from the very
        # studio visit whose follow-up we had just armed. A duplicate's booking
        # only counts if it happened SINCE the sequence started.
        if sib.get("booked") and booked_after(sib, armed_at):
            return "a duplicate record for this person booked after this sequence was armed"
    return ""


def next_due_step(seq, hours_since_armed):
    """(index, (after_hours, channel, kind), status) for the step to act on.

    status is one of:
      'due'      send it
      'waiting'  the next step exists but its delay has not elapsed
      'stale'    its delay elapsed too long ago to be worth sending
      'finished' every step has been taken

    Never skips ahead: only `next_step` is ever considered, so the steps of a
    sequence always fire in order even if the process was down for a day.
    """
    if not isinstance(seq, dict):
        return None, None, "finished"
    steps = seq.get("steps") or []
    try:
        idx = int(seq.get("next_step", 0))
    except (TypeError, ValueError):
        idx = 0
    if idx < 0 or idx >= len(steps):
        return None, None, "finished"
    step = steps[idx]
    try:
        after_hours = float(step[0])
    except (TypeError, ValueError, IndexError):
        return idx, step, "stale"
    try:
        elapsed = float(hours_since_armed)
    except (TypeError, ValueError):
        return idx, step, "waiting"
    if elapsed < after_hours:
        return idx, step, "waiting"
    if elapsed - after_hours > STEP_STALE_AFTER_HOURS:
        return idx, step, "stale"
    return idx, step, "due"


def mask_contact(value):
    """Enough to confirm WHO, never enough to contact them.

    PATCH #47. The inspection endpoint exists so a defect can be diagnosed
    without a deploy; it must not also become a way to pull contact details out
    of production if the admin secret ever leaks. "rodolfos@nestseekers.com"
    -> "rod…@nestseekers.com"; "14075551234" -> "…1234".
    """
    v = str(value or "").strip()
    if not v:
        return ""
    if "@" in v:
        local, _, domain = v.partition("@")
        head = local[:3] if len(local) > 4 else local[:1]
        return f"{head}…@{domain}"
    return "…" + v[-4:] if len(v) > 4 else "…"


def seq_should_close(seq, days_since_armed):
    """True when the sequence has outlived its close_after_days window.

    #39 gave every sequence an ending on purpose — the complaint it was
    written against was rails that chase forever. Closing is a feature.
    """
    if not isinstance(seq, dict):
        return False
    cad = seq.get("close_after_days")
    if not cad:
        return False
    try:
        return float(days_since_armed) >= float(cad)
    except (TypeError, ValueError):
        return False


# Client-facing sends are held outside these hours, local time. Patch #44B
# shipped at midnight; without this the first pass would have fired a no-show
# rebook offer at 12:05 AM. A rail that messages people while they sleep reads
# as a machine that got loose, and undoes the warmth the copy is written for.
SEND_WINDOW_START_HOUR = 8
SEND_WINDOW_END_HOUR = 20


def within_send_window(dt, start_hour=SEND_WINDOW_START_HOUR,
                       end_hour=SEND_WINDOW_END_HOUR):
    """True when it is a civilised hour to message a client, LOCAL time.

    Held, never skipped: a step delayed until morning is still sent, and the
    72h staleness budget is far wider than the longest possible hold.

    PATCH #60 — the hour is read in LOCAL time, whatever it is handed. An
    aware datetime is converted first; a naive one is taken at face value as
    already-local. Callers used to reach `.hour` on a naive UTC clock and get
    an answer that was right four hours before it was true. `/admin/lead-seq`
    passes an AWARE datetime and `outcome_sender` passes a naive one, so this
    function has to be correct for both or the two will keep disagreeing.
    """
    dt = to_local_naive(dt)
    try:
        hour = dt.hour
    except AttributeError:
        return False
    return start_hour <= hour < end_hour


# ══════════════════════════════════════════════════════════════════════
# PATCH #57 — two things Maya was allowed to do, and should not be
#
# Both came out of one real conversation (Gian Hernandez, IG DM, Aug 5):
#
#   1. The lead opened with pricing, could not afford it, and pivoted to
#      "are y'all willing to do a business exchange if I advertise for
#      y'all on my YouTube channel?" Maya answered by offering three
#      strategy-call slots and telling him "Michael loves creative
#      partnerships." Michael does not take barter proposals on calls,
#      and Maya has no standing to characterise his appetite for a deal.
#      Exchange proposals go to an inbox, in writing, or they do not go.
#
#   2. She then BOOKED a phone call for a lead whose only identifier was
#      an Instagram-scoped ID. The event location reads "Michael will
#      dial the number on this booking". There was no number. The rail
#      already knew — reminder_channel_for() wrote the note "IG-scoped
#      identifier — WhatsApp impossible" onto the event — but nothing
#      stopped the booking. A call you cannot place is not a booking,
#      it is a no-show with a calendar entry.
# ══════════════════════════════════════════════════════════════════════

PARTNERSHIP_INBOX = "info@mwmcreations.com"

# TIER 1 — the shape of an actual barter offer. Something is being given
# INSTEAD OF money. These block a booking outright.
#
# Deliberately about the SHAPE, not the vocabulary: "partnership" on its
# own is not here, because a lead saying "I'm looking for a video partner"
# usually means a paying engagement, and blocking those would cost real
# money. Bare partnership language is TIER 2 below.
_BARTER_HARD = re.compile(
    r"(barter"
    r"|permuta"
    r"|\btroca\b|\btrocar\b"
    r"|business\s+exchange"
    r"|service\s+exchange"
    r"|exchange\s+of\s+services"
    r"|in\s+exchange\s+for"
    r"|in\s+return\s+for"
    r"|trade\s+(you|services|service|work|for)"
    r"|swap\s+(services|service|work)"
    r"|(instead\s+of|rather\s+than)\s+(paying|payment|money|cash)"
    r"|(free|comp(ed)?|no\s+charge|discount(ed)?)\s+in\s+(exchange|return)"
    r"|(advertis\w+|promot\w+|shout\s*out|expos\w+)[^.?!]{0,40}\b(in\s+)?(exchange|return|instead)"
    r"|(exchange|return)[^.?!]{0,40}\b(advertis\w+|promot\w+|shout\s*out|expos\w+)"
    r")",
    re.I,
)

# TIER 2 — words that MIGHT be a barter approach and might be an ordinary
# paying enquiry. These never block. They tell Maya to ask one question
# before she offers anyone a time.
_BARTER_SOFT = re.compile(
    r"(partnership|partner\s+(with|up)"
    r"|parceria"
    r"|collab(orat\w+)?"
    r"|sponsor(ship|ed)?"
    r"|affiliate"
    r"|revenue\s+share|rev\s*share"
    r"|commission\s+(only|based)"
    r")",
    re.I,
)

BARTER_NONE = "none"
BARTER_MAYBE = "maybe"
BARTER_YES = "yes"


def barter_signal(text):
    """Classify one message: BARTER_YES / BARTER_MAYBE / BARTER_NONE."""
    if not text:
        return BARTER_NONE
    s = str(text)
    if _BARTER_HARD.search(s):
        return BARTER_YES
    if _BARTER_SOFT.search(s):
        return BARTER_MAYBE
    return BARTER_NONE


def barter_signal_in_history(messages, lookback=14):
    """Scan a conversation and return the strongest signal the LEAD gave.

    Only inbound turns are read. This is not fussiness — MWM's own sales
    copy says "One partnership = dozens of compliant clients", so scanning
    assistant turns would flag every property-management pitch Maya has
    ever made as a barter approach.

    `messages` is the usual [{"role": ..., "content": ...}] list. Content
    that arrives as a list of blocks (the tool-use shape) is flattened.
    """
    if not messages:
        return BARTER_NONE
    strongest = BARTER_NONE
    for m in list(messages)[-lookback:]:
        try:
            if (m.get("role") or "").lower() != "user":
                continue
            content = m.get("content")
        except AttributeError:
            continue
        if isinstance(content, list):
            parts = []
            for blk in content:
                if isinstance(blk, dict):
                    parts.append(str(blk.get("text") or ""))
                else:
                    parts.append(str(blk))
            content = " ".join(parts)
        sig = barter_signal(content)
        if sig == BARTER_YES:
            return BARTER_YES
        if sig == BARTER_MAYBE:
            strongest = BARTER_MAYBE
    return strongest


def barter_refusal_note(lead_name=None):
    """What Maya is told when she tries to book a barter lead.

    Addressed to Maya, not to the lead: it has to end the booking attempt
    AND give her the next sentence, or she will improvise one.
    """
    who = f" {lead_name}" if lead_name else ""
    return (
        "BOOKING REFUSED — this lead has proposed an exchange, barter or "
        "trade rather than payment. MWM does not take those on calls or "
        "studio visits, and you must not offer times, check availability, "
        "or say anything about how Michael feels about partnerships. "
        f"Tell{who} this instead, in your own words: it is not something "
        "you can set up yourself, and the way to put a proposal in front "
        f"of the team is to email {PARTNERSHIP_INBOX} with what they would "
        "provide, what they would want from MWM, and their audience "
        "numbers — Michael reads that inbox and will reply himself. "
        "Then stop. Do not book, do not offer to follow up, do not promise "
        "a date for a reply."
    )


def barter_clarify_note():
    """TIER 2. Not a refusal — one question before any time is offered."""
    return (
        "CAUTION — this lead has used partnership/collaboration language, "
        "which may or may not mean they intend to pay. Before you offer "
        "any times, ask one plain question: is this a paid engagement, or "
        "are they proposing an exchange of services? If it is an exchange, "
        f"send them to {PARTNERSHIP_INBOX} and do not book."
    )


# ── the number you are going to dial ─────────────────────────────────

# Appointment types where Michael places a call. The event location for
# these reads "Michael will dial the number on this booking", so a
# booking without a dialable number is a promise nobody can keep.
CALL_APPOINTMENT_TYPES = ("strategy_call",)


def booking_needs_number(appointment_type):
    """True when this appointment type cannot happen without a phone number."""
    return str(appointment_type or "").strip().lower() in CALL_APPOINTMENT_TYPES


def resolve_callback_number(appointment_type, identifier=None, callback=None):
    """Decide what number this booking will actually be placed on.

    Returns (ok, number, reason).

    `callback` is a number the lead gave in words — it wins, because it
    was volunteered for exactly this purpose. `identifier` is the thread
    identifier, which is a phone number on WhatsApp and an IGSID on
    Instagram; it is used only when it is genuinely dialable.

    ok is False only for appointment types that need a number and have
    none. A studio visit resolves ok=True with number=None: the lead is
    walking through the door, and refusing an in-person booking over a
    missing phone number would cost more than it saves. The caller still
    gets the reason, and should report it.
    """
    needs = booking_needs_number(appointment_type)

    if callback and is_dialable(callback):
        return True, str(callback).strip(), "callback number supplied by the lead"

    if callback and not is_dialable(callback):
        why = ("the number given is Instagram-scoped, not a phone number"
               if is_ig_scoped(callback)
               else "the number given is not a usable phone number")
        if needs:
            return False, None, why
        return True, None, why

    if identifier and is_dialable(identifier):
        return True, str(identifier).strip(), "thread identifier is a dialable number"

    if needs:
        if is_ig_scoped(identifier):
            return False, None, (
                "Instagram thread — the identifier is an IGSID, not a phone "
                "number, and no callback number was collected"
            )
        return False, None, "no dialable number on this booking"

    return True, None, "no phone number on file (not required for this type)"


def missing_number_note(appointment_type, reason=""):
    """What Maya is told when she tries to book a call with no number."""
    tail = f" ({reason})" if reason else ""
    return (
        f"BOOKING REFUSED — a {appointment_type.replace('_', ' ')} is a phone "
        f"call that Michael places, and there is no number to call{tail}. "
        "Ask the lead for the best phone number to reach them on, including "
        "country code, then book again with that number in callback_phone. "
        "Do not confirm any time until you have it. If they will not give a "
        "number, do not book — tell them Michael will follow up by email."
    )


# ══════════════════════════════════════════════════════════════════════
# PATCH #58 — "I'll check with Michael" was never wired to anything
#
# The Andrea Battis thread, Aug 3–6. A lead needed an evening call.
# check_specific_slot() answered {"available": False, "reason": "outside
# business hours"} — a WALL, with no path through it. Maya, having no tool
# that could ask a human anything, improvised: "let me flag this for him",
# "I'll follow up with Michael tonight". Nothing was created, because
# nothing existed to create.
#
# Then the follow-up rail made it worse than silence. Three automated
# messages went to Andrea over three days — "still working on pinning
# down an evening", "I'll have an answer for you shortly" — each one
# manufacturing the appearance of progress on a request that did not
# exist anywhere. Michael found it by chance, reading Instagram himself.
#
# So this module gives the promise somewhere to land:
#   · out-of-hours is a REQUEST, not a refusal
#   · a request Michael has not answered CANNOT be described to a lead
#     as flagged, pending, or being worked on
#   · unanswered requests get louder as the slot approaches, and are
#     visible in the daily health check
#   · when every option has passed, the lead is told the truth
# ══════════════════════════════════════════════════════════════════════

# Standard bookable hours, ET. These are not invented here — they are the
# hours check_specific_slot() already enforces (weekday, 9 <= hour < 17)
# and the only hours get_available_slots() ever offers (10, 11, 14, 15).
# Stated once, so the approval path and the booking path cannot drift.
STANDARD_HOURS_START = 9
STANDARD_HOURS_END = 17

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_DECLINED = "declined"
APPROVAL_EXPIRED = "expired"


def is_out_of_hours(dt, start_hour=STANDARD_HOURS_START, end_hour=STANDARD_HOURS_END):
    """True when this datetime falls outside standard bookable hours.

    Weekends are out of hours in full. `dt` must already be in ET — this
    function does NOT convert, because guessing a timezone here is how the
    07:55 send happened this morning.
    """
    try:
        if dt.weekday() >= 5:
            return True
        return not (start_hour <= dt.hour < end_hour)
    except AttributeError:
        return False


def out_of_hours_reason(dt):
    """Why this slot needs a human, in words a lead could be told."""
    try:
        if dt.weekday() >= 5:
            return "weekend"
        if dt.hour < STANDARD_HOURS_START:
            return "before standard hours"
        return "evening — after standard hours"
    except AttributeError:
        return "outside standard hours"


def build_approval_request(request_id, token, lead_name, lead_email, lead_phone,
                           slots, business="", note="", channel="",
                           created_at=None):
    """A pending approval request. Pure data — no I/O, no clock.

    `slots` is a list of ISO-8601 ET datetime strings, in the order the
    lead prefers them. `token` is the unguessable half of the one-tap
    approve link and is never shown to the lead.
    """
    return {
        "id": str(request_id),
        "token": str(token),
        "status": APPROVAL_PENDING,
        "lead_name": lead_name or "",
        "lead_email": lead_email or "",
        "lead_phone": lead_phone or "",
        "business": business or "",
        "channel": channel or "",
        "note": note or "",
        "slots": list(slots or []),
        "chosen_slot": None,
        "created_at": created_at,
        "notified_at": None,
        "reminders_sent": 0,
        "resolved_at": None,
        "lead_told_at": None,
    }


def approval_is_open(req):
    """True while this request is still waiting on Michael."""
    try:
        return req.get("status") == APPROVAL_PENDING
    except AttributeError:
        return False


def approval_live_slots(req, now):
    """The requested slots that have not yet passed. `now` must be ET-aware."""
    out = []
    for s in (req or {}).get("slots") or []:
        parsed = _parse_et(s)
        if parsed is not None and parsed > now:
            out.append(s)
    return out


def _parse_et(s):
    """Parse an ISO string, or return None. Never raises, never guesses a tz."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def approval_has_expired(req, now):
    """True when every slot the lead offered is in the past.

    An expired request is not a silent close — the lead must be told, which
    is what `lead_told_at` tracks.
    """
    if not approval_is_open(req):
        return False
    if not (req.get("slots") or []):
        return False
    return not approval_live_slots(req, now)


# Escalating reminder cadence. The point is that a request gets LOUDER as
# the slot approaches, because the cost of silence rises: three days of
# quiet is what happened to Andrea, and a 4-hourly nag would have caught
# it on day one.
#
#   soonest slot is >48h away  → remind every 12h
#   24–48h away                → every 6h
#   6–24h away                 → every 3h
#   <6h away                   → every hour
REMINDER_TIERS = (
    (48, 12),
    (24, 6),
    (6, 3),
    (0, 1),
)


def approval_reminder_interval_hours(req, now):
    """How often to re-notify, based on how close the soonest live slot is.

    Returns None when there is nothing left to remind about.
    """
    live = approval_live_slots(req, now)
    if not live:
        return None
    soonest = min(d for d in (_parse_et(s) for s in live) if d is not None)
    hours_out = (soonest - now).total_seconds() / 3600.0
    for threshold, interval in REMINDER_TIERS:
        if hours_out > threshold:
            return interval
    return REMINDER_TIERS[-1][1]


def approval_reminder_due(req, now):
    """True when Michael should be nudged again about this request."""
    if not approval_is_open(req):
        return False
    interval = approval_reminder_interval_hours(req, now)
    if interval is None:
        return False
    last = _parse_et(req.get("notified_at"))
    if last is None:
        return True
    return (now - last).total_seconds() >= interval * 3600.0


# ── the anti-stalling gate ───────────────────────────────────────────
#
# This is the half that made the Andrea failure worse than a plain miss.
# Maya may describe a request to a lead ONLY when a real one exists. No
# request, no "I've flagged it", no "still working on it", no "as soon as
# he confirms". The rail must not generate progress updates for work that
# is not happening.

_STALL_CLAIMS = re.compile(
    # "flag this for him" / "flagged all three nights for him" — the bare verb
    # and an arbitrary object between it and the person, both of which the
    # first version of this pattern missed on Andrea's real messages.
    r"(flag(g(ed|ing))?\b[^.?!]{0,40}?\b(for|with)\s+(him|her|michael)"
    # "his personal green light", "it needs his personal OK" — the approval
    # noun is often nowhere near Michael's name.
    r"|\b(his|michael'?s?)\s+(own\s+|personal\s+)?"
    r"(green\s*light|ok|okay|approval|go[- ]ahead|sign[- ]?off|blessing)\b"
    r"|(check|checking|confirm\w*|clear\w*)\s+with\s+michael"
    r"|(ask|asking|asked)\s+michael"
    r"|(as\s+soon\s+as|the\s+second|the\s+moment|once)\s+(he|michael)\s+"
    r"(picks|confirms|approves|says|gets\s+back|answers|decides)"
    r"|(still|just)\s+(working|chasing|waiting)\s+on"
    r"|(i'?ll|i\s+will)\s+(follow\s+up\s+with|get\s+back\s+to\s+you|have\s+an\s+answer)"
    r"|haven'?t\s+forgotten\s+you"
    r"|i'?ll\s+(pass|flag)\s+(that|this|it)\s+along"
    r")",
    re.I,
)


def claims_pending_approval(text):
    """True if this outbound message tells a lead a human is deciding.

    Used to gate Maya's own words and the follow-up rail's generated
    nudges. Every phrase in the pattern was said to Andrea while nothing
    was pending.
    """
    if not text:
        return False
    return bool(_STALL_CLAIMS.search(str(text)))


def stall_message_allowed(text, open_request):
    """(allowed, why) — may this message go to the lead?

    A message that claims an approval is pending is allowed ONLY when a
    real pending request backs it up. Everything else passes untouched:
    this gate is narrow on purpose, because a false positive silences a
    legitimate reply.
    """
    if not claims_pending_approval(text):
        return True, ""
    if open_request and approval_is_open(open_request):
        return True, f"backed by open request {open_request.get('id')}"
    return False, (
        "REFUSED — this message tells the lead that Michael is deciding "
        "something, and there is no open approval request for them. Either "
        "file one with request_out_of_hours_approval and then say so, or say "
        "nothing about Michael deciding. Do not promise a human's answer you "
        "have not asked for."
    )


def no_approval_tool_note(lead_name=None):
    """What Maya is told when she hits an out-of-hours wall."""
    who = f" {lead_name}" if lead_name else ""
    return (
        f"That time is outside standard hours (weekdays "
        f"{STANDARD_HOURS_START}:00–{STANDARD_HOURS_END}:00 ET), so you cannot "
        "book it yourself — but this is NOT a dead end and you must not tell "
        f"{who.strip() or 'the lead'} it is unavailable. Ask which evenings or "
        "times would work, then call request_out_of_hours_approval with those "
        "slots. That emails Michael a one-tap approval. Only AFTER the tool "
        "returns a request id may you tell the lead that Michael is looking at "
        "it. Never say you have flagged something you have not filed."
    )


def approval_filed_note(request_id, slots_display):
    """What Maya is told once a request really exists."""
    return (
        f"Request {request_id} filed with Michael for: {slots_display}. "
        "You may now tell the lead that Michael is choosing between those "
        "times and that you will confirm here as soon as he picks one. Do not "
        "give a deadline for his answer. Do not offer any of these times as "
        "booked until the approval comes back."
    )


def approval_expiry_note(req):
    """The honest message when every option has passed unanswered.

    A lead who was told 'shortly' three days ago is owed a real close, not
    another nudge.
    """
    name = (req or {}).get("lead_name") or "there"
    return (
        f"Every time {name} offered has now passed without an answer from "
        "Michael. Tell them plainly that you were not able to get an evening "
        "confirmed, apologise for the wait, and offer standard hours "
        f"(weekdays {STANDARD_HOURS_START}:00–{STANDARD_HOURS_END}:00 ET) — or "
        "offer to take it by email. Do NOT send another 'still working on it'."
    )


def approval_health_line(req, now):
    """One line for the daily health check, so this cannot go quiet again."""
    age_h = ""
    created = _parse_et((req or {}).get("created_at"))
    if created is not None:
        age_h = f", {int((now - created).total_seconds() // 3600)}h old"
    live = approval_live_slots(req or {}, now)
    return (
        f"{(req or {}).get('id')} · {(req or {}).get('lead_name') or 'unknown lead'}"
        f" · {len(live)} of {len((req or {}).get('slots') or [])} slots still live"
        f"{age_h} · {(req or {}).get('status')}"
    )


# ══════════════════════════════════════════════════════════════════════
# PATCH #59 — a service account cannot invite attendees, and the portal
# booking path had no fallback for it
#
# Vanessa Serrano booked Aug 21 through the client portal at 10:17 on
# Aug 6. WordPress fired the webhook, the webhook ran, and Google
# answered:
#
#   403 forbiddenForServiceAccounts — "Service accounts cannot invite
#   attendees without Domain-Wide Delegation of Authority."
#
# The insert threw, so NO EVENT WAS CREATED AT ALL. The studio read as
# free from 12:00 to 15:00 on a day a paying client had booked it.
#
# Why it had never fired before: of 16 portal bookings, the only other
# failure was a QA test. Todd Berger's #56 on Jul 27 succeeded because
# that event carried NO attendee — Patch #30's own notes say so. The
# rail hardening that started genuinely attaching clients as attendees
# landed after Jul 27, so Vanessa's was the FIRST real booking to take
# the new path. Every portal booking after it would have failed too.
#
# book_appointment already solved this exact problem with a three-step
# ladder (DWD -> attendees, no invites -> no attendees). The portal
# webhook had one attempt and no fallback. This module supplies the
# decision so both paths can share it and it can be tested without a
# Google client.
# ══════════════════════════════════════════════════════════════════════

# The precise Google signature. Matching on the reason string rather than
# the prose, because Google rewords messages and this must not go quiet.
_DWD_MARKERS = (
    "forbiddenforserviceaccounts",
    "cannot invite attendees without domain-wide delegation",
)


def is_attendee_permission_error(err):
    """True when this failure is 'you may not add attendees', nothing else.

    Deliberately narrow. A quota error, a bad date or an auth failure must
    NOT be swallowed by the attendee fallback — retrying those without
    attendees would just fail again while looking like a degraded success.
    """
    if err is None:
        return False
    s = str(err).lower()
    return any(m in s for m in _DWD_MARKERS)


def strip_attendees(body):
    """A copy of the event body with attendees removed, for the retry.

    The event itself is what protects the studio from being double-booked.
    The invite is a courtesy the portal has already delivered by email. If
    only one can survive, it is the event.
    """
    out = dict(body or {})
    out.pop("attendees", None)
    return out


def attendee_fallback_note(client_email=None):
    """Explains, on the event, why the client is not an attendee."""
    who = f" ({client_email})" if client_email else ""
    return (
        f"NOTE: the client{who} could not be added as a calendar attendee — "
        "the booking service account lacks Domain-Wide Delegation, so Google "
        "refuses any insert carrying attendees. The event was created WITHOUT "
        "attendees so the studio time is blocked. The client already has the "
        "confirmation email WordPress sent, so they are not left uninformed. "
        "Granting Domain-Wide Delegation would restore real calendar invites."
    )


def booking_sync_alert(name, when, booking_id, calendar_state, degraded_reason=""):
    """The #matt line for a portal booking.

    The old text said "No action needed" unconditionally — including on the
    run where the calendar write had just failed and the studio was left
    looking free. An alert that tells you to ignore a failure is worse than
    no alert.
    """
    if calendar_state == "ok":
        return (f"📅 *STUDIO BOOKING* — {name}: {when} · portal booking "
                f"#{booking_id} · calendar ✅ · confirmation email sent by WP. "
                "No action needed.")
    if calendar_state == "degraded":
        return (f"📅 *STUDIO BOOKING* — {name}: {when} · portal booking "
                f"#{booking_id} · calendar ✅ *without the client invite* "
                f"({degraded_reason}) · confirmation email sent by WP. "
                "The studio time IS blocked. No action needed today, but "
                "calendar invites stay off until Domain-Wide Delegation is "
                "granted to the booking service account.")
    return (f"🔴 *STUDIO BOOKING — CALENDAR WRITE FAILED* — {name}: {when} · "
            f"portal booking #{booking_id} · {degraded_reason or 'see #dev'}\n"
            "*The studio reads as FREE for this slot and can be double-booked.* "
            "The client has their confirmation email and believes it is booked. "
            "ACTION NEEDED: add the event by hand, or fix the sync.")


# ═══════════════════════════════════════════════════════════════════════
# PATCH #71 — AD_09: is this lead here for the $349 offer?
#
# Michael's ruling, Aug 8 2026, verbatim:
#   "I want Maya to keep sending clients to the studio and I will close them,
#    because my chances of closing studio packages are way higher... but for
#    this offer we need Maya to be very focused on the offer. Leads coming
#    from this offer need to be attacked to purchase this offer. All others,
#    she needs to do the same process that she's doing right now."
#
# So this predicate is deliberately NARROW. A false NEGATIVE is cheap: the lead
# falls into the normal flow and gets invited to the studio, which is Michael's
# best closing tool anyway. A false POSITIVE is expensive: someone who wanted a
# conversation gets a payment link, which reads as not listening.
#
# WHY NOT JUST USE ad_id: capture is live (S27, both legs) but on Aug 8 the
# lead sheet showed column U empty on every August row. Until that is fixed,
# ad_id alone would identify nobody. So ad_id is checked FIRST and trusted when
# present, with offer-specific language as the fallback.
#
# Generic studio interest — "how much is the studio", "can I book time" — must
# NOT match. That lead belongs to Michael's room, not to a checkout link.
# ═══════════════════════════════════════════════════════════════════════

import re as _re71

# Phrases that only someone who saw THIS offer would use. Each is checked
# against the lead's own words, lowercased.
_AD09_STRONG = (
    "nothing to sign",
    "studio hour",
    "one hour with editing",
    "hour with editing",
    "filmed and edited",
    "film and edit",
)

_AD09_AD_MENTION = _re71.compile(
    r"\b(saw|seen|watched|from)\s+(your|the|an|this)\s+(ad|advert|advertisement|reel|video)\b"
    r"|\byour\s+ad\b|\bthe\s+ad\b|\bad\s+on\s+(instagram|facebook|ig|whatsapp)\b",
    _re71.I,
)

# $349 written as money. A bare "349" is NOT enough — it shows up inside phone
# numbers and addresses, and a mis-fire here costs a real conversation.
_AD09_PRICE = _re71.compile(
    r"\$\s?349\b|\b349\s?(dollars|usd|bucks)\b|\b349\s?\$",
    _re71.I,
)


def ad09_lead(ad_id=None, messages=None, ad09_ad_ids=None):
    """Is this lead here for the AD_09 $349 offer? -> (bool, reason).

    `ad_id`        the Meta ad id captured at inbound (may be empty today).
    `messages`     the lead's OWN messages. Never pass Maya's replies in —
                   she says "$349" herself, and matching on that would latch
                   the branch on permanently after the first mention.
    `ad09_ad_ids`  iterable of ad ids that count as AD_09.

    Returns (False, "") when nothing matches, so the caller can log WHY a lead
    did or did not get the offer branch instead of guessing later.
    """
    ids = {str(x).strip() for x in (ad09_ad_ids or ()) if str(x).strip()}
    aid = str(ad_id or "").strip()
    if aid and ids and aid in ids:
        return True, "ad_id"

    for raw in (messages or ()):
        text = str(raw or "").lower()
        if not text:
            continue
        if _AD09_PRICE.search(text):
            return True, "price"
        for phrase in _AD09_STRONG:
            if phrase in text:
                return True, "phrase:" + phrase
        if _AD09_AD_MENTION.search(text):
            return True, "ad_mention"
    return False, ""


# ═══════════════════════════════════════════════════════════════════════
# PATCH #72 — A TALLY, BECAUSE SILENT FAILURE IS THE HOUSE DEFECT
#
# On Aug 8 ERIC reported 12 conversations across Aug 4–8 that produced ZERO
# pipeline rows. Tracing it found the shape of the problem, but not the cause,
# because BOTH candidate explanations are invisible from outside:
#
#   (a) the row was never ATTEMPTED — `is_new_sender` is computed from an
#       in-memory dict, so "new" really means "new since the last restart"; or
#   (b) the row was attempted and the Sheets write THREW — and every writer is
#       wrapped in try/except that only print()s, so the failure goes to a
#       Railway log nobody reads and the conversation carries on perfectly.
#
# Those need opposite fixes. Guessing between them is how a wrong fix ships.
# This makes both countable from one curl of /health.
#
# Deliberately in-memory and deliberately NOT persisted: it answers "what is
# this process doing right now", resets on deploy, and must never become a
# thing that can fail and take a request with it. Every method swallows.
# ═══════════════════════════════════════════════════════════════════════

import threading as _threading72


class Tally:
    """Counters with a last-note and last-time, safe to call from any thread.

    bump() can NEVER raise. It sits on the inbound message path, and an
    observability counter that breaks the thing it observes is worse than no
    counter at all.
    """

    def __init__(self):
        self._lock = _threading72.Lock()
        self._counts = {}
        self._notes = {}
        self._times = {}

    def bump(self, name, note="", n=1):
        try:
            key = str(name)
            with self._lock:
                self._counts[key] = self._counts.get(key, 0) + int(n)
                if note:
                    self._notes[key] = str(note)[:200]
                self._times[key] = local_now().isoformat(timespec="seconds")
        except Exception:
            pass  # never break a caller
        return None

    def get(self, name):
        try:
            with self._lock:
                return self._counts.get(str(name), 0)
        except Exception:
            return 0

    def snapshot(self):
        """{name: {count, last, at}} — sorted, JSON-safe, never raises."""
        try:
            with self._lock:
                out = {}
                for k in sorted(self._counts):
                    row = {"count": self._counts[k]}
                    if k in self._notes:
                        row["last"] = self._notes[k]
                    if k in self._times:
                        row["at"] = self._times[k]
                    out[k] = row
                return out
        except Exception:
            return {}


# The one instance the app shares.
TALLY = Tally()


# Above this many consecutive already-known inbounds with zero rows
# attempted, "nobody new happened to write in" stops being a credible
# explanation. ERIC's real report was 12.
LEAD_ROW_GATE_SUSPECT_AT = 10


GREETING_FALLBACK = "there"

# Whitespace .strip() does not touch these. They are why a greeting can render
# as "Hi ," with nothing between the words.
_INVISIBLE = "".join((
    "\u200b\u200c\u200d\u200e\u200f",   # zero-width space/non-joiner/joiner, LTR/RTL marks
    "\u2060\ufeff",                       # word joiner, BOM
    "\u00a0\u2007\u202f",                # non-breaking spaces
    "\u180e\u061c",                       # Mongolian vowel separator, Arabic letter mark
))


def greeting_name(name, fallback=GREETING_FALLBACK):
    """The name to greet someone by. Never empty, never raises.

    ERIC, Aug 8 2026: every ad conversation opened on a greeting reading
    `"Hi ,"` — and he mapped it as systemic across 8+ templates. It sat for a
    week because the string is not in this repo: the Meta template holds
    `Hi {{1}},` and we supply {{1}}. Nothing was wrong with the template. We
    were handing it a character you cannot see.

    Two real defects, both reproduced Aug 15 before this was written:

      (name or "there").split()[0]
        · name = "   "     -> IndexError. A whitespace-only name did not
          degrade the greeting, it KILLED THE SEND. `or` only catches falsy,
          and "   " is truthy.
        · name = "\u200e"  -> returns "\u200e". `.strip()` removes whitespace,
          and a left-to-right mark is not whitespace. Meta renders the
          parameter as nothing at all: "Hi ,". IG display names are full of
          these — they arrive with emoji, ZWJ sequences and direction marks.

    So the guard everyone wrote is right about None and wrong about everything
    that merely LOOKS empty. This is the one place that decides, and it strips
    by what a reader would see rather than by what `str.strip()` knows about.
    """
    # `if name` rather than `is not None`: the guard this replaces was
    # `(name or "there")`, and 0 / False / [] must keep resolving to the
    # fallback. Widening that to "anything not None" would greet someone
    # "Hi 0," — a new defect introduced while fixing an old one. Caught by
    # test_greeting_name.py before it shipped, which is the point of it.
    n = str(name) if name else ""
    for ch in _INVISIBLE:
        n = n.replace(ch, " ")
    n = n.strip()
    # Patch #42: a record can hold two people — "Krista Neeley (with Michael
    # Neeley)". Greet the first one, never the parenthetical.
    n = n.split("(")[0].strip()
    parts = [p for p in n.split() if p.strip()]
    return parts[0] if parts else fallback


def lead_row_verdict(created=0, failed=0, skipped_dup=0, gate_not_new=0):
    """Turn the four counters into a plain-English reading. -> (state, why)

    This is the whole point of #72: the four numbers only mean something in
    relation to each other, and the reading should not depend on whoever is
    looking at them remembering the rules at 2am.
    """
    created, failed = int(created or 0), int(failed or 0)
    skipped_dup, gate_not_new = int(skipped_dup or 0), int(gate_not_new or 0)
    attempted = created + failed + skipped_dup

    if failed and not created:
        return "broken", ("every attempted lead row FAILED to write — the Sheets "
                          "call is throwing; read `last` for the error")
    if failed:
        return "degraded", "some lead-row writes are failing; read `last` for the error"
    if attempted == 0 and gate_not_new:
        # S84: before #76 this state had exactly one meaning — the gate was
        # broken. After #76 it has TWO, and they look identical from here:
        # (a) the gate is working and every inbound really was a returning
        # sender, or (b) the gate is broken again. Reporting (a) in the
        # language of (b) is the failure this project keeps paying for:
        # a known miss and a never-attempted must not look alike, and a
        # diagnostic that asserts a cause it cannot see is worse than none.
        if gate_not_new >= LEAD_ROW_GATE_SUSPECT_AT:
            return "suspect_gate", (
                f"{gate_not_new} inbound(s) and NOT ONE was treated as new. At "
                f"this volume that is improbable — suspect the durable "
                f"first-inbound set (#76), not the Sheets write. This is the "
                f"shape of ERIC's 12-conversations-zero-rows report.")
        return "all_returning", (
            f"{gate_not_new} inbound(s), each from a sender we had already "
            f"heard from, so no row was due. Nothing is known to be wrong. "
            f"This does NOT prove the first-inbound gate works — that needs "
            f"one genuinely NEW sender, and none has written in yet. Read it "
            f"again after {LEAD_ROW_GATE_SUSPECT_AT} inbounds.")
    if attempted == 0:
        return "idle", "no inbound leads since this process started"
    if created:
        return "ok", "lead rows are being written"
    return "dedup_only", ("rows were attempted but all were skipped as duplicates "
                          "— check the month-tab dedupe, not the write")


# ══════════════════════════════════════════════════════════════════════
# PATCH #74 · STUDIO-VISIT QUALIFICATION GATE
#
# Michael's order, MAYA.md §51, written Jul 29 2026 after Dondrique Lewis
# ($100 budget) reached the founder's calendar anyway:
#
#   "A stated budget below $249 does not get booked onto Michael's
#    calendar. DECLINING THE NUMBER IS NOT ENOUGH — THE BOOKING MUST NOT
#    HAPPEN."
#
# That rule lived only in MAYA.md, which is an agent notebook. The machine
# that actually talks to leads reads the prompt in app.py, and no budget,
# role or business check has ever existed on the studio-visit path. So on
# Aug 10 2026 it happened a second time: Joseph Joel Hernandez, a hobbyist
# musician with no business and no budget, took a 10 AM studio tour.
#
# Michael, after that hour: "we only bring the right type of leads —
# business owners, entrepreneurs, people that can spend at least $349."
#
# 🔑 Joseph is why ROLE is the load-bearing test, not budget. He never
# stated a number, so a budget-only rule would have let him through again.
# He carried a "business" too — "Cositø (proyecto musical)" — so a
# non-empty business string is not enough either.
# ══════════════════════════════════════════════════════════════════════

STUDIO_FLOOR_USD = 249      # the rate card. Nothing exists below it.

# ══════════════════════════════════════════════════════════════════════
# S84 · THE FLOOR IS SOURCE-CONDITIONAL
#
# Michael, Aug 10: "The real floor is 249, but we are having a campaign
# right now for 349 — so if they're leads coming from that campaign, the
# floor is 349 because of that specific campaign."
#
# A lead who arrived on a $349 promise and is then qualified at $249
# undercuts the campaign's own economics. A referral or a walk-in has
# made no such promise and is held to the rate card.
#
# 🔑 MATT's ticket said the blocker was that the lead record carries no
# campaign attribution. That is not what the code says. `ad_id`,
# `utm_campaign`, `ctwa_clid` and `ad_referral` have been captured at
# inbound time since S27 — on BOTH the WhatsApp and Instagram legs — and
# they sit on lead_data right now. What was missing was never the capture.
# It was that nothing ever READ them: the floor was a module constant, and
# #pipeline printed the channel without the campaign.
# Verify the object, not the label — including when the label is a ticket.
# ══════════════════════════════════════════════════════════════════════

CAMPAIGN_FLOOR_USD = 349    # the live campaign's own promise


def is_campaign_sourced(ad_id=None, utm_campaign=None, ad_referral=False):
    """True when this lead is attributable to a paid ad.

    Any ONE of the three is enough. They come from different Meta payload
    shapes (WhatsApp sends `source_id`, Instagram sends `ad_id` inside
    `referral`, and `ad_referral` is our own flag set when either fired),
    so requiring agreement between them would silently drop leads whose
    payload carried only one.
    """
    if bool(ad_referral):
        return True
    for v in (ad_id, utm_campaign):
        if str(v or "").strip():
            return True
    return False


def applicable_floor(ad_id=None, utm_campaign=None, ad_referral=False):
    """The dollar floor THIS lead must clear.

    Campaign-sourced leads are held to the campaign's number; everyone
    else to the rate card. Returns an int so it reads cleanly in the
    refusal copy Maya speaks aloud.
    """
    if is_campaign_sourced(ad_id, utm_campaign, ad_referral):
        return CAMPAIGN_FLOOR_USD
    return STUDIO_FLOOR_USD


def attribution_line(ad_id=None, utm_campaign=None, utm_source=None):
    """One line naming the ad that produced this lead, or "" if organic.

    Goes on the #pipeline record. Michael's complaint was that every entry
    read `Source: Instagram DM` whether the lead came from the $349
    campaign, an organic DM or a referral — indistinguishable at a glance,
    and he was reading each thread by hand to tell them apart.
    """
    camp = str(utm_campaign or "").strip()
    aid = str(ad_id or "").strip()
    src = str(utm_source or "").strip()
    if not (camp or aid):
        return ""
    bits = []
    if camp:
        bits.append(camp)
    if aid:
        bits.append(f"ad_id {aid}")
    if src and src.lower() not in ("ad", "ads"):
        bits.append(src)
    return "Campaign: " + " · ".join(bits)

# Roles that may be invited in person.
STUDIO_ROLES_ALLOWED = {
    "owner_founder",
    "executive_decision_maker",
    "marketing_lead",
    "professional_personal_brand",   # lawyer, doctor, coach, consultant,
}                                    # realtor — an EARNING practice

# Roles that get the free call instead. Never a refusal to the lead — a
# different door.
STUDIO_ROLES_BLOCKED = {
    "employee_no_authority",
    "freelancer_hobbyist_student",
    # S29 · PATCH #101 — Michael, Aug 15: a music artist or creator with no
    # stated budget is "call or link only", never his calendar.
    "artist_musician_creator",
    "music_artist",
    "artist",
    "creator",
}


# ══════════════════════════════════════════════════════════════════════
# S29 · PATCH #101 — THE LABEL IS NOT THE FACT
#
# Aug 24, 3pm, on Michael's calendar: "Studio Visit — James Perry (1wayy5
# (music artist))", booked by Maya off an Instagram ad. Michael: "this lead
# is not a studio visit candidate."
#
# #74 was written for exactly this lead. Its own comments name the last one:
# Joseph Joel Hernandez, "a hobbyist musician with no business and no
# budget", who "carried a 'business' too — 'Cositø (proyecto musical)' — so
# a non-empty business string is not enough either."
#
# 🔴 So why did it pass? Because BOTH of #74's tests are answered by the
# model that wants to make the booking. It checks `role` against an
# allow-list and `business` for non-emptiness — and Maya supplies both. She
# wrote the business as "1wayy5 (music artist)" and must have filed the role
# under `professional_personal_brand`, which the code defines as an EARNING
# practice: lawyer, doctor, coach, consultant, realtor. To a language model
# a music artist IS a personal brand. The gate was auditing its own witness.
#
# This reads the words instead. A field that says "music artist" blocks the
# visit whatever label came with it.
#
# ⚠️ DELIBERATELY NARROW. Only music markers, plus a field that is exactly
# "artist" or "creator". A tattoo artist, a makeup artist and a visual
# artist run earning practices and are real clients — and PODCASTERS ARE THE
# CORE PRODUCT, so nothing here may touch them. Over-blocking costs Michael
# leads he wants; the failure this fixes costs him an hour. Both are real.
# ══════════════════════════════════════════════════════════════════════

_MUSIC_MARKERS = (
    r"music artist", r"musician", r"recording artist", r"rapper", r"\brap\b",
    r"singer", r"songwriter", r"vocalist", r"beatmaker", r"music producer",
    r"music project", r"proyecto musical", r"artista musical", r"cantor",
    r"\bband\b", r"\bdj\b", r"hip[- ]?hop", r"r&b", r"\brnb\b", r"mixtape",
    r"\bep\b", r"my music", r"indie artist", r"music career",
)

_BARE_ARTIST = {"artist", "creator", "artiste", "artista"}


def looks_like_music_artist(*fields):
    """True when the lead's own words place them as a music artist/creator.

    Reads role AND business, because the two are filled in independently and
    either can carry the tell. `1wayy5 (music artist)` was in the business
    field; the role field said something respectable.
    """
    import re as _re
    for f in fields:
        t = str(f or "").strip().lower()
        if not t:
            continue
        if t in _BARE_ARTIST:
            return True
        for m in _MUSIC_MARKERS:
            if _re.search(m, t):
                return True
    return False


def studio_visit_verdict(role=None, business=None, stated_budget=None,
                         budget_declined=False, floor=STUDIO_FLOOR_USD):
    """May this lead be booked for an IN-PERSON studio visit?

    Returns (allow: bool, reason: str). `reason` is written to be shown to
    Maya, so it always says what to do next rather than only what is wrong.

    FAIL-CLOSED on the role: an unknown role blocks. That is deliberate —
    it converts "the prompt says ask what their role is" into "you cannot
    book until you have asked." Every previous version of this rule was
    advisory and every advisory version was ignored.

    NOT fail-closed on budget. MAYA.md §51 rule 4 is explicit: "A budget
    ask that is merely vague is NOT below floor — this rule fires on a
    STATED sub-$249 number, not on silence." Blocking silence would refuse
    most good leads, so silence passes.
    """
    role = (role or "").strip().lower().replace(" ", "_").replace("-", "_")
    biz = (business or "").strip()

    if budget_declined:
        return False, ("This lead has already been told our floor is "
                       f"${floor} and is under it. Do not book the studio. "
                       "Offer the free strategy call instead.")

    if stated_budget is not None:
        try:
            amount = float(str(stated_budget).replace("$", "").replace(",", "").strip())
        except (TypeError, ValueError):
            amount = None
        if amount is not None and amount < float(floor):
            return False, (f"Stated budget ${amount:,.0f} is below our ${floor} "
                           "floor, and there is no product under it. Say warmly "
                           f"that our studio time starts at ${floor}/hour, do not "
                           "negotiate down, and offer the free strategy call.")

    if role in STUDIO_ROLES_BLOCKED:
        return False, ("This lead is not a decision-maker with budget "
                       "authority. Offer the free 30-minute strategy call and "
                       "the direct booking link — not an in-person visit.")

    # PATCH #101 — read the words, not the label. This fires even when the
    # role field says `professional_personal_brand`, because that is exactly
    # what it said for James Perry on Aug 15.
    if looks_like_music_artist(role, business):
        return False, ("Music artists and creators do not get an in-person "
                       "studio visit — Michael's calendar is for owners, "
                       "decision-makers and earning practices. Send them the "
                       "studio booking page at "
                       "https://mwmcreations.com/studio-hour/ so they can book "
                       "and pay for an hour themselves, or offer the free "
                       "30-minute call. Do not offer a visit and do not "
                       "present time slots.")

    if role not in STUDIO_ROLES_ALLOWED:
        return False, ("You have not established what this person does. Ask "
                       "what their business is and what their role in it is, "
                       "then book. A studio visit costs Michael an hour in the "
                       "room, so it is only for owners, decision-makers and "
                       "professionals with an earning practice.")

    if not biz or biz.lower() in {"unknown", "n/a", "na", "none", "-", "personal"}:
        return False, ("No business is on file. Ask what business they run "
                       "before booking an in-person visit.")

    return True, f"qualified: {role}, business on file, budget not below floor"


# ══════════════════════════════════════════════════════════════════════
# PATCH #75 · THE FOUNDER-CALL GATE
#
# #74 stopped unqualified leads reaching the STUDIO. It did not stop them
# reaching MICHAEL, because Path B — the free 30-minute strategy call —
# was ungated on purpose. I reasoned that a call is where unqualified
# leads are supposed to land. Michael corrected that the same day:
#
#   "Lance is another Joseph. Not even worth it for the call."
#
# Lance Richardson, Aug 6, Instagram DM. First line: "I live in
# Philadelphia you are in Orlando." Asked what business he was in:
# "Writing 4 books about my life very inspirational." No business, no
# company, no revenue. Money never came up — Maya never asked and he
# never said. He was booked onto the founder's calendar anyway.
#
# 🔑 A CALL IS NOT FREE. It is thirty minutes of the only person who
# cannot be cloned. Path B was never meant to be "put them on Michael's
# calendar instead" — it was meant to be the cheaper door.
#
# 🔑 GEOGRAPHY IS NOT THE TEST. Nathan Waters (NWPhotoVideo) is out of
# state and is one of the best leads in the pipeline. Out-of-area means
# do not pitch the STUDIO; it does not mean refuse the person. What
# separates Nathan from Lance is a business, not a zip code.
# ══════════════════════════════════════════════════════════════════════

def strategy_call_verdict(role=None, business=None, stated_budget=None,
                          budget_declined=False, floor=STUDIO_FLOOR_USD):
    """May this lead take a 30-minute call with Michael?

    Returns (allow: bool, reason: str).

    A LOWER bar than a studio visit, deliberately — this is the cheaper
    door and most leads should get through it. It asks for ONE positive
    signal, not all of them:

      · a decision-making / earning role, OR
      · a stated budget at or above the floor

    Blocks only on: an explicit sub-floor number, a lead already told they
    are under it, or NO signal at all. "No signal at all" is Lance and
    Joseph — enthusiasm, a story, and nothing that could become an invoice.
    """
    role = (role or "").strip().lower().replace(" ", "_").replace("-", "_")

    if budget_declined:
        return False, ("This lead has already been told our floor is "
                       f"${floor} and is under it. Do not put them on "
                       "Michael's calendar. Send the booking link and "
                       "pricing so they can come back when it fits.")

    amount = None
    if stated_budget is not None:
        try:
            amount = float(str(stated_budget).replace("$", "").replace(",", "").strip())
        except (TypeError, ValueError):
            amount = None
    if amount is not None and amount < float(floor):
        return False, (f"Stated budget ${amount:,.0f} is below our ${floor} "
                       "floor. Say warmly that our studio time starts at "
                       f"${floor}/hour, do not negotiate down, and send the "
                       "booking link rather than a call.")

    if role in STUDIO_ROLES_ALLOWED:
        return True, f"qualified for a call: {role}"
    if amount is not None and amount >= float(floor):
        return True, f"qualified for a call: stated budget ${amount:,.0f}"

    return False, ("Nothing here says this person can buy yet — no business "
                   "or role, and no budget named. A call is thirty minutes of "
                   "Michael's day, so it is not the default. Send the pricing "
                   "and the booking link, and offer the call again the moment "
                   "they tell you what they run or what they can spend.")


# ══════════════════════════════════════════════════════════════════════
# PATCH #76 — FIRST INBOUND
# ══════════════════════════════════════════════════════════════════════

def is_first_inbound(sender, seen_inbound=(), history=None):
    """True when this is the first message we have EVER received FROM `sender`.

    The old test — "is this sender absent from conversation_history?" — was
    wrong, because conversation_history is also written when WE send. The
    website-form auto-greeting, the Slack shadow relay and the manual /send
    endpoint each create the key with an assistant message before the lead
    has said a word. Anyone we greeted first therefore looked like a
    RETURNING lead the moment they finally replied, and so never got a CRM
    row, a NEW_LEAD event, or a Susan / LARA / ERIC assignment.

    `seen_inbound` is the durable record and is authoritative.
    `history` is a self-healing second opinion: if the stored conversation
    already carries a message with role "user" then we have heard from this
    person before, even if the durable set was lost or never seeded.
    """
    if not sender:
        return False
    if sender in seen_inbound:
        return False
    for m in (history or ()):
        if isinstance(m, dict) and m.get("role") == "user":
            return False
    return True


def seed_seen_inbound(*histories):
    """Bootstrap the durable set from stored conversations.

    Returns every sender whose stored history already contains an inbound
    message. Run once at boot so that deploying this patch does not re-fire
    NEW_LEAD across the entire existing lead base.
    """
    seen = set()
    for hist in histories:
        for sender, msgs in (hist or {}).items():
            for m in (msgs or ()):
                if isinstance(m, dict) and m.get("role") == "user":
                    seen.add(sender)
                    break
    return seen


# ─────────────────────────────────────────────────────────────────────────────
# S84 · Instagram 24-hour messaging-window guard
#
# WhatsApp got this in S24: when Meta returns 131047 the verdict is PERSISTED
# and consulted before the next send, so a doomed free-form message is refused
# rather than burned. Instagram never got the same treatment. Its 403 handler
# wrote an IN-MEMORY set, alerted #dev, and returned — so every later caller
# walked into another 403 and alerted again. Eight identical alerts for one
# IGSID in 90 minutes on Aug 10, and NOT ONE counter anywhere: the entire
# failure class was invisible to /health while it was actively firing.
#
# The alert text also read "Lead marked window-expired; re-engagement will
# skip." True only inside one process, and only on the re-engagement path.
# An alert must not claim an outcome it did not produce.
# ─────────────────────────────────────────────────────────────────────────────

IG_WINDOW_MARK_PREFIX = "ig_window_expired:"


def ig_mark_key(igsid):
    """Storage key for an IGSID's window-expired mark, or None if unusable.

    ONE function produces the key that BOTH the writer and the reader use.
    #61 and #63 were the same bug wearing different clothes: two places
    independently deriving a string that had to match, and drifting apart.
    Accepts a bare IGSID or a `instagram:<igsid>` sender key.
    """
    d = str(igsid or "").strip()
    if d.startswith("instagram:"):
        d = d[len("instagram:"):].strip()
    return (IG_WINDOW_MARK_PREFIX + d) if d else None


def ig_window_blocked(mark_iso, last_inbound_iso=None):
    """True when a 403 verdict stands un-superseded by a newer inbound.

    A newer inbound reopens the window, exactly as it does for WhatsApp.
    Both sides are normalised through to_local_naive() before comparison —
    an aware value is CONVERTED, never stripped (#60).

    Absent or unparseable data fails OPEN. Refusing to send on a value we
    could not read is a worse failure than one wasted API call.
    """
    mark = to_local_naive(_parse_et(mark_iso))
    if mark is None:
        return False
    last = to_local_naive(_parse_et(last_inbound_iso))
    if last is not None and last > mark:
        return False
    return True


def ig_should_alert_403(igsid, already_marked):
    """Alert on the FIRST 403 for an IGSID; stay silent for the repeats.

    Suppressing repeats is the point of the ticket, but a suppressed alert
    must still be countable — a capped or partial job announces what it did
    not do. The caller bumps a counter on every 403 regardless of this
    verdict, so /health carries the true volume even when #dev is quiet.
    """
    if not ig_mark_key(igsid):
        return False
    return not bool(already_marked)


# ═══════════════════════════════════════════════════════════════════
# PATCH #90 — a confirmed ROADMAP filming day, as a calendar event
# ═══════════════════════════════════════════════════════════════════
#
# The ROADMAP portal let a producer click Confirm and told the client the day
# was confirmed, and nothing was ever written to a calendar. The webhook that
# fixes that lives in app.py; the part that can be wrong in an interesting way
# lives here, where it can be tested without Google.
#
# 🔴 THE RULE THIS FUNCTION EXISTS FOR: an ON-LOCATION day must never inherit
# the studio address. The studio is the safe default for a studio day and the
# WORST possible default for a location day — it sends a crew, a camera and a
# van to Winter Park while the client waits in his own office. A location day
# with no address is a refusal, not a fallback.

ROADMAP_STUDIO = "studio"
ROADMAP_LOCATION = "location"


def roadmap_shoot_event_body(client_name, campaign_no, campaign_title, date,
                             start_time, end_time, kind, location,
                             studio_address, timezone, client_email="",
                             notes="", confirmed_by=""):
    """Build the Google Calendar body for a CONFIRMED ROADMAP filming day.

    Pure — no network, no Google, no clock. Raises EventRailRejected rather than
    returning a body that would put a crew in the wrong place or on no clock.
    """
    name = (client_name or "").strip()
    title = (campaign_title or "").strip()
    date = (date or "").strip()
    start = str(start_time or "")[:5]
    end = str(end_time or "")[:5]
    kind = (kind or ROADMAP_STUDIO).strip().lower()
    where = (location or "").strip()
    email = (client_email or "").strip()

    if not name:
        raise EventRailRejected(["a filming day needs a client name"], context="roadmap_shoot")
    if not date or not start or not end:
        raise EventRailRejected(["a filming day needs a date and a start and end time"], context="roadmap_shoot")
    if start >= end:
        raise EventRailRejected(
            ["a filming day cannot end before it starts (%s -> %s)" % (start, end)],
            context="roadmap_shoot")

    if kind == ROADMAP_LOCATION:
        # 🔴 See the note above. No address means no event.
        if not looks_like_address(where):
            raise EventRailRejected(
                ["an on-location day needs the client's address — refusing to fall "
                 "back to the studio and send the crew to the wrong place"],
                context="roadmap_shoot")
        where_label = "on location"
    else:
        where = where or (studio_address or "").strip()
        if not where:
            raise EventRailRejected(["a studio day needs the studio address"], context="roadmap_shoot")
        where_label = "MWM studio"

    camp = str(campaign_no) if campaign_no not in (None, "") else "?"
    summary = "ROADMAP: %s — C%s" % (name, camp)
    if title:
        summary += " " + title

    description = "\n".join([
        "MWM ROADMAP™ filming day",
        "Client: %s%s" % (name, (" (%s)" % email) if email else ""),
        "Campaign %s: %s" % (camp, title or "—"),
        "Where: %s — %s" % (where_label, where),
        "Notes: %s" % ((notes or "").strip() or "—"),
        "Confirmed by: %s" % ((confirmed_by or "").strip() or "—"),
        "Source: ROADMAP portal (machine, Patch #90)",
    ])

    return {
        "summary": summary,
        "description": description,
        "start": {"dateTime": "%sT%s:00" % (date, start), "timeZone": timezone},
        "end": {"dateTime": "%sT%s:00" % (date, end), "timeZone": timezone},
        "location": where,
    }, where_label


# ══════════════════════════════════════════════════════════════════════
# PATCH #105 · THE DOUBLE-BOOK DETECTOR
# ══════════════════════════════════════════════════════════════════════
# Nothing in this system has ever looked at the calendar and asked "are two
# of these on top of each other?" There were three partial guards and no
# detector:
#
#   · book_appointment's race guard — ±15 min around ONE slot, at booking
#     time, and only on the path Maya drives.
#   · slot_conflicts (#50D) — correct, pure, and wired only to the admin
#     booking form's client-side JS. It never sees anything Michael did not
#     type into that form.
#   · /studio-availability — tells the WordPress portal what is busy, then
#     /webhook/studio-booking writes the event with NO server-side check at
#     all. A paid portal booking lands on top of whatever is already there,
#     and the 120s availability cache means two people filling the form at
#     once can both be told the slot is free.
#
# So a clash created by the portal, by wp-admin, or by Michael's own hand was
# invisible until a human happened to read the calendar. Aug 19: Victory HQ
# 9:15–12:30 on Edgewater Drive against Z Brothers Construction's PAID studio
# booking 10:00–11:00. The conflict was written inside the Victory event's own
# description. It sat for seven days.
#
# ── WHAT THIS DELIBERATELY DOES NOT DO ──────────────────────────────
# It does not refuse anything. A portal client has already paid; a booking
# that vanishes because our checker disliked it is worse than a booking we
# flag loudly. Detection and refusal are different jobs and only one of them
# is safe to automate here.
#
# ── THE THREE RULES THAT KEEP IT QUIET ENOUGH TO BE READ ────────────
# An alert rail that cries wolf gets muted, and a muted rail is worse than
# none because it looks like coverage.
#
#   1. FREE means free. `transparency == "transparent"` is skipped. This is
#      not a technicality — it is a convention Michael actively maintains:
#      the Shelley Aug 27 hold is FREE *on purpose* so she can book that very
#      slot herself, and the cancelled Victory class was downgraded to FREE
#      rather than deleted. Flagging either would tell him his own careful
#      bookkeeping is a double-book.
#   2. Touching is not overlapping. Strict inequality on both sides. He runs
#      back-to-back constantly and 09:00 after an 09:00 finish is not a clash.
#      (Same rule as slot_conflicts, for the same reason.)
#   3. Two INTERNAL events never clash with each other. His flights arrive
#      twice — once from United, once from Expedia, same reservation EKZ915,
#      identical times — and a detector that reported those every fifteen
#      minutes forever would be muted within the day. This rail exists to
#      protect client bookings, not to police his own blocks against
#      themselves.

CONFLICT_HORIZON_DAYS = 30   # a clash three weeks out is still a clash

CLASH_ROOM = "room"      # both events are IN OUR STUDIO — physically impossible
CLASH_PERSON = "person"  # Michael owed in two places at once
CLASH_SEVERITY_ORDER = {CLASH_ROOM: 0, CLASH_PERSON: 1}


def _conflict_window(ev):
    """(start, end) as aware datetimes, or None if this event cannot clash.

    Returns None for anything that is not a timed, busy, live event: all-day
    entries, cancelled ones, and anything marked FREE.
    """
    if not isinstance(ev, dict):
        return None
    if str(ev.get("status") or "").lower() == "cancelled":
        return None
    if ev.get("transparency") == "transparent":
        return None                     # rule 1 — FREE means free
    s = (ev.get("start") or {}).get("dateTime")
    e = (ev.get("end") or {}).get("dateTime")
    if not s or not e:
        return None                     # all-day, or malformed
    try:
        s_dt = datetime.fromisoformat(s)
        e_dt = datetime.fromisoformat(e)
    except (TypeError, ValueError):
        return None                     # unparseable — skipped, never guessed
    if e_dt <= s_dt:
        return None
    return s_dt, e_dt


def _conflict_series(ev):
    """The recurring series an instance belongs to, or its own id."""
    return ev.get("recurringEventId") or ev.get("id") or ""


def classify_clash(kind_a, is_client_a, kind_b, is_client_b):
    """How bad is this overlap, and is it worth reporting at all?

    Returns CLASH_ROOM, CLASH_PERSON, or None for "do not report".
    """
    if not is_client_a and not is_client_b:
        return None                     # rule 3 — his own blocks, his business
    if venue_of(kind_a) == VENUE_STUDIO and venue_of(kind_b) == VENUE_STUDIO:
        return CLASH_ROOM               # one room, two bookings
    return CLASH_PERSON


def find_conflicts(events, classifier=None):
    """Every pair of live BUSY events on this calendar that genuinely overlap.

    Pure: `events` is whatever the Google list call returned, and nothing here
    touches the network or the clock. Returns a list of dicts, worst first:

        {"severity", "overlap_min", "a": {...}, "b": {...}, "key"}

    where each side carries id / summary / start / end / kind / is_client, and
    `key` is a stable identity for the pair so the caller can report a given
    clash once rather than every fifteen minutes.

    `classifier` exists so tests can pin a classification without depending on
    title-pattern drift; it defaults to this module's own classify_event.
    """
    cls = classifier or classify_event
    rows = []
    for ev in (events or []):
        win = _conflict_window(ev)
        if not win:
            continue
        try:
            kind, is_client, _why = cls(ev)
        except Exception:
            continue                    # a classifier that throws must not
                                        # silently turn a clash into "clear"
        rows.append({
            "id": ev.get("id") or "",
            "series": _conflict_series(ev),
            "summary": str(ev.get("summary") or "(untitled)"),
            "start": win[0],
            "end": win[1],
            "kind": kind,
            "is_client": bool(is_client),
        })
    rows.sort(key=lambda r: r["start"])

    out = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if b["start"] >= a["end"]:
                break                   # sorted — nothing later can overlap a
            if a["id"] and a["id"] == b["id"]:
                continue                # never an event against itself
            if a["series"] and a["series"] == b["series"]:
                continue                # two instances of one recurring series
            if not (a["start"] < b["end"] and b["start"] < a["end"]):
                continue                # rule 2 — touching is not overlapping
            sev = classify_clash(a["kind"], a["is_client"], b["kind"], b["is_client"])
            if not sev:
                continue
            overlap = (min(a["end"], b["end"]) - max(a["start"], b["start"]))
            out.append({
                "severity": sev,
                "overlap_min": int(overlap.total_seconds() // 60),
                "a": a,
                "b": b,
                # The pair AND when they collide. Ids alone would report a
                # given pair once ever, so if one of them is later moved back
                # on top of the other the second clash is silent. Stamping the
                # overlap start means a re-introduced clash reads as new,
                # while the same unchanged clash stays reported-once.
                "key": "clash:%s:%s@%s" % (
                    tuple(sorted([a["id"], b["id"]]))[0],
                    tuple(sorted([a["id"], b["id"]]))[1],
                    max(a["start"], b["start"]).isoformat(),
                ),
            })
    out.sort(key=lambda c: (CLASH_SEVERITY_ORDER.get(c["severity"], 9),
                            c["a"]["start"], c["key"]))
    return out


def describe_conflict(c):
    """One Slack-ready block for a single clash. Pure — no I/O, no clock."""
    a, b = c["a"], c["b"]
    if c["severity"] == CLASH_ROOM:
        head = "🔴 *STUDIO DOUBLE-BOOKED* — two bookings in the same room"
    else:
        head = "🟠 *SCHEDULE CLASH* — Michael is needed in two places"
    day = a["start"].strftime("%A %d %B")
    return (
        "%s\n"
        "*%s*\n"
        "• %s — %s\n"
        "• %s — %s\n"
        "_Overlap: %d min_" % (
            head, day,
            a["start"].strftime("%I:%M %p").lstrip("0") + "–" + a["end"].strftime("%I:%M %p").lstrip("0"),
            a["summary"],
            b["start"].strftime("%I:%M %p").lstrip("0") + "–" + b["end"].strftime("%I:%M %p").lstrip("0"),
            b["summary"],
            c["overlap_min"],
        )
    )
