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
LOGO_CARD = "[victory-logo]"    # a card that is the Victory Martial Arts logo (victory_cards renders it)
SHOT_SECONDS = 3.0      # a shot the machine chose
PICK_SECONDS = 5.0      # a shot the person picked
SCENE_GAP = 300.0       # two moments this close in one long recording are one scene
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
    # uncapped holds kinds of moment, and "session:<name>" for a whole evening
    # the ask named (its per-session cap is lifted; its kinds stay balanced)
    free_sessions = {u[8:] for u in (uncapped or ()) if str(u).startswith("session:")}
    uncapped = {u for u in (uncapped or ()) if not str(u).startswith("session:")}
    # a clip shorter than a shot makes a choppy fill: it goes to the back
    # unless the ask named its kind (self-test #13: a 2.2 s crowd clip as filler)
    short = {c["id"]: float(c.get("seconds") or 99) < SHOT_SECONDS + 0.5
             and c.get("category") not in uncapped for c in cands}
    # a clip the quality pass found shaky all the way through (no steady
    # stretch as long as a shot) goes behind every steady one
    shaky = {c["id"]: (steady_seconds(c) is not None and steady_seconds(c) < SHOT_SECONDS) for c in cands}
    by_id = {c["id"]: c for c in cands}
    chosen = [by_id[r] for r in requested if r in by_id]
    fam, ses, day = {}, {}, {}
    scenes = []          # (recording, second) of every shot chosen so far

    def same_scene(c):
        """Cut from the same long recording within SCENE_GAP of a shot already
        in: the same people on the same stage — near enough the same picture
        (self-test #26: three "students in red line up on stage" moments from
        four minutes of the Night of Champions, back to back)."""
        src, t = c.get("long_src"), c.get("long_start")
        if not src or t is None:
            return False
        return any(s == src and abs(float(t) - float(t0)) < SCENE_GAP for s, t0 in scenes)

    def bump(c):
        fam[c.get("category")] = fam.get(c.get("category"), 0) + 1
        ses[c.get("session")] = ses.get(c.get("session"), 0) + 1
        day[c.get("day")] = day.get(c.get("day"), 0) + 1
        if c.get("long_src") and c.get("long_start") is not None:
            scenes.append((c["long_src"], c["long_start"]))

    for c in chosen:
        bump(c)
    taken = set(x["id"] for x in chosen)
    pool = [c for c in cands if c["id"] not in taken]
    while len(chosen) < n and pool:
        if by_search:      # the ask's own footage leads (weight 10 = a hit or a named
            # kind) — before rotation: someone who asked for candlelight would
            # rather see a candle clip again than board breaks (self-test #11)
            # the ask's tier first (a hit, a named kind, the named evening all
            # sit near 10); inside it a fresh scene beats a finer weight
            pool.sort(key=lambda c: (-round(float(c.get("weight") or 0)),
                                     shaky[c["id"]], same_scene(c), -round(float(c.get("weight") or 0), 1),
                                     c["id"] in avoid, short[c["id"]],
                                     -min(2, PRIORITY.get(c.get("priority"), 0)),   # hero before standard
                                     fam.get(c.get("category"), 0),
                                     day.get(c.get("day"), 0), jitter[c["id"]]))
        else:              # hero and high are one class here: the weekend's variety comes first
            pool.sort(key=lambda c: (shaky[c["id"]], same_scene(c), c["id"] in avoid, short[c["id"]],
                                     -min(2, PRIORITY.get(c.get("priority"), 0)),
                                     fam.get(c.get("category"), 0),
                                     day.get(c.get("day"), 0), jitter[c["id"]]))
        pick = None
        for c in pool:
            if c.get("category") not in uncapped:
                in_named = c.get("session") in free_sessions
                # a named evening may repeat a kind twice as often before the
                # reel leaves that evening for the rest of the convention
                if fam.get(c.get("category"), 0) >= (max_per_family * 2 if in_named else max_per_family):
                    continue
                if not in_named and ses.get(c.get("session"), 0) >= max_per_session:
                    continue
            pick = c
            break
        if pick is None:                  # quotas exhausted: take the best left
            pick = pool[0]
        chosen.append(pick)
        bump(pick)
        pool.remove(pick)
    return story_order(chosen)


REACTION = "Crowd & parent reactions"


def story_order(shots):
    """The reel's order. Kinds follow STORY (training first, candles last);
    within the first kind the strongest moment opens the reel. Reactions are
    woven in AFTER the moments they react to — one every few shots, never
    first, never last — instead of sitting in a block: Michael's #30 (17 Sep)
    opened on sixteen seconds of seated parents before a single belt."""
    def key(c):
        return (STORY.index(c.get("category")) if c.get("category") in STORY else 99,
                c.get("day") or 0, c["id"])
    acts = sorted([c for c in shots if c.get("category") != REACTION], key=key)
    reacts = sorted([c for c in shots if c.get("category") == REACTION], key=key)
    if not acts:
        return reacts
    first_kind = acts[0].get("category")
    group = [c for c in acts if c.get("category") == first_kind]
    opener = max(group, key=lambda c: (PRIORITY.get(c.get("priority"), 0), float(c.get("weight") or 0)))
    acts.remove(opener)
    acts.insert(0, opener)
    if not reacts:
        return acts
    out, ri = [], 0
    slots = max(1, len(acts) - 1)                 # a reaction may follow any action but the last
    step = max(1, slots // len(reacts))
    for i, a in enumerate(acts):
        out.append(a)
        if ri < len(reacts) and i < len(acts) - 1 and (i + 1) % step == 0:
            out.append(reacts[ri])
            ri += 1
    if ri < len(reacts):                          # more reactions than slots: before the closer
        out[-1:-1] = reacts[ri:]
    return out


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
       "break": "board", "celebration": "celebration", "crowd": "crowd", "cheering": "crowd",
       # pace and feel words reach the music's tags ("Fast pace. Motivational." — #25)
       "fast": "energetic", "quick": "energetic", "action": "action",
       "intense": "powerful", "powerful": "powerful", "motivational": "motivational",
       "motivation": "motivational", "inspiring": "inspiring", "inspirational": "inspiring",
       "quiet": "piano", "calm": "piano", "slow": "piano", "happy": "happy", "playful": "playful",
       "upbeat": "upbeat", "rock": "rock", "trailer": "trailer", "students": "highlights"}


def ask_words(ask):
    return {SYN.get(w, w) for w in re.findall(r"[a-z]+", (ask or "").lower()) if w not in STOP}


def pick_music(library, ask, exclude=()):
    """Match the ask's words to track tags. Unknown asks get the uplifting
    default. exclude = ids this person received recently, so the music rotates."""
    words = ask_words(ask)
    every = list(library.get("tracks", []))
    fresh = [t for t in every if t["id"] not in exclude] or every

    def fit(t):
        return sum(1 for tag in t.get("tags", []) for w in tag.split() if w in words)

    best = max(fresh, key=fit, default=None)
    if best is not None and fit(best) > 0:
        return best
    # nothing fresh fits. For a slow or emotional ask a track that fits beats
    # one that merely rotates — Michael's #30 re-cut (17 Sep) put "The Sports"
    # under a slow, emotional parents reel because the one piano track had
    # just been used. Anything else rotates to the uplifting default as before.
    calm_words = {"piano", "emotional", "inspiring", "cinematic", "hopeful"}
    if words & calm_words:
        heard = max(every, key=fit, default=None)
        if heard is not None and fit(heard) > 0:
            return heard
        calm = [t for t in fresh if calm_words & set(w for tag in t.get("tags", []) for w in tag.split())]
        if calm:
            return calm[0]
    pool = [t for t in fresh if "uplifting" in t.get("tags", [])] or fresh
    return pool[0] if pool else None


# ── 2. where to look in each clip ──────────────────────────────────────────
def window_for(clip_id, reframe, t0, dur, fixed_in=None):
    """The 9:16 window (x centre as a fraction of width) and how sure we are.
    fixed_in: use this in-point (a moment cut from a long recording knows
    where its peak is) and only choose the window for it.

    reframe.json holds, per clip, per one-second window: faces (count), fx
    (area-weighted face x), ax (where the motion and detail are). Faces win
    when there are enough of them; otherwise the action window; otherwise
    the centre. Also returns the in-point: the busiest second in the clip
    that still leaves room for `dur`.
    """
    info = (reframe or {}).get(clip_id)
    if not info or not info.get("windows"):
        return 0.5, "centre", (t0 if fixed_in is None else fixed_in)
    wins = info["windows"]
    total = info.get("duration") or (len(wins) + 0.0)
    # in-point: the window with the most energy such that t0+dur fits
    last_ok = max(0, int(total - dur - 0.1))
    cands = [w for w in wins if w["t"] <= last_ok] or wins[:1]
    if fixed_in is not None:
        start = float(max(0.0, min(fixed_in, last_ok)))
    else:
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
STEADY = (1.5, 4.0)      # jitter, pan (px/frame at 480 px, 25 fps): a still hand
PASSABLE = (2.5, 8.0)    # a gimbal follow, a walking camera: fine for a shot, not for opening one


def windows_from_shake(shake, seconds, limits=STEADY, min_run=2):
    """Runs of seconds under the limits, from the quality pass's per-second
    [jitter, pan]: [[start, seconds], …]."""
    out, start, n = [], None, len(shake or [])
    jmax, pmax = limits
    for i, jp in enumerate(list(shake or []) + [[99, 99]]):
        j, p = jp[0], jp[1]
        ok = j <= jmax and p <= pmax and i < n
        if ok and start is None:
            start = i
        if not ok and start is not None:
            if i - start >= min_run:
                end = float(seconds) if (seconds and i == n) else float(i)
                out.append([float(start), round(end - start, 2)])
            start = None
    return out


def steady_in(stable, t0, dur, have=None, passable=None):
    """Move an in-point into a steady stretch of the clip. stable: [[start,
    seconds], …] from the quality pass (vidstabdetect on every library file —
    Michael, 17 Sep: "camera shaky movements where the cameraman is still
    trying to find the shot"). Returns (in_point, steady): the in-point kept
    if it already sits in a steady stretch, else the nearest steady stretch
    that holds the whole shot; (t0, False) when no stretch is long enough."""
    if stable is None:
        return t0, True                      # nothing known: trust the clip
    wins = [(float(a), float(b)) for a, b in stable if float(b) >= dur]
    if not wins and passable:
        # no still stretch long enough: a smooth follow will do
        wins = [(float(a), float(b)) for a, b in passable if float(b) >= dur]
    if not wins:
        return t0, False
    for a, b in wins:
        if a - 0.05 <= t0 and t0 + dur <= a + b + 0.05:
            return t0, True
    a, b = min(wins, key=lambda w: abs(min(max(t0, w[0]), w[0] + w[1] - dur) - t0))
    lo, hi = a, a + b - dur
    if have:
        hi = min(hi, max(0.0, have - dur - 0.05))
    return round(max(lo, min(t0, hi)), 2), True


def steady_seconds(c):
    """The longest usable stretch a clip offers (still or a smooth follow),
    or None when unknown."""
    st = c.get("stable")
    if st is None:
        return None
    return max([float(b) for a, b in list(st) + list(c.get("stable_ok") or [])] + [0.0])


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
PACE_FAST = {"fast", "quick", "rapid", "hype", "energetic", "energy", "punchy", "dynamic", "action",
             "intense", "explosive", "high-energy", "upbeat"}
PACE_SLOW = {"slow", "quiet", "calm", "emotional", "gentle", "soft", "cinematic", "moody", "tender",
             "reflective", "peaceful"}
PICK_MIN = 2.0          # a picked clip never shorter than this


def pace_seconds(ask):
    """How long a machine-chosen shot runs: 3 s, or 2 s when the ask says
    fast, 4 s when it says slow (Michael on #25: "Fast pace" gave 3 s shots)."""
    words = set(re.findall(r"[a-z\-]+", (ask or "").lower()))
    if words & PACE_FAST:
        return 2.0
    if words & PACE_SLOW:
        return 4.0
    return SHOT_SECONDS


def plan(ask, cands, requested_ids, library, reframe, length_s=30, recent_music=(), by_search=False,
         avoid=(), seed=0, lines=(), cta="", speech=(), focus=(), all_clips=None):
    """Everything the render needs, as data. Pure.
    lines:     the person's own sentences to put over the pictures, in order.
    cta:       the end card ("Enroll today — victoryma.com"); blank = the sign-off.
    speech:    interview moments from quote_shots(); they open the reel.
    focus:     kinds of moment the ask named (from candidates()); uncapped.
    all_clips: the whole library, so a PICK is always found even when the
               ask narrowed the pool (#25: nine picks, none in the cut)."""
    length_s = int(length_s) if int(length_s or 0) in LENGTHS else 30
    budget = length_s - 0.5
    shot_s = pace_seconds(ask)
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
    by_id = {c["id"]: c for c in (all_clips or ())}
    by_id.update({c["id"]: c for c in cands})
    picks = [by_id[r] for r in requested_ids if r in by_id]
    # Every pick that fits goes in, in the order picked. With many picks for a
    # short reel each gets less time, down to PICK_MIN; what still does not
    # fit is named on the card (no_room) rather than dropped in silence.
    pick_s = PICK_SECONDS
    if picks and len(picks) * pick_s > room:
        pick_s = max(PICK_MIN, min(PICK_SECONDS, room / len(picks)))
    no_room = []
    if picks and len(picks) * pick_s > room:
        keep = max(0 if speech_out else 1, int(room // pick_s))
        no_room = [p.get("title") or p["id"] for p in picks[keep:]]
        picks = picks[:keep]
    def shot(c, dur, req):
        # a clip shorter than the shot gives what it has (two convention clips
        # are 2 s long; 16 Sep self-test #5 came out 1 s short because of one)
        have = float(c.get("seconds") or 0)
        if have:
            dur = round(max(0.5, min(dur, have - 0.05)), 2)
        fixed = None
        if c.get("best_in") is not None:
            # a moment cut from a long recording knows where its peak is
            # (the applause, the break): centre the shot on it
            hi = max(0.0, (have or 99.0) - dur - 0.05)
            fixed = max(0.0, min(float(c["best_in"]) - dur / 2.0, hi))
        x, how, t0 = window_for(c["id"], reframe, 1.0, dur, fixed_in=fixed)
        t0, steady = steady_in(c.get("stable"), t0, dur, have or None, passable=c.get("stable_ok"))
        if not steady:
            how = "shaky"
        return {"id": c["id"], "drive_id": c.get("drive_id"), "file": c.get("file"),
                "title": c.get("title"), "session": c.get("session"),
                "day": c.get("day"), "category": c.get("category"),
                "priority": c.get("priority"), "in": round(t0, 2),
                "dur": dur, "x": x, "framed_by": how, "requested": req}

    lead = list(speech_out) + [shot(p, round(pick_s, 2), True) for p in picks]
    remaining = budget - sum(x["dur"] for x in lead)
    n_fill = max(0, int(round(remaining / shot_s)))
    fill = []
    pool = [c for c in cands if c["id"] not in {p["id"] for p in picks}]
    for extra in range(0, 6):                 # top up while short clips leave a hole
        if not n_fill + extra or not pool:
            break
        # a narrow ask is narrow on purpose: the kind-of-moment cap loosens with the length
        chosen = pick_shots(pool, n_fill + extra, by_search=by_search, avoid=avoid, seed=seed,
                            max_per_family=max(2, (n_fill + extra) // 3) if by_search else 2,
                            uncapped=focus)
        fill = [shot(f, shot_s, False) for f in chosen]
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
            f["dur"] = round(max(f["dur"], min(f["dur"] + per, cap, shot_s + 1.5)), 2)
    music = pick_music(library, ask, exclude=recent_music)
    out = lead + fill
    lines = [str(x).strip()[:60] for x in (lines or ()) if str(x).strip()][:4]
    return {"ask": ask, "length_s": length_s, "shots": out, "pool": "search" if by_search else "convention",
            "speech_seconds": round(sum(s["dur"] for s in speech_out), 2),
            "no_room": no_room, "pace": shot_s,
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
    # the tail: the call to action (if any) and then, always, the Victory card
    # (Michael, 17 Sep: "finish with a Victory logo")
    tail_start = end - 6.0 if cta else end - 3.0
    if lines:
        cards.append((lines[0], "", 0.3, min(3.5, tail_start - 0.5), y_head))
        mids = lines[1:]
        if mids:
            span = (tail_start - 0.2) - 3.7          # room between head and tail
            gap = span / len(mids)
            for i, text in enumerate(mids):
                t0 = 3.7 + i * gap + max(0.0, (gap - 3.0) / 2)
                cards.append((text, "", round(t0, 2), round(min(t0 + 3.0, tail_start - 0.2), 2), 0.40))
    else:
        cards.append((head[0], head[1], 0.3, 3.2, y_head))
    if cta:
        cards.append((cta, "", end - 6.0, end - 3.0, 0.42))       # the school's words, alone
    cards.append((LOGO_CARD, "", end - 3.0, end, 0.42))        # the Victory logo, always last
    return cards


KIND_TITLES = {"Board breaks": "BOARD BREAKS", "Candlelight ceremony": "CANDLELIGHT",
               "Belt & rank presentation": "BELT PRESENTATION", "Competition": "COMPETITION",
               "Winning moments": "CHAMPIONS", "Instructor training": "INSTRUCTORS",
               "Training & seminar": "TRAINING", "Crowd & parent reactions": "THE CROWD"}
# words of the asking, not of the video: "I want a video for students. This is
# gonna be an Instagram reel, 15 seconds, very fast pace…" opened on a card
# reading "I STUDENTS THIS" (self-test #26, 17 Sep)
CHATTER = {"i", "we", "you", "it", "this", "that", "is", "are", "be", "gonna", "going", "can",
           "could", "would", "should", "like", "use", "using", "some", "any", "very", "really",
           "just", "then", "also", "instagram", "facebook", "tiktok", "youtube", "story", "stories",
           "post", "reels", "shots", "shot", "footage", "clips", "clip", "moments", "pace", "paced",
           "fast", "slow", "quick", "long", "short", "minute", "minutes", "min", "with", "get",
           "give", "me", "us", "one", "something", "nice", "good", "great", "kind", "sort", "so",
           "them", "they", "their", "have", "has", "do", "does", "what", "which", "who", "how"}


def titles_for(ask, event_title="Convention 2026"):
    """A head card and a sign-off from the ask. Short, uppercase, no cleverness.

    First choice is what the editor understood — the evening, the kind of
    moment, who it is for — so a long sentence opens on NIGHT OF CHAMPIONS,
    not on its own first three words. Only an ask that names none of those
    falls back to its words (with the chatter of asking stripped)."""
    head = ""
    text = ask or ""
    try:
        b = brief_for(text)
    except Exception:
        b = {"sessions": [], "kinds": [], "audience": []}
    # a name the person wrote with capitals ("the Lake Nona page") is theirs
    # to keep on the card; a word that merely starts a sentence is not
    names = [m.group(1) for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z']+)\b", text)
             if m.group(1).lower() not in STOP | CHATTER | set(AUDIENCE_WORDS)
             and m.group(1).lower() not in {w for ws in CATEGORY_WORDS.values() for w in ws}]
    if b["sessions"]:
        head = b["sessions"][0].upper()
    elif b["kinds"]:
        head = KIND_TITLES.get(b["kinds"][0], b["kinds"][0].upper())
    elif names:
        head = " ".join(names[:3]).upper()
    elif b["audience"]:
        head = "FOR " + b["audience"][0].upper()
    if not head:
        words = [w for w in re.findall(r"[A-Za-z0-9']+", text)
                 if w.lower() not in STOP and w.lower() not in CHATTER and not w.isdigit()]
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


def card_video_cmd(ffmpeg, png, dst, seconds):
    """A card PNG as a short video with its alpha kept (PNG codec in a .mov),
    at the reel's frame rate, for exactly the seconds it is on screen."""
    return [ffmpeg, "-v", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-t", "%.2f" % max(0.2, seconds),
            "-i", png, "-c:v", "png", "-pix_fmt", "rgba", dst]


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


def _final_parts(ffmpeg, body, music, total, head, outro, font, encoder, cards, speech, sound_in_process=True):
    """The pieces of the final pass: the inputs, the sound chain (one
    filter string ending in [a]), the picture chain (filter parts ending in
    [v]) and the encoder flags."""
    end = float(total)
    venc = ["-c:v", encoder] + (["-b:v", "10M", "-allow_sw", "1"] if "videotoolbox" in encoder
                                 else ["-preset", "medium", "-crf", "21"])
    inputs = ["-i", body]
    spans = list(speech or ())
    nat_vol = _duck(spans, 1.0, BROLL_NAT)
    n_in = 1
    if music:
        inputs += ["-i", music]
        mus_vol = _duck(spans, SPEECH_MUSIC, 1.0)
        achain = ("[0:a]volume=%s:eval=frame[nat];[1:a]atrim=0:%.2f,asetpts=PTS-STARTPTS,"
                  "afade=t=in:st=0:d=0.3,afade=t=out:st=%.2f:d=1.5,volume=%s:eval=frame[mus];"
                  "[nat][mus]amix=inputs=2:duration=first:dropout_transition=0,"
                  "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.7:level=false[a]" % (nat_vol, end, end - 1.5, mus_vol))
        n_in = 2 if sound_in_process else 1     # the card inputs are numbered after the music
    else:
        achain = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.7:level=false[a]"
    vchain = []
    vin = "[0:v]"
    card_inputs = []
    vfilters = []
    if cards:
        # cards: list of (png_path, t_in, t_out); each fades in and out over 0.4 s
        for k, (png, t_in, t_out) in enumerate(cards):
            idx = n_in + k
            t_out = min(float(t_out), end)
            if str(png).lower().endswith((".mov", ".mp4")):
                # a card that is already a short video (card_video_cmd): the
                # Mini's ffmpeg 8 drops a third of the picture frames when a
                # looped PNG is overlaid, whatever its rate (video #30 "getting
                # stuck", 17 Sep: 1,105 frames where 1,800 belonged), but keeps
                # every frame when the card comes in as a real video track
                card_inputs += ["-itsoffset", "%.2f" % t_in, "-i", png]
            else:
                card_inputs += ["-loop", "1", "-framerate", str(FPS), "-itsoffset", "%.2f" % t_in,
                                "-t", "%.2f" % max(0.1, t_out - t_in + 0.2), "-i", png]
            vchain.append("[%d:v]format=rgba,fade=t=in:st=%.2f:d=0.4:alpha=1,fade=t=out:st=%.2f:d=0.4:alpha=1[c%d]"
                          % (idx, t_in, max(t_in, t_out - 0.4), k))
            vchain.append("%s[c%d]overlay=0:0:eof_action=pass:enable='between(t,%.2f,%.2f)'[v%d]"
                          % (vin, k, t_in, t_out, k))
            vin = "[v%d]" % k
    elif font and has_filter(ffmpeg, "drawtext"):
        vfilters += [_drawtext(font, head[0], 70, "h*0.40", 0.3, 3.2),
                     _drawtext(font, head[1], 42, "h*0.40+100", 0.5, 3.2, "0xE8E8E8"),
                     _drawtext(font, outro[0], 76, "h*0.42", end - 3.0, end - 0.1),
                     _drawtext(font, outro[1], 48, "h*0.42+100", end - 2.8, end - 0.1, "0xE8E8E8")]
    vfilters.append("fade=t=out:st=%.2f:d=0.5" % (end - 0.5))
    vchain.append("%s%s[v]" % (vin, ",".join(vfilters)))
    return inputs, card_inputs, achain, vchain, venc, end


def final_cmd(ffmpeg, body, music, dst, total, head, outro, font, encoder="libx264", cards=None,
              speech=None):
    """cards: optional (head_png, outro_png) paths — transparent 1080x1920
    pictures of the titles, used when this ffmpeg cannot draw text itself.
    speech: [(t0, t1)] where an interview moment plays — its own sound is
    full there and the music ducks under it.
    The one-pass form: picture and sound in one filter graph. The editor
    itself uses final_cmds (three passes) — see there for why."""
    inputs, card_inputs, achain, vchain, venc, end = _final_parts(
        ffmpeg, body, music, total, head, outro, font, encoder, cards, speech)
    cmd = [ffmpeg, "-v", "error", "-y"] + inputs + card_inputs
    cmd += ["-filter_complex", ";".join([achain] + vchain), "-map", "[v]", "-map", "[a]"]
    cmd += venc + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
                   "-movflags", "+faststart", "-t", "%.3f" % end, dst]
    return cmd


def final_cmds(ffmpeg, body, music, dst, total, head, outro, font, encoder="libx264", cards=None,
               speech=None, workdir=None):
    """The final pass as three commands: the picture (cards, fade — no sound
    in the process), the sound (mix, loudness, limiter — no picture), then
    the two joined without re-encoding. On the Mini's ffmpeg 8.0.1 a graph
    that carries the sound chain alongside a card overlay loses a third of
    the picture frames (video #30 "getting stuck", 17 Sep; the frame check
    vi_segtest.py: 154 of 240 with the sound in the graph, 239 without), so
    the picture is cut in a process of its own."""
    if any(not str(c[0]).lower().endswith((".mov", ".mp4")) for c in (cards or ())):
        # a looped still with no sound in the process never ends on that
        # ffmpeg (20:45 ET, ten-minute hang) — render() turns every card into
        # a video first; anything else takes the one-pass road
        return [final_cmd(ffmpeg, body, music, dst, total, head, outro, font, encoder, cards, speech)]
    inputs, card_inputs, achain, vchain, venc, end = _final_parts(
        ffmpeg, body, music, total, head, outro, font, encoder, cards, speech, sound_in_process=False)
    workdir = workdir or os.path.dirname(dst) or "."
    picture = os.path.join(workdir, "picture.mp4")
    sound = os.path.join(workdir, "sound.m4a")
    vcmd = [ffmpeg, "-v", "error", "-y", "-i", body] + card_inputs
    vcmd += ["-filter_complex", ";".join(vchain), "-map", "[v]", "-an"]
    vcmd += venc + ["-pix_fmt", "yuv420p", "-t", "%.3f" % end, picture]
    acmd = [ffmpeg, "-v", "error", "-y"] + inputs + ["-filter_complex", achain, "-map", "[a]", "-vn",
                                                     "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
                                                     "-t", "%.3f" % end, sound]
    mcmd = [ffmpeg, "-v", "error", "-y", "-i", picture, "-i", sound, "-map", "0:v", "-map", "1:a",
            "-c", "copy", "-movflags", "+faststart", dst]
    return [vcmd, acmd, mcmd]


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
    """(width, height, seconds) of a video. Asks ffmpeg itself, not ffprobe:
    on the Mini only ffmpeg was granted Full Disk Access, and ffprobe hung
    for two minutes on the first file it touched on the external drive
    (17 Sep, self-test #22). ffprobe is the fallback for any other build."""
    ffmpeg = ffprobe[:-5] + "mpeg" if ffprobe.endswith("ffprobe") else None
    if ffmpeg:
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=120)
            got = parse_ffmpeg_info(r.stderr)
            if got:
                return got
        except Exception:
            pass
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,duration", "-of", "json", path],
                       capture_output=True, text=True, timeout=120)
    s = json.loads(r.stdout)["streams"][0]
    return int(s["width"]), int(s["height"]), float(s.get("duration") or 0)


def parse_ffmpeg_info(text):
    """Width, height and duration out of ffmpeg's own banner for an input."""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text or "")
    dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
    v = re.search(r"Stream #\d+:\d+.*?: Video:.*?(\d{2,5})x(\d{2,5})", text or "")
    if not v:
        return None
    return int(v.group(1)), int(v.group(2)), dur


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
    if cards:
        # every card becomes a short video track before the final pass
        movs = []
        for k, (png, t_in, t_out) in enumerate(cards):
            mov = os.path.join(workdir, "card%02d.mov" % k)
            subprocess.run(card_video_cmd(ffmpeg, png, mov, min(float(t_out), total) - float(t_in) + 0.2),
                           check=True, capture_output=True, text=True, timeout=300)
            movs.append((mov, t_in, t_out))
        cards = movs
    for c in final_cmds(ffmpeg, body, music_path, out_path, total, head, outro, font_path(), encoder,
                        cards=cards, speech=speech_spans(cut), workdir=workdir):
        subprocess.run(c, check=True, capture_output=True, text=True, timeout=900)
    return out_path, round(total, 2)


# ── 4b. what the editor understood ────────────────────────────────────────
AUDIENCE_WORDS = {"students": "students", "student": "students", "kids": "kids", "children": "kids",
                  "parents": "parents", "parent": "parents", "moms": "parents", "dads": "parents",
                  "families": "families", "family": "families", "instructors": "instructors",
                  "instructor": "instructors", "masters": "masters", "schools": "schools",
                  "school": "schools", "teens": "teens", "adults": "adults"}
NUMBER_WORDS = {"fifteen": 15, "thirty": 30, "sixty": 60, "one": 60, "a": 60, "half": 30}


def length_from(ask):
    """A length the sentence names — "15 seconds", "30s", "one minute",
    "half a minute" — snapped to 15 / 30 / 60. None when it says nothing."""
    low = (ask or "").lower()
    m = re.search(r"\b(\d{1,3})\s*(?:-|\s)?(s|sec|secs|second|seconds)\b", low)
    n = None
    if m:
        n = int(m.group(1))
    elif re.search(r"\b(half\s+a|half)\s+minute", low):
        n = 30
    elif re.search(r"\b(one|a|1)\s+minute", low):
        n = 60
    else:
        m = re.search(r"\b(fifteen|thirty|sixty)\s*(s|sec|secs|second|seconds)?\b", low)
        if m:
            n = NUMBER_WORDS[m.group(1)]
    if n is None:
        return None
    return min(LENGTHS, key=lambda L: abs(L - n))


def brief_for(ask, length_s=None):
    """What the editor understood from a sentence, as data and as one plain
    line for the card — so a person sees a misreading before the cut, not
    after (Michael, 17 Sep: most people will only ever type a sentence)."""
    length = length_from(ask) or (int(length_s) if length_s in LENGTHS else 30)
    pace = pace_seconds(ask)
    sessions = ask_sessions(ask)
    cats, soft = ask_categories(ask)
    words = re.findall(r"[a-z]+", (ask or "").lower())
    audience = []
    for w in words:
        a = AUDIENCE_WORDS.get(w)
        if a and a not in audience:
            audience.append(a)
    kinds = [] if soft else [c for c in cats]
    feel = [w for w in words if SYN.get(w) in ("energetic", "epic", "emotional", "hype", "piano",
                                                "powerful", "motivational", "inspiring", "happy",
                                                "playful", "upbeat", "fun", "celebration") or w in PACE_FAST | PACE_SLOW]
    feel = [w for w in dict.fromkeys(feel) if w not in ("pace",)]
    bits = ["%d s" % length]
    if pace < SHOT_SECONDS:
        bits.append("fast pace")
    elif pace > SHOT_SECONDS:
        bits.append("slow pace")
    what = sessions + [k.lower().replace(" & ", " and ") for k in kinds]
    bits.append(", ".join(what) if what else "the whole convention")
    if audience:
        bits.append("for " + " and ".join(audience))
    if feel:
        bits.append("feel: " + ", ".join(feel[:3]))
    return {"length": length, "pace": pace, "sessions": sessions, "kinds": kinds, "audience": audience,
            "feel": feel[:3], "text": " \u00b7 ".join(bits)}


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
# whole evenings people name as one thing (the moments cut from the long
# recordings carry these as their session; every kind of moment is in them)
SESSION_PHRASES = {
    "Night of Champions": ("night of champions", "champions night", "saturday night", "awards night",
                           "awards ceremony", "night of champion"),
    "Black Belt Testing": ("black belt testing", "belt testing", "black belt test",
                           "high rank testing", "the testing"),
    "Victory Dinner": ("victory dinner", "the dinner", "dinner night", "thursday dinner"),
    "Victory for Life Reception": ("victory for life", "the reception", "reception night",
                                   "friday reception"),
}


def ask_sessions(ask):
    """Sessions the ask names by phrase, e.g. 'night of champions'."""
    low = re.sub(r"[^a-z0-9 ]+", " ", (ask or "").lower())
    low = re.sub(r"\s+", " ", low)
    return [name for name, phrases in SESSION_PHRASES.items() if any(p in low for p in phrases)]


def strip_sessions(ask):
    """The ask without the evening phrases, so "night of champions" does not
    also read as "champions" (a winning-moments word)."""
    low = re.sub(r"[^a-z0-9 ]+", " ", (ask or "").lower())
    low = re.sub(r"\s+", " ", low)
    for phrases in SESSION_PHRASES.values():
        for p in phrases:
            low = low.replace(p, " ")
    return low


def ask_categories(ask):
    """The kinds of moment an ask names, as (categories, soft).
    soft is True when only audience words ("parents") pointed anywhere."""
    words = set(re.findall(r"[a-z]+", strip_sessions(ask)))
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
    sessions = ask_sessions(ask)
    cats, soft = ask_categories(ask)
    if sessions:
        # "night of champions": that evening's footage, every kind of moment in
        # it, the index's hits first; "… and some board breaks" adds that kind
        # from the whole weekend too (Michael's example, 17 Sep)
        firm = [] if soft else list(cats)

        def wanted(c):
            return c.get("session") in sessions or c.get("category") in firm
        first, seen = [], set()
        # the named KIND leads (a few, capped by the usual per-kind rule), then
        # the index's hits from the evening, then the rest of the evening
        for c in sorted([c for c in clips if c.get("category") in firm],
                        key=lambda c: (-PRIORITY.get(c.get("priority"), 0), c["id"])):
            c = dict(c)
            c["weight"] = 9.95
            first.append(c)
            seen.add(c["id"])
        for k, cid in enumerate(hits):
            if cid in by_id and cid not in seen and wanted(by_id[cid]):
                c = dict(by_id[cid])
                c["weight"] = 9.9 - k * 0.01
                first.append(c)
                seen.add(cid)
        named = sorted([c for c in clips if c["id"] not in seen and wanted(c)],
                       key=lambda c: (-PRIORITY.get(c.get("priority"), 0), c["id"]))
        for c in named:
            c = dict(c)
            c["weight"] = 9.5
            first.append(c)
            seen.add(c["id"])
        if first:
            rest = sorted([c for c in clips if c["id"] not in seen],
                          key=lambda c: (-PRIORITY.get(c.get("priority"), 0), c["id"]))
            # the evening's own cap is lifted; its KINDS stay balanced, so the
            # reel moves across them (self-test #18: seven of ten were rank
            # presentations when everything was uncapped)
            return first + rest, True, tuple("session:" + x for x in sessions)
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
