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
    (KIND_PRODUCTION_SHOOT,
     re.compile(r"(video shoot|filmagem|production shoot|depoimento|on[- ]location)", re.I)),
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
    fn = str(first_name or "there").strip() or "there"
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
    """
    try:
        hour = dt.hour
    except AttributeError:
        return False
    return start_hour <= hour < end_hour
