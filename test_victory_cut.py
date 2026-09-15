"""test_victory_cut.py — the machine editor's decisions, without ffmpeg.

Everything the worker decides before it touches a video file is pure and is
tested here against the real convention index (victory_source/VWC26). What
these tests defend, in Michael's words from the first two reels:

  * "They look alike, from the same moment" — a broad ask spreads across the
    days and the kinds of moment; no kind takes more than two shots.
  * Moments the person picked are always in the cut.
  * A narrow ask that the index answers gets THAT footage, not the whole
    convention.
  * Music matches the ask and rotates away from what the person just heard.
  * The 9:16 window follows the people, then the action, then the centre.
  * The ffmpeg commands are well-formed and never pass user text unescaped.
"""
import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import victory_cut as vc
import victory_index as vi
import victory_ingest as ing

HERE = os.path.dirname(os.path.abspath(__file__))
CLIPS = json.load(open(os.path.join(HERE, "victory_source", "VWC26", "clips.json"), encoding="utf-8"))
LIBRARY = {"tracks": [
    {"id": "01", "file": "01_sports_hype.wav", "title": "The Sports", "tags": ["sports", "hype", "energetic", "highlights"]},
    {"id": "04", "file": "04_uplifting_cinematic.wav", "title": "Uplifting Cinematic", "tags": ["uplifting", "cinematic", "inspiring", "recap"]},
    {"id": "05", "file": "05_fun_kids.wav", "title": "Fun Kids", "tags": ["kids", "fun", "happy"]},
    {"id": "08", "file": "08_hopeful_piano.wav", "title": "Hopeful Piano", "tags": ["emotional", "piano", "candlelight", "parents", "ceremony"]},
]}

_, _, RECORDS = ing.build_rows("VWC26")
CORPUS = [{"id": r["id"], "ord": r["ord"], "event": r["event_key"], "k": r["kind"],
           "t": r["title"], "cat": r["category"], "ses": r["session"],
           "s": r["blob"], "w": r["weight"], "qb": r["quotable"]} for r in RECORDS]


def search(q):
    rows, peak, speech, fallback = vi.search_corpus(q, CORPUS)
    return {"found": len(rows), "fallback": fallback, "peak": peak,
            "results": [{"id": r["id"], "kind": r["k"]} for r in rows[:60]]}


class TestVariety(unittest.TestCase):
    def test_a_broad_ask_moves_across_days_and_kinds(self):
        pool, by_search = vc.candidates("best moments of the convention", CLIPS, 10, search)
        shots = vc.pick_shots(pool, 10, by_search=by_search)
        days = {s.get("day") for s in shots}
        kinds = {s["category"] for s in shots}
        self.assertEqual(len(shots), 10)
        self.assertGreaterEqual(len(days), 3, "all three days")
        self.assertGreaterEqual(len(kinds), 5, "many kinds of moment")
        for k in kinds:
            self.assertLessEqual(sum(1 for s in shots if s["category"] == k), 2, k)

    def test_story_order_opens_on_training_and_closes_on_the_candles(self):
        shots = vc.pick_shots(CLIPS, 10)
        order = [vc.STORY.index(s["category"]) for s in shots]
        self.assertEqual(order, sorted(order))
        self.assertEqual(shots[-1]["category"], "Candlelight ceremony")

    def test_picked_moments_always_go_in(self):
        want = ["VWC26_CROWD_01_kids-cheering_D0062", "VWC26_CROWD_02_kids-arms-raised_D0064",
                "VWC26_CROWD_03_team-celebration_D0065"]
        shots = vc.pick_shots(CLIPS, 10, requested=want)
        ids = [s["id"] for s in shots]
        for w in want:
            self.assertIn(w, ids)
        # three of one kind because they were asked for; the cap applies to the rest
        self.assertEqual(sum(1 for s in shots if s["category"] == "Crowd & parent reactions"), 3)

    def test_a_short_reel_is_five_shots_and_a_long_one_twenty(self):
        self.assertEqual(len(vc.plan("x", CLIPS, [], LIBRARY, {}, 15)["shots"]), 5)
        self.assertEqual(len(vc.plan("x", CLIPS, [], LIBRARY, {}, 60)["shots"]), 20)
        self.assertEqual(vc.plan("x", CLIPS, [], LIBRARY, {}, 45)["length_s"], 30)

    def test_no_clip_twice(self):
        shots = vc.plan("everything", CLIPS, [], LIBRARY, {}, 60)["shots"]
        self.assertEqual(len({s["id"] for s in shots}), len(shots))


class TestTheIndexLeads(unittest.TestCase):
    def test_a_narrow_ask_gets_its_own_footage(self):
        pool, by_search = vc.candidates("candlelight ceremony", CLIPS, 10, search)
        self.assertTrue(by_search)
        shots = vc.pick_shots(pool, 10, by_search=True)
        self.assertTrue(all("Candlelight" in s["session"] or "candle" in s["id"].lower()
                            for s in shots), [s["id"] for s in shots])

    def test_a_broad_ask_gets_the_whole_convention(self):
        pool, by_search = vc.candidates("best moments", CLIPS, 10, search)
        self.assertFalse(by_search)
        self.assertEqual(len(pool), len(CLIPS))

    def test_no_index_is_not_an_error(self):
        pool, by_search = vc.candidates("anything", CLIPS, 10, None)
        self.assertFalse(by_search)
        self.assertEqual(pool[0]["priority"], "hero")

    def test_a_broken_index_falls_back_quietly(self):
        def boom(q):
            raise RuntimeError("no")
        pool, by_search = vc.candidates("kids", CLIPS, 10, boom)
        self.assertFalse(by_search)
        self.assertEqual(len(pool), len(CLIPS))


class TestMusic(unittest.TestCase):
    def test_matches_the_ask(self):
        self.assertEqual(vc.pick_music(LIBRARY, "candlelight ceremony for the parents")["id"], "08")
        self.assertEqual(vc.pick_music(LIBRARY, "kids having fun")["id"], "05")
        self.assertEqual(vc.pick_music(LIBRARY, "best moments")["id"], "01")

    def test_small_words_do_not_match(self):
        # "of", "the", "for" used to match "night of champions"
        self.assertEqual(vc.pick_music(LIBRARY, "a video of the day for a page")["id"], "04")

    def test_rotates_away_from_what_they_just_heard(self):
        self.assertEqual(vc.pick_music(LIBRARY, "kids having fun", exclude=["05"])["id"], "04")

    def test_an_empty_library_is_no_music_not_a_crash(self):
        self.assertIsNone(vc.pick_music({"tracks": []}, "kids"))
        p = vc.plan("kids", CLIPS, [], {"tracks": []}, {}, 15)
        self.assertIsNone(p["music_id"])


class TestTheWindow(unittest.TestCase):
    REFRAME = {"clipA": {"duration": 8.0, "windows": [
        {"t": 0, "faces": 0, "fx": None, "ax": 0.30, "energy": 1.0},
        {"t": 1, "faces": 4, "fx": 0.80, "ax": 0.75, "energy": 5.0},
        {"t": 2, "faces": 4, "fx": 0.80, "ax": 0.75, "energy": 5.0},
        {"t": 3, "faces": 3, "fx": 0.70, "ax": 0.70, "energy": 4.0},
        {"t": 4, "faces": 0, "fx": None, "ax": 0.20, "energy": 0.5},
        {"t": 5, "faces": 0, "fx": None, "ax": 0.20, "energy": 0.5},
        {"t": 6, "faces": 0, "fx": None, "ax": 0.20, "energy": 0.5},
        {"t": 7, "faces": 0, "fx": None, "ax": 0.20, "energy": 0.5}]}}

    def test_faces_win_when_there_are_enough(self):
        x, how, t0 = vc.window_for("clipA", self.REFRAME, 1.0, 3.0)
        self.assertEqual(how, "faces")
        self.assertAlmostEqual(x, (0.8 * 4 + 0.8 * 4 + 0.7 * 3) / 11, places=3)
        self.assertEqual(t0, 1.0)         # the busiest second that still fits

    def test_action_when_faces_are_few(self):
        rf = {"c": {"duration": 8.0, "windows": [
            {"t": t, "faces": 1, "fx": 0.1, "ax": 0.66, "energy": 1.0} for t in range(8)]}}
        x, how, t0 = vc.window_for("c", rf, 1.0, 3.0)
        self.assertEqual(how, "action")
        self.assertAlmostEqual(x, 0.66)

    def test_unknown_clip_is_centred(self):
        self.assertEqual(vc.window_for("nope", self.REFRAME, 1.0, 3.0), (0.5, "centre", 1.0))
        self.assertEqual(vc.window_for("nope", None, 1.0, 3.0), (0.5, "centre", 1.0))

    def test_the_in_point_leaves_room_for_the_shot(self):
        rf = {"c": {"duration": 4.0, "windows": [
            {"t": 0, "faces": 0, "fx": None, "ax": 0.5, "energy": 0.1},
            {"t": 1, "faces": 0, "fx": None, "ax": 0.5, "energy": 0.1},
            {"t": 2, "faces": 0, "fx": None, "ax": 0.5, "energy": 0.1},
            {"t": 3, "faces": 0, "fx": None, "ax": 0.5, "energy": 9.0}]}}
        x, how, t0 = vc.window_for("c", rf, 1.0, 3.0)
        self.assertLessEqual(t0 + 3.0, 4.0)


class TestTheCommands(unittest.TestCase):
    def test_segment_crops_to_nine_sixteen_and_clamps(self):
        cmd = vc.segment_cmd("ffmpeg", "in.mp4", "out.mp4", 3840, 2160, 0.99, 1.0, 3.0)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("crop=1215:2160:2625:0", vf)         # clamped to the right edge
        self.assertIn("scale=1080:1920", vf)
        cmd = vc.segment_cmd("ffmpeg", "in.mp4", "out.mp4", 3840, 2160, 0.5, 1.0, 3.0)
        self.assertIn("crop=1215:2160:1313:0", cmd[cmd.index("-vf") + 1])

    def test_videotoolbox_on_the_mac_x264_elsewhere(self):
        mac = vc.segment_cmd("f", "i", "o", 1920, 1080, 0.5, 0, 3, encoder="h264_videotoolbox")
        self.assertIn("h264_videotoolbox", mac)
        self.assertNotIn("-crf", mac)
        lin = vc.segment_cmd("f", "i", "o", 1920, 1080, 0.5, 0, 3)
        self.assertIn("libx264", lin)
        self.assertIn("-crf", lin)

    def test_user_text_cannot_break_the_filter(self):
        # titles_for keeps only words; and even raw text is escaped by _esc
        head, outro = vc.titles_for("kids' night: 100% fun; the best")
        self.assertEqual(head[0], "KIDS' NIGHT 100 FUN")     # the apostrophe is escaped later, by _esc
        self.assertEqual(vc._esc("a:b 'c' 100%"), "a\\:b \u2019c\u2019 100%%")
        cmd = vc.final_cmd("f", "body.mp4", "m.wav", "out.mp4", 29.0, ("x:y", "z"), outro, "/f.ttf")
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("text='x\\:y'", vf)
        self.assertIn("loudnorm", " ".join(cmd))

    def test_no_music_still_normalises(self):
        cmd = vc.final_cmd("f", "body.mp4", None, "out.mp4", 15.0, ("A", "B"), ("C", "D"), None)
        self.assertNotIn("amix", " ".join(cmd))
        self.assertIn("loudnorm", " ".join(cmd))

    def test_titles_are_short_and_never_empty(self):
        self.assertEqual(vc.titles_for("")[0][0], "CONVENTION 2026")
        head = vc.titles_for("a thirty second reel of the candlelight ceremony for the parents of Lake Nona")[0][0]
        self.assertLessEqual(len(head), 22)
        self.assertTrue(head.isupper())


class TestThePlan(unittest.TestCase):
    def test_it_is_plain_data_the_page_can_show(self):
        p = vc.plan("candlelight for parents", CLIPS, [], LIBRARY, {}, 30)
        j = json.loads(json.dumps(p))
        self.assertEqual(j["length_s"], 30)
        self.assertEqual(len(j["shots"]), 10)
        self.assertEqual(j["music_id"], "08")
        for s in j["shots"]:
            for k in ("id", "drive_id", "in", "dur", "x", "framed_by", "day", "category"):
                self.assertIn(k, s)


if __name__ == "__main__":
    res = unittest.main(verbosity=2, exit=False).result
    print("PATCH142_GATE_RESULT: %s" % ("PASS" if res.wasSuccessful() else "FAIL"))
    raise SystemExit(0 if res.wasSuccessful() else 1)
