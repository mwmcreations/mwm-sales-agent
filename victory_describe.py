"""victory_describe.py — a short, honest name for a moment of footage.

Michael, 16 Sep: the long recordings (Night of Champions runs as long as the
whole night; the black-belt testing the same) hold many moments each, and
"that needs to be cut down to a lot of short clips … so people can pick the
individual moments." The cutting is energy-driven (vi_scan_long.py on the
Mini side); the NAMING is this file: six frames of a candidate moment go to
Claude, which answers with a title, a category from the Library's own list,
search words, who is in frame, and how much the moment is worth (a title
screen, an empty stage, someone at a podium reading a list = 1; a belt
handed over, a board breaking, a kid's face as their name is called = 5).

describe_sheet() never raises on the model's account: any problem returns
None and the caller decides. The API key is the app's (ANTHROPIC_API_KEY on
Railway); nothing here reads or logs it.
"""
import base64
import json
import os
import re

CATEGORIES = ["Training & seminar", "Instructor training", "Competition", "Board breaks",
              "Winning moments", "Crowd & parent reactions", "Belt & rank presentation",
              "Candlelight ceremony"]

PROMPT = """You are naming footage for Victory Martial Arts' own video library, so their staff can find moments and make short videos for parents and students.

The picture is a contact sheet: six frames, two seconds apart, of one 12-second moment. Context: %s

Answer with ONE JSON object and nothing else:
{"title": "3 to 6 plain words saying what we SEE (no names of people, no adjectives like 'amazing')",
 "category": one of %s,
 "keywords": ["5 to 8 lowercase words a staff member might type to find this: what is happening, who is in it, the setting"],
 "people": "who is in frame: kids, teens, adults, instructors, masters, parents, crowd, or a mix",
 "interest": 1 to 5,
 "why": "one short sentence"}

interest 5 = a moment a parent or a school would share on its own (a belt handed over, a board breaking, a kid's reaction, a hug, the crowd on its feet, a candle lit);
interest 3 = usable in a montage (a class drilling, a line-up, a demonstration);
interest 1 = a title screen, a logo, an empty stage, a blurred or dark frame, or someone at a podium reading from a list.
If frames are near-identical still slides or screens, that is interest 1."""


def describe_sheet(jpeg_bytes, context="", client=None, model=None):
    """-> {"title", "category", "keywords", "people", "interest", "why"} or None."""
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        model = model or os.environ.get("MODEL_MAIN", "claude-sonnet-4-6")
        msg = client.messages.create(
            model=model, max_tokens=400,
            messages=[{"role": "user", "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/jpeg",
                            "data": base64.b64encode(jpeg_bytes).decode("ascii")}},
                {"type": "text",
                 "text": PROMPT % (context or "Victory World Convention 2026", json.dumps(CATEGORIES))},
            ]}])
        text = "".join(getattr(b, "text", "") for b in msg.content)
        return parse_answer(text)
    except Exception as e:
        print("[VI-DESCRIBE] failed: %r" % (e,))
        return None


def parse_answer(text):
    """The JSON object out of the model's text, normalised. None if unusable."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    title = re.sub(r"\s+", " ", str(d.get("title") or "")).strip().strip(".")[:60]
    if not title:
        return None
    cat = str(d.get("category") or "")
    if cat not in CATEGORIES:
        low = cat.lower()
        stem = low.split()[0].rstrip("s") if low.split() else ""
        cat = next((c for c in CATEGORIES if c.lower() == low), None) or \
            next((c for c in CATEGORIES if stem and stem in c.lower()), None) or "Competition"
    kws = d.get("keywords") or []
    if isinstance(kws, str):
        kws = re.findall(r"[a-z0-9']+", kws.lower())
    kws = [re.sub(r"[^a-z0-9' -]", "", str(k).lower()).strip() for k in kws]
    kws = [k for k in kws if k][:10]
    try:
        interest = max(1, min(5, int(round(float(d.get("interest") or 1)))))
    except Exception:
        interest = 1
    return {"title": title, "category": cat, "keywords": kws,
            "people": str(d.get("people") or "")[:60], "interest": interest,
            "why": str(d.get("why") or "")[:160]}
