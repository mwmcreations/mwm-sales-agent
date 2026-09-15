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
WORK_DIR = os.environ.get("VI_WORK_DIR", os.path.join(HERE, ".deploy", "vi_work"))
LOG_FILE = os.environ.get("VI_WORKER_LOG", "")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
ENCODER = os.environ.get("VI_ENCODER", "libx264")
MAX_JOBS = int(os.environ.get("VI_MAX_JOBS", "5"))


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


def load_sources():
    src = os.path.join(HERE, "victory_source", EVENT)
    clips = json.load(open(os.path.join(src, "clips.json")))
    reframe_path = os.path.join(src, "reframe.json")
    reframe = json.load(open(reframe_path)) if os.path.exists(reframe_path) else {}
    library_path = os.path.join(MUSIC_DIR, "library.json")
    library = json.load(open(library_path)) if os.path.exists(library_path) else {"tracks": []}
    return clips, reframe, library


def local_search():
    """The same ranking engine the app runs, on the same source files, with
    no database: victory_index.search_corpus is pure."""
    import victory_index as vi
    import victory_ingest as ing
    _, _, records = ing.build_rows(EVENT)
    corpus = [{"id": r["id"], "ord": r["ord"], "event": r["event_key"], "k": r["kind"],
               "t": r["title"], "cat": r["category"], "ses": r["session"],
               "s": r["blob"], "w": r["weight"], "qb": r["quotable"]} for r in records]

    def search(q):
        rows, peak, speech, fallback = vi.search_corpus(q, corpus)
        return {"found": len(rows), "fallback": fallback, "peak": peak,
                "results": [{"id": r["id"], "kind": r["k"]} for r in rows[:60]]}
    return search


# ── one job ────────────────────────────────────────────────────────────────
def do_job(job, clips, reframe, library, search_fn):
    import victory_cut as vc
    rid = job["id"]
    ask = (job.get("note") or "").strip()
    items = job.get("items") or []
    requested = [it.get("id", "").split(":", 1)[-1] for it in items if it.get("kind") == "clip"]
    need = int(round((int(job.get("length_s") or 30) - 0.5) / vc.SHOT_SECONDS))
    pool, by_search = vc.candidates(ask, clips, need, search_fn)
    plan = vc.plan(ask, pool, requested, library, reframe, job.get("length_s") or 30,
                   recent_music=job.get("recent_music") or [], by_search=by_search)
    log("job #%s: %r -> %d shots (%s pool), music %s" % (rid, ask[:60], len(plan["shots"]),
                                                          plan["pool"], plan.get("music_title")))
    os.makedirs(CACHE_DIR, exist_ok=True)
    paths = {}
    t = time.time()
    for s in plan["shots"]:
        if not s.get("drive_id"):
            raise RuntimeError("clip %s has no Drive id" % s["id"])
        paths[s["id"]] = fetch_drive(s["drive_id"], os.path.join(CACHE_DIR, s["id"] + ".mp4"))
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
    vc.render(plan, paths, music_path, workdir, out_path, ffmpeg=FFMPEG, ffprobe=FFPROBE,
              encoder=ENCODER, log=log)
    plan["render_seconds"] = round(time.time() - t, 1)
    plan["worker"] = WORKER
    plan["encoder"] = ENCODER
    plan["titles"] = bool(vc.font_path() and vc.has_filter(FFMPEG, "drawtext"))
    plan["bytes"] = os.path.getsize(out_path)
    seconds = sum(s["dur"] for s in plan["shots"])
    log("  rendered %s (%d bytes) in %.0fs; uploading" % (out_name, plan["bytes"], plan["render_seconds"]))
    res = _post_file("/vi/jobs/%s/deliver" % rid,
                     {"summary": json.dumps(plan), "seconds": "%.2f" % seconds},
                     "video", out_path)
    if not res.get("ok"):
        raise RuntimeError("deliver refused: %s" % (res.get("error"),))
    log("  delivered #%s -> drive %s" % (rid, res.get("drive_id")))
    shutil.rmtree(workdir, ignore_errors=True)
    return res


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
        clips = reframe = library = search_fn = None
        done = 0
        while done < MAX_JOBS:
            try:
                job = _get("/vi/jobs/next", {"worker": WORKER}).get("job")
            except Exception as e:
                log("could not reach the app: %r" % (e,))
                return 1
            if not job:
                if done == 0:
                    log("queue empty")
                return 0
            if clips is None:
                clips, reframe, library = load_sources()
                search_fn = local_search()
                log("sources: %d clips, reframe for %d, %d tracks" % (len(clips), len(reframe),
                                                                      len(library.get("tracks", []))))
            try:
                do_job(job, clips, reframe, library, search_fn)
            except subprocess.CalledProcessError as e:
                err = "ffmpeg failed: %s" % ((e.stderr or str(e))[-500:],)
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
