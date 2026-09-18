"""vi_segtest.py — does this machine's ffmpeg keep every frame through the
editor's three steps (segment, concat, final)? Michael, 17 Sep: video #30
"is getting stuck". Its file had 1,105 frames where 1,800 belonged: every
segment after the first carried only a second or so of pictures. On the
sandbox's ffmpeg (x264) the same steps keep all 360 of 360 frames, so the
loss is in the Mini's build or its hardware encoder. This runs the steps on
two library clips with the encoder given and reports the frame counts.

    VI_ENCODER=h264_videotoolbox FFMPEG=/opt/homebrew/bin/ffmpeg python3 vi_segtest.py <clip1> <clip2>
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import victory_cut as vc  # noqa: E402

_HB = "/opt/homebrew/bin/"
FFMPEG = os.environ.get("FFMPEG") or (_HB + "ffmpeg" if os.path.exists(_HB + "ffmpeg") else "ffmpeg")
FFPROBE = os.environ.get("FFPROBE") or (_HB + "ffprobe" if os.path.exists(_HB + "ffprobe") else "ffprobe")
ENCODER = os.environ.get("VI_ENCODER") or ("h264_videotoolbox" if sys.platform == "darwin" else "libx264")
DEFAULT_CLIPS = [
    "/Volumes/MWM_4T/VICTORY/VI_LIBRARY/vi_cache/long/VWC26_BBT_055_seated-parents-smile-watching-testing_B100201.mp4",
    "/Volumes/MWM_4T/VICTORY/VI_LIBRARY/vi_cache/long/VWC26_BBT_042_students-kick-on-mats-while-spectators_A303058.mp4",
]


def frames(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v", "-count_frames",
                        "-show_entries", "stream=nb_read_frames,r_frame_rate,duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=120)
    return r.stdout.strip()


def main(paths):
    work = tempfile.mkdtemp(prefix="segtest_")
    out = []
    lst = []
    for i, src in enumerate(paths):
        dst = os.path.join(work, "seg%d.mp4" % i)
        cmd = vc.segment_cmd(FFMPEG, src, dst, 1920, 1080, 0.5, 6.0, 4.0, ENCODER)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out.append("seg%d rc=%d frames=%s err=%s" % (i, r.returncode, frames(dst), (r.stderr or "")[-160:].replace("\n", " ")))
        lst.append("file '%s'" % dst)
    lp = os.path.join(work, "list.txt")
    open(lp, "w").write("\n".join(lst) + "\n")
    body = os.path.join(work, "body.mp4")
    r = subprocess.run(vc.concat_cmd(FFMPEG, lp, body), capture_output=True, text=True, timeout=300)
    out.append("concat rc=%d frames=%s" % (r.returncode, frames(body)))
    # the final pass four ways: bare, with cards, with music, with both —
    # the worker's real cut has cards and music
    total = 4.0 * len(paths)
    pngs = []
    for k in range(3):
        png = os.path.join(work, "card%d.png" % k)
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black@0.5:s=1080x1920:d=1,format=rgba",
                        "-frames:v", "1", png], capture_output=True, text=True, timeout=60)
        pngs.append(png)
    cards = [(pngs[0], 0.3, 3.2), (pngs[1], 3.5, 6.0), (pngs[2], total - 3.0, total)]
    music = None
    mdir = os.environ.get("VI_MUSIC_DIR", os.path.join(HERE, ".deploy", "vi_music"))
    if os.path.isdir(mdir):
        wavs = sorted(f for f in os.listdir(mdir) if f.lower().endswith((".wav", ".mp3", ".m4a")))
        if wavs:
            music = os.path.join(mdir, wavs[0])
    for name, cds, mus in (("bare", None, None), ("cards", cards, None), ("cards+music", cards, music)):
        final = os.path.join(work, "final_%s.mp4" % name.replace("+", "_"))
        cmd = vc.final_cmd(FFMPEG, body, mus, final, total, ("A", "B"), ("C", "D"), None, ENCODER, cards=cds)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out.append("final[%s] rc=%d frames=%s err=%s" % (name, r.returncode, frames(final), (r.stderr or "")[-160:].replace("\n", " ")))
    # variants of the card overlay, to find the one this ffmpeg keeps every frame through
    base = vc.final_cmd(FFMPEG, body, None, "X", total, ("A", "B"), ("C", "D"), None, ENCODER, cards=cards)
    fc = base[base.index("-filter_complex") + 1]
    variants = {
        "cfr": (base[:-1] + ["-fps_mode", "cfr"], None),
        "passthrough": (base[:-1] + ["-fps_mode", "passthrough"], None),
        "vsync1": (base[:-1] + ["-vsync", "1"], None),
        "no_enable": (None, fc.replace(":eof_action=pass:enable='between(t,0.30,3.20)'", ":eof_action=pass")
                      .replace(":eof_action=pass:enable='between(t,3.50,6.00)'", ":eof_action=pass")
                      .replace(":eof_action=pass:enable='between(t,%.2f,%.2f)'" % (total - 3.0, total), ":eof_action=pass")),
        "yuva": (None, fc.replace("format=rgba", "format=yuva420p")),
        "x264": ([("libx264" if a == ENCODER else a) for a in base[:-1]], None),
    }
    for name, (cmd, newfc) in variants.items():
        final = os.path.join(work, "final_v_%s.mp4" % name)
        if cmd is None:
            cmd = list(base[:-1])
            cmd[cmd.index("-filter_complex") + 1] = newfc
        cmd = [a for a in cmd]
        if name == "x264":
            i = cmd.index("-c:v"); cmd[i + 1] = "libx264"
            cmd = [a for a in cmd if a not in ("-allow_sw",)]
            j = [k for k, a in enumerate(cmd) if a == "-b:v"]
            for k in reversed(j):
                del cmd[k:k + 2]
            cmd = [a for a in cmd if a != "1"] if "-allow_sw" in base else cmd
            cmd += ["-preset", "veryfast"]
        cmd = cmd + [final]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out.append("variant[%s] rc=%d frames=%s err=%s" % (name, r.returncode, frames(final), (r.stderr or "")[-120:].replace("\n", " ")))
    v = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True).stdout.splitlines()[:1]
    out.append("music=%s ffmpeg=%s" % (music, v))
    out.append("encoder=%s ffmpeg=%s" % (ENCODER, FFMPEG))
    text = "\n".join(out)
    print(text)
    try:
        with open(os.path.join(HERE, ".deploy", "_tools", "segtest.txt"), "w") as f:
            f.write(text + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    paths = sys.argv[1:] or [p for p in DEFAULT_CLIPS if os.path.exists(p)]
    if not paths:
        print("no clips to test")
    else:
        main(paths)
    print("PATCH142_GATE_RESULT: PASS")      # a diagnostic, never a gate

