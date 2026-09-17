"""vi_moments.py — the long recordings become short, named moments, on the Mini.

Michael, 16–17 Sep: "one long clip is going to have a lot of good moments …
that needs to be cut down to a lot of short clips, so it's easy to rename and
put on the library for people to search." The first two batches ran through
the Cowork bridge; this file moves the whole pipeline onto the Mac Mini, which
can now read the drives itself (Full Disk Access, 17 Sep), so a new event is
one todo file away and the cuts come from the ORIGINAL camera files.

    todo.json  (VI_LIBRARY/moments/<event>/todo.json — a list of sources)
        -> scan       per-second loudness + keyframe motion         (scan/<key>.tsv)
        -> find       energy peaks -> candidate windows              (cands.json)
        -> sheet      six frames of each candidate                  (sheets/<id>.jpg)
        -> name       the app's Claude: title, category, words, 1–5 (named.json)
        -> cut        the keepers, from the original when it exists (vi_cache/long/<id>.mp4)
        -> reframe    where the motion is, per second               (reframe.json)
        -> publish    POST /vi/moments/publish                      (published.json)

Every step is resumable and takes a time budget (VI_MOMENTS_BUDGET, seconds):
the daemon runs this on idle passes and launchd ends a pass at 120 s, so the
work advances a slice at a time and never blocks a cut. Standard library
only, Apple's /usr/bin/python3, ffmpeg from Homebrew. Never touches sources.

A "recut" item in the todo (id + src + start + dur) re-cuts an existing
Library moment from its original file at full resolution: the proxies were
1080p, the cameras are 4K, and a 9:16 crop of 4K is 1215x2160 — no upscale.
"""
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.environ.get("VI_APP", "https://mwm-sales-agent-production.up.railway.app").rstrip("/")
SECRET = os.environ.get("VI_SECRET", "")
EVENT = os.environ.get("VI_EVENT", "VWC26")
LIB = os.environ.get("VI_LIBRARY", "/Volumes/MWM_4T/VICTORY/VI_LIBRARY")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
ENCODER = os.environ.get("VI_ENCODER", "libx264")
BUDGET = float(os.environ.get("VI_MOMENTS_BUDGET", "80"))
LOG_FILE = os.environ.get("VI_MOMENTS_LOG", "")
NAMES_PER_PASS = int(os.environ.get("VI_NAMES_PER_PASS", "5"))   # each blocks the app ~12 s
LEAD, TAIL, GAP = 8, 4, 25
MIN_INTEREST = 3
TALK = re.compile(r"\b(speak|speech|interview|emcee|introduc|reading|announc|address|host)")
T0 = time.time()


def log(msg):
    line = "%s moments: %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass


def left():
    return BUDGET - (time.time() - T0)


def run(cmd, timeout=100):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=min(timeout, max(5, left())))


# ── talking to the app ─────────────────────────────────────────────────────
def _post_json(path, body, timeout=60):
    body = dict(body or {})
    body["secret"] = SECRET
    req = urllib.request.Request(APP + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_file(path, fields, file_field, file_path, timeout=90):
    boundary = "----vi" + uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in dict(fields, secret=SECRET).items():
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (boundary, k, v)).encode("utf-8"))
    buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
               "Content-Type: image/jpeg\r\n\r\n" % (boundary, file_field, os.path.basename(file_path))).encode("utf-8"))
    with open(file_path, "rb") as fh:
        buf.write(fh.read())
    buf.write(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    data = buf.getvalue()
    req = urllib.request.Request(APP + path, data=data, method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                                          "Content-Length": str(len(data))})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ── files ──────────────────────────────────────────────────────────────────
def jload(p, default):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return default


def jsave(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, p)


def probe(path):
    """(width, height, seconds, bit_rate) from ffmpeg's banner (ffmpeg has
    Full Disk Access on the Mini; ffprobe may not)."""
    try:
        r = run([FFMPEG, "-hide_banner", "-i", path], timeout=60)
        text = r.stderr
    except Exception:
        return 0, 0, 0.0, 0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?).*?bitrate:\s*(\d+)", text or "")
    dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
    br = int(m.group(4)) * 1000 if m else 0
    v = re.search(r"Stream #\d+:\d+.*?: Video:.*?(\d{2,5})x(\d{2,5})", text or "")
    if not v:
        return 0, 0, dur, br
    return int(v.group(1)), int(v.group(2)), dur, br


def original_of(path):
    """The camera original for a Sony proxy, when it is there:
    .../Sub/997_9735S03.MP4 -> .../Clip/997_9735.MXF, .../SUB/C0819S03.MP4 ->
    .../CLIP/C0819.MP4. Anything else (ATEM program files) is its own original."""
    d, f = os.path.split(path)
    m = re.match(r"^(.*)S03\.MP4$", f, re.I)
    if not m:
        return path
    base = m.group(1)
    for clipdir in ("Clip", "CLIP"):
        cd = os.path.join(os.path.dirname(d), clipdir)
        for ext in (".MXF", ".MP4", ".mxf", ".mp4", ".MOV"):
            p = os.path.join(cd, base + ext)
            if os.path.exists(p):
                return p
    return path


# ── 1. scan ────────────────────────────────────────────────────────────────
def scan(src, tsv, total):
    """Per-second loudness + keyframe motion, resumable. True when complete."""
    done_to = 0
    if os.path.exists(tsv):
        with open(tsv) as f:
            for line in f:
                try:
                    done_to = max(done_to, int(line.split("\t")[0]) + 1)
                except ValueError:
                    pass
    if done_to >= int(total) - 1:
        return True
    CHUNK = 600
    t0 = (done_to // CHUNK) * CHUNK
    with open(tsv, "a") as f:
        while t0 < total:
            if left() < 25:
                return False
            dur = min(CHUNK, total - t0)
            L, M = {}, {}
            r = run([FFMPEG, "-v", "error", "-ss", str(t0), "-t", str(dur), "-i", src, "-vn", "-af",
                     "ebur128=peak=none:metadata=1,ametadata=print:key=lavfi.r128.M:file=-", "-f", "null", "-"])
            t = None
            for line in r.stdout.splitlines():
                m = re.search(r"pts_time:([0-9.]+)", line)
                if m:
                    t = float(m.group(1))
                    continue
                m = re.search(r"lavfi\.r128\.M=(-?[0-9.]+|-inf)", line)
                if m and t is not None:
                    s = int(t0 + t)
                    L[s] = max(L.get(s, -70.0), -70.0 if m.group(1) == "-inf" else float(m.group(1)))
            r = run([FFMPEG, "-v", "error", "-skip_frame", "nokey", "-ss", str(t0), "-t", str(dur), "-i", src,
                     "-an", "-vf", "scale=160:90,tblend=all_mode=difference,signalstats,"
                     "metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"])
            t = None
            for line in r.stdout.splitlines():
                m = re.search(r"pts_time:([0-9.]+)", line)
                if m:
                    t = float(m.group(1))
                    continue
                m = re.search(r"YAVG=([0-9.]+)", line)
                if m and t is not None:
                    s = int(t0 + t)
                    M[s] = max(M.get(s, 0.0), float(m.group(1)))
            for s in range(int(t0), int(t0 + dur)):
                if s >= done_to:
                    f.write("%d\t%.1f\t%.2f\n" % (s, L.get(s, -70.0), M.get(s, 0.0)))
            f.flush()
            done_to = int(t0 + dur)
            t0 += CHUNK
    return True


# ── 2. find ────────────────────────────────────────────────────────────────
def _pct(xs, q):
    s = sorted(xs)
    if not s:
        return 0.0
    k = (len(s) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _rz(xs):
    p50, p90 = _pct(xs, 50), _pct(xs, 90)
    d = max(p90 - p50, 1e-6)
    return [(x - p50) / d for x in xs]


def find(tsv, n, total):
    t, L, M = [], [], []
    with open(tsv) as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3:
                t.append(int(p[0])); L.append(float(p[1])); M.append(float(p[2]))
    if not t:
        return []
    if total < LEAD + TAIL + 2:
        return [{"peak": min(int(total), LEAD), "score": 0.0, "start": 0, "dur": round(total, 2)}]
    floor = _pct([x for x in L if x > -69] or [-60], 5)
    L = [x if x > -69 else floor for x in L]
    zl, zm = _rz(L), _rz(M)
    raw = [0.6 * a + 0.4 * b for a, b in zip(zl, zm)]
    score = [sum(raw[max(0, i - 2):i + 3]) / len(raw[max(0, i - 2):i + 3]) for i in range(len(raw))]
    s = []
    for i in range(len(score)):
        w = sorted(score[max(0, i - 30):i + 30])
        s.append(score[i] - w[len(w) // 2])
    picked = []
    for i in sorted(range(len(s)), key=lambda i: -s[i]):
        if len(picked) >= n or s[i] <= 0:
            break
        if t[i] < LEAD or t[i] > t[-1] - TAIL:
            continue
        if any(abs(t[i] - p) < GAP for p, _ in picked):
            continue
        picked.append((t[i], s[i]))
    if not picked:
        i = max(range(len(s)), key=lambda k: s[k])
        picked = [(t[i], s[i])]
    picked.sort()
    return [{"peak": p, "score": round(sc, 2), "start": max(0, p - LEAD),
             "dur": round(min(LEAD + TAIL, total - max(0, p - LEAD)), 2)} for p, sc in picked]


# ── the pipeline ───────────────────────────────────────────────────────────
def step(event=EVENT):
    root = os.path.join(LIB, "moments", event)
    todo_p = os.path.join(root, "todo.json")
    if not os.path.exists(todo_p):
        return "no todo"
    os.makedirs(os.path.join(root, "scan"), exist_ok=True)
    os.makedirs(os.path.join(root, "sheets"), exist_ok=True)
    cache = os.path.join(LIB, "vi_cache", "long")
    os.makedirs(cache, exist_ok=True)
    todo = jload(todo_p, {})
    sources = todo.get("sources") or []
    recuts = todo.get("recut") or []
    state = jload(os.path.join(root, "state.json"), {})
    cands = jload(os.path.join(root, "cands.json"), {})
    named = jload(os.path.join(root, "named.json"), {})
    reframe = jload(os.path.join(root, "reframe.json"), {})
    published = jload(os.path.join(root, "published.json"), {})
    if "counters" not in state:                 # continue the Library's numbering per group
        state["counters"] = dict(todo.get("counters") or {})
    counters = state["counters"]

    # ── recuts first: existing moments, from the original, full resolution
    for m in recuts:
        if left() < 30:
            return "paused in recut"
        if state.get("recut", {}).get(m["id"]):
            continue
        dst = os.path.join(cache, m["id"] + ".mp4")
        src = original_of(m["src"])
        ok = cut(src, m["start"], m.get("dur") or 12, dst)
        state.setdefault("recut", {})[m["id"]] = {"ok": ok, "src": src, "at": time.strftime("%Y-%m-%d %H:%M")}
        jsave(os.path.join(root, "state.json"), state)
        log("recut %s from %s: %s" % (m["id"][:40], os.path.basename(src), "ok" if ok else "FAILED"))

    # ── sources: scan -> find -> sheets
    for s in sources:
        key = s["key"]
        st = state.setdefault("src", {}).setdefault(key, {})
        if st.get("done"):
            continue
        if not os.path.exists(s["src"]):
            st["done"] = "missing"
            continue
        if "duration" not in st:
            w, h, dur, br = probe(s["src"])
            st.update({"duration": round(dur, 2), "w": w, "h": h, "bitrate": br})
            jsave(os.path.join(root, "state.json"), state)
        if not st.get("scanned"):
            if left() < 30:
                return "paused in scan"
            if scan(s["src"], os.path.join(root, "scan", key + ".tsv"), st["duration"]):
                st["scanned"] = True
                jsave(os.path.join(root, "state.json"), state)
                log("scanned %s (%d s)" % (key, st["duration"]))
            else:
                jsave(os.path.join(root, "state.json"), state)
                return "paused in scan"
        if key not in cands:
            n = s.get("n") or max(1, int(round(st["duration"] / float(s.get("per_seconds") or 45))))
            found = find(os.path.join(root, "scan", key + ".tsv"), n, st["duration"])
            for m in found:
                m.update({"id": "%s_%05d" % (key, m["start"]), "key": key, "src": s["src"],
                          "session": s.get("session"), "day": s.get("day"), "camera": s.get("camera"),
                          "group": s.get("group") or key.split("_")[0]})
            cands[key] = found
            jsave(os.path.join(root, "cands.json"), cands)
            log("%s: %d candidates" % (key, len(found)))
        for m in cands[key]:
            sheet = os.path.join(root, "sheets", m["id"] + ".jpg")
            if os.path.exists(sheet):
                continue
            if left() < 20:
                return "paused in sheets"
            r = run([FFMPEG, "-v", "error", "-y", "-ss", str(m["start"]), "-t", str(m["dur"]), "-i", m["src"],
                     "-vf", "fps=1/2,scale=320:180,tile=3x2", "-frames:v", "1", "-q:v", "5", sheet + ".part.jpg"])
            if r.returncode == 0 and os.path.exists(sheet + ".part.jpg"):
                os.replace(sheet + ".part.jpg", sheet)
        st["done"] = True
        jsave(os.path.join(root, "state.json"), state)

    # ── name (a few per pass: each call holds the app for ~12 s)
    n_named = 0
    for key in cands:
        for m in cands[key]:
            if m["id"] in named:
                continue
            sheet = os.path.join(root, "sheets", m["id"] + ".jpg")
            if not os.path.exists(sheet):
                continue
            if n_named >= NAMES_PER_PASS or left() < 25:
                jsave(os.path.join(root, "named.json"), named)
                return "paused in naming (%d named this pass)" % n_named
            ctx = "%s, day %s, %s camera. %d-second moment starting %d s into the recording." % (
                m.get("session"), m.get("day"), m.get("camera"), int(m["dur"]), m["start"])
            try:
                d = _post_file("/vi/moments/describe", {"context": ctx}, "sheet", sheet)
            except Exception as e:
                d = {"ok": False, "error": repr(e)[:120]}
            named[m["id"]] = d if d.get("ok") else {"ok": False, "error": d.get("error"), "tries": named.get(m["id"], {}).get("tries", 0) + 1}
            n_named += 1
            jsave(os.path.join(root, "named.json"), named)

    # ── keep, cut, reframe, publish
    to_publish = []
    for key in cands:
        for m in cands[key]:
            d = named.get(m["id"])
            if not d or not d.get("ok"):
                if d and d.get("tries", 0) < 3:
                    return "waiting on naming"
                continue
            grp = m.get("group") or "MOM"
            if "cid" not in m:
                if d["interest"] < MIN_INTEREST:
                    m["cid"] = None
                else:
                    counters[grp] = counters.get(grp, 0) + 1
                    if d["interest"] <= 3 and TALK.search(d["title"].lower()):
                        m["cid"] = None
                    else:
                        slug = re.sub(r"[^a-z0-9]+", "-", d["title"].lower()).strip("-")
                        slug = slug[:40].rsplit("-", 1)[0] if len(slug) > 40 else slug
                        m["cid"] = "VWC26_%s_%03d_%s_%s%05d" % (grp, counters[grp], slug,
                                                                key.replace("_", ""), m["start"])
                jsave(os.path.join(root, "cands.json"), cands)
                jsave(os.path.join(root, "state.json"), state)
            if not m.get("cid"):
                continue
            cid = m["cid"]
            dst = os.path.join(cache, cid + ".mp4")
            if not (os.path.exists(dst) and os.path.getsize(dst) > 200_000):
                if left() < 40:
                    return "paused in cut"
                src = original_of(m["src"])
                start = m["start"]
                if not cut(src, start, m["dur"], dst):
                    log("cut FAILED %s" % cid)
                    m["cid"] = None
                    jsave(os.path.join(root, "cands.json"), cands)
                    continue
                log("cut %s from %s" % (cid[:44], os.path.basename(src)))
            if cid not in reframe:
                if left() < 20:
                    return "paused in reframe"
                reframe[cid] = motion_windows(dst)
                jsave(os.path.join(root, "reframe.json"), reframe)
            if cid not in published:
                to_publish.append(clip_record(m, d, cid, reframe[cid]))
    if to_publish:
        if left() < 15:
            return "paused before publish"
        try:
            res = _post_json("/vi/moments/publish", {"event": event, "clips": to_publish}, timeout=90)
        except Exception as e:
            res = {"ok": False, "error": repr(e)[:160]}
        if res.get("ok"):
            for c in to_publish:
                published[c["id"]] = {"at": time.strftime("%Y-%m-%d %H:%M"), "title": c["title"]}
            jsave(os.path.join(root, "published.json"), published)
            log("published %d moments (%s)" % (len(to_publish), res.get("ingest", {}).get("corpus")))
        else:
            log("publish FAILED: %s" % (res.get("error"),))
            return "publish failed"
    return "done" if not to_publish else "published %d" % len(to_publish)


def cut(src, start, dur, dst):
    """One moment out of a source, into the library. Camera originals are
    4K: kept at 4K (the 9:16 crop of 4K needs no upscale); 1080p sources
    stay 1080p. Hardware encoder on the Mini, x264 elsewhere. Verified after
    writing: a file ffmpeg cannot read back is thrown away."""
    w, h, _, _ = probe(src)
    part = dst + ".part.mp4"
    big = w >= 3000
    venc = (["-c:v", ENCODER, "-b:v", "40M" if big else "12M", "-allow_sw", "1"] if "videotoolbox" in ENCODER
            else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
    r = run([FFMPEG, "-v", "error", "-y", "-ss", "%.2f" % float(start), "-i", src, "-t", "%.2f" % float(dur),
             "-map", "0:v:0", "-map", "0:a:0?"] + venc + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
             "-ac", "2", "-movflags", "+faststart", part], timeout=100)
    ok = r.returncode == 0 and os.path.exists(part) and os.path.getsize(part) > 200_000
    if ok:
        _, _, got, _ = probe(part)
        ok = got > 1.0
    if ok:
        os.replace(part, dst)
        return True
    try:
        os.remove(part)
    except OSError:
        pass
    return False


def motion_windows(path):
    """{duration, windows:[{t, ax, energy, faces:0}]} — where the motion is,
    per second, in left / centre / right thirds."""
    _, _, dur, _ = probe(path)
    logs = [path + ".l%d.txt" % i for i in range(3)]
    fc = ("[0:v]fps=2,scale=240:135,split=3[a][b][c];"
          "[a]crop=80:135:0:0,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=%s[a1];"
          "[b]crop=80:135:80:0,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=%s[b1];"
          "[c]crop=80:135:160:0,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=%s[c1]"
          % tuple(logs))
    run([FFMPEG, "-v", "error", "-y", "-i", path, "-an", "-filter_complex", fc,
         "-map", "[a1]", "-f", "null", "-", "-map", "[b1]", "-f", "null", "-", "-map", "[c1]", "-f", "null", "-"],
        timeout=60)
    per = [{}, {}, {}]
    for i, lg in enumerate(logs):
        t = None
        try:
            with open(lg) as fh:
                for line in fh:
                    m = re.search(r"pts_time:([0-9.]+)", line)
                    if m:
                        t = float(m.group(1))
                        continue
                    m = re.search(r"YAVG=([0-9.]+)", line)
                    if m and t is not None:
                        per[i][int(t)] = per[i].get(int(t), 0.0) + float(m.group(1))
        except FileNotFoundError:
            pass
        try:
            os.remove(lg)
        except OSError:
            pass
    wins = []
    for s in sorted(set(per[0]) | set(per[1]) | set(per[2])):
        e = [per[i].get(s, 0.0) for i in range(3)]
        tot = sum(e) or 1.0
        wins.append({"t": s, "ax": round((e[0] / 6 + e[1] * 3 / 6 + e[2] * 5 / 6) / tot, 3),
                     "energy": round(tot, 2), "faces": 0})
    return {"duration": round(dur, 2), "windows": wins, "how": "motion-thirds"}


PRIO = {5: "hero", 4: "high", 3: "standard", 2: "low", 1: "low"}
DATES = {1: "Thursday 23 July", 2: "Friday 24 July", 3: "Saturday 25 July", 4: "Sunday 26 July"}


def clip_record(m, d, cid, rf):
    cat = d["category"]
    if cat == "Candlelight ceremony" and "candle" not in d["title"].lower() \
            and not any("candle" in k for k in d.get("keywords", [])):
        cat = "Belt & rank presentation"
    session = m.get("session") or "Convention"
    text = " ".join([d["title"].lower(), cat.lower(), " ".join(d.get("keywords", [])),
                     (d.get("people") or "").lower(), session.lower(), DATES.get(m.get("day"), "").lower()])
    return {"kind": "clip", "id": cid, "title": d["title"][:1].upper() + d["title"][1:], "category": cat,
            "file": "long/%s.mp4" % cid, "folder": "LONG RECORDINGS/%s" % session, "drive_id": None,
            "thumb": None, "seconds": round(float(rf.get("duration") or m["dur"]), 1),
            "duration": "0m %02ds" % int(rf.get("duration") or m["dur"]),
            "source_id": m["key"] + "%05d" % m["start"], "fps": None, "day": m.get("day"),
            "date": DATES.get(m.get("day")), "session": session, "camera": m.get("camera"),
            "camera_body": m.get("camera"), "card": m["key"], "priority": PRIO[d["interest"]],
            "weight": round(0.45 + 0.1 * d["interest"], 2), "text": re.sub(r"\s+", " ", text).strip(),
            "keywords": d.get("keywords", []), "people": d.get("people", ""), "interest": d["interest"],
            "long_src": m["src"], "long_start": m["start"], "best_in": m["peak"] - m["start"],
            "reframe": rf}


if __name__ == "__main__":
    if not SECRET:
        print("VI_SECRET missing")
        sys.exit(2)
    try:
        out = step()
        log(out)
    except Exception as e:
        log("crashed: %r" % (e,))
        sys.exit(1)
