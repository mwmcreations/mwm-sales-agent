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
        pool, by_search, _ = vc.candidates("best moments of the convention", CLIPS, 10, search)
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


class TestPicksLead(unittest.TestCase):
    """16 Sep: "the final result did not include what I asked" — the picks were
    in, but 3 s each, buried in story order. Now they open the reel."""
    WANT = ["VWC26_BREAK_04_break-stance_D0141", "VWC26_BREAK_07_break-partner_D0144",
            "VWC26_CROWD_01_kids-cheering_D0062", "VWC26_COMP_14_sparring-kids-headgear_C0622_REC709"]

    def test_picks_come_first_in_the_order_picked_and_longer(self):
        p = vc.plan("parents proud", CLIPS, self.WANT, LIBRARY, {}, 30)
        ids = [s["id"] for s in p["shots"]]
        self.assertEqual(ids[:4], self.WANT)
        # (the first pick is a 4.2 s clip: it gives what it has)
        self.assertTrue(all(s["dur"] >= 4.0 and s["requested"] for s in p["shots"][:4]))
        self.assertTrue(all(vc.SHOT_SECONDS <= s["dur"] <= 4.5 and not s["requested"] for s in p["shots"][4:]))
        total = sum(s["dur"] for s in p["shots"])
        self.assertTrue(28 <= total <= 31, total)
        self.assertEqual(len(set(ids)), len(ids))

    def test_a_short_reel_keeps_as_many_picks_as_fit(self):
        p = vc.plan("x", CLIPS, self.WANT, LIBRARY, {}, 15)
        self.assertEqual([s["id"] for s in p["shots"]][:2], self.WANT[:2])
        self.assertLessEqual(sum(s["dur"] for s in p["shots"]), 16)

    def test_no_picks_means_the_old_behaviour(self):
        p = vc.plan("x", CLIPS, [], LIBRARY, {}, 30)
        self.assertEqual(len(p["shots"]), 10)
        self.assertTrue(all(s["dur"] == vc.SHOT_SECONDS for s in p["shots"]))


class TestRotation(unittest.TestCase):
    """Michael, after the first live cuts: "the computer tries to go for the
    same ones." Footage a person has already been given goes to the back."""

    def test_recent_clips_are_avoided(self):
        first = [s["id"] for s in vc.pick_shots(CLIPS, 10, seed=1)]
        second = [s["id"] for s in vc.pick_shots(CLIPS, 10, seed=2, avoid=first)]
        self.assertEqual(set(first) & set(second), set())

    def test_two_similar_asks_do_not_make_the_same_reel(self):
        a = [s["id"] for s in vc.pick_shots(CLIPS, 10, seed=101)]
        b = [s["id"] for s in vc.pick_shots(CLIPS, 10, seed=102)]
        self.assertNotEqual(a, b)
        self.assertEqual(len(set(a)), 10)

    def test_the_same_request_is_reproducible(self):
        self.assertEqual(vc.pick_shots(CLIPS, 10, seed=7), vc.pick_shots(CLIPS, 10, seed=7))

    def test_a_requested_clip_is_never_avoided(self):
        want = ["VWC26_CROWD_01_kids-cheering_D0062"]
        shots = vc.pick_shots(CLIPS, 5, requested=want, avoid=want, seed=3)
        self.assertIn(want[0], [s["id"] for s in shots])

    def test_avoiding_everything_still_makes_a_full_reel(self):
        shots = vc.pick_shots(CLIPS, 10, avoid=[c["id"] for c in CLIPS], seed=1)
        self.assertEqual(len(shots), 10)


class TestWordsOnScreen(unittest.TestCase):
    def test_no_words_means_title_and_signoff(self):
        cards = vc.card_plan(30, "kids having fun", [], "")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0][0], "KIDS HAVING FUN")
        self.assertEqual(cards[-1][0], "Victory Martial Arts")
        self.assertEqual(cards[-1][2], 27.0)

    def test_the_persons_sentences_are_spread_across_the_reel(self):
        cards = vc.card_plan(30, "x", ["Four days.", "Every school.", "One floor."], "Enroll today")
        self.assertEqual([c[0] for c in cards], ["Four days.", "Every school.", "One floor.", "Enroll today"])
        self.assertEqual(cards[0][2], 0.3)
        self.assertLess(cards[0][3], cards[1][2])          # head ends before the next starts
        self.assertLess(cards[1][3], cards[2][2])
        self.assertLessEqual(cards[2][3], cards[3][2])     # middle ends before the end card
        self.assertEqual(cards[3][2:4], (27.0, 30.0))

    def test_a_short_reel_with_many_lines_still_fits(self):
        cards = vc.card_plan(15, "x", ["a", "b", "c", "d"], "go")
        for c in cards:
            self.assertLessEqual(c[3], 15.0)
            self.assertLessEqual(c[2], c[3])

    def test_the_plan_carries_the_words(self):
        p = vc.plan("x", CLIPS, [], LIBRARY, {}, 30, lines=["Hello"], cta="Join")
        self.assertEqual(p["lines"], ["Hello"])
        self.assertEqual(p["cta"], "Join")
        self.assertEqual(p["cards"][-1][0], "Join")

    def test_many_cards_in_the_ffmpeg_command(self):
        cmd = vc.final_cmd("f", "b.mp4", "m.wav", "o.mp4", 30.0, ("A", "B"), ("C", "D"), None,
                           cards=[("c0.png", 0.3, 3.5), ("c1.png", 12.0, 15.0), ("c2.png", 27.0, 30.0)])
        joined = " ".join(cmd)
        self.assertEqual(joined.count("-loop 1 -framerate 10 -i"), 3)
        self.assertIn("between(t,12.00,15.00)", joined)
        self.assertIn("[v2]", joined)


class TestTheIndexLeads(unittest.TestCase):
    def test_a_narrow_ask_gets_its_own_footage(self):
        pool, by_search, focus = vc.candidates("candlelight ceremony", CLIPS, 10, search)
        self.assertTrue(by_search)
        self.assertEqual(focus, ("Candlelight ceremony",))
        shots = vc.pick_shots(pool, 10, by_search=True, uncapped=focus)
        self.assertTrue(all("Candlelight" in s["session"] or "candle" in s["id"].lower()
                            for s in shots), [s["id"] for s in shots])

    def test_a_sentence_still_names_its_footage(self):
        """16 Sep self-test #5: "a reel about the candlelight ceremony for our
        parents please" came back as belt presentations. The words that name
        the footage win over the words around them."""
        for ask in ("a reel about the candlelight ceremony for our parents please",
                    "[DEV test] candlelight ceremony for the parents",
                    "Instagram reel, candlelight, emotional"):
            pool, by_search, focus = vc.candidates(ask, CLIPS, 10, search)
            p = vc.plan(ask, pool, [], LIBRARY, {}, 30, by_search=by_search, focus=focus)
            kinds = {s["category"] for s in p["shots"]}
            self.assertEqual(kinds, {"Candlelight ceremony"}, (ask, kinds))

    def test_the_ask_beats_rotation(self):
        """Self-test #11: every candle clip had been used recently, so the
        rotation rule swapped in board breaks. Asked-for footage repeats
        before other footage takes its place."""
        pool, by_search, focus = vc.candidates("candlelight ceremony", CLIPS, 10, search)
        used = [c["id"] for c in CLIPS if c["category"] == "Candlelight ceremony"]
        p = vc.plan("candlelight ceremony", pool, [], LIBRARY, {}, 30, by_search=by_search,
                    focus=focus, avoid=used, seed=2)
        self.assertEqual({s["category"] for s in p["shots"]}, {"Candlelight ceremony"})

    def test_short_clips_are_not_filler(self):
        for seed in range(1, 8):
            p = vc.plan("proud parents", CLIPS, [], LIBRARY, {}, 30, seed=seed)
            for sh in p["shots"]:
                self.assertGreaterEqual(sh["dur"], 3.0, (seed, sh["id"], sh["dur"]))

    def test_a_named_kind_is_not_capped(self):
        """"board breaks", 60 s: all nine board clips, then the rest — not two
        board clips and eighteen of something else."""
        pool, by_search, focus = vc.candidates("board breaks", CLIPS, 20, search)
        self.assertEqual(focus, ("Board breaks",))
        p = vc.plan("board breaks", pool, [], LIBRARY, {}, 60, by_search=by_search, focus=focus)
        boards = sum(1 for c in CLIPS if c["category"] == "Board breaks")
        self.assertEqual(sum(1 for s in p["shots"] if s["category"] == "Board breaks"), boards)
        self.assertEqual(len(p["shots"]), 20)
        p = vc.plan("board breaks", pool, [], LIBRARY, {}, 15, by_search=by_search, focus=focus)
        self.assertTrue(all(s["category"] == "Board breaks" for s in p["shots"]))

    def test_audience_words_steer_softly(self):
        """"parents" alone is who the reel is FOR: crowd and parent reactions
        lead, but the whole convention still shows."""
        pool, by_search, focus = vc.candidates("Instagram reels. Parents. Proud.", CLIPS, 10, search)
        self.assertEqual(focus, ())
        p = vc.plan("Instagram reels. Parents. Proud.", pool, [], LIBRARY, {}, 30, by_search=by_search, focus=focus)
        kinds = [s["category"] for s in p["shots"]]
        self.assertGreaterEqual(kinds.count("Crowd & parent reactions"), 3)
        self.assertGreaterEqual(len(set(kinds)), 4)

    def test_a_named_evening_gets_that_evening(self):
        """Michael, 16 Sep: Night of Champions is one long recording; once it
        is cut into moments, asking for it must bring those moments."""
        self.assertEqual(vc.ask_sessions("a reel from the Night of Champions"), ["Night of Champions"])
        self.assertEqual(vc.ask_sessions("black belt testing, proud parents"),
                         ["Black Belt Testing"])
        self.assertEqual(vc.ask_sessions("candlelight for parents"), [])
        self.assertEqual(vc.ask_sessions("highlights of the Victory Dinner"), ["Victory Dinner"])
        self.assertEqual(vc.ask_sessions("victory for life, emotional"), ["Victory for Life Reception"])
        noc = [c for c in CLIPS if c["session"] == "Night of Champions"]
        self.assertGreaterEqual(len(noc), 100, "the moments cut from the long recordings")
        pool, by_search, focus = vc.candidates("night of champions, epic", CLIPS, 20, search)
        self.assertTrue(by_search)
        self.assertEqual(focus, ("session:Night of Champions",), "the evening's cap lifts; its kinds stay balanced")
        for length in (30, 60):
            p = vc.plan("night of champions, epic", pool, [], LIBRARY, {}, length, by_search=by_search, focus=focus)
            self.assertTrue(all(s["session"] == "Night of Champions" for s in p["shots"]), [s["id"] for s in p["shots"]])
            self.assertGreaterEqual(len({s["category"] for s in p["shots"]}), 3)
        # the other long evening
        pool, by_search, focus = vc.candidates("black belt testing", CLIPS, 10, search)
        p = vc.plan("black belt testing", pool, [], LIBRARY, {}, 30, by_search=by_search, focus=focus)
        self.assertTrue(all(s["session"] == "Black Belt Testing" for s in p["shots"]))
        # a library without those sessions still cuts something
        old = [c for c in CLIPS if c["session"] not in ("Night of Champions", "Black Belt Testing")]
        pool, by_search, focus = vc.candidates("night of champions", old, 10, search)
        self.assertEqual(len(pool), len(old))

    def test_a_long_recording_moment_is_cut_around_its_peak(self):
        c = dict(CLIPS[0], id="X_peak", seconds=12.0, best_in=8.0)
        p = vc.plan("x", [c], ["X_peak"], LIBRARY, {}, 15)
        s = p["shots"][0]
        self.assertEqual(s["dur"], 5.0)
        self.assertEqual(s["in"], 5.5)          # 8 - 5/2
        p = vc.plan("x", [dict(c, best_in=11.5)], ["X_peak"], LIBRARY, {}, 15)
        self.assertAlmostEqual(p["shots"][0]["in"], 12.0 - 5.0 - 0.05, places=2)
        # with a reframe entry the window follows the action but the in-point stays
        rf = {"X_peak": {"duration": 12.0, "windows": [{"t": t, "ax": 0.8 if t >= 5 else 0.2, "energy": 1}
                                                       for t in range(12)]}}
        p = vc.plan("x", [c], ["X_peak"], LIBRARY, rf, 15)
        self.assertEqual(p["shots"][0]["in"], 5.5)
        self.assertEqual(p["shots"][0]["framed_by"], "action")
        self.assertGreater(p["shots"][0]["x"], 0.7)

    def test_ceremony_alone_means_both(self):
        self.assertEqual(vc.ask_categories("the ceremony"), (list(vc.CEREMONIES), False))
        self.assertEqual(vc.ask_categories("belt ceremony"), (["Belt & rank presentation"], False))
        self.assertEqual(vc.ask_categories("best moments"), ([], False))
        self.assertEqual(vc.ask_categories("for the moms"), (["Crowd & parent reactions"], True))

    def test_a_broad_ask_gets_the_whole_convention(self):
        pool, by_search, _ = vc.candidates("best moments", CLIPS, 10, search)
        self.assertFalse(by_search)
        self.assertEqual(len(pool), len(CLIPS))

    def test_no_index_is_not_an_error(self):
        pool, by_search, _ = vc.candidates("anything", CLIPS, 10, None)
        self.assertFalse(by_search)
        self.assertEqual(pool[0]["priority"], "hero")

    def test_a_broken_index_falls_back_quietly(self):
        def boom(q):
            raise RuntimeError("no")
        pool, by_search, _ = vc.candidates("kids", CLIPS, 10, boom)
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

    def test_short_clips_are_topped_up(self):
        """A 2 s clip gives 2 s; the reel still reaches its length."""
        short = [dict(c) for c in CLIPS]
        p = vc.plan("candlelight", short, ["VWC26_BELT_09_judging-panel_D0155"], LIBRARY, {}, 30)
        pick = p["shots"][0]
        self.assertEqual(pick["id"], "VWC26_BELT_09_judging-panel_D0155")
        self.assertLess(pick["dur"], 2.0)
        total = sum(s["dur"] for s in p["shots"])
        self.assertGreaterEqual(total, 28.5)
        self.assertLessEqual(total, 30.0)
        for length in (15, 30, 60):
            p = vc.plan("best moments", CLIPS, [], LIBRARY, {}, length, seed=5)
            total = sum(s["dur"] for s in p["shots"])
            self.assertGreaterEqual(total, length - 1.5, (length, total))
            self.assertLessEqual(total, length, (length, total))

    def test_cards_follow_a_short_body(self):
        cards = [("head.png", 0.3, 3.2), ("mid.png", 12.0, 15.0), ("outro.png", 27.0, 30.0)]
        self.assertEqual(vc.reanchor_cards(cards, 30.0, 28.9),
                         [("head.png", 0.3, 3.2), ("mid.png", 12.0, 15.0), ("outro.png", 25.9, 28.9)])
        self.assertEqual(vc.reanchor_cards(cards, 30.0, 30.0)[2], ("outro.png", 27.0, 30.0))
        self.assertEqual(vc.reanchor_cards(None, 30.0, 28.9), None)

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
        self.assertEqual(head[0], "KIDS' NIGHT FUN")     # numbers dropped; the apostrophe is escaped later, by _esc
        self.assertEqual(vc._esc("a:b 'c' 100%"), "a\\:b \u2019c\u2019 100%%")
        vc._filters_cache[("f", "drawtext")] = True        # pretend this ffmpeg can draw
        cmd = vc.final_cmd("f", "body.mp4", "m.wav", "out.mp4", 29.0, ("x:y", "z"), outro, "/f.ttf")
        vf = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("text='x\\:y'", vf)
        self.assertIn("loudnorm", " ".join(cmd))

    def test_cards_are_overlaid_when_given(self):
        cmd = vc.final_cmd("f", "body.mp4", "m.wav", "out.mp4", 30.0, ("A", "B"), ("C", "D"), None,
                           cards=[("head.png", 0.3, 3.2), ("outro.png", 27.0, 30.0)])
        joined = " ".join(cmd)
        self.assertIn("-loop 1 -framerate 10 -i head.png", joined)
        self.assertIn("overlay=0:0:enable='between(t,0.30,3.20)'", joined)
        self.assertIn("between(t,27.00,30.00)", joined)
        self.assertNotIn("drawtext", joined)

    def test_titles_drop_numbers_and_stay_short(self):
        head, _ = vc.titles_for("A 30-second reel for the Lake Nona page, aimed at parents.")
        self.assertEqual(head[0], "LAKE NONA PARENTS")

    def test_an_ffmpeg_without_drawtext_still_cuts_just_without_titles(self):
        # Homebrew's ffmpeg 8 on the Mini: "No such filter: 'drawtext'" — 14 Sep
        vc._filters_cache[("plainffmpeg", "drawtext")] = False
        cmd = vc.final_cmd("plainffmpeg", "body.mp4", "m.wav", "out.mp4", 29.0, ("A", "B"), ("C", "D"), "/f.ttf")
        self.assertNotIn("drawtext", " ".join(cmd))
        self.assertIn("fade=t=out", " ".join(cmd))

    def test_a_limiter_guards_the_peaks(self):
        """Self-tests #9 and #14 came back at +0.1 and +0.4 dBTP after the AAC
        encode; a limiter after loudnorm keeps 1 dB of headroom."""
        for music in ("m.wav", None):
            cmd = vc.final_cmd("f", "b.mp4", music, "o.mp4", 30.0, ("A", "B"), ("C", "D"), None)
            fc = cmd[cmd.index("-filter_complex") + 1]
            self.assertIn("loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.8:level=false[a]", fc)

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


MOMENTS = json.load(open(os.path.join(HERE, "victory_source", "VWC26", "quote_moments.json"), encoding="utf-8"))
MOM_Q = {"kind": "quote", "id": "VWC26:ROAM_J24-2_full@498",
         "quote": "And for you mom, what was really a true reason why you put these girls into Victory Martial Arts?"}


class TestInterviewMoments(unittest.TestCase):
    """Michael, 16 Sep, on Video #4: he picked the mom's line and previewed it;
    the result did not include it. Now a picked line is a shot, it opens the
    reel, and a picked QUESTION plays the answer."""

    def test_the_index_covers_the_transcripts(self):
        self.assertGreater(len(MOMENTS["moments"]), 150)
        self.assertGreater(len(MOMENTS["quotes"]), 1400)
        for q in MOMENTS["quotes"].values():
            self.assertIn(q["moment"], MOMENTS["moments"])
            m = MOMENTS["moments"][q["moment"]]
            self.assertLess(q["offset"], m["end"] - m["start"])

    def test_a_picked_question_plays_the_answer(self):
        shots, missing = vc.quote_shots([MOM_Q], MOMENTS, lambda f: True)
        self.assertEqual(missing, [])
        self.assertEqual(len(shots), 1)
        s = shots[0]
        self.assertEqual(s["kind"], "speech")
        self.assertEqual(s["file"], "M_ROAM_J24-2_full_0484.mp4")
        self.assertEqual(s["in"], 21.0)              # the answer, not the question
        self.assertGreaterEqual(s["dur"], vc.SPEECH_MIN)
        self.assertLessEqual(s["dur"], vc.SPEECH_MAX)
        self.assertLessEqual(s["in"] + s["dur"], 29.0 + 0.01)   # inside the 29 s piece
        self.assertTrue(s["requested"])
        self.assertIn("mom", s["title"])

    def test_a_statement_starts_where_it_is_said(self):
        shots, _ = vc.quote_shots([{"kind": "quote", "id": "VWC26:POD_J24-02_37min@14", "quote": "x"}],
                                  MOMENTS, lambda f: True)
        self.assertEqual(shots[0]["in"], 8.0)
        self.assertGreaterEqual(shots[0]["dur"], vc.SPEECH_MIN)

    def test_a_colliding_id_still_finds_its_line(self):
        shots, missing = vc.quote_shots([{"kind": "quote", "id": "VWC26:ROAM_J24-2_full@498#2", "quote": "x"}],
                                        MOMENTS, lambda f: True)
        self.assertEqual(len(shots), 1)

    def test_missing_recording_is_named_not_dropped_silently(self):
        shots, missing = vc.quote_shots([MOM_Q, {"kind": "quote", "id": "VWC26:NOPE@1", "quote": "gone"}],
                                        MOMENTS, lambda f: False)
        self.assertEqual(shots, [])
        self.assertEqual(len(missing), 2)
        self.assertIn("mom", missing[0])
        self.assertEqual(missing[1], "gone")

    def test_clips_are_not_quotes(self):
        shots, missing = vc.quote_shots([{"kind": "clip", "id": "VWC26:x"}], MOMENTS, lambda f: True)
        self.assertEqual((shots, missing), ([], []))

    def test_the_interview_opens_the_reel_and_the_picks_follow(self):
        speech, _ = vc.quote_shots([MOM_Q], MOMENTS, lambda f: True)
        p = vc.plan("parents", CLIPS, [CLIPS[3]["id"]], LIBRARY, {}, 30, speech=speech)
        self.assertEqual(p["shots"][0]["kind"], "speech")
        self.assertEqual(p["shots"][1]["id"], CLIPS[3]["id"])
        self.assertEqual(p["shots"][1]["dur"], vc.PICK_SECONDS)
        total = sum(s["dur"] for s in p["shots"])
        self.assertLessEqual(total, 30.5)
        self.assertGreaterEqual(total, 26.0)
        self.assertEqual(p["speech_seconds"], speech[0]["dur"])
        json.dumps(p)

    def test_a_long_interview_is_trimmed_to_the_length(self):
        speech = [{"id": "a", "file": "a.mp4", "kind": "speech", "dur": 12.0, "in": 0, "x": 0.5,
                   "framed_by": "centre", "requested": True}] * 3
        p = vc.plan("x", CLIPS, [], LIBRARY, {}, 15, speech=speech)
        talk = [s for s in p["shots"] if s.get("kind") == "speech"]
        self.assertEqual(len(talk), 1)
        self.assertEqual(talk[0]["dur"], 12.0)
        self.assertLessEqual(sum(s["dur"] for s in p["shots"]), 15.5)

    def test_music_ducks_under_the_talking(self):
        spans = vc.speech_spans([{"kind": "speech", "dur": 8.0}, {"kind": "speech", "dur": 4.0},
                                 {"kind": None, "dur": 3.0}, {"kind": "speech", "dur": 5.0}])
        self.assertEqual(spans, [(0.0, 12.0), (15.0, 20.0)])
        cmd = vc.final_cmd("f", "body.mp4", "m.wav", "out.mp4", 30.0, ("A", "B"), ("C", "D"), None,
                           speech=spans)
        fc = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[0:a]volume='if(between(t,0.00,12.00),1.00,", fc)
        self.assertIn("volume='if(between(t,0.00,12.00),%.2f," % vc.SPEECH_MUSIC, fc)
        self.assertIn(":eval=frame[mus]", fc)
        self.assertIn("loudnorm", fc)
        # without speech the mix is what shipped before
        cmd0 = vc.final_cmd("f", "body.mp4", "m.wav", "out.mp4", 30.0, ("A", "B"), ("C", "D"), None)
        self.assertIn("[0:a]volume=0.25:eval=frame[nat]", cmd0[cmd0.index("-filter_complex") + 1])


if __name__ == "__main__":
    res = unittest.main(verbosity=2, exit=False).result
    print("PATCH142_GATE_RESULT: %s" % ("PASS" if res.wasSuccessful() else "FAIL"))
    raise SystemExit(0 if res.wasSuccessful() else 1)
