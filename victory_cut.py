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
SHOT_SECONDS = 3.0

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
def pick_shots(cands, n, requested=(), max_per_family=2, max_per_session=3, by_search=False):
    """Choose n clips. Requested ids always go in, in the order given. Then
    hero > high > the rest, but never more than max_per_family of one kind of
    shot or max_per_session from one session, and the kinds and days are
    balanced as we go. Returns them in story order.

    cands: clip dicts with id, category, session, day, priority, weight.
    """
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
        if by_search:      # the index already ranked these for the ask: its order leads
            pool.sort(key=lambda c: (fam.get(c.get("category"), 0), day.get(c.get("day"), 0),
                                     -float(c.get("weight") or 0), c["id"]))
        else:
            pool.sort(key=lambda c: (-PRIORITY.get(c.get("priority"), 0),
                                     fam.get(c.get("category"), 0),
                                     day.get(c.get("day"), 0),
                                     -float(c.get("weight") or 0), c["id"]))
        pick = None
        for c in pool:
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


# ── 3. the plan ────────────────────────────────────────────────────────────
def plan(ask, cands, requested_ids, library, reframe, length_s=30, recent_music=(), by_search=False):
    """Everything the render needs, as data. Pure."""
    length_s = int(length_s) if int(length_s or 0) in LENGTHS else 30
    n = int(round((length_s - 0.5) / SHOT_SECONDS))
    shots = pick_shots(cands, n, requested=requested_ids, by_search=by_search)
    music = pick_music(library, ask, exclude=recent_music)
    out = []
    for c in shots:
        x, how, t0 = window_for(c["id"], reframe, 1.0, SHOT_SECONDS)
        out.append({"id": c["id"], "drive_id": c.get("drive_id"), "file": c.get("file"),
                    "title": c.get("title"), "session": c.get("session"),
                    "day": c.get("day"), "category": c.get("category"),
                    "priority": c.get("priority"), "in": round(t0, 2),
                    "dur": SHOT_SECONDS, "x": x, "framed_by": how,
                    "requested": c["id"] in set(requested_ids)})
    return {"ask": ask, "length_s": length_s, "shots": out, "pool": "search" if by_search else "convention",
            "music_id": music["id"] if music else None,
            "music_title": music.get("title") if music else None,
            "music_file": music.get("file") if music else None,
            "days": sorted({s["day"] for s in out if s.get("day")}),
            "kinds": sorted({s["category"] for s in out if s.get("category")})}


def titles_for(ask, event_title="Convention 2026"):
    """A head card and a sign-off from the ask. Short, uppercase, no cleverness."""
    words = [w for w in re.findall(r"[A-Za-z0-9']+", ask or "") if w.lower() not in STOP]
    head = " ".join(words[:4]).upper() if words else event_title.upper()
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


def final_cmd(ffmpeg, body, music, dst, total, head, outro, font, encoder="libx264"):
    end = float(total)
    filters = []
    if font:
        filters += [_drawtext(font, head[0], 70, "h*0.40", 0.3, 3.2),
                    _drawtext(font, head[1], 42, "h*0.40+100", 0.5, 3.2, "0xE8E8E8"),
                    _drawtext(font, outro[0], 76, "h*0.42", end - 3.0, end - 0.1),
                    _drawtext(font, outro[1], 48, "h*0.42+100", end - 2.8, end - 0.1, "0xE8E8E8")]
    filters.append("fade=t=out:st=%.2f:d=0.5" % (end - 0.5))
    venc = ["-c:v", encoder] + (["-b:v", "10M", "-allow_sw", "1"] if "videotoolbox" in encoder
                                 else ["-preset", "medium", "-crf", "21"])
    cmd = [ffmpeg, "-v", "error", "-y", "-i", body]
    if music:
        cmd += ["-i", music, "-filter_complex",
                "[0:a]volume=0.25[nat];[1:a]atrim=0:%.2f,asetpts=PTS-STARTPTS,"
                "afade=t=in:st=0:d=0.3,afade=t=out:st=%.2f:d=1.5[mus];"
                "[nat][mus]amix=inputs=2:duration=first:dropout_transition=0,"
                "loudnorm=I=-14:TP=-1.5:LRA=11[a]" % (end, end - 1.5),
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    cmd += ["-vf", ",".join(filters)] + venc + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                                               "-movflags", "+faststart", "-t", "%.3f" % end, dst]
    return cmd


def probe(ffprobe, path):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,duration", "-of", "json", path],
                       capture_output=True, text=True)
    s = json.loads(r.stdout)["streams"][0]
    return int(s["width"]), int(s["height"]), float(s.get("duration") or 0)


def render(plan_, clip_paths, music_path, workdir, out_path, ffmpeg="ffmpeg",
           ffprobe="ffprobe", encoder="libx264", event_title="Convention 2026", log=print):
    """Run the plan. clip_paths: id -> local file. Returns (out_path, seconds)."""
    os.makedirs(workdir, exist_ok=True)
    segs, total = [], 0.0
    for i, s in enumerate(plan_["shots"], 1):
        src = clip_paths[s["id"]]
        width, height, length = probe(ffprobe, src)
        dur = min(s["dur"], max(0.5, length - s["in"] - 0.05)) if length else s["dur"]
        dst = os.path.join(workdir, "seg%02d.mp4" % i)
        subprocess.run(segment_cmd(ffmpeg, src, dst, width, height, s["x"], s["in"], dur, encoder),
                       check=True, capture_output=True, text=True)
        segs.append(dst)
        total += dur
        log("  seg %02d %-48s in %.1f dur %.1f x %.2f (%s)" % (i, s["id"][:48], s["in"], dur, s["x"], s["framed_by"]))
    lst = os.path.join(workdir, "list.txt")
    with open(lst, "w") as f:
        for sgm in segs:
            f.write("file '%s'\n" % sgm)
    body = os.path.join(workdir, "body.mp4")
    subprocess.run(concat_cmd(ffmpeg, lst, body), check=True, capture_output=True, text=True)
    head, outro = titles_for(plan_["ask"], event_title)
    subprocess.run(final_cmd(ffmpeg, body, music_path, out_path, total, head, outro, font_path(), encoder),
                   check=True, capture_output=True, text=True)
    return out_path, round(total, 2)


# ── 5. the candidate pool ──────────────────────────────────────────────────
def candidates(ask, clips, need, search_fn=None):
    """Which clips the machine may choose from, and whether the index led.

    A narrow ask ("candlelight for the parents") that the index answers with
    enough footage gets ONLY that footage, in the index's order. A broad ask
    ("best moments"), a fallback, or a thin answer gets the whole convention,
    with any hits first. Returns (pool, by_search).
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
    first = []
    for k, cid in enumerate(hits):
        if cid in by_id:
            c = dict(by_id[cid])
            c["weight"] = 10.0 - k * 0.01
            first.append(c)
    # A PEAK ask ("best moments", "iconic") is the index picking highlights for
    # us — a curated slice, but a slice. The variety rule wants the whole
    # convention behind it, so peak asks stay broad with the hits leading.
    peak = bool(res.get("peak"))
    if first and not fallback and not peak and len(first) >= need:
        return first, True
    seen = set(c["id"] for c in first)
    rest = sorted([c for c in clips if c["id"] not in seen],
                  key=lambda c: (-PRIORITY.get(c.get("priority"), 0), c["id"]))
    return first + rest, False
