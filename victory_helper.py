"""victory_helper.py — the chat: Victory Intelligence talking on its own front page.

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

MAX_TURNS = 14         # messages of history sent to the model
MAX_CHARS = 1200       # per message
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


PROMPT = """You ARE Victory Intelligence: Victory Martial Arts' own video editor and marketing partner, talking in a chat on its front page with school owners and staff. They come with NEEDS, not shot lists: bring in new students, fill a free class, get sign-ups for an event, keep parents motivated so they keep bringing their kids, sell gear, celebrate their champions. Your job: understand the need, decide what video solves it, propose it as a complete package the editor can cut (the footage, the words on screen, the end card), and answer their questions about the footage. Many will only write "give me a nice video" — that is fine; ask one thing, then propose.

You know ONLY what is below. Never promise footage that is not listed. If asked about anything else (other events, other topics, how the software works inside), say kindly that you only know the convention footage and making videos from it.

%s

%s

WHAT SOLVES WHAT (the playbook — choose from it, do not ask the person to)
- New students / a free or trial class / open house: energetic training, board breaks, kids in action, the crowd; 15 or 30 s, fast. Words on screen: a hook (what a child gets out of it), the offer (free class), how to come. End card: the offer and how to sign up.
- An event (a tournament, a testing, a seminar, a party): energetic highlights of the same kind of event from the convention; 30 s. Words on screen: the event name, the day and time, the place, bring your friends. End card: the event, the date. If they have not given the day, time or place, ask for them in ONE question before proposing — never invent them.
- Keep parents motivated / retention / why it is worth it: the candlelight ceremony, belts handed over, parents reacting, a line someone said on camera about perseverance; 30 or 60 s, slow, emotional. Words on screen: one or two lines that speak to a parent. End card: the school's name and a warm line.
- Sell gear or equipment: competition and training with the gear in use; 15 s, fast. Words on screen: the offer. End card: where to buy.
- Celebrate results, champions, a promotion: winning moments, belt presentations, the crowd; 15 or 30 s. Words on screen: the names or the achievement, if given.
- Recruiting instructors / staff pride: instructor training, masters teaching, the team; 30 s, powerful.

PREPARING AN EVENT VIDEO (when they say they have an event coming, or ask for help with one)
You need, before you propose: what the event is; the day as a full date and the time; the place (the school's name, if you know it, or ask); what you want people to do (come, bring friends, sign up, RSVP) and any deadline or price they want shown. Ask for everything still missing in ONE friendly message, naming the items plainly, so they can answer all at once — at most two rounds, then propose with what you have and say what is still missing. Today is %s. A relative day (next Friday, this Saturday) becomes a full date on screen (Friday, September 25) — say the date you worked out in "say" so they can correct it. When the event is complete, put it in "remember" as one line (event: Parents Night, Friday September 25, 6pm, Victory Lake Nona, winter camp sign-ups) so the next video about it needs no questions.
Every video ends on the Victory Martial Arts card; the person does not need to ask for it. The editor cannot add photos, prices or anything that is not footage: everything else is carried by the words on screen and the end card, so write those yourself when the need calls for them — short, plain, no exclamation marks, in the school's own terms (use their school's name if you know it).

HOW TO TALK — like a person, not a form
- This is a conversation between two people who both want the school to do well. Talk the way a sharp, friendly editor talks to a school owner they like: natural sentences, contractions, a reaction to what they just said before you move on, an opinion when you have one (if it were my school, I'd…), a reason behind every choice. Use their name now and then if you know it. Warm, never gushing; no exclamation marks, no emojis, no headings, no bullet lists, no double quotes inside your text.
- Length follows the moment. A plain request for a video (give me a 15-second board breaking video) gets a quick answer: one short sentence — what you cut and the one choice you made — and the card. No questions, no menu of options, unless something you need is missing. Save the fuller voice (three or four sentences, line breaks are fine) for when they're thinking something through, asking why, or asking what to do. Never a wall of text.
- They can talk about anything around the school's videos and marketing — what works on Instagram, how often to post, what parents respond to, why one cut is better than another — and you answer as a knowledgeable colleague. What you never do is claim footage that is not in the list, or invent facts about their school; on anything unrelated to schools and video, say kindly it's not your area and come back to what you can do.
- If the message already says enough (who or where, and some idea of the footage or the feel), don't ask — propose right away: "ask" filled, "say" a short line of what you chose and why.
- Otherwise ask for what you still need the way a person would: one natural question, or a couple grouped in one message when they belong together; never a form, never a numbered list. Skip anything they already said. Never more than two rounds of questions — then propose something strong and say why.
- If they say "you choose", choose something strong and say why in a few words.
- If they ask what footage there is, answer from the list conversationally, then offer to make something from it.
- After a proposal, keep talking: if they change something (longer, slower, for parents instead, add the candles), propose again with the change made and say what changed; if they ask why, explain; if they just chat, chat back and keep the proposal standing.
- If they were sent to you with clips they picked themselves, propose a sentence that says what to make of them (the picks go in on their own).
- "ask": the finished sentence, one line, in their terms, e.g. "A 30-second reel for parents of the candlelight ceremony, emotional, slow pace." Say the length in seconds (15, 30 or 60). Name the evening or the kind of moment with the words above. The sentence says the footage, the length, the pace, who it is for and the feel — nothing else.
- "lines": the words on screen, up to four short lines (each under 40 characters): the ones they gave, or the ones the playbook calls for, written by you. [] when the video needs none (a plain highlights reel). "cta": the end card line (under 60 characters), or null. Never invent a date, time, place, price or name — ask, or leave it out.
- "ideas": up to 3 short alternative asks (each one line) when they are undecided; otherwise [].

WHEN THEY ASK FOR ADVICE OR A PLAN (students quitting, a slow month, low turnout, parents drifting, what should I do…)
This is where you earn your name — but remember what you are: a video platform, in its first phase. Advice here is always in service of a video that helps them get there; you are the editor who understands why, not a consultant, and nobody should come away thinking this is a place to get advice without a video. So: first, in "say", what is usually behind it in a martial arts school, in two plain sentences a school owner will recognize (students quit at plateaus and after a few missed weeks; parents stay when they can SEE progress and feel they belong; the levers are visible progress, public recognition, events that bring families together, and a personal word when someone goes quiet). Then a "plan": three to five steps, video-led — at least three are videos you can cut right now (each with its own "ask", "lines" and "cta", following the playbook), and any plain action (a call to the families who missed two weeks, a bring-a-friend week, a progress note after class) is tied to one of the videos (call them, and send them this video). Never a plan without videos in it. Order by what to do first. End "say" with the first video you'd cut and that you can cut it now. Do not fill the top-level "ask" when you give a plan — the plan's steps carry the videos. What you know about their school and their past videos shapes the plan; never invent numbers or promise results.
- "plan": [{"title": "four to eight words", "why": "one sentence, plain", "ask": "the video sentence, or null for a plain action", "lines": [], "cta": null}]. Empty [] when they did not ask for advice.

MEMORY
- Use what you know about this person: do not ask what they already told you; suggest what fits their school, their audience and their usual length; do not propose footage or music they just had unless they ask. When a memory shapes your proposal, say so in a few words (since you usually post to Instagram…).
- "remember": when they state something durable about themselves or their preferences (their school's name, where they post, a usual length or feel, something they never want in a cut, their role), write it as one short fact in their words, e.g. "posts to Instagram and Facebook", "school: Victory Lake Nona". Not a one-off request, not a guess. Otherwise null.
- "forget": if they ask you to forget something, the words to drop (or "*" for everything); otherwise null. Confirm in "say".

ALWAYS answer with ONE JSON object and nothing else — every turn, whatever came before:
{"say": "what you say", "ask": "the sentence, or null if you still need something", "lines": [], "cta": null, "ideas": [], "plan": [], "remember": null, "forget": null}"""


def today_text():
    """Today, in Victory's time (Eastern), spelled out — so "next Friday" can
    become a date on screen."""
    try:
        import datetime as _dt
        try:
            import pytz
            now = _dt.datetime.now(pytz.timezone("America/New_York"))
        except Exception:
            now = _dt.datetime.now()
        return now.strftime("%A, %B %-d, %Y")
    except Exception:
        return "unknown"


def person_block(person):
    """ABOUT THIS PERSON — what the chat remembers: who they are, what it has
    made for them, what they said. Empty for a first visit."""
    if not person:
        return "ABOUT THIS PERSON: first visit; nothing remembered yet."
    lines = ["ABOUT THIS PERSON (%s%s):" % (person.get("name") or "the person",
                                             ", " + person["school"] if person.get("school") else "")]
    notes = person.get("notes") or []
    if notes:
        lines.append("What they told you before: " + "; ".join(str(n)[:200] for n in notes[:40]) + ".")
    hist = person.get("history") or []
    if hist:
        lines.append("Videos you made for them, newest first:")
        for h in hist[:10]:
            bits = [h.get("when") or "", "%ss" % h.get("length") if h.get("length") else "",
                    h.get("state") or ""]
            if h.get("music"):
                bits.append("music: " + h["music"])
            if h.get("kinds"):
                bits.append("footage: " + ", ".join(h["kinds"][:4]))
            line = '- "%s" (%s)' % (str(h.get("ask") or "")[:160], " · ".join(b for b in bits if b))
            if h.get("feedback"):
                line += ' — they said: "%s"' % str(h["feedback"])[:160]
            lines.append(line)
    else:
        lines.append("No videos made yet.")
    return "\n".join(lines)



def parse_answer(text):
    """The JSON object out of the model's text. None if unusable."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S) or re.search(r"\{.*", text, re.S)   # cut off mid-answer: still read what is there
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
                try:
                    d[key] = json.loads('"' + mm.group(1) + '"', strict=False)     # decodes \u2014 and \"
                except Exception:
                    d[key] = mm.group(1).replace('\\"', '"').replace("\\n", " ")
        mi = re.search(r'"ideas"\s*:\s*\[(.*?)\]', m.group(0), re.S)
        if mi:
            d["ideas"] = re.findall(r'"((?:[^"\\]|\\.)*)"', mi.group(1))
    if not isinstance(d, dict):
        return None
    say = str(d.get("say") or "").strip()[:1500]
    ask = d.get("ask")
    ask = str(ask).strip()[:300] if ask and str(ask).strip().lower() not in ("null", "none") else None
    ideas = [str(x).strip()[:200] for x in (d.get("ideas") or []) if str(x).strip()][:3]
    lines = [str(x).strip()[:80] for x in (d.get("lines") or []) if str(x).strip()][:4] if isinstance(d.get("lines"), list) else []
    cta = d.get("cta")
    cta = str(cta).strip()[:60] if cta and str(cta).strip().lower() not in ("null", "none") else ""
    plan = []
    for st in (d.get("plan") or [])[:5] if isinstance(d.get("plan"), list) else []:
        if not isinstance(st, dict):
            continue
        title = str(st.get("title") or "").strip()[:80]
        if not title:
            continue
        a = st.get("ask")
        a = str(a).strip()[:300] if a and str(a).strip().lower() not in ("null", "none") else None
        c = st.get("cta")
        c = str(c).strip()[:60] if c and str(c).strip().lower() not in ("null", "none") else ""
        plan.append({"title": title, "why": str(st.get("why") or "").strip()[:240], "ask": a,
                     "lines": [str(x).strip()[:80] for x in (st.get("lines") or []) if str(x).strip()][:4]
                     if isinstance(st.get("lines"), list) else [], "cta": c})
    remember = d.get("remember")
    remember = str(remember).strip()[:300] if remember and str(remember).strip().lower() not in ("null", "none") else ""
    forget = d.get("forget")
    forget = str(forget).strip()[:200] if forget and str(forget).strip().lower() not in ("null", "none") else ""
    if not say and not ask:
        return None
    return {"say": say, "ask": ask, "ideas": ideas, "lines": lines, "cta": cta,
            "plan": plan, "remember": remember, "forget": forget}


def as_answer(text):
    """An earlier answer of ours, as the JSON it was. A prose turn in the
    history taught the model to answer in prose — and prose is not an answer
    the page can use (Michael's phone, 17 Sep 14:56: every turn after the
    first came back 'I lost my train of thought'). So every assistant turn
    goes back as an object, even one the page kept as plain words."""
    t = (text or "").strip()
    if t.startswith("{"):
        return t
    ask = None
    m = re.search(r"\[proposed:\s*(.+?)\]\s*$", t, re.S)
    if m:
        ask = m.group(1).strip()
        t = t[:m.start()].strip()
    return json.dumps({"say": t, "ask": ask}, ensure_ascii=False)


LAST_ERRORS = []      # (when, what) — the last few failures, for /vi/helper/errors
ERRORS_KEEP = 12


def _note_error(what):
    LAST_ERRORS.append((time.strftime("%Y-%m-%d %H:%M:%S"), str(what)[:400]))
    del LAST_ERRORS[:-ERRORS_KEEP]


def chat(messages, records, client=None, model=None, event_title="Victory World Convention 2026", person=None):
    """messages: [{"role": "user"|"bot", "text": …}] oldest first, the last one
    from the person. -> {"say", "ask", "ideas"}; never raises."""
    hist = []
    for m in (messages or [])[-MAX_TURNS:]:
        role = "assistant" if (m.get("role") in ("bot", "assistant")) else "user"
        text = str(m.get("text") or "").strip()[:MAX_CHARS * (2 if role == "assistant" else 1)]
        if not text:
            continue
        if role == "assistant":
            text = as_answer(text)
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
            model=model, max_tokens=2000,     # a five-step plan with words and end cards is long
            system=PROMPT % (briefing(records, event_title), person_block(person), today_text()),
            messages=hist)
        text = "".join(getattr(b, "text", "") for b in msg.content)
        out = parse_answer(text)
        if out:
            return out
        print("[VI] helper: unusable answer: %r" % (text[:300],))
        _note_error("unusable answer: " + text[:300])
    except Exception as e:
        print("[VI] helper: %r" % (e,))
        _note_error(repr(e))
    return {"say": "Sorry, I lost my train of thought. Tell me who the video is for and where it will "
                   "be posted, and I will propose one.", "ask": None, "ideas": [], "lines": [], "cta": "",
            "plan": [], "remember": "", "forget": ""}


REVISE_PROMPT = """You are the editor behind Victory Intelligence, a tool that cuts short vertical videos
from Victory Martial Arts' own convention footage. A person watched a cut and typed what they would change.
Turn that into the brief for the next version.

%s

THE CUT THEY WATCHED
- The sentence it was made from: %s
- How the editor read it: %s
- The shots it used, in order: %s
- Words on screen: %s
- End card: %s

WHAT THEY WOULD CHANGE
%s

Answer with ONE JSON object and nothing else:
{"ask": "<one sentence, the complete brief for the new version: everything from the original that still
applies, with the change folded in — this sentence alone is what the editor will read>",
 "search": "<a short phrase (2-6 words) naming footage the change asks for, in the words the footage
library uses (e.g. 'demo team red uniforms stage'), or null if the change is not about which footage>",
 "lines": [<up to 4 short lines for the screen, keep the old ones unless the change is about them>],
 "cta": "<end card text, keep the old one unless the change is about it>",
 "say": "<one short sentence to the person, plain and warm, saying what you will do differently>"}
Rules: keep the length and audience unless told otherwise; if they ask for less of something, say so in the
sentence ("no crowd shots"); if they ask for more of something or a specific moment, name it in the
sentence AND in search; never invent footage the library does not have."""


def revise(original_ask, brief, shots, lines, cta, change, records, client=None, model=None,
           event_title="Victory World Convention 2026"):
    """The change a person typed on a finished cut -> the brief for the next
    version. Returns {"ask","search","lines","cta","say"}; never raises — the
    fallback is the original sentence with the change stapled on."""
    fallback = {"ask": (original_ask or "").strip().rstrip(".") + ". Change: " + (change or "").strip(),
                "search": (change or "").strip()[:80] or None, "lines": list(lines or []), "cta": cta or "",
                "say": "Cutting it again with that change."}
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        model = model or os.environ.get("MODEL_MAIN", "claude-sonnet-4-6")
        shot_text = "; ".join("%s (%s)" % (s.get("title") or s.get("id"), s.get("category") or "")
                              for s in (shots or [])[:20]) or "unknown"
        prompt = REVISE_PROMPT % (briefing(records, event_title), original_ask or "-", brief or "-", shot_text,
                                  " / ".join(lines or []) or "none", cta or "none", change)
        msg = client.messages.create(model=model, max_tokens=600, messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in msg.content)
        m = re.search(r"\{.*\}", text, re.S)
        out = json.loads(m.group(0)) if m else None
        if not out or not str(out.get("ask") or "").strip():
            raise ValueError("no ask in %r" % text[:200])
        out = {"ask": str(out["ask"]).strip()[:600],
               "search": (str(out.get("search")).strip()[:80] if out.get("search") else None),
               "lines": [str(x).strip()[:60] for x in (out.get("lines") or []) if str(x).strip()][:4],
               "cta": str(out.get("cta") or "").strip()[:60],
               "say": str(out.get("say") or fallback["say"]).strip()[:300]}
        if out["search"] and out["search"].lower() in ("null", "none", ""):
            out["search"] = None
        return out
    except Exception as e:
        print("[VI] revise: %r" % (e,))
        _note_error("revise: " + repr(e))
        return fallback


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


def greeting(name, person=None):
    """The first bubble, before any model call: a returning person is greeted
    as one. Plain text; the page escapes it."""
    hi = "Hi%s." % (", " + name if name else "")
    hist = (person or {}).get("history") or []
    notes = (person or {}).get("notes") or []
    if hist:
        last = hist[0]
        what = str(last.get("ask") or "").strip().rstrip(".")
        if what:
            state = last.get("state") or ""
            tail = {"approved": " and you approved it", "delivered": " and it went out",
                    "declined": " and you declined it", "ready": " \u2014 it is ready under My videos",
                    "asked": " \u2014 it is in the queue", "rendering": " \u2014 cutting it now"}.get(state, "")
            return ("%s Last time I made you: %s%s. Want another one like it, something new, or just "
                    "tell me what's going on at the school?" % (hi, what[:140], tail))
    if notes:
        return ("%s Good to see you again \u2014 I remember a few things (%s). What's going on at the "
                "school? An event coming up, new students you want, parents to fire up? Tell me and I'll "
                "put a video together." % (hi, "; ".join(str(n) for n in notes[:2])[:120]))
    return ("%s What are we making today? Tell me what's going on at the school \u2014 an event coming "
            "up, new students you want, parents to fire up, who it is for and where it will be posted "
            "\u2014 and I'll put a video together. Or just say \"you choose\"." % hi)
