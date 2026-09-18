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
        self.assertIn("15 or 30 seconds", b)          # 60 s is not offered for now (Michael, 18 Sep)
        self.assertNotIn("15, 30 or 60", b)
        self.assertLess(len(b), 12000, "a briefing the model reads on every message stays small")

    def test_ideas_only_name_footage_we_have(self):
        ideas = vh.ideas(CLIPS + QUOTES, seed=0)
        self.assertEqual(len(ideas), vh.IDEAS_N)
        self.assertTrue(any("board breaks" in i for i in ideas), ideas)
        self.assertNotEqual(vh.ideas(CLIPS + QUOTES, seed=0), vh.ideas(CLIPS + QUOTES, seed=1))
        few = [c for c in CLIPS if c["category"] == "Training & seminar"][:4]
        self.assertEqual(vh.ideas(few, seed=0), ["A 15-second reel of the training sessions for new students, fast"])
        self.assertEqual(vh.ideas([], seed=0), ["A 30-second highlights reel of the whole convention"])


class TestMemory(unittest.TestCase):
    """Michael, 17 Sep: "make sure Victory Intelligence is for real intelligent
    and has memory" — persistent, per person, in their words."""
    PERSON = {"name": "Michael", "school": "Lake Nona",
              "notes": ["posts to Instagram and Facebook", "school: Victory Lake Nona"],
              "history": [{"id": 27, "ask": "A 30-second video for parents of the candlelight ceremony, emotional.",
                           "length": 30, "state": "approved", "when": "Sep 17, 12:40 PM",
                           "music": "The Sports", "kinds": ["Candlelight ceremony"], "feedback": "loved it"}]}

    def test_the_model_is_told_who_it_is_talking_to(self):
        fake = FakeClaude()
        vh.chat([{"role": "user", "text": "something new"}], CLIPS, client=fake, person=self.PERSON)
        sysm = fake.calls[0]["system"]
        self.assertIn("ABOUT THIS PERSON (Michael, Lake Nona)", sysm)
        self.assertIn("posts to Instagram and Facebook", sysm)
        self.assertIn("candlelight ceremony", sysm)
        self.assertIn("music: The Sports", sysm)
        self.assertIn('they said: "loved it"', sysm)
        self.assertIn('"remember"', sysm)
        # and a first visit says so, rather than pretending
        fake = FakeClaude()
        vh.chat([{"role": "user", "text": "hi"}], CLIPS, client=fake, person=None)
        self.assertIn("first visit; nothing remembered yet", fake.calls[0]["system"])

    def test_the_greeting_knows_a_returning_person(self):
        g = vh.greeting("Michael", self.PERSON)
        self.assertTrue(g.startswith("Hi, Michael. Last time I made you: A 30-second video for parents"), g)
        self.assertIn("you approved it", g)
        g = vh.greeting("Michael", {"notes": ["posts to Instagram"], "history": []})
        self.assertIn("I remember a few things (posts to Instagram)", g)
        g = vh.greeting("Michael", None)
        self.assertIn("What are we making today?", g)
        self.assertTrue(vh.greeting("", None).startswith("Hi. "))


class TestThePlaybook(unittest.TestCase):
    def test_the_model_is_briefed_on_needs_not_shot_lists(self):
        fake = FakeClaude()
        vh.chat([{"role": "user", "text": "help me bring people to a free class"}], CLIPS, client=fake)
        sysm = fake.calls[0]["system"]
        for phrase in ("WHAT SOLVES WHAT", "free or trial class", "An event", "Keep parents motivated",
                       "Sell gear", "Victory Martial Arts card", "Never invent a date",
                       "PREPARING AN EVENT VIDEO", "in ONE friendly message", "Today is ",
                       "WHEN THEY ASK FOR ADVICE OR A PLAN", '"plan": [{"title"',
                       "A plain request for a video", "Never a plan without videos in it"):
            self.assertIn(phrase, sysm)
        import re as _re
        self.assertRegex(vh.today_text(), r"^[A-Z][a-z]+day, [A-Z][a-z]+ \d{1,2}, 20\d\d$")

    def test_our_earlier_turns_go_back_as_answers(self):
        """A prose turn of ours in the history taught the model to answer in
        prose: every turn after the first failed (Michael's phone, 17 Sep)."""
        fake = FakeClaude()
        vh.chat([{"role": "user", "text": "you choose"},
                 {"role": "bot", "text": "Training moments, fast. [proposed: A 15-second reel of training, fast.]"},
                 {"role": "user", "text": "a video for a free class"}], CLIPS, client=fake)
        m = fake.calls[0]["messages"]
        self.assertEqual(m[1]["role"], "assistant")
        d = json.loads(m[1]["content"])
        self.assertEqual(d, {"say": "Training moments, fast.", "ask": "A 15-second reel of training, fast."})
        self.assertEqual(vh.as_answer('{"say": "kept"}'), '{"say": "kept"}')
        self.assertIn("ALWAYS answer with ONE JSON object", fake.calls[0]["system"])

    def test_failures_are_kept_for_mwm_to_read(self):
        class Prose:
            def __init__(self):
                self.messages = self

            def create(self, **kw):
                class _B:
                    text = "Sure! Who is it for?"

                class _M:
                    content = [_B()]
                return _M()
        del vh.LAST_ERRORS[:]
        vh.chat([{"role": "user", "text": "hi"}], CLIPS, client=Prose())
        self.assertEqual(len(vh.LAST_ERRORS), 1)
        self.assertIn("unusable answer", vh.LAST_ERRORS[0][1])


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
        self.assertIn("You ARE Victory Intelligence", call["system"])
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
        self.assertEqual(d, {"say": "ok", "ask": None, "ideas": ["a", "b", "c"], "lines": [], "cta": "",
                             "plan": [], "remember": "", "forget": ""})
        d = vh.parse_answer('{"say": "Here is the plan.", "ask": null, "plan": [' +
                            '{"title": "Show parents the progress", "why": "They stay when they see it.", ' +
                            '"ask": "A 30-second reel for parents of belt presentations, emotional, slow pace.", ' +
                            '"lines": ["Every class adds up"], "cta": "Victory Lake Nona"}, ' +
                            '{"title": "Call the quiet families", "why": "Two missed weeks is the moment.", "ask": null}, ' +
                            '{"title": ""}, "junk"]}')
        self.assertEqual(len(d["plan"]), 2)
        self.assertEqual(d["plan"][0]["ask"], "A 30-second reel for parents of belt presentations, emotional, slow pace.")
        self.assertEqual(d["plan"][0]["lines"], ["Every class adds up"])
        self.assertIsNone(d["plan"][1]["ask"])
        d = vh.parse_answer('{"say": "Noted.", "ask": null, "remember": "posts to Instagram", "forget": "null"}')
        self.assertEqual((d["remember"], d["forget"]), ("posts to Instagram", ""))
        d = vh.parse_answer('{"say": "Done.", "ask": null, "forget": "*"}')
        self.assertEqual(d["forget"], "*")
        # cut off by the token limit: what is there is still an answer
        d = vh.parse_answer('{"say": "Since you post to Instagram, 15 seconds.", "ask": "A 15-second reel for parents, fast", "ideas": ["A 30-second')
        self.assertEqual((d["say"], d["ask"]), ("Since you post to Instagram, 15 seconds.", "A 15-second reel for parents, fast"))
        d = vh.parse_answer('{"say": "ok", "ask": "x", "lines": ["One", " ", "Two", "Three", "Four", "Five"], "cta": "Enroll today"}')
        self.assertEqual((d["lines"], d["cta"]), (["One", "Two", "Three", "Four"], "Enroll today"))
        d = vh.parse_answer('{"say": "ok", "ask": "None"}')
        self.assertIsNone(d["ask"])
        # a real line break inside a string, and a stray quote: still an answer
        d = vh.parse_answer('{"say": "Great.\nHere it is.", "ask": "A 15-second reel, fast", "ideas": []}')
        self.assertEqual(d["ask"], "A 15-second reel, fast")
        d = vh.parse_answer('{"say": "Here is "the" one", "ask": "A 15-second reel, fast", "ideas": ["a", "b"]}')
        self.assertEqual((d["ask"], d["ideas"]), ("A 15-second reel, fast", ["a", "b"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestRevise(unittest.TestCase):
    """The change typed on a finished cut becomes the brief for the next one."""

    def test_the_change_is_folded_into_a_new_brief(self):
        class Fake:
            def __init__(self):
                self.messages = self
                self.calls = []

            def create(self, **kw):
                self.calls.append(kw)

                class B:
                    text = ('{"ask": "15 seconds of board breaks and the demo team on stage in red, fast.", '
                            '"search": "demo team red uniforms", "lines": ["Break through"], "cta": "Join us", '
                            '"say": "Adding the demo team."}')

                class M:
                    content = [B()]
                return M()
        f = Fake()
        out = vh.revise("15 seconds of board breaks, fast", "15 s · fast · board breaks",
                        [{"title": "Board strike", "category": "Board breaks"}], [], "",
                        "use the demo team on stage in the red uniforms", [], client=f)
        self.assertIn("demo team", out["ask"])
        self.assertEqual(out["search"], "demo team red uniforms")
        self.assertEqual(out["lines"], ["Break through"])
        prompt = f.calls[0]["messages"][0]["content"]
        self.assertIn("use the demo team on stage", prompt)
        self.assertIn("Board strike", prompt)

    def test_when_the_model_fails_the_change_is_stapled_on(self):
        class Broken:
            def __init__(self):
                self.messages = self

            def create(self, **kw):
                raise RuntimeError("down")
        out = vh.revise("15 seconds of board breaks, fast", "", [], [], "", "slower", [], client=Broken())
        self.assertIn("board breaks", out["ask"])
        self.assertIn("slower", out["ask"])
        self.assertEqual(out["search"], "slower")


