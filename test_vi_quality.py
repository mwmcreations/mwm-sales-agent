"""test_vi_quality.py — the quality pass on synthetic footage: a steady clip
with a shaky middle gets its steady stretches found; a 'log' clip gets graded
in place through the LUT and is still a readable file afterwards."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TMP = tempfile.mkdtemp(prefix="viq_")
os.environ["VI_LIBRARY"] = TMP
os.environ["VI_CACHE_DIR"] = os.path.join(TMP, "vi_cache")
os.environ["VI_QUALITY_BUDGET"] = "300"
os.environ["VI_ENCODER"] = "libx264"
import vi_quality as vq  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
HAVE_VIDSTAB = HAVE_FFMPEG and "vidstabdetect" in subprocess.run(
    ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout


def make_clip(path, shaky=(4, 8), seconds=12):
    """testsrc2, steady except between shaky[0] and shaky[1] where the frame
    jumps around like a hand hunting for the shot."""
    x = "if(between(t,%d,%d), 40+30*sin(t*43), 40)" % shaky
    y = "if(between(t,%d,%d), 30+30*cos(t*37), 30)" % shaky
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=720x480:rate=25",
                    "-t", str(seconds), "-vf", "crop=640:360:x='%s':y='%s'" % (x, y),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path], check=True)


@unittest.skipUnless(HAVE_VIDSTAB, "ffmpeg with vidstabdetect not installed")
class TestSteadiness(unittest.TestCase):
    def test_the_shaky_middle_is_left_out_of_the_steady_stretches(self):
        p = os.path.join(TMP, "shaky.mp4")
        make_clip(p)
        m = vq.measure(p)
        self.assertIsNotNone(m)
        self.assertEqual(len(m["shake"]), 12)
        self.assertTrue(all(j <= vq.JITTER_MAX for j, _ in m["shake"][:4]), m["shake"])
        self.assertTrue(any(j > vq.JITTER_MAX or p_ > vq.PAN_MAX for j, p_ in m["shake"][4:8]), m["shake"])
        starts = [w[0] for w in m["stable"]]
        self.assertIn(0.0, starts)
        self.assertTrue(any(s >= 8.0 for s in starts), m["stable"])
        self.assertTrue(all(not (4.0 <= s < 8.0) for s in starts), m["stable"])
        self.assertFalse(os.path.exists(p + ".trf"), "the transform file is cleaned up")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class TestGrading(unittest.TestCase):
    def test_a_log_file_is_graded_in_place_and_still_plays(self):
        p = os.path.join(TMP, "log.mp4")
        make_clip(p, shaky=(0, 0), seconds=3)
        before = os.path.getsize(p)
        self.assertTrue(os.path.exists(vq.LUT), "the LUT ships with the app")
        self.assertTrue(vq.grade(p))
        w, h, fps, dur = vq.probe(p)
        self.assertEqual((w, h), (640, 360))
        self.assertGreater(dur, 2.5)
        self.assertNotEqual(os.path.getsize(p), before)
        self.assertFalse(os.path.exists(p + ".graded.mp4"))


class TestPureParts(unittest.TestCase):
    def test_stable_windows(self):
        per = [[0.1, 0.2], [0.2, 0.1], [3.0, 1.0], [7.0, 9.0], [0.5, 0.5], [0.4, 0.3], [0.3, 0.2]]
        self.assertEqual(vq.stable_windows(per), [[0.0, 2.0], [4.0, 3.0]])
        self.assertEqual(vq.stable_windows(per, duration=7.4), [[0.0, 2.0], [4.0, 3.4]])
        self.assertEqual(vq.stable_windows([[9, 9]] * 5), [])
        self.assertEqual(vq.stable_windows([[0.1, 0.1]]), [])           # one second is not a stretch

    def test_shake_profile_scales_to_25_fps(self):
        frames = [(1, 0)] * 60 + [(0, 0)] * 60
        per = vq.shake_profile(frames, 60)
        self.assertEqual(len(per), 2)
        self.assertAlmostEqual(per[0][1], 2.4, places=1)     # 1 px/frame at 60 fps = 2.4 px at 25
        self.assertEqual(per[1], [0.0, 0.0])

    def test_sidecar_and_paths(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "CLIP"))
        os.makedirs(os.path.join(d, "SUB"))
        open(os.path.join(d, "CLIP", "C0553.MP4"), "w").close()
        open(os.path.join(d, "CLIP", "C0553M01.XML"), "w").write(
            '<x><Item name="CaptureGammaEquation" value="s-log3-cine"/></x>')
        proxy = os.path.join(d, "SUB", "C0553S03.MP4")
        self.assertEqual(vq.original_for(proxy), os.path.join(d, "CLIP", "C0553.MP4"))
        self.assertEqual(vq.sidecar_gamma(proxy), "s-log3-cine")
        self.assertTrue(vq.is_log("s-log3-cine"))
        self.assertFalse(vq.is_log("rec709"))
        self.assertEqual(vq.sidecar_gamma("/nowhere/x.MXF"), "")
        self.assertEqual(vq.on_this_machine("/sessions/rcw-abc/mnt/MWM_4T/VICTORY/x.MP4"), "/Volumes/MWM_4T/VICTORY/x.MP4")

    def test_a_pass_over_an_empty_library_is_done(self):
        self.assertTrue(vq.step().startswith("done: 0 files"))


if __name__ == "__main__":
    res = unittest.main(verbosity=2, exit=False).result
    shutil.rmtree(TMP, ignore_errors=True)
    raise SystemExit(0 if res.wasSuccessful() else 1)
