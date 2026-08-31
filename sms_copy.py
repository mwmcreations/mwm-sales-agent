"""
sms_copy.py — PATCH #113. Every word this company sends by text.

WHY THIS IS ITS OWN MODULE
──────────────────────────
Copy is the part most likely to be wrong and the part nobody notices is wrong.
It is also, for SMS specifically, the part a carrier reads. The A2P campaign
was approved against two sample messages with a particular shape:

    MWM Creations & Studios: Hi Ana, your studio session is confirmed for
    Thu Aug 21 at 10:00 AM at 1500 Park Center Dr, Suite 230, Orlando.
    Reply STOP to opt out, HELP for help.

Brand named at the front. Opt-out named at the back. Every message we send
must look like that, and no sender should be able to forget it — so senders
do not build strings. They call a function here, and compose() puts the brand
on the front and the opt-out on the back whether the caller remembered or not.

PURE ON PURPOSE
───────────────
No network, no clock, no Flask. Every rule below is testable, which matters
more here than anywhere else in the machine: a bad reminder reaches a paying
client's phone at 8am and cannot be recalled.

THE THREE THINGS THIS ENFORCES
──────────────────────────────
1. GSM-7 ONLY. A single smart quote or emoji flips the whole message to
   UCS-2, which cuts the segment length from 160 characters to 70 and can
   silently triple the bill. Everything is folded to plain ASCII.
2. THE OPT-OUT IS NOT OPTIONAL. It is appended by compose(), not typed by
   callers, so it cannot be left off a new sender written in a hurry.
3. NOTHING RENDERS AS "None". A missing name becomes "there"; a missing time
   raises rather than texting a client the word None.
"""

import re
import unicodedata

BRAND = "MWM Creations & Studios"
PREFIX = BRAND + ": "
SUFFIX = " Reply STOP to opt out, HELP for help."

# One GSM-7 segment is 160 chars; concatenated parts are 153 each. Two
# segments is our ceiling — past that the copy is wrong, not the limit.
SEGMENT_SINGLE = 160
SEGMENT_CONCAT = 153
MAX_SEGMENTS = 2

_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "‒": "-", "―": "-",
    "…": "...", " ": " ", " ": " ", " ": " ",
    "·": "-", "•": "-", "→": "->", "­": "",
}


def ascii_fold(value):
    """Plain ASCII, always. Typography, accents and emoji all cost money in
    UCS-2, and an emoji in a compliance-sensitive message costs more than
    money."""
    s = "" if value is None else str(value)
    for bad, good in _FOLD.items():
        s = s.replace(bad, good)
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    # A newline in a name is a way to make one message look like two.
    s = re.sub(r"[\r\n\t]+", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def is_gsm7(text):
    """True when every character survives a GSM-7 encode. Cheap approximation:
    ASCII printable plus newline. Anything else would force UCS-2."""
    return all(32 <= ord(c) <= 126 for c in (text or ""))


def segments(text):
    """How many SMS segments this body costs."""
    n = len(text or "")
    if n == 0:
        return 0
    if n <= SEGMENT_SINGLE:
        return 1
    return -(-n // SEGMENT_CONCAT)      # ceiling division


def safe_name(value, fallback="there"):
    """A first name we are willing to put in front of a stranger's phone.

    Anything that is not plainly a name — empty, numeric, an email, an
    Instagram id, something absurdly long — becomes the fallback. "Hi there"
    is a warm message. "Hi None" is a broken one, and "Hi 4075551234" is
    worse: it tells the reader we do not know who they are."""
    s = ascii_fold(value)
    # A name field holding an email is common enough to handle deliberately:
    # take the local part rather than texting somebody "Hi Anaexamplecom".
    if "@" in s:
        s = s.split("@", 1)[0]
    s = s.split()[0] if s.split() else ""
    s = re.sub(r"[^A-Za-z'\-]", "", s)
    if not s or len(s) > 20:
        return fallback
    return s[:1].upper() + s[1:]


def compose(core):
    """Brand on the front, opt-out on the back, ASCII throughout.

    Callers pass only the sentence that differs. They cannot forget the parts
    a carrier checks for, because they never write them."""
    body = ascii_fold(core).rstrip()
    if not body:
        raise ValueError("refusing to send an empty SMS")
    if not body.endswith((".", "!", "?")):
        body += "."
    text = PREFIX + body + SUFFIX
    if not is_gsm7(text):
        raise ValueError("SMS body is not GSM-7 after folding: %r" % text[:80])
    if segments(text) > MAX_SEGMENTS:
        raise ValueError("SMS body is %d segments (max %d): %r"
                         % (segments(text), MAX_SEGMENTS, text[:80]))
    return text


def _require(value, label):
    v = ascii_fold(value)
    if not v:
        raise ValueError("refusing to send an SMS with no %s" % label)
    return v


# ── THE MESSAGES ───────────────────────────────────────────────────────────

def opt_in_confirmation(first_name=None, marketing=False):
    """Sent once, the moment a consent record turns yes.

    This is the message that proves the opt-in worked, to the person who just
    opted in. It states what they will now receive, because a confirmation
    that does not say what was agreed to is not a confirmation."""
    fn = safe_name(first_name)
    if marketing:
        core = ("Hi %s, you are signed up for booking updates and occasional "
                "offers (no more than 4 a month)" % fn)
    else:
        core = ("Hi %s, you are signed up for booking messages - "
                "confirmations and reminders" % fn)
    return compose(core)


def studio_booking_confirmed(first_name, when_long, time_str, location=""):
    """A studio session has been booked and paid for. Matches the shape of the
    transactional sample registered with the campaign."""
    fn = safe_name(first_name)
    when = _require(when_long, "date")
    at = _require(time_str, "time")
    where = ascii_fold(location)
    core = "Hi %s, your studio session is confirmed for %s at %s" % (fn, when, at)
    if where:
        candidate = core + " at " + where
        # The address is a courtesy. If carrying it would push the message
        # into a third segment, the date and time matter more.
        try:
            return compose(candidate)
        except ValueError:
            pass
    return compose(core)


def film_shoot_confirmed(first_name, when_long, time_str, location="",
                         campaign_title=""):
    """A roadmap filming day has been confirmed by a producer.

    Deliberately different words from a studio booking: a client who has both
    must be able to tell from the first line which one this is."""
    fn = safe_name(first_name)
    when = _require(when_long, "date")
    at = _require(time_str, "time")
    title = ascii_fold(campaign_title)
    core = "Hi %s, your filming day is confirmed for %s at %s" % (fn, when, at)
    if title:
        core += " (%s)" % title[:40]
    where = ascii_fold(location)
    if where:
        try:
            return compose(core + " at " + where)
        except ValueError:
            pass
    return compose(core)


def session_reminder(stage_h, first_name, when_long, time_str):
    """One rung of the T-168h / T-24h / T-2h ladder.

    Carries the DATE at every tier, not a horizon phrase. Patch #45B learned
    this on WhatsApp: "in a couple of days at 10" is not something a client
    can write in a diary, and a reminder carrying the wrong day is worse than
    no reminder because they believe it."""
    fn = safe_name(first_name)
    when = _require(when_long, "date")
    at = _require(time_str, "time")
    try:
        h = float(stage_h)
    except (TypeError, ValueError):
        h = 24.0
    if h < 12:
        core = "Hi %s, reminder: your session is today at %s" % (fn, at)
    else:
        core = ("Hi %s, reminder: your session is %s at %s. Need to change "
                "it? Just reply" % (fn, when, at))
    return compose(core)


# ── FORMATTING THE PORTAL'S OWN STRINGS ────────────────────────────────────
# The studio and roadmap webhooks send dates as "2026-09-04" and times as
# "10:00". A client should never read either of those in a text message.

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
         "Sunday")


def pretty_date(iso_date):
    """'2026-09-04' -> 'Friday, September 4'. Returns '' when unparseable,
    which every caller treats as a refusal to send rather than a reason to
    text somebody the string '2026-09-04'."""
    s = ascii_fold(iso_date)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return ""
    try:
        import datetime as _dt
        wd = _DAYS[_dt.date(y, mo, d).weekday()]
    except ValueError:
        return ""
    return "%s, %s %d" % (wd, _MONTHS[mo - 1], d)


def pretty_time(hhmm):
    """'14:30' -> '2:30 PM'. '' when unparseable."""
    s = ascii_fold(hhmm)
    m = re.match(r"^(\d{1,2}):(\d{2})", s)
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return ""
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return "%d:%02d %s" % (h12, mi, ampm)
