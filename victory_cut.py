"""victory_cut.py — the machine editor. Phase 3, built the way Michael asked for it:

    "a real automated system that actually finds the footage, edits the footage,
     and delivers it right there in the app."                       — 14 Sep 2026

    ask + picked moments
        -> candidates   (the index ranks the convention for the ask)
        -> pick_shots   (variety across days and kinds of moment, story order)
        -> pick_music   (the library, matched to the ask, rotated per person)
        -> plan         (in-point per shot, 9:16 window from reframe.json)
        -> render       (pure ffmpeg: segments, concat, titles, music, loudness)

Everything above `render` is pure and runs anywhere with the JSON sources.
`render` needs ffmpeg and the clip files; it runs on the Mac Mini worker
(vi_render_worker.py) for the test week. No OpenCV anywhere at run time: the
one-time look at every clip lives in victory_source/<event>/reframe.json.

THE TWO RULES FROM THE FIRST TWO REELS (Michael, 14 Sep)
  1. Variety. "They look alike, from the same moment." A broad ask must move
     across the days and the moments of the convention. Caps per kind of shot
     and per session, days balanced as we go, and a story order so the reel
     opens on training and closes on the candles.
  2. Music from a library, rotated. Never the same track twice running for
     the same person.
"""
import json
import os
import re
import subprocess

W, H, FPS = 1080, 1920, 30
PRIORITY = {"hero": 3, "high": 2, "standard": 1, "low": 0}
# the story a highlights reel tells, in order
STORY = ["Training & seminar", "Instructor training", "Competition", "Board breaks",
         "Winning moments", "Crowd & parent reactions", "Belt & rank presentation",
         "Candlelight ceremony"]
LENGTHS = (15, 30, 60)
SHOT_SECONDS = 3.0      # a shot the machine chose
PICK_SECONDS = 5.0      # a shot the person picked
SPEECH_MAX = 12.0       # an interview moment, at most (ends on a line boundary)
SPEECH_MIN = 4.0        # never a sound bite shorter than this
SPEECH_MUSIC = 0.12     # music under someone talking
BROLL_NAT = 0.25        # natural sound under music elsewhere

FONT_CANDIDATES = [
    os.environ.get("VI_FONT", ""),
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",       # macOS
    "/System/Library/Fonts/Supplemental/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",     # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def font_path():
    for f in FONT_CANDIDATES:
        if f and os.path.exists(f):
            return f
    return None


# ── 1. what to cut ─────────────────────────────────────────────────────────
def pick_shots(cands, n, requested=(), max_per_family=2, max_per_session=3, by_search=False,
               avoid=(), seed=0, uncapped=()):
    """Choose n clips. Requested ids always go in, in the order given. Then
    hero > high > the rest, but never more than max_per_family of one kind of
    shot or max_per_session from one session, and the kinds and days are
    balanced as we go. Returns them in story order.

    avoid: ids this person has already been given in recent cuts — they go to
    the back of the line, so the weekend's variety is used before anything
    repeats (Michael, 14 Sep: "the computer tries to go for the same ones").
    seed: a per-request number; equal candidates are shuffled by it, so two
    similar asks do not produce the same reel.
    uncapped: kinds of moment the ask NAMED ("board breaks") — the caps do not
    apply to them; an ask for board breaks gets board breaks.

    cands: clip dicts with id, category, session, day, priority, weight.
    """
    import random
    rnd = random.Random(seed)
    jitter = {c["id"]: rnd.random() for c in cands}
    avoid = set(avoid or ())
    uncapped = set(uncapped or ())
    # a clip shorter than a shot makes a choppy fill: it goes to the back
    # unless the ask named its kind (self-test #13: a 2.2 s crowd clip as filler)
    short = {c["id"]: float(c.get("seconds") or 99) < SHOT_SECONDS + 0.5
             and c.get("category") not in uncapped for c in cands}
    by_id = {c["id"]: c for c in cands}
    chosen = [by_id[r] for r in requested if r in by_id]
    fam, ses, day = {}, {}, {}

    def bump(c):
        fam[c.get("category")] = fam.get(c.get("category"), 0) + 1
        ses[c.get("session")] = ses.get(c.get("session"), 0) + 1
        day[c.get("day")] = day.get(c.get("day"), 0) + 1

    for c in chosen:
        bump(c)
    taken = set(x["id"] for x in chosen)
    pool = [c for c in cands if c["id"] not in taken]
    while len(chosen) < n and pool:
        if by_search:      # the ask's own footage leads (weight 10 = a hit or a named
            # kind) — before rotation: someone who asked for candlelight would
            # rather see a candle clip again than board breaks (self-test #11)
            pool.sort(key=lambda c: (-round(float(c.get("weight") or 0), 1),
                                     c["id"] in avoid, short[c["id"]],
                                     fam.get(c.get("category"), 0),
                                     day.get(c.get("day"), 0), jitter[c["id"]]))
        else:              # hero and high are one class here: the weekend's variety comes first
            pool.sort(key=lambda c: (c["id"] in avoid, short[c["id"]],
                                     -min(2, PRIORITY.get(c.get("priority"), 0)),
                                     fam.get(c.get("category"), 0),
                                     day.get(c.get("day"), 0), jitter[c["id"]]))
        pick = None
        for c in pool:
            if c.get("category") not in uncapped:
                if fam.get(c.get("category"), 0) >= max_per_family:
                    continue
                if ses.get(c.get("session"), 0) >= max_per_session:
                    continue
            pick = c
            break
        if pick is None:                  # quotas exhausted: take the best left
            pick = pool[0]
        chosen.append(pick)
        bump(pick)
        pool.remove(pick)
    chosen.sort(key=lambda c: (STORY.index(c.get("category")) if c.get("category") in STORY else 99,
                               c.get("day") or 0, c["id"]))
    return chosen


STOP = {"a", "an", "the", "of", "for", "and", "to", "in", "on", "at", "with", "from",
        "our", "my", "page", "second", "seconds", "sec", "s", "reel", "video", "clip",
        "make", "cut", "please", "want", "need", "aimed", "about"}
SYN = {"best": "highlights", "moments": "recap", "highlights": "highlights",
       "champions": "highlights", "kids": "kids", "children": "kids", "kid": "kids",
       "parents": "parents", "parent": "parents", "mom": "parents", "moms": "parents",
       "mother": "parents", "dad": "parents", "family": "parents", "families": "parents",
       "ceremony": "ceremony", "candle": "candlelight", "candles": "candlelight",
       "belt": "ceremony", "belts": "ceremony", "tournament": "tournament",
       "sparring": "sparring", "fight": "sparring", "fighting": "sparring",
       "instructor": "instructor", "instructors": "instructor", "interview": "interview",
       "interviews": "interview", "grandmaster": "grandmaster", "fun": "fun",
       "medals": "medals", "medal": "medals", "winners": "medals", "winning": "medals",
       "epic": "epic", "emotional": "emotional", "energy": "energetic",
       "energetic": "energetic", "hype": "hype", "training": "corporate",
       "seminar": "corporate", "board": "board", "boards": "board", "breaks": "board",
       "break": "board", "celebration": "celebration", "crowd": "crowd", "cheering": "crowd"}


def ask_words(ask):
    return {SYN.get(w, w) for w in re.findall(r"[a-z]+", (ask or "").lower()) if w not in STOP}


def pick_music(library, ask, exclude=()):
    """Match the ask's words to track tags. Unknown asks get the uplifting
    default. exclude = ids this person received recently, so the music rotates."""
    words = ask_words(ask)
    tracks = [t for t in library.get("tracks", []) if t["id"] not in exclude]
    if not tracks:
        tracks = list(library.get("tracks", []))
    best, score = None, 0
    for t in tracks:
        s = sum(1 for tag in t.get("tags", []) for w in tag.split() if w in words)
        if s > score:
            best, score = t, s
    if best is None:
        pool = [t for t in tracks if "uplifting" in t.get("tags", [])] or tracks
        best = pool[0] if pool else None
    return best


# ── 2. where to look in each clip ──────────────────────────────────────────
def window_for(clip_id, reframe, t0, dur):
    """The 9:16 window (x centre as a fraction of width) and how sure we are.

    reframe.json holds, per clip, per one-second window: faces (count), fx
    (area-weighted face x), ax (where the motion and detail are). Faces win
    when there are enough of them; otherwise the action window; otherwise
    the centre. Also returns the in-point: the busiest second in the clip
    that still leaves room for `dur`.
    """
    info = (reframe or {}).get(clip_id)
    if not info or not info.get("windows"):
        return 0.5, "centre", t0
    wins = info["windows"]
    total = info.get("duration") or (len(wins) + 0.0)
    # in-point: the window with the most energy such that t0+dur fits
    last_ok = max(0, int(total - dur - 0.1))
    cands = [w for w in wins if w["t"] <= last_ok] or wins[:1]
    start = max(cands, key=lambda w: (w.get("energy") or 0))["t"]
    start = float(max(0.0, min(start, last_ok)))
    seg = [w for w in wins if start <= w["t"] < start + dur] or cands[:1]
    faces = sum(w.get("faces") or 0 for w in seg)
    fxs = [(w["fx"], w["faces"]) for w in seg if w.get("fx") is not None and w.get("faces")]
    if faces >= 6 and fxs:
        x = sum(fx * n for fx, n in fxs) / sum(n for _, n in fxs)
        return round(x, 3), "faces", start
    axs = [w["ax"] for w in seg if w.get("ax") is not None]
    if axs:
        return round(sum(axs) / len(axs), 3), "action", start
    return 0.5, "centre", start


# ── 2b. interview moments ─────────────────────────────────────────────────
def quote_shots(items, moments_index, have_file, max_s=SPEECH_MAX):
    """The interview lines the person picked, as "speech" shots. Pure.

    items:          the request's picks (dicts with kind, id, quote/title).
    moments_index:  victory_source/<event>/quote_moments.json — every transcript
                    line mapped to a ~30 s piece of the ATEM recording it was
                    said in (offset inside that piece, its length, whether it
                    is the interviewer's question, and where the next line
                    starts).
    have_file:      moment file name -> True when the worker has that piece.

    A picked QUESTION ("And for you mom, why Victory?") plays the ANSWER: the
    person picked it because of what came next, so the shot starts at the next
    line. The shot then runs to a line boundary, at least SPEECH_MIN, at most
    max_s. Returns (shots, missing): missing are the picks nothing could be
    found for, in the person's words, for the card.
    """
    quotes = (moments_index or {}).get("quotes") or {}
    moments = (moments_index or {}).get("moments") or {}
    by_moment = {}
    for qid, q in quotes.items():
        by_moment.setdefault(q["moment"], []).append(q)
    for v in by_moment.values():
        v.sort(key=lambda q: q["offset"])
    shots, missing = [], []
    for it in items or ():
        if it.get("kind") == "clip":
            continue
        label = (it.get("quote") or it.get("title") or it.get("id") or "")[:120]
        nat = (it.get("id") or "").split(":", 1)[-1]
        q = quotes.get(nat) or quotes.get(re.sub(r"#\d+$", "", nat))
        m = moments.get(q["moment"]) if q else None
        if not q or not m or not have_file(m["file"]):
            missing.append(label)
            continue
        m_len = float(m["end"]) - float(m["start"])
        start = float(q["next_offset"] if q.get("question") else q["offset"])
        if start >= m_len - 1.0:                     # the answer is off the end of this piece
            start = float(q["offset"])
        end = start
        for ln in by_moment.get(q["moment"], []):    # run to a line boundary
            if ln["offset"] < start:
                continue
            e = ln["offset"] + float(ln.get("line_dur") or 0)
            if e - start > max_s:
                break
            end = max(end, e)
            if end - start >= 7.0:
                break
        end = max(end, start + SPEECH_MIN)
        end = min(end, start + max_s, m_len)
        dur = round(end - start, 2)
        if dur < 2.0:
            missing.append(label)
            continue
        shots.append({"id": m["file"][:-4] if m["file"].endswith(".mp4") else m["file"],
                      "file": m["file"], "drive_id": None, "kind": "speech",
                      "title": label, "quote_id": nat, "session": it.get("session"),
                      "day": None, "category": "Interview", "priority": "hero",
                      "in": round(start, 2), "dur": dur, "x": 0.5, "framed_by": "centre",
                      "requested": True})
    return shots, missing


# ── 3. the plan ────────────────────────────────────────────────────────────
def plan(ask, cands, requested_ids, library, reframe, length_s=30, recent_music=(), by_search=False,
         avoid=(), seed=0, lines=(), cta="", speech=(), focus=()):
    """Everything the render needs, as data. Pure.
    lines:  the person's own sentences to put over the pictures, in order.
    cta:    the end card ("Enroll today — victoryma.com"); blank = the sign-off.
    speech: interview moments from quote_shots(); they open the reel.
    focus:  kinds of moment the ask named (from candidates()); uncapped."""
    length_s = int(length_s) if int(length_s or 0) in LENGTHS else 30
    budget = length_s - 0.5
    # THE PERSON'S PICKS LEAD (Michael, 16 Sep: his picks were "buried and
    # short"). Interview moments come first, then picked clips in the order
    # picked at PICK_SECONDS each; the machine fills whatever time is left at
    # SHOT_SECONDS, in story order, never repeating a pick.
    speech_out = []
    for s in speech or ():
        s = dict(s)
        room = budget - sum(x["dur"] for x in speech_out)
        if room < SPEECH_MIN:
            break
        s["dur"] = round(min(float(s["dur"]), room), 2)
        speech_out.append(s)
    room = budget - sum(x["dur"] for x in speech_out)
    by_id = {c["id"]: c for c in cands}
    picks = [by_id[r] for r in requested_ids if r in by_id]
    if len(picks) * PICK_SECONDS > room:                    # too many picks for the length
        picks = picks[:max(0 if speech_out else 1, int(room // PICK_SECONDS))]
    def shot(c, dur, req):
        # a clip shorter than the shot gives what it has (two convention clips
        # are 2 s long; 16 Sep self-test #5 came out 1 s short because of one)
        have = float(c.get("seconds") or 0)
        if have:
            dur = round(max(0.5, min(dur, have - 0.05)), 2)
        x, how, t0 = window_for(c["id"], reframe, 1.0, dur)
        return {"id": c["id"], "drive_id": c.get("drive_id"), "file": c.get("file"),
                "title": c.get("title"), "session": c.get("session"),
                "day": c.get("day"), "category": c.get("category"),
                "priority": c.get("priority"), "in": round(t0, 2),
                "dur": dur, "x": x, "framed_by": how, "requested": req}

    lead = list(speech_out) + [shot(p, PICK_SECONDS, True) for p in picks]
    remaining = budget - sum(x["dur"] for x in lead)
    n_fill = max(0, int(round(remaining / SHOT_SECONDS)))
    fill = []
    pool = [c for c in cands if c["id"] not in {p["id"] for p in picks}]
    for extra in range(0, 6):                 # top up while short clips leave a hole
        if not n_fill + extra or not pool:
            break
        # a narrow ask is narrow on purpose: the kind-of-moment cap loosens with the length
        chosen = pick_shots(pool, n_fill + extra, by_search=by_search, avoid=avoid, seed=seed,
                            max_per_family=max(2, (n_fill + extra) // 3) if by_search else 2,
                            uncapped=focus)
        fill = [shot(f, SHOT_SECONDS, False) for f in chosen]
        if remaining - sum(x["dur"] for x in fill) < 1.5 or len(chosen) < n_fill + extra:
            break
    over = sum(x["dur"] for x in lead + fill) - budget
    if over > 0.5 and fill:                   # never past the length asked for
        if fill[-1]["dur"] - over >= 2.0:
            fill[-1]["dur"] = round(fill[-1]["dur"] - over, 2)
        else:
            fill.pop()
    hole = budget - sum(x["dur"] for x in lead + fill)
    if hole > 0.1 and fill:                   # short clips left a hole: the fills breathe a little
        per = hole / len(fill)
        for f in fill:
            have = float(by_id.get(f["id"], {}).get("seconds") or 0)
            cap = (have - f["in"] - 0.05) if have else f["dur"] + per
            f["dur"] = round(max(f["dur"], min(f["dur"] + per, cap, 4.5)), 2)
    music = pick_music(library, ask, exclude=recent_music)
    out = lead + fill
    lines = [str(x).strip()[:60] for x in (lines or ()) if str(x).strip()][:4]
    return {"ask": ask, "length_s": length_s, "shots": out, "pool": "search" if by_search else "convention",
            "speech_seconds": round(sum(s["dur"] for s in speech_out), 2),
            "lines": lines, "cta": (cta or "").strip()[:60],
            "cards": card_plan(length_s, ask, lines, (cta or "").strip()[:60], top=bool(speech_out)),
            "music_id": music["id"] if music else None,
            "music_title": music.get("title") if music else None,
            "music_file": music.get("file") if music else None,
            "days": sorted({s["day"] for s in out if s.get("day")}),
            "kinds": sorted({s["category"] for s in out if s.get("category")})}


def card_plan(length_s, ask, lines, cta, event_title="Convention 2026", top=False):
    """The cards over the reel, as (big, small, t_in, t_out, y).

    top: the reel opens on someone talking — the head card sits high in the
    frame (y 0.14) instead of across their face.

    No words from the person: the auto title at the head, the sign-off at the
    tail (what shipped on 14 Sep). With words: the head card is the FIRST
    sentence, the rest are spread evenly across the middle, each held for ~3 s,
    and the tail is the call to action if given, otherwise the sign-off.
    """
    end = float(length_s)
    head, outro = titles_for(ask, event_title)
    cards = []
    y_head = 0.14 if top else 0.40
    if lines:
        cards.append((lines[0], "", 0.3, min(3.5, end - 3.5), y_head))
        mids = lines[1:]
        if mids:
            span = (end - 3.2) - 3.7          # room between head and tail
            gap = span / len(mids)
            for i, text in enumerate(mids):
                t0 = 3.7 + i * gap + max(0.0, (gap - 3.0) / 2)
                cards.append((text, "", round(t0, 2), round(min(t0 + 3.0, end - 3.2), 2), 0.40))
    else:
        cards.append((head[0], head[1], 0.3, 3.2, y_head))
    if cta:
        cards.append((cta, event_title, end - 3.0, end, 0.42))
    else:
        cards.append((outro[0], outro[1], end - 3.0, end, 0.42))
    return cards


def titles_for(ask, event_title="Convention 2026"):
    """A head card and a sign-off from the ask. Short, uppercase, no cleverness."""
    words = [w for w in re.findall(r"[A-Za-z0-9']+", ask or "")
             if w.lower() not in STOP and not w.isdigit()]
    head = " ".join(words[:3]).upper() if words else event_title.upper()
    if len(head) > 22:
        head = head[:22].rsplit(" ", 1)[0]
    return (head or event_title.upper(), event_title), ("Victory Martial Arts", event_title)


# ── 4. ffmpeg ──────────────────────────────────────────────────────────────
def _esc(text):
    return (text or "").replace("\\", "\\\\").replace("'", "’").replace(":", "\\:").replace("%", "%%")


def _drawtext(font, text, size, y, t_in, t_out, col="white"):
    return ("drawtext=fontfile=%s:text='%s':fontcolor=%s:fontsize=%d:x=(w-text_w)/2:y=%s:"
            "shadowcolor=black@0.6:shadowx=3:shadowy=3:"
            "alpha='if(lt(t,%.2f),0,if(lt(t,%.2f),(t-%.2f)/0.4,if(lt(t,%.2f),1,if(lt(t,%.2f),(%.2f-t)/0.4,0))))'"
            % (font, _esc(text), col, size, y, t_in, t_in + 0.4, t_in, t_out - 0.4, t_out, t_out))


def segment_cmd(ffmpeg, src, dst, width, height, x, t0, dur, encoder="libx264"):
    cw = int(height * 9 / 16)
    x0 = max(0, min(width - cw, int(x * width) - cw // 2))
    vf = "crop=%d:%d:%d:0,scale=%d:%d:flags=lanczos,fps=%d,format=yuv420p" % (cw, height, x0, W, H, FPS)
    venc = ["-c:v", encoder] + (["-b:v", "12M", "-allow_sw", "1"] if "videotoolbox" in encoder
                                 else ["-preset", "fast", "-crf", "18"])
    return [ffmpeg, "-v", "error", "-y", "-ss", "%.3f" % t0, "-i", src, "-t", "%.3f" % dur,
            "-vf", vf] + venc + ["-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k",
                                 "-af", "aresample=async=1", dst]


def concat_cmd(ffmpeg, list_file, dst):
    return [ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", dst]


_filters_cache = {}


def has_filter(ffmpeg, name):
    """Does this ffmpeg build have a filter? Homebrew's ffmpeg 8 on the Mini
    ships without drawtext (no freetype), so titles are optional, not fatal."""
    key = (ffmpeg, name)
    if key not in _filters_cache:
        try:
            out = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                                 text=True, timeout=60).stdout
            _filters_cache[key] = (" %s " % name) in out
        except Exception:
            _filters_cache[key] = False
    return _filters_cache[key]


def speech_spans(shots):
    """Where in the finished reel someone is talking: [(t0, t1), ...], from
    the shots' durations in order (the actual segment lengths, once known)."""
    spans, t = [], 0.0
    for s in shots:
        d = float(s.get("dur") or 0)
        if s.get("kind") == "speech" and d > 0:
            if spans and abs(spans[-1][1] - t) < 0.01:
                spans[-1] = (spans[-1][0], t + d)
            else:
                spans.append((t, t + d))
        t += d
    return spans


def _duck(spans, inside, outside, ramp=0.4):
    """A volume expression: `inside` while someone is talking, `outside`
    elsewhere, a short ramp between so the music breathes rather than jumps."""
    if not spans:
        return "%.2f" % outside
    expr = "%.2f" % outside
    for t0, t1 in reversed(spans):
        # ramp down to `inside` over [t0-ramp, t0], back up over [t1, t1+ramp]
        expr = ("if(between(t,%.2f,%.2f),%.2f,"
                "if(between(t,%.2f,%.2f),%.2f+(%.2f-%.2f)*(t-%.2f)/%.2f,"
                "if(between(t,%.2f,%.2f),%.2f+(%.2f-%.2f)*(1-(t-%.2f)/%.2f),%s)))"
                % (t0, t1, inside,
                   t1, t1 + ramp, inside, outside, inside, t1, ramp,
                   max(0.0, t0 - ramp), t0, inside, outside, inside, max(0.0, t0 - ramp), ramp, expr))
    return "'" + expr + "'"


def final_cmd(ffmpeg, body, music, dst, total, head, outro, font, encoder="libx264", cards=None,
              speech=None):
    """cards: optional (head_png, outro_png) paths — transparent 1080x1920
    pictures of the titles, used when this ffmpeg cannot draw text itself.
    speech: [(t0, t1)] where an interview moment plays — its own sound is
    full there and the music ducks under it."""
    end = float(total)
    venc = ["-c:v", encoder] + (["-b:v", "10M", "-allow_sw", "1"] if "videotoolbox" in encoder
                                 else ["-preset", "medium", "-crf", "21"])
    cmd = [ffmpeg, "-v", "error", "-y", "-i", body]
    chain = []          # filter_complex parts
    vin = "[0:v]"
    n_in = 1
    spans = list(speech or ())
    nat_vol = _duck(spans, 1.0, BROLL_NAT)
    if music:
        cmd += ["-i", music]
        mus_vol = _duck(spans, SPEECH_MUSIC, 1.0)
        chain.append("[0:a]volume=%s:eval=frame[nat];[1:a]atrim=0:%.2f,asetpts=PTS-STARTPTS,"
                     "afade=t=in:st=0:d=0.3,afade=t=out:st=%.2f:d=1.5,volume=%s:eval=frame[mus];"
                     "[nat][mus]amix=inputs=2:duration=first:dropout_transition=0,"
                     "loudnorm=I=-14:TP=-1.5:LRA=11[a]" % (nat_vol, end, end - 1.5, mus_vol))
        n_in = 2
    else:
        chain.append("[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    vfilters = []
    if cards:
        # cards: list of (png_path, t_in, t_out); each fades in and out over 0.4 s
        for k, (png, t_in, t_out) in enumerate(cards):
            idx = n_in + k
            cmd += ["-loop", "1", "-i", png]
            t_out = min(float(t_out), end)
            chain.append("[%d:v]format=rgba,fade=t=in:st=%.2f:d=0.4:alpha=1,fade=t=out:st=%.2f:d=0.4:alpha=1[c%d]"
                         % (idx, t_in, max(t_in, t_out - 0.4), k))
            chain.append("%s[c%d]overlay=0:0:enable='between(t,%.2f,%.2f)'[v%d]" % (vin, k, t_in, t_out, k))
            vin = "[v%d]" % k
    elif font and has_filter(ffmpeg, "drawtext"):
        vfilters += [_drawtext(font, head[0], 70, "h*0.40", 0.3, 3.2),
                     _drawtext(font, head[1], 42, "h*0.40+100", 0.5, 3.2, "0xE8E8E8"),
                     _drawtext(font, outro[0], 76, "h*0.42", end - 3.0, end - 0.1),
                     _drawtext(font, outro[1], 48, "h*0.42+100", end - 2.8, end - 0.1, "0xE8E8E8")]
    vfilters.append("fade=t=out:st=%.2f:d=0.5" % (end - 0.5))
    chain.append("%s%s[v]" % (vin, ",".join(vfilters)))
    cmd += ["-filter_complex", ";".join(chain), "-map", "[v]", "-map", "[a]"]
    cmd += venc + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                   "-movflags", "+faststart", "-t", "%.3f" % end, dst]
    return cmd


def reanchor_cards(cards, planned, actual):
    """Cards are timed against the planned length. If the body came out a
    different length, cards that touch the planned end move with the end;
    the rest stay, clipped to the new end."""
    if not cards:
        return cards
    shift = actual - planned
    out = []
    for png, t_in, t_out in cards:
        if t_out >= planned - 0.05:
            t_in, t_out = t_in + shift, t_out + shift
        t_in = max(0.0, min(t_in, actual))
        t_out = max(t_in, min(t_out, actual))
        if t_out - t_in >= 0.5:
            out.append((png, round(t_in, 2), round(t_out, 2)))
    return out


def probe(ffprobe, path):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,duration", "-of", "json", path],
                       capture_output=True, text=True, timeout=120)
    s = json.loads(r.stdout)["streams"][0]
    return int(s["width"]), int(s["height"]), float(s.get("duration") or 0)


def render(plan_, clip_paths, music_path, workdir, out_path, ffmpeg="ffmpeg",
           ffprobe="ffprobe", encoder="libx264", event_title="Convention 2026", log=print, cards=None):
    """Run the plan. clip_paths: id -> local file. Returns (out_path, seconds)."""
    os.makedirs(workdir, exist_ok=True)
    segs, total, cut = [], 0.0, []
    for i, s in enumerate(plan_["shots"], 1):
        src = clip_paths[s["id"]]
        width, height, length = probe(ffprobe, src)
        dur = min(s["dur"], max(0.5, length - s["in"] - 0.05)) if length else s["dur"]
        dst = os.path.join(workdir, "seg%02d.mp4" % i)
        subprocess.run(segment_cmd(ffmpeg, src, dst, width, height, s["x"], s["in"], dur, encoder),
                       check=True, capture_output=True, text=True, timeout=600)
        segs.append(dst)
        total += dur
        cut.append({"kind": s.get("kind"), "dur": dur})
        log("  seg %02d %-48s in %.1f dur %.1f x %.2f (%s%s)" % (i, s["id"][:48], s["in"], dur, s["x"],
                                                                 s["framed_by"], ", speech" if s.get("kind") == "speech" else ""))
    lst = os.path.join(workdir, "list.txt")
    with open(lst, "w") as f:
        for sgm in segs:
            f.write("file '%s'\n" % sgm)
    body = os.path.join(workdir, "body.mp4")
    subprocess.run(concat_cmd(ffmpeg, lst, body), check=True, capture_output=True, text=True, timeout=300)
    # the body as it really is, not as planned: the sign-off is anchored to
    # the true end so it always gets its three seconds and its fade
    try:
        _, _, actual = probe(ffprobe, body)
    except Exception:
        actual = 0.0
    if actual and abs(actual - total) > 0.05:
        log("  body is %.2fs, planned %.2fs — cards re-anchored" % (actual, total))
        cards = reanchor_cards(cards, total, actual)
        total = actual
    head, outro = titles_for(plan_["ask"], event_title)
    subprocess.run(final_cmd(ffmpeg, body, music_path, out_path, total, head, outro, font_path(), encoder,
                             cards=cards, speech=speech_spans(cut)),
                   check=True, capture_output=True, text=True, timeout=900)
    return out_path, round(total, 2)


# ── 5. the candidate pool ──────────────────────────────────────────────────
# The kinds of moment people name, in their words (16 Sep, from the first
# self-tests: "a reel about the candlelight ceremony for our parents please"
# came back as belt presentations, because the Library's ranking scores a
# sentence, not an ask). Firm words name the footage; soft words name the
# audience and only steer when nothing firmer is said.
CATEGORY_WORDS = {
    "Candlelight ceremony": ("candlelight", "candle", "candles"),
    "Belt & rank presentation": ("belt", "belts", "rank", "ranks", "promotion", "promotions",
                                 "graduation", "presentation"),
    "Board breaks": ("board", "boards", "break", "breaks", "breaking"),
    "Competition": ("competition", "competitions", "compete", "competing", "competitor",
                    "competitors", "tournament", "sparring", "spar", "fight", "fights",
                    "fighting", "forms", "weapons", "match", "matches", "kata"),
    "Winning moments": ("winning", "winners", "winner", "win", "wins", "medal", "medals",
                        "trophy", "trophies", "champion", "champions", "podium"),
    "Instructor training": ("instructor", "instructors", "master", "masters", "teaching",
                            "teach", "teachers"),
    "Training & seminar": ("training", "seminar", "seminars", "class", "classes", "drill",
                           "drills", "workout", "practice", "technique", "techniques"),
    "Crowd & parent reactions": ("crowd", "crowds", "cheering", "cheer", "reactions", "reaction",
                                 "audience", "celebration", "celebrating", "celebrate",
                                 "parents", "parent", "mom", "moms", "mother", "mothers",
                                 "dad", "dads", "father", "fathers", "family", "families"),
}
SOFT_WORDS = {"parents", "parent", "mom", "moms", "mother", "mothers", "dad", "dads", "father",
              "fathers", "family", "families"}
CEREMONIES = ("Candlelight ceremony", "Belt & rank presentation")


def ask_categories(ask):
    """The kinds of moment an ask names, as (categories, soft).
    soft is True when only audience words ("parents") pointed anywhere."""
    words = set(re.findall(r"[a-z]+", (ask or "").lower()))
    firm, soft = [], []
    for cat, ws in CATEGORY_WORDS.items():
        hit = words.intersection(ws)
        if not hit:
            continue
        (soft if hit <= SOFT_WORDS else firm).append(cat)
    if not firm and ("ceremony" in words or "ceremonies" in words):
        firm = list(CEREMONIES)                  # "the ceremony" alone: both of them
    if firm:
        return firm, False
    return soft, bool(soft)


def candidates(ask, clips, need, search_fn=None):
    """Which clips the machine may choose from, and whether the ask led.

    An ask that NAMES a kind of moment ("board breaks", "the candlelight
    ceremony") gets that footage first, all of it, with the index's hits in
    front. A narrow ask the index answers with enough footage gets ONLY that
    footage, in the index's order. A broad ask ("best moments"), a fallback,
    or a thin answer gets the whole convention, with any hits first.
    Returns (pool, by_search, focus): focus = the named kinds, which the
    variety caps leave alone.
    """
    hits, found, fallback, res = [], 0, True, {}
    if search_fn and ask:
        try:
            res = search_fn(ask)
            found, fallback = int(res.get("found") or 0), bool(res.get("fallback"))
            hits = [r.get("id", "").split(":", 1)[-1] for r in res.get("results", [])
                    if r.get("kind") == "clip"]
        except Exception as e:
            print("[VI-CUT] search failed, using the whole convention: %r" % (e,))
    by_id = {c["id"]: c for c in clips}
    cats, soft = ask_categories(ask)
    first = []
    for k, cid in enumerate(hits):
        if cid in by_id and (not cats or by_id[cid].get("category") in cats):
            c = dict(by_id[cid])
            c["weight"] = 10.0 - k * 0.01
            first.append(c)
    seen = set(c["id"] for c in first)
    if cats:
        named = sorted([c for c in clips if c["id"] not in seen and c.get("category") in cats],
                       key=lambda c: (-PRIORITY.get(c.get("priority"), 0), c["id"]))
        for c in named:
            c = dict(c)
            c["weight"] = 9.5
            first.append(c)
            seen.add(c["id"])
        rest = sorted([c for c in clips if c["id"] not in seen],
                      key=lambda c: (-PRIORITY.get(c.get("priority"), 0), c["id"]))
        return first + rest, True, () if soft else tuple(cats)
    # A PEAK ask ("best moments", "iconic") is the index picking highlights for
    # us — a curated slice, but a slice. The variety rule wants the whole
    # convention behind it, so peak asks stay broad with the hits leading.
    peak = bool(res.get("peak"))
    if first and not fallback and not peak and len(first) >= need:
        return first, True, ()
    rest = sorted([c for c in clips if c["id"] not in seen],
                  key=lambda c: (-PRIORITY.get(c.get("priority"), 0), c["id"]))
    return first + rest, False, ()
