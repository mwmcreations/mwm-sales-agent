"""victory_helper.py — the helper that turns "give me a nice video" into an ask.

Michael, 17 Sep: "A lot of people don't know how to ask for a video. They
would just do something like, Give me a nice video … So what about we have,
since this is called Victory Intelligence, not only an intelligence for the
editing, but also to help them with prompting and asking what they want."

Two things, both small:

  ideas(records, seed)   three or four ready-made asks, built from what the
                         Library actually holds — no model, no cost, shown
                         the moment the page opens
  chat(messages, …)      the helper: a short exchange that ends with a
                         finished sentence for the box ("ask"). It knows
                         ONLY this tool and this footage: the briefing it
                         reads is built from the Library and nothing else,
                         so it cannot promise footage we do not have.

The model call is the app's (ANTHROPIC_API_KEY on Railway); nothing here
reads or logs it. chat() never raises on the model's account: any problem
returns a plain "try again" answer and the page carries on.
"""
import json
import os
import re
import time

MAX_TURNS = 8          # messages of history sent to the model
MAX_CHARS = 600        # per message
IDEAS_N = 4

KIND_ASKS = {
    "Board breaks": "board breaks",
    "Candlelight ceremony": "the candlelight ceremony",
    "Belt & rank presentation": "the belt presentations",
    "Competition": "the competition",
    "Winning moments": "the winning moments",
    "Instructor training": "the instructors",
    "Training & seminar": "the training sessions",
    "Crowd & parent reactions": "the crowd and the parents' reactions",
}

# (what, who/where, length, feel) — only kinds with footage are used
TEMPLATES = [
    ("Board breaks", "for Instagram", 15, "fast"),
    ("Night of Champions", "for the whole school", 30, "energetic"),
    ("Candlelight ceremony", "for parents", 30, "emotional, slow"),
    ("Black Belt Testing", "for students", 30, "motivational"),
    ("Winning moments", "for our champions", 15, "fast"),
    ("Crowd & parent reactions", "for families", 30, "happy"),
    ("Victory Dinner", "for the staff", 30, "warm"),
    ("Victory for Life Reception", "for our masters", 30, "emotional"),
    ("Instructor training", "for the team", 30, "powerful"),
    ("Training & seminar", "for new students", 15, "fast"),
    ("interviews", "with words on screen", 30, "inspiring"),
]


def _rows(records):
    for r in records or ():
        if not isinstance(r, dict):
            continue
        yield r


def inventory(records):
    """What the Library holds, counted: sessions, kinds, the strongest
    moments of each evening, and the interview lines people said."""
    sessions, kinds, best, quotes = {}, {}, {}, []
    for r in _rows(records):
        if r.get("kind") == "quote" or r.get("quote"):
            q = (r.get("quote") or r.get("title") or "").strip()
            if q and r.get("quotable", True):
                quotes.append((float(r.get("weight") or 0), q[:110], r.get("title") or ""))
            continue
        ses = r.get("session") or "other"
        cat = r.get("category") or "other"
        sessions[ses] = sessions.get(ses, 0) + 1
        kinds[cat] = kinds.get(cat, 0) + 1
        best.setdefault(ses, []).append((
            {"hero": 3, "high": 2}.get(r.get("priority"), 1), float(r.get("weight") or 0),
            r.get("title") or ""))
    for ses in best:
        best[ses].sort(reverse=True)
        best[ses] = [t for _, _, t in best[ses][:8] if t]
    quotes.sort(reverse=True)
    return {"sessions": sessions, "kinds": kinds, "best": best,
            "quotes": [q for _, q, _ in quotes[:25]]}


def briefing(records, event_title="Victory World Convention 2026"):
    inv = inventory(records)
    lines = ["THE TOOL — Victory Intelligence makes short vertical videos (9:16) from Victory Martial Arts' "
             "own footage of the %s. A person types ONE sentence in the box and presses Make it; the "
             "editor finds the footage, cuts it to music, and it appears under My videos in a few minutes."
             % event_title,
             "A sentence can say: how long (15, 30 or 60 seconds), the pace (fast / slow), which evening or "
             "kind of moment, who it is for (students, parents, kids, families, instructors, schools), where "
             "it will be posted (Instagram, Facebook, a school's page, an email), and the feel (energetic, "
             "emotional, motivational, happy, quiet). Optional: words on screen (up to four short lines) "
             "and an end card (a call to action). Someone who wants to choose their own clips can switch "
             "on 'I want to choose my own clips'.",
             "",
             "THE FOOTAGE (counts are moments in the Library):"]
    for ses, n in sorted(inv["sessions"].items(), key=lambda kv: -kv[1]):
        lines.append("- %s: %d moments. Strongest: %s" % (ses, n, "; ".join(inv["best"].get(ses, [])[:6])))
    lines.append("")
    lines.append("KINDS OF MOMENT: " + ", ".join("%s (%d)" % (k, n) for k, n in
                                                sorted(inv["kinds"].items(), key=lambda kv: -kv[1])))
    if inv["quotes"]:
        lines.append("")
        lines.append("THINGS PEOPLE SAID ON CAMERA (interview lines the editor can cut in, with the person's "
                     "own voice): " + " | ".join('"%s"' % q for q in inv["quotes"][:20]))
    return "\n".join(lines)


PROMPT = """You are the helper inside Victory Intelligence, Victory Martial Arts' video tool. Your one job: help a person say what video they want, in one sentence the editor can use. Many people will only write "give me a nice video" — that is fine; you ask, briefly, and then you write the sentence for them.

You know ONLY what is below. Never promise footage that is not listed. If asked about anything else (other events, other topics, how the software works inside), say kindly that you only know the convention footage and this tool.

%s

HOW TO TALK
- Plain, warm, short. At most 50 words per answer, on one line. No bullet lists, no headings, no emojis, no double quotes inside your text.
- Ask at most ONE question at a time, and only what you still need: who will watch it, where it goes (that sets the length), and which part of the weekend or kind of moment. Skip anything they already said.
- After two exchanges at most, write the sentence. If they say "you choose", choose something strong and say why in a few words.
- The sentence goes in "ask": one line, ready for the box, in the person's own terms, e.g. "A 30-second reel for parents of the candlelight ceremony, emotional, slow pace." Say the length in seconds (15, 30 or 60). Name the evening or the kind of moment with the words above.
- "ideas": up to 3 short alternative asks (each one line) when they are undecided; otherwise an empty list.

Answer with ONE JSON object and nothing else:
{"say": "what you say to the person", "ask": "the finished sentence, or null if you still need something", "ideas": []}"""


def parse_answer(text):
    """The JSON object out of the model's text. None if unusable."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    d = None
    try:
        # strict=False: a real line break inside "say" is not a reason to
        # throw the whole answer away
        d = json.loads(m.group(0), strict=False)
    except Exception:
        # the fields one by one, for an answer with a stray quote in it
        d = {}
        for key in ("say", "ask"):
            mm = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % key, m.group(0), re.S)
            if mm:
                d[key] = mm.group(1).replace('\\"', '"').replace("\\n", " ")
        mi = re.search(r'"ideas"\s*:\s*\[(.*?)\]', m.group(0), re.S)
        if mi:
            d["ideas"] = re.findall(r'"((?:[^"\\]|\\.)*)"', mi.group(1))
    if not isinstance(d, dict):
        return None
    say = str(d.get("say") or "").strip()[:600]
    ask = d.get("ask")
    ask = str(ask).strip()[:300] if ask and str(ask).strip().lower() not in ("null", "none") else None
    ideas = [str(x).strip()[:200] for x in (d.get("ideas") or []) if str(x).strip()][:3]
    if not say and not ask:
        return None
    return {"say": say, "ask": ask, "ideas": ideas}


def chat(messages, records, client=None, model=None, event_title="Victory World Convention 2026"):
    """messages: [{"role": "user"|"bot", "text": …}] oldest first, the last one
    from the person. -> {"say", "ask", "ideas"}; never raises."""
    hist = []
    for m in (messages or [])[-MAX_TURNS:]:
        role = "assistant" if (m.get("role") in ("bot", "assistant")) else "user"
        text = str(m.get("text") or "").strip()[:MAX_CHARS]
        if not text:
            continue
        if hist and hist[-1]["role"] == role:
            hist[-1]["content"] += "\n" + text
        else:
            hist.append({"role": role, "content": text})
    if not hist or hist[-1]["role"] != "user":
        hist.append({"role": "user", "content": "I want a video."})
    if hist[0]["role"] != "user":
        hist.insert(0, {"role": "user", "content": "Hi"})
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        model = model or os.environ.get("MODEL_MAIN", "claude-sonnet-4-6")
        msg = client.messages.create(
            model=model, max_tokens=400,
            system=PROMPT % briefing(records, event_title),
            messages=hist)
        text = "".join(getattr(b, "text", "") for b in msg.content)
        out = parse_answer(text)
        if out:
            return out
        print("[VI] helper: unusable answer: %r" % (text[:300],))
    except Exception as e:
        print("[VI] helper: %r" % (e,))
    return {"say": "Sorry, I could not think just now. Tell me who the video is for and where it will "
                   "be posted, and I will write the sentence for you.", "ask": None, "ideas": []}


def ideas(records, seed=None, n=IDEAS_N):
    """Ready-made asks from what the Library holds. Rotates by the hour so the
    page does not always open on the same four."""
    inv = inventory(records)
    have_kind = {k for k, c in inv["kinds"].items() if c >= 3}
    have_ses = {s for s, c in inv["sessions"].items() if c >= 5}
    pool = []
    for what, who, length, feel in TEMPLATES:
        if what == "interviews":
            if inv["quotes"]:
                pool.append("30 seconds of the instructors talking about what Victory means, with words on screen")
            continue
        if what in have_kind:
            pool.append("A %d-second reel of %s %s, %s" % (length, KIND_ASKS.get(what, what.lower()), who, feel))
        elif what in have_ses:
            pool.append("%d seconds of the %s %s, %s" % (length, what, who, feel))
    if not pool:
        return ["A 30-second highlights reel of the whole convention"]
    if seed is None:
        seed = int(time.time() // 3600)
    k = seed % len(pool)
    return (pool[k:] + pool[:k])[:n]
