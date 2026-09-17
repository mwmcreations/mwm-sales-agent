"""test_vi_moments.py — the Mini's own moment pipeline, end to end on a synthetic recording.

No network, no Postgres: the two app calls (name a sheet, publish) are stubbed,
ffmpeg is real. Proves that a 40-second recording with two loud, busy passages
becomes two named, cut, framed, published Library moments — and that every
step resumes across passes (the daemon gives it ~80 s at a time).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TMP = tempfile.mkdtemp(prefix="vimom_")
os.environ["VI_LIBRARY"] = TMP
os.environ["VI_SECRET"] = "test"
os.environ["VI_MOMENTS_BUDGET"] = "300"
os.environ["VI_ENCODER"] = "libx264"

import vi_moments as vm  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def make_source(path):
    """50 s: quiet stillness, then a loud busy burst at 8–12 s and 38–42 s."""
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "50", "-filter_complex",
                    "[0:v]drawbox=x=0:y=0:w=640:h=360:color=black@0.9:t=fill:enable='not(between(t,8,12)+between(t,38,42))'[v];"
                    "[1:a]volume='if(between(t,8,12)+between(t,38,42),1.0,0.02)':eval=frame[a]",
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
                    "-c:a", "aac", path], check=True)


class Answers:
    def __init__(self):
        self.calls = []

    def post_file(self, path, fields, file_field, file_path):
        self.calls.append((path, fields["context"]))
        return {"ok": True, "title": "Kids cheer on the mat", "category": "Crowd & parent reactions",
                "keywords": ["kids", "cheer", "mat"], "people": "kids", "interest": 4, "why": "test"}


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = os.path.join(TMP, "REC_test.mp4")
        make_source(cls.src)
        root = os.path.join(TMP, "moments", "VWC26")
        os.makedirs(root, exist_ok=True)
        json.dump({"sources": [{"key": "TST_A_1", "src": cls.src, "session": "Test Session", "day": 3,
                                "camera": "FX6", "per_seconds": 15, "group": "TST"}]},
                  open(os.path.join(root, "todo.json"), "w"))
        cls.answers = Answers()
        cls.published = []
        vm._post_file = cls.answers.post_file
        vm._post_json = lambda path, body, timeout=60: (cls.published.append(body) or {"ok": True, "ingest": {"corpus": 1}})

    def test_1_runs_to_published(self):
        outs = []
        for _ in range(6):
            vm.T0 = __import__("time").time()
            outs.append(vm.step("VWC26"))
            if outs[-1] == "done" or outs[-1].startswith("published"):
                break
        self.assertTrue(any(o.startswith("published") or o == "done" for o in outs), outs)
        root = os.path.join(TMP, "moments", "VWC26")
        cands = json.load(open(os.path.join(root, "cands.json")))["TST_A_1"]
        self.assertGreaterEqual(len(cands), 2, cands)
        peaks = sorted(c["peak"] for c in cands)
        self.assertTrue(any(7 <= p <= 14 for p in peaks) and any(37 <= p <= 44 for p in peaks), peaks)
        self.assertTrue(self.published, "publish was called")
        clips = self.published[0]["clips"]
        self.assertGreaterEqual(len(clips), 2)
        c = clips[0]
        self.assertTrue(c["id"].startswith("VWC26_TST_001_kids-cheer-on-the-mat_TSTA1"), c["id"])
        self.assertEqual(c["session"], "Test Session")
        self.assertEqual(c["priority"], "high")
        self.assertIn("windows", c["reframe"])
        self.assertTrue(c["reframe"]["windows"])
        f = os.path.join(TMP, "vi_cache", "long", c["id"] + ".mp4")
        self.assertTrue(os.path.exists(f) and os.path.getsize(f) > 200_000, f)
        w, h, dur, _ = vm.probe(f)
        self.assertEqual((w, h), (640, 360))
        self.assertGreater(dur, 10)
        self.assertIn("Test Session, day 3, FX6 camera", self.answers.calls[0][1])

    def test_2_a_second_pass_has_nothing_to_do(self):
        vm.T0 = __import__("time").time()
        n = len(self.published)
        self.assertEqual(vm.step("VWC26"), "done")
        self.assertEqual(len(self.published), n)


class TestAFailedNameIsTriedAgain(unittest.TestCase):
    def test_three_tries_then_skipped(self):
        root = os.path.join(TMP, "moments", "RETRY")
        os.makedirs(os.path.join(root, "sheets"), exist_ok=True)
        m = {"id": "K1", "key": "K", "start": 0, "peak": 5, "dur": 10.0, "session": "S", "day": 1,
             "camera": "C", "src": "/x", "group": "TST"}
        json.dump({"sources": []}, open(os.path.join(root, "todo.json"), "w"))
        json.dump({"K": [m]}, open(os.path.join(root, "cands.json"), "w"))
        json.dump({"K1": {"ok": False, "error": "502", "tries": 1}}, open(os.path.join(root, "named.json"), "w"))
        json.dump({"counters": {}, "recut": {}, "src": {}, "scanned": ["K"]}, open(os.path.join(root, "state.json"), "w"))
        open(os.path.join(root, "sheets", "K1.jpg"), "wb").write(b"\xff\xd8")
        calls = []

        def fail(path, fields, file_field, file_path):
            calls.append(path)
            return {"ok": False, "error": "502"}
        old = vm._post_file
        vm._post_file = fail
        try:
            for _ in range(4):
                vm.T0 = __import__("time").time()
                vm.step("RETRY")
        finally:
            vm._post_file = old
        named = json.load(open(os.path.join(root, "named.json")))
        self.assertEqual(named["K1"]["tries"], 3)
        self.assertEqual(len(calls), 2, "tries 2 and 3, then it is left alone")


class TestPureParts(unittest.TestCase):
    def test_original_of_finds_the_camera_file(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "Clip"))
        os.makedirs(os.path.join(d, "Sub"))
        open(os.path.join(d, "Clip", "997_9735.MXF"), "w").close()
        proxy = os.path.join(d, "Sub", "997_9735S03.MP4")
        self.assertEqual(vm.original_of(proxy), os.path.join(d, "Clip", "997_9735.MXF"))
        self.assertEqual(vm.original_of(os.path.join(d, "Sub", "997_0001S03.MP4")), os.path.join(d, "Sub", "997_0001S03.MP4"))
        self.assertEqual(vm.original_of("/x/ATEM/VICTORY_July_25.mp4"), "/x/ATEM/VICTORY_July_25.mp4")

    def test_a_short_clip_is_its_own_moment(self):
        p = os.path.join(TMP, "short.tsv")
        with open(p, "w") as f:
            for t in range(9):
                f.write("%d\t-20.0\t10.0\n" % t)
        m = vm.find(p, 3, 9.0)
        self.assertEqual(len(m), 1)
        self.assertEqual((m[0]["start"], m[0]["dur"]), (0, 9.0))

    def test_talk_and_low_interest_are_not_moments(self):
        self.assertTrue(vm.TALK.search("emcee speaks to the room"))
        self.assertFalse(vm.TALK.search("kids celebrate with trophy"))
        self.assertEqual(vm.MIN_INTEREST, 3)

    def test_a_log_source_is_graded_on_the_way_in(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "CLIP"))
        src = os.path.join(d, "CLIP", "C0553.MP4")
        open(src, "w").close()
        with open(os.path.join(d, "CLIP", "C0553M01.XML"), "w") as f:
            f.write('<x><Item name="CaptureGammaEquation" value="s-log3-cine"/></x>')
        self.assertTrue((vm.lut_for(src) or "").endswith("slog3_to_709.cube"))
        self.assertIsNone(vm.lut_for("/x/ATEM/VICTORY_July_25.mp4"))

    def test_clip_record_shape(self):
        m = {"key": "NOC_A1", "start": 100, "peak": 108, "dur": 12.0, "session": "Night of Champions", "day": 3,
             "camera": "FX6", "src": "/v/x.MP4"}
        d = {"title": "candidates line up on stage", "category": "Candlelight ceremony", "keywords": ["lineup"],
             "people": "kids", "interest": 5}
        c = vm.clip_record(m, d, "VWC26_NOC_001_x_NOCA100100", {"duration": 12.4, "windows": []})
        self.assertEqual(c["category"], "Belt & rank presentation")     # no candle in sight
        self.assertEqual(c["title"], "Candidates line up on stage")
        self.assertEqual(c["priority"], "hero")
        self.assertEqual(c["best_in"], 8)
        self.assertEqual(c["seconds"], 12.4)
        self.assertIn("night of champions", c["text"])


if __name__ == "__main__":
    res = unittest.main(verbosity=2, exit=False).result
    shutil.rmtree(TMP, ignore_errors=True)
    raise SystemExit(0 if res.wasSuccessful() else 1)
