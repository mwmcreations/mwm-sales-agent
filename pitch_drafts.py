"""
pitch_drafts.py — PATCH #282. After a visit where Michael pitched a plan, the
machine writes the follow-up emails from the report (package + meeting notes)
in his voice, and he sends each one with a tap. Nothing unread goes out.

WHY (Michael, Nov 12–17 2026)
  Ayodele Pompey was pitched AI Pro on Nov 12; the only written sequence knew
  the $1,200 Studio Package, so #280 halted it and #281 closed the generic
  rail — and from then on an AI-plan pitch got NO automated email at all. The
  recap he finally received (Nov 13, 16:56) and Mike Martinez's ROADMAP recap
  (Nov 17, 08:27) were written by hand from the meeting notes, in the same
  shape each time: what I heard · what we do and don't · the plan · the first
  30 days · the link · one question. This module writes that shape from the
  Desk report, for every plan we sell, so the draft is ready the minute the
  report is filed — and Michael's tap is the send (his rule: nothing unread
  goes out; "Michael taps Send", Nov 13).

WHAT IT KNOWS (facts as published on mwmcreations.com/book-studio, Nov 2026,
and ROADMAP as Michael pitched it on Nov 16): see PLANS. Prices are founding
prices through Nov 30, 2026 with the regular price in brackets where the page
shows one. ROADMAP Platinum carries no public price: the draft says "the
Platinum numbers we discussed" unless the report's notes name a figure.

PURE: no clock, no store, no Flask. The app stores the drafts on the lead
record (rec["pitch_drafts"]), the Desk shows them, the Send button sends.
"""
import html as _html
import re

PLANS_URL = "https://mwmcreations.com/book-studio/#st-plans"
ROADMAP_URL = "https://mwmcreations.com/roadmap/"
ROADMAP_PLANS_URL = "https://mwmcreations.com/video-production-plans/"
FOUNDING_UNTIL = "November 30"

# kind -> facts. `price` is the founding price line, `regular` the struck-through one.
PLANS = {
    "real_sets": {
        "label": "Real Sets", "family": "studio", "price": "$1,200/month", "regular": "$1,497",
        "what": "4 hours a month on the real sets, no AI",
        "includes": ["4 studio hours a month on the real sets",
                     "each hour: up to 10 edited short videos, or 1 podcast episode with 10 short cuts",
                     "strategy, scripts and editing included; your hours tracked in your own client portal"],
        "url": PLANS_URL},
    "ai_starter": {
        "label": "AI Starter", "family": "studio", "price": "$1,297/month", "regular": "$1,497",
        "what": "2 studio hours a month, one on the real sets and one on the AI Wall, plus a Full Immersion video every month",
        "includes": ["2 studio hours a month: 1 on the real sets, 1 on the AI Wall",
                     "1 Full Immersion video a month",
                     "each hour: up to 10 edited short videos, or 1 podcast episode with 10 short cuts"],
        "url": PLANS_URL},
    "ai_growth": {
        "label": "AI Growth", "family": "studio", "price": "$1,697/month", "regular": "$1,997",
        "what": "4 studio hours a month, up to 2 on the AI Wall, plus a Full Immersion video every month",
        "includes": ["4 studio hours a month, up to 2 of them on the AI Wall",
                     "1 Full Immersion video a month",
                     "each hour: up to 10 edited short videos, or 1 podcast episode with 10 short cuts"],
        "url": PLANS_URL},
    "ai_pro": {
        "label": "AI Pro", "family": "studio", "price": "$2,497/month", "regular": "$2,997",
        "what": "4 AI Wall hours a month plus two Full Immersion videos every month",
        "includes": ["4 AI Wall hours a month",
                     "2 Full Immersion videos a month",
                     "each hour: up to 10 edited short videos, or 1 podcast episode with 10 short cuts"],
        "url": PLANS_URL},
    "roadmap_silver": {
        "label": "ROADMAP Silver", "family": "roadmap", "price": "$1,997/month", "regular": "",
        "what": "6 strategic campaigns a year, one produced every other month",
        "includes": ["6 campaigns a year, one every other month, so the content never repeats",
                     "strategy, scripts, filming (on location, drone, or our studio) and the finished videos in horizontal and vertical",
                     "one to two days a month of your time on camera, some months none"],
        "url": ROADMAP_URL},
    "roadmap_gold": {
        "label": "ROADMAP Gold", "family": "roadmap", "price": "$2,497/month", "regular": "",
        "what": "12 strategic campaigns a year, one produced every month",
        "includes": ["12 campaigns a year, one every month, so you never repeat content",
                     "strategy, scripts, filming (on location, drone, or our studio) and the finished videos in horizontal and vertical",
                     "one to two days a month of your time on camera, some months none"],
        "url": ROADMAP_URL},
    "roadmap_platinum": {
        "label": "ROADMAP Platinum", "family": "roadmap", "price": "", "regular": "",
        "what": "two tracks at once, the company brand and your personal brand",
        "includes": ["two campaign tracks running in parallel: the company's story and yours",
                     "strategy, scripts, filming (on location, drone, or our studio) and the finished videos in horizontal and vertical",
                     "the Platinum numbers we discussed in the room"],
        "url": ROADMAP_URL},
}

ROADMAP_TERMS = ("A yearly roadmap, billed monthly. Upgrade or downgrade any time; if it isn't working, "
                 "60 days' notice and you're out. I will never ask you to pay the rest of the year.")
STUDIO_TERMS = (f"All plans have a 3-month minimum; the founding price holds for commitments made by {FOUNDING_UNTIL} "
                "and moves with you if you upgrade. Your month starts the day you pay.")

_KIND_WORDS = (
    ("roadmap platinum", "roadmap_platinum"), ("platinum", "roadmap_platinum"),
    ("roadmap gold", "roadmap_gold"), ("roadmap silver", "roadmap_silver"), ("silver", "roadmap_silver"),
    ("gold", "roadmap_gold"), ("roadmap", "roadmap_gold"),
    ("ai pro", "ai_pro"), ("ai growth", "ai_growth"), ("ai starter", "ai_starter"),
    ("real sets", "real_sets"), ("real set", "real_sets"),
)


def kind_for(service):
    """The report's package words -> a PLANS key, or '' when no draft fits
    (the 3-month Studio Package keeps its own written sequence; 'other' and
    blank get nothing — Michael writes those)."""
    s = str(service or "").strip().lower()
    if not s:
        return ""
    if s in PLANS:
        return s
    for word, kind in _KIND_WORDS:
        if word in s:
            return kind
    return ""


def first_name(name):
    for w in str(name or "").split():
        if w.lower().strip(".") not in ("dr", "mr", "mrs", "ms", "prof", "rev", "pastor", "coach"):
            return w.strip(",.")
    return "there"


_PRONOUNS = (
    (r"\b[Hh]e\b|\b[Ss]he\b|\b[Tt]hey\b", "you"),
    (r"\b[Hh]is\b|\b[Hh]er\b|\b[Tt]heir\b", "your"),
    (r"\b[Hh]im\b|\b[Tt]hem\b", "you"),
    (r"\b[Hh]imself\b|\b[Hh]erself\b|\b[Tt]hemselves\b", "yourself"),
)
_VERBS = {"needs": "need", "wants": "want", "has": "have", "is": "are", "was": "were", "confirms": "confirm",
          "likes": "like", "plans": "plan", "prefers": "prefer", "thinks": "think", "says": "say", "expects": "expect",
          "runs": "run", "owns": "own", "works": "work", "does": "do", "asks": "ask", "comes": "come", "gets": "get",
          "pays": "pay", "signs": "sign", "starts": "start", "films": "film", "sells": "sell", "wants": "want",
          "doesn't": "don't", "hasn't": "haven't", "isn't": "aren't", "wasn't": "weren't"}


def second_person(text):
    """Michael writes his notes about the lead ('he needs a week for funds');
    the email speaks to the lead ('you need a week for funds'). Pronouns and
    the verbs that follow them are turned; everything else is left alone.
    He reads the draft before it goes, so a clumsy sentence costs a tap, not a client."""
    s = str(text or "")
    for pat, rep in _PRONOUNS:
        s = re.sub(pat, rep, s)

    def _fix(m):
        v = m.group(2)
        return m.group(1) + _VERBS.get(v.lower(), v)

    s = re.sub(r"(\b[Yy]ou(?:r)?\s+)(\w+'?\w*)", lambda m: _fix(m) if m.group(1).strip().lower() == "you" else m.group(0), s)
    return s


def _sentences(notes, limit=4, to_you=True):
    """The meeting notes as clean sentences, turned to the lead ('you')."""
    s = re.sub(r"\s+", " ", str(notes or "")).strip()
    if not s:
        return []
    if to_you:
        s = second_person(s)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+|;\s+", s) if p.strip()]
    out = []
    for p in parts[:limit]:
        if to_you:
            w = p.split(" ", 1)
            if w[0].lower() in _VERBS:              # shorthand with the subject left out: "needs a week" -> "You need a week"
                p = "You " + _VERBS[w[0].lower()] + (" " + w[1] if len(w) > 1 else "")
        p = p[0].upper() + p[1:]
        if not p.endswith((".", "!", "?")):
            p += "."
        out.append(p)
    return out


def _heard_paragraph(notes):
    sents = _sentences(notes)
    if not sents:
        return ""
    return "What I heard from you: " + " ".join(sents)


def _plan_lines(kind, notes=""):
    p = PLANS[kind]
    price = p["price"]
    if kind == "roadmap_platinum":
        m = re.search(r"\$\s?([\d,]{4,6})", str(notes or ""))
        price = f"${m.group(1)}/month" if m else ""
    head = f"The plan we discussed, {p['label']}: {p['what']}."
    if price:
        head += f" {price}" + (f" (regular {p['regular']})" if p["regular"] else "") + "."
    return head, list(p["includes"])


def draft(kind, name, business="", notes="", next_steps="", hold_until=""):
    """-> {"recap": {...}, "value": {...}, "nudge": {...}} or {} when no draft
    fits. Each stage: subject, lines (plain), html, text. Michael's voice,
    first person, the shape of the Ayodele / Mike recaps."""
    kind = kind_for(kind) if kind not in PLANS else kind
    if not kind:
        return {}
    p = PLANS[kind]
    fn = first_name(name)
    biz = str(business or "").strip()
    about = f" for {biz}" if biz and len(biz) < 48 else ""
    heard = _heard_paragraph(notes)
    head, incl = _plan_lines(kind, notes)
    terms = ROADMAP_TERMS if p["family"] == "roadmap" else STUDIO_TERMS
    nxt = _sentences(next_steps, limit=3)
    hold = f" I'm holding the dates we talked about until {hold_until}." if hold_until else ""

    recap_lines = [f"Hi {fn},", "",
                   "Thanks for the time today. Here is what we went through, in one place, so you have it when you sit down with it."]
    if heard:
        recap_lines.append(heard)
    recap_lines.append(head)
    recap_lines += ["- " + x for x in incl]
    recap_lines.append(terms)
    if p["family"] == "roadmap":
        recap_lines.append("The first 30 days: we sit down for the brainstorming interview, you are the source of truth on your business, "
                           "then you get the scripts to approve, then we film. Campaign one is the brand story.")
    else:
        recap_lines.append("The first month: we book your first session, I come with the shot list from what we discussed, "
                           "and the first edited videos follow that session.")
    if nxt:
        recap_lines.append("Next steps as we agreed: " + " ".join(nxt))
    recap_lines.append(f"The plans in detail: {p['url']}" + (f" · the roadmap: {ROADMAP_PLANS_URL}" if p["family"] == "roadmap" else ""))
    recap_lines.append(f"Any question, reply to this email or call me.{hold} When you're ready, say the word and I'll send you two dates to start.")
    recap_lines += ["", "Michael", "MWM Creations & Studios · (813) 503-1224"]

    value_lines = [f"Hi {fn},", "",
                   f"One more thing from our conversation{about}, because it is the part people underestimate: the content never runs out.",
                   (f"With {p['label']} you get {p['what']}. " if p["family"] == "studio" else f"With {p['label']}, {p['what']}. ") +
                   "Every piece is planned before we film, so each month answers a question your customers are already asking, "
                   "and your ads, your social and your website get fresh material instead of recycling the same clips.",
                   "If you want, I can walk whoever runs your marketing through exactly what they will receive from us each month, "
                   "so they know what to do with it.",
                   f"Plans: {p['url']}",
                   "", "Michael", "MWM Creations & Studios · (813) 503-1224"]

    nudge_lines = [f"Hi {fn},", "",
                   f"I'll keep this short. The {p['label']} plan is still open as we discussed" +
                   (f", and the founding price holds through {FOUNDING_UNTIL}." if p["family"] == "studio" else "."),
                   "If it's a yes, I'll send two dates for the first session. If the timing is wrong, tell me the month and I'll come back then.",
                   "", "Michael", "MWM Creations & Studios · (813) 503-1224"]

    def pack(stage, subject, lines):
        return {"stage": stage, "subject": subject, "lines": lines, "html": as_html(lines),
                "text": "\n".join(lines), "status": "draft"}

    return {
        "recap": pack("recap", f"{fn}, the {p['label']} plan we talked about, in writing", recap_lines),
        "value": pack("value", f"What {p['label']} does month after month", value_lines),
        "nudge": pack("nudge", f"{fn}, still open: {p['label']}", nudge_lines),
    }


def as_html(lines):
    out = []
    for ln in lines:
        s = str(ln)
        if not s.strip():
            continue
        if s.startswith("- "):
            out.append("<p style=\"margin:0 0 6px 18px;font-family:Arial,Helvetica,sans-serif;font-size:15px;"
                       "line-height:1.5;color:#1a1a1a\">&bull; " + _link(_html.escape(s[2:])) + "</p>")
        else:
            out.append("<p style=\"margin:0 0 14px 0;font-family:Arial,Helvetica,sans-serif;font-size:15px;"
                       "line-height:1.5;color:#1a1a1a\">" + _link(_html.escape(s)) + "</p>")
    return "<div style=\"max-width:640px;padding:8px 0\">" + "".join(out) + "</div>"


def _link(escaped):
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#0f2a3c;font-weight:bold">\1</a>', escaped)


def summary_line(drafts):
    """One line for Slack: which drafts exist and their status."""
    if not drafts:
        return "no drafts"
    return " · ".join(f"{k}: {v.get('status', 'draft')}" for k, v in drafts.items() if isinstance(v, dict))
