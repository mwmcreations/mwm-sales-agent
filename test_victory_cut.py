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
        acts = [s for s in shots if s["category"] != vc.REACTION]
        order = [vc.STORY.index(s["category"]) for s in acts]
        self.assertEqual(order, sorted(order))
        self.assertEqual(shots[-1]["category"], "Candlelight ceremony")
        self.assertNotEqual(shots[0]["category"], vc.REACTION)

    def test_reactions_follow_the_moments_they_react_to(self):
        """Michael's #30 (17 Sep): a 60 s parents reel opened on four seated
        crowds in a row before any belt. A reaction shot never opens, never
        closes, and never sits in a block."""
        pool, by_search, focus = vc.candidates(
            "A 60-second reel for parents of belt presentations and parent reactions, slow pace, emotional.",
            CLIPS, 20, search)
        p = vc.plan("belt presentations and parent reactions, slow, emotional", pool, [], LIBRARY, {}, 60,
                    by_search=by_search, focus=focus, all_clips=CLIPS, seed=4)
        kinds = [s["category"] for s in p["shots"]]
        self.assertIn(vc.REACTION, kinds)
        self.assertNotEqual(kinds[0], vc.REACTION)
        self.assertNotEqual(kinds[-1], vc.REACTION)
        for a, b in zip(kinds, kinds[1:]):
            self.assertFalse(a == vc.REACTION and b == vc.REACTION, kinds)
        # the opener is the strongest belt moment on offer
        belts = [s for s in p["shots"] if s["category"] == "Belt & rank presentation"]
        best = max(vc.PRIORITY.get(s.get("priority"), 0) for s in belts)
        self.assertEqual(vc.PRIORITY.get(p["shots"][0].get("priority"), 0), best)

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

    def test_picks_survive_a_narrow_pool(self):
        """Michael's #25 (17 Sep): "For students. Fast pace. Motivational."
        with nine Night of Champions picks — the ask narrowed the pool to
        index hits and none of the picks were in it, so the cut had none."""
        pool, by_search, focus = vc.candidates("For students. Fast pace. Motivational.", CLIPS, 5, search)
        picks = [c["id"] for c in CLIPS if c["session"] == "Night of Champions"][:9]
        p = vc.plan("For students. Fast pace. Motivational.", pool, picks, LIBRARY, {}, 15,
                    by_search=by_search, focus=focus, all_clips=CLIPS)
        got = [s["id"] for s in p["shots"] if s.get("requested")]
        self.assertGreaterEqual(len(got), 6, got)
        self.assertEqual(got, picks[:len(got)])                 # in the order picked
        self.assertTrue(all(s["dur"] >= vc.PICK_MIN for s in p["shots"] if s.get("requested")))
        self.assertEqual(len(p["no_room"]), 9 - len(got))
        self.assertLessEqual(sum(s["dur"] for s in p["shots"]), 15.0)
        self.assertEqual(p["pace"], 2.0)

    def test_pace_follows_the_ask(self):
        self.assertEqual(vc.pace_seconds("fast pace, motivational"), 2.0)
        self.assertEqual(vc.pace_seconds("a quiet, emotional reel"), 4.0)
        self.assertEqual(vc.pace_seconds("candlelight for parents"), 3.0)
        p = vc.plan("fast and hype", CLIPS, [], LIBRARY, {}, 30, seed=1)
        self.assertGreaterEqual(len(p["shots"]), 13)
        p = vc.plan("slow and quiet", CLIPS, [], LIBRARY, {}, 30, seed=1)
        self.assertLessEqual(len(p["shots"]), 8)

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
        self.assertEqual(cards[0][0], "FOR KIDS")
        self.assertEqual(cards[-1][0], vc.LOGO_CARD)
        self.assertEqual(cards[-1][2], 27.0)

    def test_the_persons_sentences_are_spread_across_the_reel(self):
        cards = vc.card_plan(30, "x", ["Four days.", "Every school.", "One floor."], "Enroll today")
        self.assertEqual([c[0] for c in cards],
                         ["Four days.", "Every school.", "One floor.", "Enroll today", vc.LOGO_CARD])
        self.assertEqual(cards[0][2], 0.3)
        self.assertLess(cards[0][3], cards[1][2])          # head ends before the next starts
        self.assertLess(cards[1][3], cards[2][2])
        self.assertLessEqual(cards[2][3], cards[3][2])     # middle ends before the end card
        self.assertEqual(cards[3][2:4], (24.0, 27.0))      # the call to action…
        self.assertEqual(cards[4][2:4], (27.0, 30.0))      # …then, always, the Victory card

    def test_a_short_reel_with_many_lines_still_fits(self):
        cards = vc.card_plan(15, "x", ["a", "b", "c", "d"], "go")
        for c in cards:
            self.assertLessEqual(c[3], 15.0)
            self.assertLessEqual(c[2], c[3])

    def test_the_plan_carries_the_words(self):
        p = vc.plan("x", CLIPS, [], LIBRARY, {}, 30, lines=["Hello"], cta="Join")
        self.assertEqual(p["lines"], ["Hello"])
        self.assertEqual(p["cta"], "Join")
        self.assertEqual(p["cards"][-2][0], "Join")
        self.assertEqual(p["cards"][-1][0], vc.LOGO_CARD)

    def test_a_card_that_is_a_video_comes_in_by_offset(self):
        """The Mini's ffmpeg keeps every frame only when the card is a real
        video track (17 Sep, video #30 "getting stuck")."""
        cmd = vc.final_cmd("f", "b.mp4", "m.wav", "o.mp4", 30.0, ("A", "B"), ("C", "D"), None,
                           cards=[("card00.mov", 0.3, 3.5), ("card01.mov", 27.0, 30.0)])
        joined = " ".join(cmd)
        self.assertIn("-itsoffset 0.30 -i card00.mov", joined)
        self.assertIn("-itsoffset 27.00 -i card01.mov", joined)
        self.assertNotIn("-loop", joined)
        cv = vc.card_video_cmd("f", "c.png", "c.mov", 3.4)
        self.assertEqual(cv[-4:], ["-c:v", "png", "-pix_fmt", "rgba", "c.mov"][-4:])
        self.assertIn("-t", cv)
        self.assertEqual(cv[cv.index("-t") + 1], "3.40")

    def test_the_picture_and_the_sound_are_cut_in_separate_passes(self):
        """The Mini's ffmpeg 8 loses a third of the picture frames when the
        sound chain shares the process with a card overlay (17 Sep, #30):
        the editor cuts the picture alone, the sound alone, then joins them
        without re-encoding."""
        cmds = vc.final_cmds("f", "b.mp4", "m.wav", "o.mp4", 30.0, ("A", "B"), ("C", "D"), None,
                             "h264_videotoolbox", cards=[("card00.mov", 0.3, 3.5), ("card01.mov", 27.0, 30.0)],
                             workdir="w")
        self.assertEqual(len(cmds), 3)
        pic, snd, mux = [" ".join(c) for c in cmds]
        self.assertIn("-an", pic)
        self.assertNotIn("m.wav", pic)
        self.assertNotIn("loudnorm", pic)
        self.assertIn("-itsoffset 0.30 -i card00.mov -itsoffset 27.00 -i card01.mov", pic)
        self.assertIn("[1:v]format=rgba", pic)          # cards numbered right after the body
        self.assertIn("[2:v]format=rgba", pic)
        self.assertIn("[v1]fade=t=out:st=29.50:d=0.5[v]", pic)
        self.assertTrue(pic.endswith("w/picture.mp4"))
        self.assertIn("-vn", snd)
        self.assertIn("loudnorm", snd)
        self.assertIn("alimiter=limit=0.7", snd)
        self.assertIn("-ar 48000", snd)
        self.assertNotIn("overlay", snd)
        self.assertTrue(snd.endswith("w/sound.m4a"))
        self.assertIn("-i w/picture.mp4 -i w/sound.m4a -map 0:v -map 1:a -c copy -movflags +faststart o.mp4", mux)
        # from the segments, the picture is one continuous stream (no joins to drop frames at)
        seg = vc.final_cmds("f", "b.mp4", "m.wav", "o.mp4", 30.0, ("A", "B"), ("C", "D"), None,
                            "h264_videotoolbox", cards=[("card00.mov", 0.3, 3.5)], workdir="w",
                            segments=["s0.mp4", "s1.mp4", "s2.mp4"])
        pic = " ".join(seg[0])
        self.assertIn("-i s0.mp4 -i s1.mp4 -i s2.mp4 -itsoffset 0.30 -i card00.mov", pic)
        self.assertIn("[0:v]setsar=1[s0];[1:v]setsar=1[s1];[2:v]setsar=1[s2];[s0][s1][s2]concat=n=3:v=1:a=0,fps=30[body];[3:v]format=rgba", pic)
        self.assertIn("[body][c0]overlay=", pic)
        self.assertNotIn("b.mp4", pic)
        self.assertIn("-i b.mp4", " ".join(seg[1]))     # the sound still comes from the joined body
        # a still card would hang the picture pass: that takes the one-pass road
        one = vc.final_cmds("f", "b.mp4", "m.wav", "o.mp4", 30.0, ("A", "B"), ("C", "D"), None,
                            "h264_videotoolbox", cards=[("card00.png", 0.3, 3.5)], workdir="w")
        self.assertEqual(len(one), 1)
        self.assertIn("-loop", " ".join(one[0]))

    def test_many_cards_in_the_ffmpeg_command(self):
        cmd = vc.final_cmd("f", "b.mp4", "m.wav", "o.mp4", 30.0, ("A", "B"), ("C", "D"), None,
                           cards=[("c0.png", 0.3, 3.5), ("c1.png", 12.0, 15.0), ("c2.png", 27.0, 30.0)])
        joined = " ".join(cmd)
        self.assertEqual(joined.count("-loop 1 -framerate 30 -itsoffset"), 3)
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

    def test_hero_footage_leads_inside_a_named_kind(self):
        """The Sunday live-set candle moments are dark and 'standard'; the
        roaming camera's are 'hero'. Asked for candlelight, hero comes first."""
        pool, by_search, focus = vc.candidates("candlelight", CLIPS, 10, search)
        p = vc.plan("candlelight", pool, [], LIBRARY, {}, 30, by_search=by_search, focus=focus, seed=4)
        heroes = [s for s in p["shots"] if s["priority"] == "hero"]
        self.assertGreaterEqual(len(heroes), 8, [(s["id"][:30], s["priority"]) for s in p["shots"]])

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

    def test_a_track_that_fits_beats_one_that_merely_rotates(self):
        """Michael's #30 re-cut: "The Sports" under a slow, emotional parents
        reel, because the one piano track had just been used."""
        ask = "A 60-second reel for parents of belt presentations and parent reactions, slow pace, emotional."
        self.assertEqual(vc.pick_music(LIBRARY, ask)["id"], "08")
        self.assertEqual(vc.pick_music(LIBRARY, ask, exclude=["08"])["id"], "08", "better the same piano again than sports")
        # and an ask with no matching words at all still never gets sports when it says slow
        lib = {"tracks": [t for t in LIBRARY["tracks"] if t["id"] in ("01", "04")]}
        self.assertEqual(vc.pick_music(lib, "something slow and quiet")["id"], "04")

    def test_an_empty_library_is_no_music_not_a_crash(self):
        self.assertIsNone(vc.pick_music({"tracks": []}, "kids"))
        p = vc.plan("kids", CLIPS, [], {"tracks": []}, {}, 15)
        self.assertIsNone(p["music_id"])


class TestTheAskNamesAThing(unittest.TestCase):
    """Rehearsal #39 (21 Sep): "the candlelight ceremony, emotional" came out
    as one candle shot and three stage line-ups from the same category. A
    clip whose own name carries the ask's word goes first."""

    def test_candles_beat_a_line_up_in_the_same_category(self):
        a = {"id": "VWC26_BBL_060_instructors-cheer-with-arms-raised-on-stage", "title": "Instructors cheer with arms raised on stage",
             "category": "Candlelight ceremony", "session": "BBT", "day": 4, "priority": "high", "weight": 10, "seconds": 12}
        b = {"id": "VWC26_CANDLE_02_masters-holding-candles_D0217", "title": "Masters holding candles",
             "category": "Candlelight ceremony", "session": "BBT", "day": 4, "priority": "standard", "weight": 10, "seconds": 12}
        stems = vc.named_words("A video for parents of the candlelight ceremony, emotional, slow pace.")
        self.assertIn("candl", stems)
        self.assertNotIn("cerem", stems)          # a word every ceremony clip carries says nothing
        self.assertNotIn("paren", stems)          # audience words are handled elsewhere
        got = vc.pick_shots([a, b], 1, by_search=True, stems=stems)
        self.assertEqual(got[0]["id"], b["id"])
        got = vc.pick_shots([a, b], 1, by_search=False, stems=stems)
        self.assertEqual(got[0]["id"], b["id"])
        # without a named thing, the stronger clip leads as before
        self.assertEqual(vc.pick_shots([a, b], 1, by_search=True)[0]["id"], a["id"])
        # and rotation never holds back the clip that carries the ask's word
        got = vc.pick_shots([a, b], 1, by_search=True, stems=stems, avoid=[b["id"]])
        self.assertEqual(got[0]["id"], b["id"])

    def test_kind_words_do_not_boost(self):
        # "reactions" names a kind of moment, not a thing in a picture:
        # the category logic owns it (the #30 weave would otherwise drown in reactions)
        self.assertEqual(vc.named_words("belt presentations and parent reactions, slow, emotional"), set())
        self.assertEqual(vc.named_words("15 seconds of board breaks, fast, for students"), {"board", "break"})


class TestSteadyShots(unittest.TestCase):
    """Michael, 17 Sep, on #30: "camera shaky movements where the cameraman
    is still trying to find the shot". The quality pass measures every
    library file; the editor keeps its shots inside the steady stretches."""

    def test_the_in_point_moves_into_a_steady_stretch(self):
        stable = [[0.0, 4.0], [8.0, 5.0]]         # BBT_055: steady 0-4 s, hunting 4-8, steady 8-13
        self.assertEqual(vc.steady_in(stable, 6.0, 4.1), (8.0, True))      # off the hunt, into the next stretch
        self.assertEqual(vc.steady_in(stable, 1.0, 3.0), (1.0, True))      # already steady: untouched
        self.assertEqual(vc.steady_in(stable, 9.5, 4.1)[0], 8.9)           # clamped so the whole shot fits
        self.assertEqual(vc.steady_in(stable, 6.0, 6.0), (6.0, False))     # nothing long enough: flagged
        self.assertEqual(vc.steady_in(None, 6.0, 4.0), (6.0, True))        # unmeasured: trusted
        self.assertEqual(vc.steady_in([], 6.0, 4.0), (6.0, False))         # measured, nothing steady
        # a smooth follow (passable) is used when nothing is perfectly still
        self.assertEqual(vc.steady_in([], 6.0, 4.0, passable=[[2.0, 6.0]]), (4.0, True))
        shake = [[0.1, 0.2], [0.2, 0.1], [2.0, 5.0], [2.2, 6.0], [9.0, 9.0], [0.3, 0.3], [0.2, 0.2]]
        self.assertEqual(vc.windows_from_shake(shake, 7.0), [[0.0, 2.0], [5.0, 2.0]])
        self.assertEqual(vc.windows_from_shake(shake, 7.0, vc.PASSABLE), [[0.0, 4.0], [5.0, 2.0]])

    def test_a_shot_lands_in_the_steady_stretch_and_a_shaky_clip_goes_last(self):
        c = dict(CLIPS[0], id="X_shake", seconds=12.0, best_in=8.0, stable=[[0.0, 5.5], [8.5, 3.5]])
        p = vc.plan("x", [c], ["X_shake"], LIBRARY, {}, 15)
        s = p["shots"][0]
        self.assertEqual(s["dur"], 5.0)
        self.assertEqual(s["in"], 0.5, "the 5 s shot only fits the first steady stretch (as late as it can)")
        self.assertNotEqual(s["framed_by"], "shaky")
        c2 = dict(c, id="X_allshake", stable=[[3.0, 1.0]])
        p = vc.plan("x", [c2], ["X_allshake"], LIBRARY, {}, 15)
        self.assertEqual(p["shots"][0]["framed_by"], "shaky")
        # the machine's own choice: steady clips before an all-shaky one of the same kind
        a = dict(CLIPS[0], id="S1", stable=[[0.0, 10.0]], priority="standard")
        b = dict(CLIPS[0], id="S2", stable=[[2.0, 1.5]], priority="hero")
        self.assertEqual([x["id"] for x in vc.pick_shots([b, a], 1)], ["S1"])


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
        self.assertEqual(head[0], "FOR KIDS")            # who it is for; numbers never reach a card
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
        self.assertIn("-loop 1 -framerate 30 -itsoffset 0.30 -t 3.10 -i head.png", joined)
        self.assertIn("eof_action=pass", joined)
        self.assertIn("overlay=0:0:eof_action=pass:enable='between(t,0.30,3.20)'", joined)
        self.assertIn("between(t,27.00,30.00)", joined)
        self.assertNotIn("drawtext", joined)

    def test_titles_drop_numbers_and_stay_short(self):
        head, _ = vc.titles_for("A 30-second reel for the Lake Nona page, aimed at parents.")
        self.assertEqual(head[0], "LAKE NONA")            # the name they wrote with capitals

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
            self.assertIn("loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.7:level=false[a]", fc)

    def test_probe_reads_ffmpegs_own_banner(self):
        banner = ("Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'x.mp4':\n  Duration: 00:00:12.01, start: 0.000000, bitrate: 6183 kb/s\n"
                  "  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive), "
                  "1920x1080 [SAR 1:1 DAR 16:9], 5698 kb/s, 24 fps, 24 tbr, 12288 tbn (default)\n"
                  "  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6D703461), 48000 Hz, stereo, fltp, 317 kb/s (default)\n"
                  "  Stream #0:2[0x3](und): Data: none (tmcd / 0x64636D74)\n")
        self.assertEqual(vc.parse_ffmpeg_info(banner), (1920, 1080, 12.01))
        self.assertIsNone(vc.parse_ffmpeg_info("nothing here"))

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


class TestWhatTheEditorUnderstood(unittest.TestCase):
    """Michael, 17 Sep: "I want a video for students. This is gonna be an
    Instagram reel, 15 seconds, very fast pace. You can use footage from the
    Night of Champions and some board breaking shots." — one sentence, no
    clips picked. The editor must read all of it, and say what it read."""
    ASK = ("I want a video for students. This is gonna be an Instagram reel, 15 seconds, "
           "very fast pace. You can use footage from the Night of Champions and some board breaking shots.")

    def test_a_length_in_the_sentence(self):
        self.assertEqual(vc.length_from("15 seconds, fast"), 15)
        # 15 s is the only length offered in this phase (Michael, 18 Sep): every ask lands on it
        self.assertEqual(vc.length_from("a 30s reel"), 15)
        self.assertEqual(vc.length_from("about one minute"), 15)
        self.assertEqual(vc.length_from("half a minute"), 15)
        self.assertEqual(vc.length_from("twenty seconds"), None)     # not a word we snap
        self.assertEqual(vc.length_from("20 seconds"), 15)
        self.assertEqual(vc.length_from("45 sec"), 15)
        self.assertEqual(vc.length_from("proud parents"), None)
        self.assertEqual(vc.length_from(""), None)

    def test_the_brief_line(self):
        b = vc.brief_for(self.ASK, 30)
        self.assertEqual(b["length"], 15, "the sentence beats the radio button")
        self.assertLess(b["pace"], 3.0)
        self.assertEqual(b["sessions"], ["Night of Champions"])
        self.assertEqual(b["kinds"], ["Board breaks"])
        self.assertEqual(b["audience"], ["students"])
        self.assertIn("fast", b["feel"])
        self.assertEqual(b["text"], "15 s \u00b7 fast pace \u00b7 Night of Champions, board breaks \u00b7 for students \u00b7 feel: fast")
        b = vc.brief_for("something nice for the schools", 60)
        self.assertEqual(b["length"], 15)          # only 15 s is on offer while the editor learns
        self.assertIn("the whole convention", b["text"])
        self.assertIn("for schools", b["text"])
        b = vc.brief_for("", None)
        self.assertEqual(b["length"], 15)          # the standard of this phase

    def test_the_card_says_what_was_understood_not_the_first_three_words(self):
        """#26 opened on "I STUDENTS THIS"."""
        self.assertEqual(vc.titles_for(self.ASK)[0][0], "NIGHT OF CHAMPIONS")
        self.assertEqual(vc.titles_for("For students. Fast pace. Motivational.")[0][0], "FOR STUDENTS")
        self.assertEqual(vc.titles_for("some board breaking, quick")[0][0], "BOARD BREAKS")
        self.assertEqual(vc.titles_for("Reel for Victory Winter Garden. Kids. Fun.")[0][0], "VICTORY WINTER GARDEN")
        self.assertEqual(vc.titles_for("something nice and quick")[0][0], "CONVENTION 2026")

    def test_the_sound_is_48k_and_limited_after_the_resample(self):
        """#26 came back at 96 kHz with a true peak of +0.4 dBTP: loudnorm
        works at 192 kHz and the AAC encoder overshot the limiter."""
        cmd = vc.final_cmd("f", "body.mp4", "m.wav", "out.mp4", 15.0, ("A", "B"), ("C", "D"), None)
        fc = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.7", fc)
        self.assertEqual(cmd[cmd.index("-ar") + 1], "48000")
        cmd = vc.final_cmd("f", "body.mp4", None, "out.mp4", 15.0, ("A", "B"), ("C", "D"), None)
        self.assertIn("aresample=48000,alimiter", cmd[cmd.index("-filter_complex") + 1])

    def test_one_scene_is_one_shot(self):
        """#26's cut had three "students in red line up on stage" moments from
        four minutes of the same recording, back to back. Two moments from one
        long recording within SCENE_GAP are one scene: only one goes in while
        anything else is left."""
        import itertools
        by = {c["id"]: c for c in CLIPS}
        for ask in (self.ASK, "night of champions, epic", "black belt testing"):
            for length in (15, 30):
                for seed in range(1, 5):
                    pool, by_search, focus = vc.candidates(ask, CLIPS, 20, search)
                    p = vc.plan(ask, pool, [], LIBRARY, {}, length, by_search=by_search, focus=focus,
                                all_clips=CLIPS, seed=seed)
                    shots = [by[s["id"]] for s in p["shots"]]
                    for a, b in itertools.combinations(shots, 2):
                        if a.get("long_src") and a["long_src"] == b.get("long_src"):
                            self.assertGreaterEqual(abs(a["long_start"] - b["long_start"]), vc.SCENE_GAP,
                                                    (ask[:30], length, seed, a["id"], b["id"]))

    def test_the_sentence_cuts_the_evening_and_the_boards(self):
        pool, by_search, focus = vc.candidates(self.ASK, CLIPS, 10, search)
        self.assertEqual(focus, ("session:Night of Champions",))
        p = vc.plan(self.ASK, pool, [], LIBRARY, {}, 15, by_search=by_search, focus=focus,
                    all_clips=CLIPS, seed=3)
        kinds = [s["category"] for s in p["shots"]]
        sessions = {s["session"] for s in p["shots"]}
        self.assertIn("Board breaks", kinds, kinds)
        self.assertIn("Night of Champions", sessions, sessions)
        self.assertTrue(all(s["session"] == "Night of Champions" or s["category"] == "Board breaks"
                            for s in p["shots"]), [(s["session"], s["category"]) for s in p["shots"]])
        self.assertLessEqual(max(s["dur"] for s in p["shots"]), 2.5, "fast pace")


if __name__ == "__main__":
    res = unittest.main(verbosity=2, exit=False).result
    print("PATCH142_GATE_RESULT: %s" % ("PASS" if res.wasSuccessful() else "FAIL"))
    raise SystemExit(0 if res.wasSuccessful() else 1)
