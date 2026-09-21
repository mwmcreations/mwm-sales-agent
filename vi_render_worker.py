"""vi_render_worker.py — the machine editor's hands. Runs on the Mac Mini.

    claim a request  ->  find the footage  ->  cut it  ->  hand the file to the app

Started by .deploy/mwm_autodeploy.sh on every idle pass (every ~2 min), detached,
under a lock so two never run at once. Stops when the queue is empty. Standard
library only, on Apple's /usr/bin/python3 (3.9): no Flask, no psycopg2, no
OpenCV, no requests. ffmpeg is the only thing it needs installed.

Why on the Mac and not on Railway (14 Sep, for the test week): Apple M4 with the
hardware encoder cuts a 30-second reel in about a minute; the 111 convention
clips (~6.5 GB) are downloaded once and cached; and the sales machine on
Railway never competes with a render for CPU. Moving it is a config change,
not a rewrite — victory_cut.py does not care where it runs.

The admin secret arrives in the environment from the daemon (it reads
~/.mwm_upload_secret); it is never written to a log or a file here.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

APP = os.environ.get("VI_APP", "https://mwm-sales-agent-production.up.railway.app").rstrip("/")
SECRET = os.environ.get("VI_SECRET", "")
WORKER = os.environ.get("VI_WORKER", "mac-mini")
EVENT = os.environ.get("VI_EVENT", "VWC26")
MUSIC_DIR = os.environ.get("VI_MUSIC_DIR", os.path.join(HERE, ".deploy", "vi_music"))
CACHE_DIR = os.environ.get("VI_CACHE_DIR", os.path.join(HERE, ".deploy", "vi_cache"))
QUOTES_DIR = os.environ.get("VI_QUOTES_DIR", os.path.join(CACHE_DIR, "quotes"))
WORK_DIR = os.environ.get("VI_WORK_DIR", os.path.join(HERE, ".deploy", "vi_work"))
LOG_FILE = os.environ.get("VI_WORKER_LOG", "")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
ENCODER = os.environ.get("VI_ENCODER", "libx264")
MAX_JOBS = int(os.environ.get("VI_MAX_JOBS", "5"))
# after an empty queue the worker keeps listening this long (polling every
# few seconds) instead of leaving until the daemon's next pass two minutes
# later — a person who just pressed Make it waits seconds, not minutes
LINGER = float(os.environ.get("VI_LINGER", "105"))    # the daemon runs this inline; what is left of its ~115 s pass goes to the moments and quality passes
LINGER_POLL = float(os.environ.get("VI_LINGER_POLL", "4"))


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass


# ── talking to the app ─────────────────────────────────────────────────────
def _get(path, params=None, timeout=60):
    params = dict(params or {})
    params["secret"] = SECRET
    url = APP + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_json(path, body, timeout=60):
    body = dict(body or {})
    body["secret"] = SECRET
    req = urllib.request.Request(APP + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_bytes(path, params=None, timeout=60):
    params = dict(params or {})
    params["secret"] = SECRET
    url = APP + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def fetch_cards(card_plan, workdir):
    """The title pictures, from the app: one PNG per planned card. Returns a
    list of (png_path, t_in, t_out), or None if anything is off — the cut then
    ships without words on it rather than failing."""
    try:
        out = []
        for k, (big, small, t_in, t_out, y) in enumerate(card_plan):
            png = _get_bytes("/vi/card", {"big": big, "small": small, "y": "%.2f" % y,
                                          "size": "64" if len(big) > 22 else "70"})
            if not png.startswith(b"\x89PNG"):
                raise RuntimeError("not a PNG for card %d" % k)
            p = os.path.join(workdir, "card%02d.png" % k)
            with open(p, "wb") as f:
                f.write(png)
            out.append((p, float(t_in), float(t_out)))
        return out
    except Exception as e:
        log("  no title cards: %r" % (e,))
        return None


def _post_file(path, fields, file_field, file_path, timeout=600):
    """Multipart upload with the standard library."""
    boundary = "----vi" + uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in dict(fields, secret=SECRET).items():
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (boundary, k, v)).encode("utf-8"))
    buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
               "Content-Type: video/mp4\r\n\r\n" % (boundary, file_field, os.path.basename(file_path))).encode("utf-8"))
    with open(file_path, "rb") as f:
        shutil.copyfileobj(f, buf)
    buf.write(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    data = buf.getvalue()
    req = urllib.request.Request(APP + path, data=data, method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                                          "Content-Length": str(len(data))})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ── the footage ────────────────────────────────────────────────────────────
def fetch_drive(drive_id, dst):
    """Download one Drive file by id, through the >100 MB virus-scan page."""
    if os.path.exists(dst) and os.path.getsize(dst) > 1_000_000:
        return dst
    tmp = dst + ".part"
    url = "https://drive.google.com/uc?export=download&id=" + drive_id
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    with open(tmp, "rb") as f:
        head = f.read(400)
    if b"<!DOCTYPE html" in head or b"<html" in head:
        page = open(tmp, "rb").read().decode("utf-8", "replace")
        m = re.search(r'name="uuid" value="([^"]+)"', page)
        if not m:
            os.remove(tmp)
            raise RuntimeError("Drive did not offer a download for %s" % drive_id)
        url2 = ("https://drive.usercontent.google.com/download?id=%s&export=download&confirm=t&uuid=%s"
                % (drive_id, m.group(1)))
        with urllib.request.urlopen(url2, timeout=600) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
    os.replace(tmp, dst)
    return dst


def clip_path(c):
    """Where a clip's file is. Moments cut from the long recordings live only
    in the cache (file 'long/<id>.mp4', no Drive id); the 111 convention
    selects are fetched from Drive once and cached."""
    f = c.get("file") or ""
    local = os.path.join(CACHE_DIR, f) if f else ""
    if f and os.path.exists(local) and os.path.getsize(local) > 100_000:
        return local
    if not c.get("drive_id"):
        raise RuntimeError("clip %s: no file in the cache and no Drive id" % c["id"])
    return fetch_drive(c["drive_id"], os.path.join(CACHE_DIR, c["id"] + ".mp4"))


_EXTRA = {"clips": None}


def published_clips():
    """Moments the Mini published on its own (the app keeps them; each may
    carry its reframe windows). Fetched once per run; empty on any trouble."""
    if _EXTRA["clips"] is None:
        try:
            _EXTRA["clips"] = _get("/vi/moments/published", {"event": EVENT}).get("clips") or []
        except Exception as e:
            log("published moments: could not ask the app: %r" % (e,))
            _EXTRA["clips"] = []
    return _EXTRA["clips"]


def load_sources():
    src = os.path.join(HERE, "victory_source", EVENT)
    clips = json.load(open(os.path.join(src, "clips.json")))
    reframe_path = os.path.join(src, "reframe.json")
    reframe = json.load(open(reframe_path)) if os.path.exists(reframe_path) else {}
    have = {c.get("id") for c in clips}
    for c in published_clips():
        if c.get("id") and c["id"] not in have:
            c = dict(c)
            rf = c.pop("reframe", None)
            clips.append(c)
            have.add(c["id"])
            if rf:
                reframe[c["id"]] = rf
    library_path = os.path.join(MUSIC_DIR, "library.json")
    # the quality pass (vi_quality.py): steady stretches per file, so every
    # shot lands where the camera was still (Michael, 17 Sep, on #30)
    qdir = os.path.dirname(CACHE_DIR)
    quality = {}
    for name in ("quality.json", "quality_steady.json"):      # the Mini's pass, then the VM's measurements
        qpath = os.path.join(qdir, name)
        try:
            if os.path.exists(qpath):
                for k, v in json.load(open(qpath)).items():
                    if v and v.get("stable") is not None:
                        quality[k] = v
        except Exception as e:
            log("quality: could not read %s: %r" % (name, e))
    if quality:
        import victory_cut as vc
        n = 0
        for c in clips:
            q = quality.get(c["id"])
            if q and q.get("stable") is not None:
                if q.get("shake"):
                    c["stable"] = vc.windows_from_shake(q["shake"], q.get("seconds"), vc.STEADY)
                    c["stable_ok"] = vc.windows_from_shake(q["shake"], q.get("seconds"), vc.PASSABLE)
                else:
                    c["stable"] = q["stable"]
                n += 1
        log("quality: steady stretches for %d of %d clips" % (n, len(clips)))
    library = json.load(open(library_path)) if os.path.exists(library_path) else {"tracks": []}
    qm_path = os.path.join(src, "quote_moments.json")
    moments = json.load(open(qm_path)) if os.path.exists(qm_path) else {}
    return clips, reframe, library, moments


def local_search():
    """The same ranking engine the app runs, on the same source files, with
    no database: victory_index.search_corpus is pure."""
    import victory_index as vi
    import victory_ingest as ing
    _, _, records = ing.build_rows(EVENT, published_clips())
    corpus = [{"id": r["id"], "ord": r["ord"], "event": r["event_key"], "k": r["kind"],
               "t": r["title"], "cat": r["category"], "ses": r["session"],
               "s": r["blob"], "w": r["weight"], "qb": r["quotable"]} for r in records]

    def search(q):
        rows, peak, speech, fallback = vi.search_corpus(q, corpus)
        return {"found": len(rows), "fallback": fallback, "peak": peak,
                "results": [{"id": r["id"], "kind": r["k"]} for r in rows[:60]]}
    return search


# ── one job ────────────────────────────────────────────────────────────────
def count_frames(path):
    """How many picture frames a finished file holds. ffmpeg, not ffprobe
    (see victory_cut.probe); the picture is decoded to nothing and the
    frames counted on the way. -1 when it cannot be told."""
    try:
        r = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-map", "0:v:0", "-an", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=300)
        m = re.findall(r"frame=\s*(\d+)", r.stderr or "")
        return int(m[-1]) if m else -1
    except Exception:
        return -1


def do_job(job, clips, reframe, library, search_fn, moments=None):
    import victory_cut as vc
    rid = job["id"]
    ask = (job.get("note") or "").strip()
    items = job.get("items") or []
    requested = [it.get("id", "").split(":", 1)[-1] for it in items if it.get("kind") == "clip"]
    # interview moments the person picked: the ~30 s piece of the recording each
    # line was said in lives in CACHE_DIR/quotes (from the ATEM files on MWM_4T)
    speech, skipped = vc.quote_shots(items, moments or {},
                                     lambda f: os.path.exists(os.path.join(QUOTES_DIR, f)))
    need = int(round((int(job.get("length_s") or 30) - 0.5) / vc.pace_seconds(ask)))
    pool, by_search, focus = vc.candidates(ask, clips, need, search_fn)
    text = job.get("text") or {}
    plan = vc.plan(ask, pool, requested, library, reframe, job.get("length_s") or 30,
                   recent_music=job.get("recent_music") or [], by_search=by_search,
                   avoid=job.get("recent_clips") or [], seed=int(rid),
                   lines=text.get("lines") or [], cta=text.get("cta") or "", speech=speech,
                   focus=focus, all_clips=clips)
    log("job #%s: %r -> %d shots (%s pool, %d picks in, %d no room, %d speech, %d picks missing, pace %.0fs), music %s"
        % (rid, ask[:60], len(plan["shots"]), plan["pool"], sum(1 for x in plan["shots"] if x.get("requested")),
           len(plan.get("no_room") or []), len(speech), len(skipped), plan.get("pace") or 3, plan.get("music_title")))
    os.makedirs(CACHE_DIR, exist_ok=True)
    paths = {}
    t = time.time()
    dropped = []
    for s in list(plan["shots"]):
        try:
            if s.get("kind") == "speech":
                paths[s["id"]] = os.path.join(QUOTES_DIR, s["file"])
                continue
            paths[s["id"]] = clip_path(s)
        except Exception as e:
            # one missing file must not sink the cut: drop that shot, say so
            log("  dropping %s: %r" % (s["id"][:48], e))
            dropped.append(s["id"])
            plan["shots"].remove(s)
    if len(plan["shots"]) < 2:
        raise RuntimeError("footage missing for this cut: %s" % ", ".join(dropped)[:300])
    plan["dropped"] = dropped
    plan["fetch_seconds"] = round(time.time() - t, 1)
    music_path = os.path.join(MUSIC_DIR, plan["music_file"]) if plan.get("music_file") else None
    if music_path and not os.path.exists(music_path):
        log("  music file missing: %s — cutting without music" % music_path)
        music_path = None
        plan["music_id"] = None
    workdir = os.path.join(WORK_DIR, "req%s" % rid)
    if os.path.isdir(workdir):
        shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)
    out_name = "VI_%s_req%s.mp4" % (re.sub(r"[^a-z0-9]+", "-", ask.lower())[:40].strip("-") or "cut", rid)
    out_path = os.path.join(workdir, out_name)
    t = time.time()
    cards = fetch_cards(plan["cards"], workdir)
    vc.render(plan, paths, music_path, workdir, out_path, ffmpeg=FFMPEG, ffprobe=FFPROBE,
              encoder=ENCODER, log=log, cards=cards)
    plan["render_seconds"] = round(time.time() - t, 1)
    plan["skipped"] = skipped
    plan["worker"] = WORKER
    plan["encoder"] = ENCODER
    plan["titles"] = "cards" if cards else "none"
    plan["bytes"] = os.path.getsize(out_path)
    seconds = sum(s["dur"] for s in plan["shots"])
    # the file, counted cold before it goes out: #30 (17 Sep) had 1,105 frames
    # where 1,800 belonged and nobody knew until Michael pressed play
    plan["frames"] = count_frames(out_path)
    plan["frames_expected"] = int(round(seconds * vc.FPS))
    short = plan["frames"] >= 0 and plan["frames"] < plan["frames_expected"] * 0.97
    plan["frames_ok"] = not short
    log("  rendered %s (%d bytes, %s of %d frames%s) in %.0fs; uploading" % (
        out_name, plan["bytes"], plan["frames"] if plan["frames"] >= 0 else "?", plan["frames_expected"],
        " — SHORT, this cut will not play smoothly" if short else "", plan["render_seconds"]))
    res = _post_file("/vi/jobs/%s/deliver" % rid,
                     {"summary": json.dumps(plan), "seconds": "%.2f" % seconds},
                     "video", out_path)
    if not res.get("ok"):
        raise RuntimeError("deliver refused: %s" % (res.get("error"),))
    log("  delivered #%s -> drive %s" % (rid, res.get("drive_id")))
    shutil.rmtree(workdir, ignore_errors=True)
    return res


def prep_media(limit=8):
    """After the queue is empty: give clips that have none a poster and a small
    preview, a few per pass, so the Library fills itself in and new footage is
    covered automatically. Nothing here can fail a cut."""
    try:
        missing = _get("/vi/media/missing", {"limit": limit}).get("missing") or []
    except Exception as e:
        log("prep: could not ask the app: %r" % (e,))
        return 0
    if not missing:
        return 0
    clips, reframe, _, _ = load_sources()
    by_id = {c["id"]: c for c in clips}
    os.makedirs(WORK_DIR, exist_ok=True)
    done = 0
    for cid in missing:
        c = by_id.get(cid)
        moment = os.path.join(QUOTES_DIR, cid + ".mp4") if cid.startswith("M_") else None
        if moment and not os.path.exists(moment):
            continue
        if not moment and not c:
            continue
        try:
            poster = os.path.join(WORK_DIR, "poster_%s.jpg" % cid)
            preview = os.path.join(WORK_DIR, "preview_%s.mp4" % cid)
            venc = (["-c:v", ENCODER, "-b:v", "900k", "-allow_sw", "1"] if "videotoolbox" in ENCODER
                    else ["-c:v", "libx264", "-preset", "fast", "-crf", "28"])
            if moment:
                # an interview piece: the picture 2 s in, the preview is the whole
                # ~30 s piece, small, WITH its sound — the point is to hear the line
                src = moment
                subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "2.0", "-i", src, "-frames:v", "1",
                                "-vf", "scale=480:-2", "-q:v", "4", poster], check=True, capture_output=True, timeout=120)
                venc_m = (["-c:v", ENCODER, "-b:v", "500k", "-allow_sw", "1"] if "videotoolbox" in ENCODER
                          else ["-c:v", "libx264", "-preset", "fast", "-crf", "30"])
                subprocess.run([FFMPEG, "-v", "error", "-y", "-i", src, "-vf", "scale=426:-2,fps=24"] + venc_m +
                               ["-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "1", "-b:a", "48k",
                                "-movflags", "+faststart", preview], check=True, capture_output=True, timeout=300)
            else:
                src = clip_path(c)
                info = (reframe or {}).get(cid) or {}
                wins = info.get("windows") or []
                t = float(max(wins, key=lambda w: w.get("energy") or 0)["t"]) + 0.5 if wins else 1.0
                subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "%.2f" % t, "-i", src, "-frames:v", "1",
                                "-vf", "scale=480:-2", "-q:v", "4", poster], check=True, capture_output=True, timeout=120)
                subprocess.run([FFMPEG, "-v", "error", "-y", "-i", src, "-t", "12", "-vf", "scale=480:-2,fps=24",
                                "-an"] + venc + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", preview],
                               check=True, capture_output=True, timeout=300)
            res = _post_files("/vi/media/%s" % cid, {}, {"poster": poster, "preview": preview})
            if res.get("ok"):
                done += 1
                log("prep: %s poster %dB preview %dB" % (cid[:40], res.get("poster_bytes", 0), res.get("preview_bytes", 0)))
            else:
                log("prep: %s refused: %s" % (cid[:40], res.get("error")))
        except Exception as e:
            log("prep: %s failed: %r" % (cid[:40], e))
        finally:
            for f in (os.path.join(WORK_DIR, "poster_%s.jpg" % cid), os.path.join(WORK_DIR, "preview_%s.mp4" % cid)):
                try:
                    os.remove(f)
                except OSError:
                    pass
    return done


def _post_files(path, fields, files, timeout=300):
    """Multipart upload of several files (stdlib)."""
    boundary = "----vi" + uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in dict(fields, secret=SECRET).items():
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (boundary, k, v)).encode("utf-8"))
    for field, fpath in files.items():
        ctype = "image/jpeg" if fpath.endswith(".jpg") else "video/mp4"
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                   "Content-Type: %s\r\n\r\n" % (boundary, field, os.path.basename(fpath), ctype)).encode("utf-8"))
        with open(fpath, "rb") as f:
            shutil.copyfileobj(f, buf)
        buf.write(b"\r\n")
    buf.write(("--%s--\r\n" % boundary).encode("utf-8"))
    data = buf.getvalue()
    req = urllib.request.Request(APP + path, data=data, method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                                          "Content-Length": str(len(data))})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    # launchd ends the daemon's whole process group when the daemon exits;
    # a new session keeps this worker alive after its parent is gone.
    try:
        os.setsid()
    except OSError:
        pass
    if not SECRET:
        log("no VI_SECRET in the environment — nothing to do")
        return 2
    os.makedirs(WORK_DIR, exist_ok=True)
    lock = os.path.join(WORK_DIR, "worker.lock")
    if os.path.exists(lock):
        try:
            pid = int(open(lock).read().strip() or 0)
            os.kill(pid, 0)
            age = time.time() - os.path.getmtime(lock)
            if age < 3 * 3600:
                log("another worker (pid %d) is running — leaving" % pid)
                return 0
            log("lock from pid %d is %.0fs old — taking over" % (pid, age))
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    with open(lock, "w") as f:
        f.write(str(os.getpid()))
    try:
        clips = reframe = library = search_fn = moments = None
        done = 0
        started = time.time()
        prepped = False
        while done < MAX_JOBS:
            try:
                job = _get("/vi/jobs/next", {"worker": WORKER}).get("job")
            except Exception as e:
                log("could not reach the app: %r" % (e,))
                return 1
            if not job:
                # listen first (a person who just pressed Make it is waiting);
                # the media prep runs once the listening window is over
                if time.time() - started < LINGER:
                    time.sleep(LINGER_POLL)
                    try:
                        with open(lock, "w") as f:     # keep the lock fresh while listening
                            f.write(str(os.getpid()))
                    except OSError:
                        pass
                    continue
                if done == 0 and not prepped:
                    print("%s queue empty" % time.strftime("%Y-%m-%d %H:%M:%S"), flush=True)
                    prep_media(limit=int(os.environ.get("VI_PREP_PER_PASS", "8")))
                    prepped = True
                return 0
            if clips is None:
                clips, reframe, library, moments = load_sources()
                search_fn = local_search()
                log("sources: %d clips, reframe for %d, %d tracks; library at %s" % (
                    len(clips), len(reframe), len(library.get("tracks", [])), CACHE_DIR))
            try:
                do_job(job, clips, reframe, library, search_fn, moments)
            except subprocess.CalledProcessError as e:
                text = (e.stderr or str(e)).strip()
                # the first lines say what went wrong; the last say how it ended
                err = "ffmpeg failed: %s" % (text if len(text) <= 900 else text[:500] + " … " + text[-400:],)
                log("  job #%s FAILED: %s" % (job["id"], err))
                try:
                    _post_json("/vi/jobs/%s/fail" % job["id"], {"error": err, "worker": WORKER})
                except Exception as e2:
                    log("  and could not report it: %r" % (e2,))
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, str(e)[:500])
                log("  job #%s FAILED: %s" % (job["id"], err))
                try:
                    _post_json("/vi/jobs/%s/fail" % job["id"], {"error": err, "worker": WORKER})
                except Exception as e2:
                    log("  and could not report it: %r" % (e2,))
            done += 1
        return 0
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
