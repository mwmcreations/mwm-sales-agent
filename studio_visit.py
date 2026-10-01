"""
studio_visit.py — PATCH #143. One script, every door.

WHY THIS MODULE EXISTS
──────────────────────
On 26 Sep 2026 Michael approved ERIC's acquisition strategy ("Yes for all")
and ERIC posted the exact Maya copy in #dev: one opener, two qualifying
questions, the price said once when asked, a polite disqualify. Michael then
corrected it three times (26 Sep PM: one-hour, no minimum term in chat;
28 Sep on set: THIRTY minutes, "in projects with", "we"). None of it reached
the machine: on 30 Sep, the night before the C1 launch, every prompt still
sold the "Studio Package" and the Meta lead-form path still sent a
free-form WhatsApp greeting that Meta blocks.

So the script lives here once — as prompt text for the four Maya prompts,
and as the exact strings the automated first touch (SMS / email) and the
chase chain send — and a test asserts that the prompts carry it and that
the banned wordings do not come back.

PURE ON PURPOSE. No network, no clock, no Flask.
"""

import html as _html
import re

# ── the words Michael corrected, as constants nothing can drift from ───────
VISIT_MINUTES = 30
VISIT_NAME = "Studio Strategy Visit"
CREDITS = "in projects with Disney, Universal, Amazon and TV Globo for over 20 years"
WE_DO = "we plan it, write it, shoot it and cut it"
PRICE_LINE = ("The Studio Subscription is $1,200 a month: four studio hours - "
              "up to 8 short videos an hour, or a podcast episode and ten cuts - "
              "plus strategy, scripts and editing. The visit is where Michael "
              "maps what your month looks like.")
MINIMUM_IF_ASKED = ("there's a three-month minimum; Michael walks you through "
                    "it at the visit.")
MAYA_WA = "+1 407-871-6473"
BOOK_STUDIO_URL = "mwmcreations.com/book-studio"

# Wordings that must never appear in a prompt or an outgoing text again.
BANNED = (
    "45-minute",
    "45 minute studio strategy visit",
    "one-hour studio strategy visit",
    "one hour studio strategy visit",
    "directed for",
    "michael does a 30-minute",
    "michael does a one-hour",
)

# ── the prompt block ───────────────────────────────────────────────────────
SCRIPT_RULE = """
THE STUDIO STRATEGY VISIT SCRIPT — STANDING RULE (Michael, 26 and 28 Sep 2026).
This block wins over any older package, hourly or "Studio Package" lines
elsewhere in this prompt. Same script on every door: Instagram, WhatsApp,
website chat, SMS, and leads who arrive from an ad form.

WHAT WE SELL: one thing — the Studio Subscription for business owners whose
customers must understand what they do before they buy. The free step is the
30-minute Studio Strategy Visit with Michael at the studio. The visit is the
goal of every conversation. No Calendly, ever: you book the visit yourself
with get_available_slots / book_appointment on the MWM CREATIONS calendar.

OPENER (every channel, and the reply to ANY first message with no text — a
shared reel, a photo, a sticker, a story reply):
"Hi {first_name}, Maya here from Michael Moraes' team at MWM Studios. Two
quick questions so I match you with the right session: what's the business,
and what do your customers need to understand before they buy from you?"
If the person arrived from an ad form, you already have their answers — do
not ask again; acknowledge them and go straight to the visit.

QUALIFIED (owner / founder / partner + a real business + revenue band fits:
$50K+ a month; $20-50K only if they are the owner and the industry fits):
"That's exactly what we build. The next step is a free 30-minute Studio
Strategy Visit: you walk the studio, we map the videos your buyers need to
see, you leave with a 90-day plan. I have {slot_1} or {slot_2} this week —
which works?"
→ book_appointment on MWM CREATIONS. Then capture email + mobile, then ask:
"Can we text you the confirmation and reminders? Reply YES."
If they will not drive in: "Then let's do 20 minutes by phone first — Michael
will tell you exactly what he'd shoot. {slot_1} or {slot_2}?" The call's only
goal is the visit.
A named budget is NOT required to offer the visit. Business + role + revenue
band is enough.

CREDITS, if you ever mention them: "Michael has been in projects with Disney,
Universal, Amazon and TV Globo for over 20 years." Never claim he directed
anything for those brands.
THE WORK is "we plan it, write it, shoot it and cut it" — never "Michael
does" / "I do".
THE VISIT is 30 minutes. Never 45 minutes, never one hour.

PRICE — only when asked, said once, no discount, never $349, never "only" or
"just":
"The Studio Subscription is $1,200 a month: four studio hours — up to 8 short
videos an hour, or a podcast episode and ten cuts — plus strategy, scripts
and editing. The visit is where Michael maps what your month looks like."
Do NOT volunteer the minimum term. If asked directly, never deny it: "there's
a three-month minimum; Michael walks you through it at the visit."

DISQUALIFIED (creator, artist, musician, writer, podcaster-as-hobby,
actor/model, photographer/videographer, student, under $20K a month,
outside Florida):
"Thanks for reaching out. We work with established businesses on a monthly
subscription, so we're probably not the right fit. If you ever need studio
hours on their own, mwmcreations.com/book-studio has the calendar."
No follow-up chain. No retargeting. Be warm, be brief.

AI AD LEADS (the "Film once, go anywhere" ad): open on the AI sets instead of
the education line — one shoot in our studio, your business in any scene:
rooftop, restaurant, stage, city at night — then the same questions and the
same 30-minute visit. Prices for AI are in the Hybrid AI block, if present.
"""


# ── helpers ────────────────────────────────────────────────────────────────

def first_name(name, fallback="there"):
    """A first name we are willing to put in front of a stranger."""
    s = str(name or "").strip()
    if "@" in s:
        s = s.split("@", 1)[0]
    s = s.split()[0] if s.split() else ""
    s = re.sub(r"[^A-Za-zÀ-ɏ'\-]", "", s)
    if not s or len(s) > 20:
        return fallback
    return s[:1].upper() + s[1:]


def contains_banned(text):
    """The banned wording found in `text`, or None."""
    low = str(text or "").lower()
    for b in BANNED:
        if b in low:
            return b
    return None


def short_slot(slot):
    """'Thursday, October 02 at 10:00 AM EST' -> 'Thu Oct 2, 10:00 AM'.

    get_available_slots() gives {id: ISO datetime, display: long form}. The
    id is used when present (exact), the display is shortened otherwise, and
    anything unreadable is returned as it came — a long slot is better than
    no slot."""
    if isinstance(slot, dict):
        iso = slot.get("id") or ""
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(str(iso))
            return (d.strftime("%a %b ") + str(d.day) + ", " +
                    _short_time(d.hour, d.minute))
        except Exception:
            pass
        disp = str(slot.get("display") or "").strip()
    else:
        disp = str(slot or "").strip()
    m = re.match(r"([A-Za-z]+),?\s+([A-Za-z]+)\s+0?(\d+)\s+at\s+0?(\d+):(\d+)\s*([AP]M)",
                 disp, re.IGNORECASE)
    if m:
        h = int(m.group(4)) % 12 + (12 if m.group(6).upper() == "PM" else 0)
        return (f"{m.group(1)[:3]} {m.group(2)[:3]} {m.group(3)}, "
                f"{_short_time(h, int(m.group(5)))}")
    return disp


def _short_time(hour, minute):
    """10:00 -> '10am', 15:30 -> '3:30pm'."""
    ap = "am" if hour < 12 else "pm"
    h = hour % 12 or 12
    return f"{h}{ap}" if not minute else f"{h}:{minute:02d}{ap}"


def _slot_phrase(slots, joiner="or"):
    """'Thu Oct 2, 10:00 AM or Fri Oct 3, 3:00 PM' from up to two slots."""
    disp = [short_slot(s) for s in (slots or []) if s]
    disp = [d for d in disp if d][:2]
    if not disp:
        return ""
    if len(disp) == 1:
        return disp[0]
    return f"{disp[0]} {joiner} {disp[1]}"


# ── chat opener (IG / WhatsApp / web, no form answers yet) ──────────────────

def opener(name, ai=False):
    fn = first_name(name)
    if ai:
        return (f"Hi {fn}, Maya here from Michael Moraes' team at MWM Studios. "
                f"One shoot in our studio and your business appears in any scene - "
                f"a rooftop, your restaurant, a stage, the city at night. Two quick "
                f"questions so I match you with the right session: what's the "
                f"business, and what do your customers need to understand before "
                f"they buy from you?")
    return (f"Hi {fn}, Maya here from Michael Moraes' team at MWM Studios. Two "
            f"quick questions so I match you with the right session: what's the "
            f"business, and what do your customers need to understand before "
            f"they buy from you?")


# ── first touch for a FORM lead (we already hold the answers) ───────────────

def form_first_touch_sms(name, business="", ai=False, slots=None):
    """The core of the first SMS to a consenting form lead. The caller wraps
    it with sms_copy.compose(), which adds the brand and the opt-out, so this
    must stay short: ~240 characters is the ceiling for two segments.

    Carries the three words Michael corrected: 30-minute, "in projects
    with", "we"."""
    fn = first_name(name)
    when = _slot_phrase(slots)
    who = "Michael (20+ yrs in projects with Disney, Universal)"
    if ai:
        if when:
            core = (f"Hi {fn}, Maya from Michael Moraes' team. One studio shoot and "
                    f"we put your business in any scene. {who} has {when} for your "
                    f"free 30-minute Strategy Visit. Which works?")
        else:
            core = (f"Hi {fn}, Maya from Michael Moraes' team. One studio shoot and "
                    f"we put your business in any scene. {who} offers a free "
                    f"30-minute Strategy Visit. Which day this week works for you?")
    else:
        if when:
            core = (f"Hi {fn}, Maya from Michael Moraes' team. Next: your free "
                    f"30-minute Strategy Visit, where we map the videos your buyers "
                    f"need to see. {who} has {when}. Which works?")
        else:
            core = (f"Hi {fn}, Maya from Michael Moraes' team. Next: your free "
                    f"30-minute Strategy Visit, where we map the videos your buyers "
                    f"need to see. {who} is in the studio this week. Which day works "
                    f"for you?")
    return core


def form_first_touch_email(name, business="", must_understand="", ai=False,
                           slots=None, sms_sent=False):
    """(subject, html, text) — the opener as an email, for leads with no SMS
    consent / no dialable mobile, or alongside the text when the text had to
    wait for the sending window."""
    fn = first_name(name)
    biz = str(business or "").strip()
    mu = str(must_understand or "").strip()
    when = _slot_phrase(slots)
    subject = f"{fn}, your {VISIT_NAME} with Michael Moraes"
    lines = [f"Hi {fn},", ""]
    lines.append("Maya here from Michael Moraes' team at MWM Studios. Thanks for "
                 "applying for the Studio Strategy Visit.")
    if ai:
        lines.append("You asked about the AI side: one shoot in our studio and your "
                     "business appears in any scene - a rooftop, your restaurant, a "
                     "stage, the city at night. You stay real; only the world around "
                     "you is AI.")
    if biz and mu:
        lines.append(f"{biz} is exactly what we build for - a business whose customers "
                     f"need to understand something before they buy. You wrote: "
                     f"\"{mu[:240]}\". That is the video we would start with.")
    elif biz:
        lines.append(f"{biz} is exactly what we build for.")
    lines.append(f"The next step is a free {VISIT_MINUTES}-minute {VISIT_NAME}: you "
                 "walk the studio, we map the videos your buyers need to see, and "
                 "you leave with a 90-day plan. Michael has been " + CREDITS +
                 "; " + WE_DO + ".")
    if when:
        lines.append(f"Michael has {when}. Which works? Reply to this email with the "
                     f"one you want, or a better time, and I will book it.")
    else:
        lines.append("Reply to this email with a day that works this week and I will "
                     "book it.")
    if sms_sent:
        lines.append("I also sent you a text, so you can answer wherever is easier.")
    else:
        lines.append(f"If you would rather text, Maya answers at {MAYA_WA}.")
    lines += ["", "Maya", "Michael Moraes' team - MWM Creations & Studios",
              "1500 Park Center Dr, Suite 230, Orlando, FL"]
    text = "\n".join(lines)
    return subject, _as_html(lines), text


def disqualify_text():
    return ("Thanks for reaching out. We work with established businesses on a "
            "monthly subscription, so we're probably not the right fit. If you "
            "ever need studio hours on their own, " + BOOK_STUDIO_URL +
            " has the calendar.")


def disqualify_email(name):
    fn = first_name(name)
    lines = [f"Hi {fn},", "", disqualify_text(), "", "Maya",
             "Michael Moraes' team - MWM Creations & Studios"]
    return ("Thanks for reaching out to MWM Studios", _as_html(lines),
            "\n".join(lines))


# ── the chase chain ────────────────────────────────────────────────────────
# ERIC's spec (26 Sep): Day 1 "what a visit looks like" · Day 5 case study by
# industry · Day 10 "the three videos every [industry] needs" · Day 14 recap ·
# Day 30 "I'll stop here; the door stays open." Michael's first-person voice,
# $1,200 flat, no attachments, one CTA, 48h+ between sends. Two short texts
# (day 2, day 9) ride alongside for leads who consented to texts.

CTA_EMAIL = ("Reply to this email with a day that works, or text Maya at "
             + MAYA_WA + ", and she will book your " + VISIT_NAME + ".")

_CASE_STUDIES = (
    (("martial", "gym", "fitness", "dojo", "karate", "jiu", "taekwondo", "yoga",
      "crossfit", "training"),
     "Victory Martial Arts",
     "Victory runs schools across Florida. Parents do not enrol a child because "
     "a school has a nice logo; they enrol when they understand what the "
     "training does for the child. We filmed the instructors explaining exactly "
     "that, in the studio, in one session a month. Those videos run before the "
     "parent ever walks in, so the first visit is a yes, not a tour."),
    (("real estate", "realtor", "home", "property", "broker", "mortgage",
      "lending", "loan", "title"),
     "Top Florida Homes",
     "A buyer who understands the market before the first call is a buyer who "
     "trusts the agent. Top Florida Homes records a month of market-education "
     "videos in one studio session, and the agents send them before the "
     "meeting. The meeting is shorter and the close is faster."),
    (("auto", "car", "mechanic", "repair", "tire", "body shop", "dealer"),
     "Enzo Auto Service",
     "Nobody buys a repair they do not understand. Enzo's videos show the "
     "problem, the fix and the price logic in plain language, in English and "
     "Portuguese, filmed in the studio. The customer arrives already trusting "
     "the estimate."),
    (("dental", "dentist", "clinic", "medical", "doctor", "health", "chiro",
      "therapy", "aesthetic", "med spa", "wellness", "ortho"),
     "Smile American",
     "A patient who understands the treatment before the consultation accepts "
     "it in the consultation. Smile American films the dentist answering the "
     "questions patients ask most, one studio session at a time, and plays them "
     "before the appointment."),
)
_DEFAULT_CASE = (
    "Top Florida Homes",
    "A buyer who understands what you do before the first call is a buyer who "
    "trusts you. Top Florida Homes records a month of education videos in one "
    "studio session and sends them before the meeting. The meeting is shorter "
    "and the close is faster.")


def case_study_for(business, must_understand=""):
    hay = (str(business or "") + " " + str(must_understand or "")).lower()
    for words, client, story in _CASE_STUDIES:
        if any(w in hay for w in words):
            return client, story
    return _DEFAULT_CASE


def industry_word(business):
    """A short noun for '[industry]' in the day-10 subject. Falls back to
    'business' rather than guessing."""
    b = str(business or "").strip()
    if not b or len(b) > 40:
        return "business"
    return b


def chase_email(step, name, business="", must_understand="", ai=False):
    """(subject, html, text) for one chase step. step in 1..5.

    First person — Michael — because the corrected first-person email is what
    converted Todd Berger (ERIC, 26 Sep)."""
    fn = first_name(name)
    biz = str(business or "").strip()
    ind = industry_word(biz)
    client, story = case_study_for(biz, must_understand)
    if step == 1:
        subject = f"What a {VISIT_MINUTES}-minute Studio Strategy Visit looks like"
        body = [
            f"Hi {fn},", "",
            "Michael Moraes here. You applied for a Studio Strategy Visit, so let "
            "me tell you exactly what happens in those 30 minutes.",
            "You walk the studio. We sit down and I map the videos your buyers "
            "need to see before they decide - the questions they ask, the "
            "doubts that cost you the sale, the proof that closes it. You leave "
            "with a 90-day plan on one page. No pitch deck.",
            ("If you came in through the AI ad: yes, that is real. One shoot in "
             "our studio, and your business appears in any scene. We show you "
             "how at the visit." if ai else
             "I have been " + CREDITS + ". The work is simple: " + WE_DO + "."),
            CTA_EMAIL,
        ]
    elif step == 2:
        subject = f"How {client} uses the studio"
        body = [
            f"Hi {fn},", "",
            "A quick story, because it is closer to your situation than it looks.",
            story,
            "That is the whole idea behind the Studio Subscription: one session a "
            "month, we plan it, write it, shoot it and cut it, and your customers "
            "arrive already understanding you.",
            CTA_EMAIL,
        ]
    elif step == 3:
        subject = f"The three videos every {ind} needs before the customer buys"
        body = [
            f"Hi {fn},", "",
            "Every business whose customers must understand something before "
            "they buy needs the same three videos.",
            "1. The problem video - what goes wrong when people choose badly, in "
            "your words.",
            "2. The process video - what working with you actually looks like, "
            "step by step.",
            "3. The proof video - a customer who understood, bought, and is glad "
            "they did.",
            "One studio hour makes up to eight short videos, so a month covers "
            "all three with room to spare. At the visit we decide which one you "
            "shoot first.",
            CTA_EMAIL,
        ]
    elif step == 4:
        subject = f"Your {VISIT_NAME}, still open"
        body = [
            f"Hi {fn},", "",
            "Two weeks ago you applied for a Studio Strategy Visit. The offer has "
            "not changed, so here it is in one paragraph.",
            f"A free {VISIT_MINUTES}-minute visit: you walk the studio, we map the "
            "videos your buyers need to see, you leave with a 90-day plan. If it "
            "makes sense to continue, the Studio Subscription is $1,200 a month: "
            "four studio hours - up to 8 short videos an hour, or a podcast "
            "episode and ten cuts - plus strategy, scripts and editing.",
            CTA_EMAIL,
        ]
    else:
        subject = "I'll stop here - the door stays open"
        body = [
            f"Hi {fn},", "",
            "This is my last email about the Studio Strategy Visit. I would "
            "rather not keep writing if the timing is wrong.",
            "The door stays open. When your customers need to understand you "
            "better than they do today, the visit is still free, still 30 "
            "minutes, and Maya still books it.",
            CTA_EMAIL, "",
            "Michael Moraes", "MWM Creations & Studios - Orlando",
        ]
    if step != 5:
        body += ["", "Michael Moraes", "MWM Creations & Studios - Orlando"]
    return subject, _as_html(body), "\n".join(body)


def chase_sms(step, name, slots=None):
    """Core of the day-2 / day-9 texts (wrapped by sms_copy.compose)."""
    fn = first_name(name)
    when = _slot_phrase(slots)
    if step == 1:
        if when:
            return (f"Hi {fn}, Maya from Michael Moraes' team. Still happy to book "
                    f"your free 30-minute Studio Strategy Visit. Michael has {when}. "
                    f"Which works?")
        return (f"Hi {fn}, Maya from Michael Moraes' team. Still happy to book your "
                f"free 30-minute Studio Strategy Visit. Which day this week works?")
    if when:
        return (f"Hi {fn}, Michael has {when} open for your 30-minute Studio "
                f"Strategy Visit. Want one? Reply with the time, or 'later'.")
    return (f"Hi {fn}, Michael has time this week for your 30-minute Studio "
            f"Strategy Visit. Reply with a day that works, or 'later'.")


# ── html ───────────────────────────────────────────────────────────────────

def _as_html(lines):
    """Plain, readable HTML. One paragraph per non-empty line; no images, no
    attachments, no tracking."""
    out = []
    for ln in lines:
        s = str(ln)
        if not s.strip():
            continue
        out.append("<p style=\"margin:0 0 14px 0;font-family:Arial,Helvetica,"
                   "sans-serif;font-size:15px;line-height:1.5;color:#1a1a1a\">"
                   + _html.escape(s) + "</p>")
    return ("<div style=\"max-width:600px;padding:8px 0\">" + "".join(out) +
            "</div>")
