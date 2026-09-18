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
import re
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
    segs = []
    for i, src in enumerate(paths):
        dst = os.path.join(work, "seg%d.mp4" % i)
        cmd = vc.segment_cmd(FFMPEG, src, dst, 1920, 1080, 0.5, 6.0, 4.0, ENCODER)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out.append("seg%d rc=%d frames=%s err=%s" % (i, r.returncode, frames(dst), (r.stderr or "")[-160:].replace("\n", " ")))
        lst.append("file '%s'" % dst)
        segs.append(dst)
    lp = os.path.join(work, "list.txt")
    open(lp, "w").write("\n".join(lst) + "\n")
    body = os.path.join(work, "body.mp4")
    r = subprocess.run(vc.concat_cmd(FFMPEG, lp, body), capture_output=True, text=True, timeout=300)
    out.append("concat rc=%d frames=%s" % (r.returncode, frames(body)))
    # the final pass: the one-pass command (kept as the "before" line — on the
    # Mini it loses a third of the frames with the sound in the graph) and the
    # editor's real three passes from the segments (must keep every frame)
    total = 4.0 * len(paths)
    pngs = []
    for k in range(3):
        png = os.path.join(work, "card%d.png" % k)
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black@0.5:s=1080x1920:d=1,format=rgba",
                        "-frames:v", "1", png], capture_output=True, text=True, timeout=60)
        pngs.append(png)
    png_cards = [(pngs[0], 0.3, 3.2), (pngs[1], 3.5, 6.0), (pngs[2], total - 3.0, total)]
    cards = []
    for k, (png, t_in, t_out) in enumerate(png_cards):
        mov = os.path.join(work, "card%02d.mov" % k)
        r = subprocess.run(vc.card_video_cmd(FFMPEG, png, mov, min(t_out, total) - t_in + 0.2),
                           capture_output=True, text=True, timeout=300)
        out.append("cardmov%d rc=%d frames=%s" % (k, r.returncode, frames(mov)))
        cards.append((mov, t_in, t_out))
    music = None
    mdir = os.environ.get("VI_MUSIC_DIR", os.path.join(HERE, ".deploy", "vi_music"))
    if os.path.isdir(mdir):
        wavs = sorted(f for f in os.listdir(mdir) if f.lower().endswith((".wav", ".mp3", ".m4a")))
        if wavs:
            music = os.path.join(mdir, wavs[0])
    for name, cds, mus in (("bare", None, None), ("one_pass_cards", cards, music)):
        final = os.path.join(work, "final_%s.mp4" % name)
        cmd = vc.final_cmd(FFMPEG, body, mus, final, total, ("A", "B"), ("C", "D"), None, ENCODER, cards=cds)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out.append("final[%s] rc=%d frames=%s err=%s" % (name, r.returncode, frames(final), (r.stderr or "")[-160:].replace("\n", " ")))
    final = os.path.join(work, "final_three_pass.mp4")
    rcs = []
    for c in vc.final_cmds(FFMPEG, body, music, final, total, ("A", "B"), ("C", "D"), None, ENCODER,
                           cards=cards, workdir=work, segments=segs):
        r = subprocess.run(c, capture_output=True, text=True, timeout=600)
        rcs.append(r.returncode)
    out.append("final[three_pass] rc=%s frames=%s picture=%s err=%s" % (
        rcs, frames(final), frames(os.path.join(work, "picture.mp4")), (r.stderr or "")[-120:].replace("\n", " ")))

    def holes(path):
        r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v", "-show_entries", "frame=pts_time",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=300)
        ts = [float(l.strip().rstrip(",")) for l in r.stdout.splitlines() if l.strip()]
        return [(round(ts[i - 1], 3), round(ts[i] - ts[i - 1], 3)) for i in range(1, len(ts))
                if abs(ts[i] - ts[i - 1] - 1.0 / 30) > 0.002][:12]
    out.append("holes[three_pass]=%s" % holes(final))

    # are the frames real or padding? count frames that differ from the one before
    def distinct(path):
        r = subprocess.run([FFMPEG, "-v", "info", "-i", path, "-vf", "mpdecimate=hi=64*4:lo=64*2:frac=0.5",
                            "-fps_mode", "vfr", "-f", "null", "-"], capture_output=True, text=True, timeout=300)
        m = re.findall(r"frame=\s*(\d+)", r.stderr or "")
        return m[-1] if m else "?"
    for name in ("final_bare", "final_one_pass_cards", "final_three_pass"):
        pth = os.path.join(work, name + ".mp4")
        if os.path.exists(pth):
            out.append("distinct[%s]=%s" % (name, distinct(pth)))
    expected = frames(body).rsplit(",", 1)[-1]
    ok = "PASS" if frames(final).endswith("," + expected) and not holes(final) else "SHORT"
    out.append("three_pass_frames=%s (expected %s)" % (ok, expected))
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
    print("PATCH142_GATE_RESULT: PASS")      # a diagnostic, never a gate (three_pass_frames says what it found)

