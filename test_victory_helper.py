"""test_victory_helper.py — the helper that writes the sentence for people
who would only ever type "give me a nice video" (Michael, 17 Sep)."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import victory_helper as vh  # noqa: E402

CLIPS = json.load(open(os.path.join(HERE, "victory_source", "VWC26", "clips.json"), encoding="utf-8"))
QUOTES = [{"id": "Q%d" % i, "kind": "quote", "title": "Master on perseverance", "quote": q, "quotable": True,
           "weight": 0.9, "session": "Interviews"}
          for i, q in enumerate(["Never give up, even when it hurts.", "Victory is a family.",
                                 "The belt is not the goal; the person you become is."])]


class FakeClaude:
    answer = ('{"say": "Got it. Here is your sentence.", '
              '"ask": "A 30-second reel for parents of the candlelight ceremony, emotional, slow pace.", '
              '"ideas": ["15 seconds of board breaks for Instagram, fast"]}')

    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)

        class _B:
            text = FakeClaude.answer

        class _M:
            content = [_B()]
        return _M()


class TestBriefing(unittest.TestCase):
    def test_the_briefing_is_built_from_the_library_only(self):
        b = vh.briefing(CLIPS + QUOTES)
        self.assertIn("Night of Champions:", b)
        self.assertIn("Black Belt Testing:", b)
        self.assertIn("Board breaks (", b)
        self.assertIn("Never give up", b)
        self.assertIn("15, 30 or 60 seconds", b)
        self.assertLess(len(b), 12000, "a briefing the model reads on every message stays small")

    def test_ideas_only_name_footage_we_have(self):
        ideas = vh.ideas(CLIPS + QUOTES, seed=0)
        self.assertEqual(len(ideas), vh.IDEAS_N)
        self.assertTrue(any("board breaks" in i for i in ideas), ideas)
        self.assertNotEqual(vh.ideas(CLIPS + QUOTES, seed=0), vh.ideas(CLIPS + QUOTES, seed=1))
        few = [c for c in CLIPS if c["category"] == "Training & seminar"][:4]
        self.assertEqual(vh.ideas(few, seed=0), ["A 15-second reel of the training sessions for new students, fast"])
        self.assertEqual(vh.ideas([], seed=0), ["A 30-second highlights reel of the whole convention"])


class TestChat(unittest.TestCase):
    def test_the_model_gets_the_briefing_and_the_history_and_answers_with_a_sentence(self):
        fake = FakeClaude()
        out = vh.chat([{"role": "user", "text": "give me a nice video"},
                       {"role": "bot", "text": "Who is it for?"},
                       {"role": "user", "text": "parents, the candles"}], CLIPS + QUOTES, client=fake)
        self.assertEqual(out["ask"], "A 30-second reel for parents of the candlelight ceremony, emotional, slow pace.")
        self.assertEqual(out["ideas"], ["15 seconds of board breaks for Instagram, fast"])
        call = fake.calls[0]
        self.assertIn("Night of Champions:", call["system"])
        self.assertIn("Never promise footage that is not listed", call["system"])
        self.assertEqual([m["role"] for m in call["messages"]], ["user", "assistant", "user"])
        self.assertEqual(call["messages"][-1]["content"], "parents, the candles")

    def test_history_is_trimmed_and_always_ends_with_the_person(self):
        fake = FakeClaude()
        msgs = [{"role": "user", "text": "x" * 2000}] * 20 + [{"role": "bot", "text": "?"}]
        vh.chat(msgs, CLIPS, client=fake)
        m = fake.calls[0]["messages"]
        self.assertLessEqual(len(m), vh.MAX_TURNS + 1)
        self.assertEqual(m[-1]["role"], "user")
        self.assertEqual(m[0]["role"], "user")
        self.assertTrue(all(len(x["content"]) <= vh.MAX_CHARS * vh.MAX_TURNS + 20 for x in m))

    def test_a_broken_model_is_a_plain_sorry_not_an_error(self):
        class Broken:
            def __init__(self):
                self.messages = self

            def create(self, **kw):
                raise RuntimeError("no")
        out = vh.chat([{"role": "user", "text": "hi"}], CLIPS, client=Broken())
        self.assertIsNone(out["ask"])
        self.assertIn("Tell me who the video is for", out["say"])

    def test_answers_are_normalised(self):
        self.assertIsNone(vh.parse_answer("no json here"))
        d = vh.parse_answer('Sure! {"say": "ok", "ask": null, "ideas": ["a", "", "b", "c", "d"]}')
        self.assertEqual(d, {"say": "ok", "ask": None, "ideas": ["a", "b", "c"]})
        d = vh.parse_answer('{"say": "ok", "ask": "None"}')
        self.assertIsNone(d["ask"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
