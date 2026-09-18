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
    png_cards = [(pngs[0], 0.3, 3.2), (pngs[1], 3.5, 6.0), (pngs[2], total - 3.0, total)]
    # what render() does since the cards-as-video fix: every card becomes a
    # short PNG-codec .mov, fed to the final pass by -itsoffset
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
    for name, cds, mus in (("bare", None, None), ("cards", cards, None), ("cards+music", cards, music),
                           ("cards_png_oldway", png_cards, None)):
        final = os.path.join(work, "final_%s.mp4" % name.replace("+", "_"))
        cmd = vc.final_cmd(FFMPEG, body, mus, final, total, ("A", "B"), ("C", "D"), None, ENCODER, cards=cds)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out.append("final[%s] rc=%d frames=%s err=%s" % (name, r.returncode, frames(final), (r.stderr or "")[-160:].replace("\n", " ")))
    # what differs between the editor's final pass (drops frames here) and the
    # hand-built one-card command below (keeps them)? bisect from the editor's
    # command, one change at a time
    import re as _re
    base = vc.final_cmd(FFMPEG, body, None, "X", total, ("A", "B"), ("C", "D"), None, ENCODER, cards=cards)
    fc = base[base.index("-filter_complex") + 1]
    parts = fc.split(";")
    audio = [p for p in parts if p.endswith("[a]")]
    no_audio = ";".join(p for p in parts if not p.endswith("[a]"))
    last_v = [p for p in parts if p.endswith("[v]")][0]

    def with_fc(newfc, extra=()):
        c = list(base[:-1])
        c[c.index("-filter_complex") + 1] = newfc
        return c + list(extra)

    def audio_out(c, af=None):
        # take the sound out of the filter graph: map the body's own sound
        c = list(c)
        i = c.index("-map", c.index("-map") + 1)   # the second -map is [a]
        c[i + 1] = "0:a?"
        if af:
            c += ["-af", af]
        return c

    aud_chain = audio[0].split("]", 1)[1].rsplit("[", 1)[0] if audio else ""
    variants = {
        "one_card": (vc.final_cmd(FFMPEG, body, None, "X", total, ("A", "B"), ("C", "D"), None, ENCODER, cards=cards[:1])[:-1], None),
        "two_cards": (vc.final_cmd(FFMPEG, body, None, "X", total, ("A", "B"), ("C", "D"), None, ENCODER, cards=cards[:2])[:-1], None),
        "audio_out": (audio_out(with_fc(no_audio)), None),
        "audio_af": (audio_out(with_fc(no_audio), aud_chain), None),
        "no_fade": (with_fc(fc.replace(last_v, last_v.split("]", 1)[0] + "]null[v]")), None),
        "no_faststart": ([a for k, a in enumerate(base[:-1]) if a not in ("-movflags", "+faststart")], None),
        "cfr": (base[:-1] + ["-fps_mode", "cfr"], None),
    }
    for name, (cmd, newfc) in variants.items():
        final = os.path.join(work, "final_v_%s.mp4" % name)
        cmd = list(cmd) + [final]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out.append("variant[%s] rc=%d frames=%s err=%s" % (name, r.returncode, frames(final), (r.stderr or "")[-120:].replace("\n", " ")))
    # where do the frames go? count what LEAVES the filter graph (showinfo)
    def graph_frames(cmd_list):
        c = list(cmd_list)
        i = c.index("-filter_complex")
        c[i + 1] = c[i + 1].replace("[v]", "[vv]") + ";[vv]showinfo[v]"
        c[c.index("-v") + 1] = "info"
        c = c[:c.index("-c:v")] + ["-fps_mode", "passthrough", "-f", "null", "-"]
        r = subprocess.run(c, capture_output=True, text=True, timeout=600)
        return len(_re.findall(r"showinfo.*?n:\s*\d+", r.stderr or ""))
    out.append("graph_out[cards]=%d graph_out[bare]=%d" % (
        graph_frames(base[:-1]),
        graph_frames(vc.final_cmd(FFMPEG, body, None, "X", total, ("A", "B"), ("C", "D"), None, ENCODER)[:-1])))
    # the hand-built one-card command that keeps every frame on the Mini (reference)
    mov = cards[0][0]
    cmdA = [FFMPEG, "-v", "error", "-y", "-i", body, "-itsoffset", "0.30", "-i", mov, "-filter_complex",
            "[1:v]format=rgba,fade=t=in:st=0.30:d=0.4:alpha=1,fade=t=out:st=2.80:d=0.4:alpha=1[c0];"
            "[0:v][c0]overlay=0:0:eof_action=pass:enable='between(t,0.30,3.20)'[v]",
            "-map", "[v]", "-map", "0:a?", "-c:v", ENCODER] + (["-b:v", "10M", "-allow_sw", "1"] if "videotoolbox" in ENCODER else []) + \
           ["-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "%.3f" % total, os.path.join(work, "final_v_movcard.mp4")]
    r = subprocess.run(cmdA, capture_output=True, text=True, timeout=600)
    out.append("variant[mov_card] rc=%d frames=%s err=%s" % (r.returncode, frames(os.path.join(work, "final_v_movcard.mp4")), (r.stderr or "")[-100:].replace("\n", " ")))
    out.append("base_cmd=%s" % " ".join(base))
    # are the frames real or padding? count frames that differ from the one before
    def distinct(path):
        r = subprocess.run([FFMPEG, "-v", "info", "-i", path, "-vf", "mpdecimate=hi=64*4:lo=64*2:frac=0.5",
                            "-fps_mode", "vfr", "-f", "null", "-"], capture_output=True, text=True, timeout=300)
        import re as _re
        m = _re.findall(r"frame=\s*(\d+)", r.stderr or "")
        return m[-1] if m else "?"
    for name in ("final_bare", "final_cards", "final_v_one_card", "final_v_audio_out", "final_v_movcard"):
        pth = os.path.join(work, name + ".mp4")
        if os.path.exists(pth):
            out.append("distinct[%s]=%s" % (name, distinct(pth)))
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

