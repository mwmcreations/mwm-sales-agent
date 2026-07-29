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

import re
import unicodedata

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


def reminder_channel_for(identifier, email=None):
    """Which rail can actually reach this person? Returns (channel, why).

    channel is one of "whatsapp" / "instagram" / "email" / None.
    None means UNREMINDABLE — that is a hard S-1 failure, not a warning.
    """
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
                      require_attendee=True, require_postal=True):
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
    rchan, rwhy = reminder_channel_for(source_identifier, attendee_email)
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

    # ── stamp what we resolved onto the event, so the next audit can read it ──
    desc = body.get("description") or ""
    stamp = [
        "",
        "—— Event Rail ——",
        f"Source channel: {channel}   (resolved from identifier, not from a label)",
        f"Reminder channel: {rchan or 'NONE — UNREMINDABLE'}",
    ]
    for n in notes:
        stamp.append(f"note: {n}")
    if issues:
        stamp.append("ISSUES AT CREATION: " + "; ".join(issues))
    body["description"] = desc + "\n".join(stamp)

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
