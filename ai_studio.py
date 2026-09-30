"""PATCH #140 — Maya knows the AI Studio offers (Michael, 30 Sep 2026).

ROB's pricing (doc "MWM AI Video Pricing — Proposal", Michael's decisions 29–30 Sep):
  available now   AI shots added to studio videos, per second of finished video:
                  B-roll $6 · Motion Replace $12 · Cinematic $24
                  (minimum 10 s per order, billed in 5-second blocks)
  coming soon     open with the new studio (no date promised), after the AI-wall test:
                  AI Sets (Hour / Subscription / upgrade): unpriced, early access only,
                  3-month minimum ($2,197 for Founding Ten clients) ·
                  (prices hidden on the page since 30 Sep, ROB + Michael)
Positioning: studio first ("one shoot in our studio, your business in any scene"),
never "send us photos"; "No green screens" is true and stays; the 30-minute Studio
Strategy Visit is the call to action.

Price rule (Michael, 29 Sep, via ERIC: the AI ad carries no price, "the price is
quoted in the room"): Maya quotes AI prices ONLY to a visitor chatting on the AI
Studio page, where the same prices are printed. Everywhere else she books the visit.

Pure functions, no I/O: app.py decides WHEN, this module decides WHAT.
"""
import os
import re

AI_PAGE_PATH = "/ai-studio"

# The public page is an unpublished draft until Michael says go. Maya must not
# send people to a 404, so the link is only offered once this is switched on.
def page_live():
    return str(os.getenv("AI_STUDIO_PAGE_LIVE", "0")).strip().lower() in ("1", "true", "yes", "on")

def ai_ad_ids():
    """AD_19 "Film once" and later AI ads: Railway var AI_AD_IDS (comma list)."""
    return {x.strip() for x in str(os.getenv("AI_AD_IDS", "")).split(",") if x.strip()}

# What a lead's OWN words look like when they are asking about AI video.
# Deliberately narrow: "AI" alone is too common ("ai" inside words, "AI" chatbots).
_AI_ASK = re.compile(
    r"\b(ai|a\.i\.)\s*(video|videos|set|sets|scene|scenes|studio|shot|shots|background|backgrounds|b-?roll|version)\b"
    r"|\bartificial intelligence\b"
    r"|\bgenjutsu\b|\bhiggsfield\b"
    r"|\bmotion replace\b"
    r"|\bfilm(ed)? once\b|\bgo anywhere\b|\bany (scene|world)\b"
    r"|\bno green ?screen\b|\bwithout (a )?green ?screen\b"
    r"|\b(rooftop|stage|restaurant)\b.{0,40}\b(ai|video|scene)\b"
    r"|\bv[ií]deo(s)? com (ia|intelig[eê]ncia artificial)\b"
    r"|\b(ia|inteligencia artificial)\b.{0,30}\bv[ií]deo",
    re.I,
)

_HEADLINE_HINT = re.compile(r"film once|go anywhere|any scene|any world|\bai\b|genjutsu", re.I)


def on_ai_page(page_url):
    return bool(page_url) and AI_PAGE_PATH in str(page_url).lower()


def ai_lead(ad_id=None, messages=None, headline="", ad_ids=None):
    """Is this conversation about the AI offers? -> (bool, reason).

    `messages` = the LEAD's own messages only (never Maya's — she will say
    "AI" herself once she is on the branch, which would latch it on)."""
    ids = set(ad_ids if ad_ids is not None else ai_ad_ids())
    aid = str(ad_id or "").strip()
    if aid and aid in ids:
        return True, "ad_id"
    if headline and _HEADLINE_HINT.search(str(headline)):
        return True, "ad_headline"
    for raw in (messages or ()):
        if _AI_ASK.search(str(raw or "")):
            return True, "asked"
    return False, ""


_FACTS = """
WHAT WE OFFER (facts — do not add to them, do not invent dates, deliverables or discounts):
- It is a HYBRID AI studio — call it that. It is NOT 100% AI: the person still comes in and records with us, for real. Only the world around them is AI.
- The idea: they film ONE session with Michael in our Orlando studio, and we place them in any scene with AI (a rooftop, their own restaurant or business, a stage, a city at night). Their real face, real voice and real performance; AI builds the world around them. "No green screens" is true and you may say it.
- Available NOW: AI shots added to studio videos, priced per second of finished video. AI B-roll (fully generated scenes and cutaways), AI Motion Replace (their real footage with the objects or environment replaced while they move), AI Cinematic (4K hero shots with native audio). Minimum 10 seconds per order, billed in 5-second blocks.
- COMING WITH OUR NEW STUDIO: AI Sets. The client films on our new AI wall and appears in the location of their choice, in every video they record with us. There is NO public price and NO date yet: never quote a price or promise a date or month for AI Sets, the AI Studio Hour, the AI Studio Subscription or the AI hour upgrade. If asked, say: "AI Sets open with our new studio. Want early access?" and offer the 30-minute Strategy Visit. Do NOT take bookings or payments for them.
- If someone wants "a video like the demo" (the 47-second video on the AI page: rooftop, restaurant, martial arts, stage, city at night), explain that the demo was made with the per-second AI shots (AI Motion Replace and AI Cinematic), not with an AI Set, and offer the Strategy Visit to plan and price theirs.
- Billing rules: paid before we generate; one revision round per video (up to 25% of its AI seconds); standard editing is separate and never includes AI generation.
- NEVER say or imply "send us your photos and we'll turn them into AI video". Every AI video starts with a real shoot in our studio. If someone asks for photo-to-video, explain kindly that our AI work starts from a real studio shoot, and invite them to the visit.
- The next step is ALWAYS the free 30-minute Studio Strategy Visit with Michael, booked with your usual tools. That is where scenes and pricing are decided.
- If this person is ALREADY A CLIENT (client mode above), do not pitch the visit or quote prices: tell them Michael will go over AI options for their next session, and let the team know.
"""

_PRICES_ON_PAGE = """
PRICES — the visitor is on the AI Studio page, where these are printed, so you may confirm them:
- AI B-roll $6 · AI Motion Replace $12 · AI Cinematic $24, per second of finished video (min 10 s, 5-s blocks).
- AI Sets, the AI Studio Hour, the AI Studio Subscription and the AI hour upgrade have NO public price: never quote one (the page no longer shows them). Say "AI Sets open with our new studio. Want early access?"
Say prices plainly ("$12 per second"), never "only" or "just". No discounts, coupons or payment plans.
"""

_PRICES_OFF_PAGE = """
PRICES — do NOT quote AI prices in this conversation (Michael's rule: AI pricing depends on the scenes, and he walks every client through it in the 30-minute Strategy Visit). If they ask, say exactly that, warmly, and offer times for the visit. Do not guess, do not give ranges, do not compare with other offers.
"""


def maya_ai_context(page_url="", why=""):
    """The extra system-prompt block. Empty string = not an AI conversation."""
    here = on_ai_page(page_url)
    if not here and not why:
        return ""
    head = ("\n\n═══ AI STUDIO — this visitor is " +
            ("on our AI Studio page" if here else "asking about AI video (" + why + ")") +
            ". Read before replying. ═══")
    link = ""
    if page_live():
        link = "\n- You may share the page: https://mwmcreations.com/ai-studio/ (once, when it helps)."
    return head + _FACTS + (_PRICES_ON_PAGE if here else _PRICES_OFF_PAGE) + link
