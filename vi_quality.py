"""vi_quality.py — the quality pass over every file in the Library (runs on the Mini).

Michael, 17 Sep, on his video #30: "a lot of camera shaky movements where the
cameraman is still trying to find the shot … other shots had no color
correction, probably one of the cameras shooting in S-Log3 … maybe those clips
need to be trimmed down to the exactly good moments."

Two measurements, one fix, all resumable inside the daemon's idle pass:

  STEADY   ffmpeg's vidstabdetect (at 480 px) gives, per frame, where the
           picture moved. The median of those local motions is the camera's
           own move; per second we keep its wobble (jitter) and drift (pan),
           both scaled to 25 fps. Seconds under the thresholds are steady;
           runs of them become "stable" stretches: [[start, seconds], …].
           The editor keeps every shot inside one (victory_cut.steady_in),
           and a clip with no stretch as long as a shot goes to the back.

  LOG      A moment cut from a camera that shot S-Log3 (the FX3 cards: the
           sidecar XML next to the original says CaptureGammaEquation
           "s-log3-cine") is flat and grey. Those files are re-encoded once
           through victory_assets/slog3_to_709.cube (Sony's published curve
           and matrices, a soft highlight roll-off and a touch of contrast)
           and replaced in place, verified by reading back.

Results: <VI_LIBRARY>/quality.json — {clip_id: {"fps", "shake": [[jitter,
pan] per second], "stable": [[start, seconds]], "log": bool, "graded": bool}}.
The render worker merges "stable" into every clip it plans with. Nothing
here touches the database or needs the app.
"""
import json
import os
import re
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.environ.get("VI_LIBRARY", os.path.join(HERE, ".deploy"))
CACHE = os.environ.get("VI_CACHE_DIR", os.path.join(LIB, "vi_cache"))
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
ENCODER = os.environ.get("VI_ENCODER", "libx264")
BUDGET = float(os.environ.get("VI_QUALITY_BUDGET", "80"))
LUT = os.path.join(HERE, "victory_assets", "slog3_to_709.cube")
OUT = os.path.join(LIB, "quality.json")
T0 = time.time()

JITTER_MAX = 1.5      # px/frame at 480 px wide, 25 fps: more is a hand that cannot hold still
PAN_MAX = 4.0         # px/frame: more is the camera hunting for the shot
MIN_STEADY = 2        # seconds in a row before a stretch counts
LOG_CARDS = ("s-log3", "slog3")


def log(msg):
    line = "%s quality: %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(os.path.join(LIB, "_tools", "vi_quality.log"), "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def left():
    return BUDGET - (time.time() - T0)


def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe(path):
    """(width, height, fps, seconds) from ffmpeg's banner (ffprobe may lack disk access)."""
    r = run([FFMPEG, "-hide_banner", "-i", path], timeout=30)
    txt = r.stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", txt)
    dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
    m = re.search(r"Video:.*?(\d{3,5})x(\d{3,5})", txt)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    m = re.search(r"(\d+(?:\.\d+)?) fps", txt)
    fps = float(m.group(1)) if m else 25.0
    return w, h, fps, dur


def jload(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


# ── steadiness ─────────────────────────────────────────────────────────────
LM = re.compile(r"\(LM (-?\d+) (-?\d+) \d+ \d+ \d+ [\d.]+ [\d.]+\)")


def parse_trf(path):
    """Per-frame global motion (dx, dy): the median of vidstab's local motions."""
    frames = []
    with open(path) as f:
        for line in f:
            if not line.startswith("Frame"):
                continue
            lms = LM.findall(line)
            if not lms:
                frames.append((0.0, 0.0))
                continue
            frames.append((statistics.median(int(a) for a, b in lms),
                           statistics.median(int(b) for a, b in lms)))
    return frames


def shake_profile(frames, fps):
    """[[jitter, pan], …] per second, scaled to 25 fps so 24p and 60p compare."""
    win = max(1, int(round(fps)))
    scale = fps / 25.0
    per = []
    for s in range(0, len(frames), win):
        seg = frames[s:s + win]
        if len(seg) < max(2, win // 2):
            break
        mx = statistics.mean(dx for dx, dy in seg)
        my = statistics.mean(dy for dx, dy in seg)
        pan = (mx * mx + my * my) ** 0.5
        jitter = statistics.mean(((dx - mx) ** 2 + (dy - my) ** 2) ** 0.5 for dx, dy in seg)
        per.append([round(jitter * scale, 2), round(pan * scale, 2)])
    return per


def stable_windows(per, duration=None):
    """Runs of steady seconds, at least MIN_STEADY long: [[start, seconds]]."""
    out, start = [], None
    n = len(per)
    for i, (j, p) in enumerate(per + [[99, 99]]):
        ok = j <= JITTER_MAX and p <= PAN_MAX and i < n
        if ok and start is None:
            start = i
        if not ok and start is not None:
            if i - start >= MIN_STEADY:
                end = float(i)
                if duration and i == n:
                    end = float(duration)         # the last steady run reaches the true end
                out.append([float(start), round(end - start, 2)])
            start = None
    return out


_have_vidstab = None


def have_vidstab():
    """This ffmpeg can measure steadiness. The Mini's Homebrew build cannot
    (no libvidstab), so there the measuring is done from the bridge VM with
    steady_vm.py and this pass only grades."""
    global _have_vidstab
    if _have_vidstab is None:
        r = run([FFMPEG, "-hide_banner", "-filters"], timeout=30)
        _have_vidstab = "vidstabdetect" in (r.stdout or "")
    return _have_vidstab


def measure(path):
    w, h, fps, dur = probe(path)
    if not dur:
        return None
    trf = path + ".trf"
    r = run([FFMPEG, "-v", "error", "-y", "-i", path, "-an",
             "-vf", "scale=480:-2,vidstabdetect=result=%s:shakiness=5:accuracy=9:stepsize=8" % trf,
             "-f", "null", "-"], timeout=110)
    if r.returncode != 0 or not os.path.exists(trf):
        log("vidstabdetect failed for %s: %s" % (os.path.basename(path), (r.stderr or "")[-200:]))
        return None
    try:
        frames = parse_trf(trf)
    finally:
        try:
            os.remove(trf)
        except OSError:
            pass
    per = shake_profile(frames, fps)
    return {"fps": round(fps, 3), "seconds": round(dur, 2), "shake": per,
            "stable": stable_windows(per, dur)}


# ── colour ─────────────────────────────────────────────────────────────────
def on_this_machine(src):
    """A source path as the Mini sees it: the first batches were listed from
    the bridge VM (/sessions/<id>/mnt/MWM_4T/...), the drive is /Volumes/MWM_4T."""
    return re.sub(r"^/sessions/[^/]+/mnt/", "/Volumes/", src or "")


def original_for(src):
    """The camera original behind a Sony proxy: .../Sub/997_9735S03.MP4 ->
    .../Clip/997_9735.MXF, .../SUB/C0553S03.MP4 -> .../CLIP/C0553.MP4."""
    src = on_this_machine(src)
    d, f = os.path.split(src)
    m = re.match(r"^(.*)S03\.MP4$", f, re.I)
    if not m:
        return src
    for clipdir in ("Clip", "CLIP"):
        cd = os.path.join(os.path.dirname(d), clipdir)
        for ext in (".MXF", ".MP4", ".mxf", ".mp4"):
            p = os.path.join(cd, m.group(1) + ext)
            if os.path.exists(p):
                return p
    return src


def sidecar_gamma(src):
    """CaptureGammaEquation from the Sony sidecar next to a camera original
    (997_9735.MXF -> 997_9735M01.XML; C0347.MP4 -> C0347M01.XML), or ""."""
    if not src:
        return ""
    stem, _ = os.path.splitext(original_for(src))
    for cand in (stem + "M01.XML", stem + "M01.xml"):
        try:
            with open(cand, "r", errors="ignore") as f:
                txt = f.read(20000)
            m = re.search(r'CaptureGammaEquation"?\s+value="([^"]+)"', txt)
            if m:
                return m.group(1).lower()
        except OSError:
            continue
    return ""


def is_log(gamma):
    return any(k in (gamma or "") for k in LOG_CARDS)


def grade(path):
    """Re-encode a log file through the LUT, in place, verified. True when done."""
    if not os.path.exists(LUT):
        log("no LUT at %s" % LUT)
        return False
    w, h, fps, dur = probe(path)
    big = w >= 3000
    part = path + ".graded.mp4"
    venc = (["-c:v", ENCODER, "-b:v", "40M" if big else "12M", "-allow_sw", "1"] if "videotoolbox" in ENCODER
            else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"])
    r = run([FFMPEG, "-v", "error", "-y", "-i", path, "-map", "0:v:0", "-map", "0:a:0?",
             "-vf", "lut3d=%s" % LUT.replace(":", "\\:"), "-pix_fmt", "yuv420p",
             "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"] + venc +
            ["-c:a", "copy", "-movflags", "+faststart", part], timeout=110)
    ok = r.returncode == 0 and os.path.exists(part) and os.path.getsize(part) > 100_000
    if ok:
        _, _, _, got = probe(part)
        ok = got > 0.5 and abs(got - dur) < 1.0
    if ok:
        os.replace(part, path)
        return True
    try:
        os.remove(part)
    except OSError:
        pass
    log("grading failed for %s: %s" % (os.path.basename(path), (r.stderr or "")[-200:]))
    return False


# ── the pass ───────────────────────────────────────────────────────────────
def library_files():
    """(clip_id, path) for every clip file the editor can use."""
    out = []
    for d in (CACHE, os.path.join(CACHE, "long")):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".mp4") and not f.startswith("M_") and ".part" not in f and ".graded" not in f:
                out.append((f[:-4], os.path.join(d, f)))
    return out


def sources(repo=HERE):
    """clip_id -> camera original path, from clips.json (the 214 first
    moments) and the Mini's own published moments."""
    src = {}
    for c in jload(os.path.join(repo, "victory_source", "VWC26", "clips.json"), []):
        if c.get("long_src"):
            src[c["id"]] = c["long_src"]
    for d in os.listdir(os.path.join(LIB, "moments")) if os.path.isdir(os.path.join(LIB, "moments")) else []:
        cands = jload(os.path.join(LIB, "moments", d, "cands.json"), {})
        for key, ms in cands.items():
            for m in ms:
                if m.get("cid") and m.get("src"):
                    src[m["cid"]] = m["src"]
    return src


def step():
    q = jload(OUT, {})
    files = library_files()
    srcs = sources()
    done_measure = done_grade = 0
    for cid, path in files:
        if left() < 20:
            jsave(OUT, q)
            return "paused (%d measured, %d graded this pass; %d of %d done)" % (
                done_measure, done_grade, sum(1 for c, _ in files if c in q and "stable" in q[c]), len(files))
        entry = q.get(cid) or {}
        if "log" not in entry:
            gamma = sidecar_gamma(srcs.get(cid))
            entry["log"] = is_log(gamma)
            entry["gamma"] = gamma
        if entry["log"] and not entry.get("graded"):
            if left() < 60:
                jsave(OUT, q)
                return "paused before grading %s" % cid
            if grade(path):
                entry["graded"] = True             # steadiness is unchanged by the grade
                done_grade += 1
                log("graded %s" % cid)
            else:
                entry["graded"] = False
                entry["grade_failed"] = entry.get("grade_failed", 0) + 1
        if "stable" not in entry and entry.get("grade_failed", 0) < 3 and have_vidstab():
            m = measure(path)
            if m:
                entry.update(m)
                done_measure += 1
            else:
                entry["stable"] = None
        q[cid] = entry
        jsave(OUT, q)
    jsave(OUT, q)
    steady = sum(1 for e in q.values() if e.get("stable"))
    return "done: %d files, %d with steady stretches, %d graded" % (
        len(files), steady, sum(1 for e in q.values() if e.get("graded")))


if __name__ == "__main__":
    try:
        log(step())
    except Exception as e:
        log("failed: %r" % (e,))
        sys.exit(1)
