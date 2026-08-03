"""Meeting-report parsing helpers (Jul 8 2026 matcher fix — pure stdlib, unit-tested).

Root cause fixed here: calendar titles like
    "Studio Visit — Dr. Scott Robinson (There Are No Lines In Heaven)"
were split on the separator with the LEFT side taken as the lead name,
so the report tried to match a lead literally named "Studio Visit".
"""
import re

# Left-side words that mean "this is the meeting TYPE, the person is on the right".
MEETING_TYPE_PREFIXES = {
    "studio visit", "visit", "meeting", "consultation", "call", "video call",
    "strategy call", "session", "podcast", "gravacao", "gravação", "reuniao",
    "reunião", "recording", "shoot", "studio session", "walkthrough", "delivery",
}

_PAREN_RE = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*$")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def parse_event_summary(summary: str):
    """Return (name, business) extracted from a calendar event title."""
    name = (summary or "").strip()
    business = ""

    # Em-dash first: it's the studio's standard "Type — Person" separator.
    for sep in (" — ", " – ", " - ", " | ", ": "):
        if sep in name:
            left, right = (p.strip() for p in name.split(sep, 1))
            if left.lower().rstrip(":").strip() in MEETING_TYPE_PREFIXES:
                # "Studio Visit — Dr. Scott Robinson (...)" -> person on the RIGHT
                name, business = right, ""
            else:
                # "Name - Business" / "Name | Business"
                name, business = left, right
            break

    # Legacy prefixes ("Meeting with X", "Studio Visit: X")
    for prefix in ("Meeting with ", "Studio Visit: ", "Consultation: ", "Visit: "):
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix):].strip()
            break

    # "Dr. Scott Robinson (There Are No Lines In Heaven)" -> name + business
    #
    # PATCH #40 — _PAREN_RE uses `\(([^)]+)\)$`, which cannot span a nested
    # parenthesis, so ANY business name containing brackets defeated it and the
    # whole title was returned as the person's name. Live case, Aug 3 2026:
    #   "Studio Visit — Krista Neeley (New Media Cruise (with Michael Neeley
    #    - Infinite Leads))"
    # parsed to name="Krista Neeley (New Media Cruise (with Michael Neeley -
    # Infinite Leads))" and business="". The lead lookup is an EXACT name match,
    # so it found nothing, and every downstream automation was built on an
    # empty lead record. Priti Verma (Pretty_dangles) worked; Krista did not.
    # The difference was one pair of brackets.
    #
    # Scan back from the end counting depth instead — brackets nest, regexes
    # of this shape do not.
    _before, _inside = _split_trailing_parens(name)
    if _inside:
        name = _before
        if not business:
            business = _inside

    return name, business


def _split_trailing_parens(s: str):
    """(text_before, text_inside) for a trailing BALANCED (...) group.

    Returns (s, "") when there is no balanced trailing group, so the caller
    keeps the original string rather than a half-parsed one. Refusing to split
    beats splitting wrongly: a wrong name silently matches nobody.
    """
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


def extract_emails(text: str):
    """Lower-cased set of every email address found in free text (e.g. report notes)."""
    return {m.lower() for m in EMAIL_RE.findall(text or "")}


def booking_status_for(appointment_type: str) -> str:
    """CRM Status-column value for a booking — same vocabulary as update_booking_in_sheets.

    INVARIANT (Michael, Jul 8 2026): a lead is promoted to Client ONLY by a confirmed
    Stripe payment (webhook path). Booking/pitch flows may move a lead between lead
    stages but must NEVER set a Client stage.
    """
    return "✅ Studio Visit Booked" if appointment_type == "studio_visit" else "📞 Strategy Call Booked"
