"""test_victory_index.py — Phase 1 parity: the Python port must rank exactly
like the JavaScript the client was shown.

The fixtures in victory_fixtures/ were taken from the shipped demo itself:

  demo_records.json  the 1,873 records lifted out of START_HERE__VICTORY_DEMO.html
  demo_scorer.js     the scorer, verbatim, from the same file
  demo_queries.json  40 queries chosen to hit peak, speech, synonyms, the
                     word-boundary traps, empty input and the fallback path
  demo_ranking.json  what that JavaScript returned for those queries, in order

So this is not a test of what I think the ranking should be. It is a test
against the artefact that already went in front of Victory. If it fails, the
port is wrong.

The fixtures are also the only copy of the demo corpus outside a 45.8 MB HTML
file, which is a second reason to keep them in the repo.
"""
import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import victory_index as vi

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "victory_fixtures")


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


RECORDS = _load("demo_records.json")
RANKING = _load("demo_ranking.json")
QUERIES = _load("demo_queries.json")

# The scorer reads ten fields. 'ord' is the record's position in the demo's
# DATA array and stands in for an id, so parity is asserted on identity rather
# than on titles that repeat across a podcast set.
CORPUS = [{"id": r["ord"], "ord": r["ord"], "k": r.get("k"), "t": r.get("t"),
           "cat": r.get("cat"), "ses": r.get("ses"), "s": r.get("s"),
           "w": r.get("w"), "qb": r.get("qb")} for r in RECORDS]


class TestFixtures(unittest.TestCase):
    """The fixtures themselves have to be what I claim they are."""

    def test_record_count(self):
        self.assertEqual(len(RECORDS), 1873)

    def test_kind_split(self):
        clips = [r for r in RECORDS if r.get("k") == "clip"]
        quotes = [r for r in RECORDS if r.get("k") == "quote"]
        self.assertEqual(len(clips), 111)
        self.assertEqual(len(quotes), 1762)

    def test_every_query_has_a_recorded_answer(self):
        for q in QUERIES:
            self.assertIn(q, RANKING, "no recorded JS answer for %r" % (q,))

    def test_no_images_in_fixture(self):
        # base64 thumbnails are what made the demo 45.8 MB; they must not have
        # followed the records into the repo.
        self.assertFalse(any("img" in r for r in RECORDS))


class TestNorm(unittest.TestCase):
    def test_lowercases_and_strips_punctuation(self):
        self.assertEqual(vi.norm("Night of CHAMPIONS!"), "night of champions")

    def test_keeps_apostrophes(self):
        self.assertEqual(vi.norm("didn't quit"), "didn't quit")

    def test_collapses_whitespace(self):
        self.assertEqual(vi.norm("  a   b  "), "a b")

    def test_none_is_empty(self):
        self.assertEqual(vi.norm(None), "")


class TestExpand(unittest.TestCase):
    def test_literal_terms_weigh_one(self):
        self.assertEqual(vi.expand("candlelight")["candlelight"], 1.0)

    def test_stopwords_dropped(self):
        self.assertNotIn("the", vi.expand("the belt"))

    def test_synonyms_weigh_less(self):
        terms = vi.expand("iconic")
        self.assertEqual(terms["iconic"], 1.0)
        self.assertAlmostEqual(terms["candlelight"], 0.62)

    def test_multiword_key_fires_on_raw_query(self):
        self.assertIn("presentation", vi.expand("black belt"))

    def test_synonym_never_overwrites_a_typed_term(self):
        # 'belt' is typed AND is a synonym of 'black belt'; typed must win.
        self.assertEqual(vi.expand("black belt")["belt"], 1.0)

    def test_empty_query_expands_to_nothing(self):
        self.assertEqual(vi.expand(""), {})
        self.assertEqual(vi.expand("the a an of"), {})


class TestFieldHit(unittest.TestCase):
    def test_whole_word_is_full_credit(self):
        self.assertEqual(vi.field_hit(" a candle b ", "candle"), 1.0)

    def test_word_start_is_partial_credit_when_long_enough(self):
        self.assertEqual(vi.field_hit(" candlelight ", "candle"), 0.75)

    def test_short_term_does_not_prefix_match(self):
        # this is the 'bo' in 'board' problem that turned 9 results into 98
        self.assertEqual(vi.field_hit(" board ", "bo"), 0.0)

    def test_no_mid_word_matching(self):
        self.assertEqual(vi.field_hit(" about ", "bo"), 0.0)


class TestPeakSpeech(unittest.TestCase):
    def test_peak_detected(self):
        self.assertTrue(vi.PEAK.search("the best moments"))

    def test_speech_detected(self):
        self.assertTrue(vi.SPEECH.search("on perseverance"))

    def test_peak_suppresses_speech(self):
        rows, peak, speech, fb = vi.search_corpus("the best story", CORPUS)
        self.assertTrue(peak)
        self.assertFalse(speech, "peak must win over speech")


class TestParity(unittest.TestCase):
    """The whole point of the file."""

    def _js(self, q):
        return RANKING[q]

    def test_result_counts_match(self):
        bad = []
        for q in QUERIES:
            rows, _, _, _ = vi.search_corpus(q, CORPUS)
            if len(rows) != self._js(q)["found"]:
                bad.append((q, len(rows), self._js(q)["found"]))
        self.assertFalse(bad, "count mismatch (query, py, js): %r" % (bad,))

    def test_ordering_matches(self):
        bad = []
        for q in QUERIES:
            rows, _, _, _ = vi.search_corpus(q, CORPUS)
            mine = [r["ord"] for r in rows[:12]]
            theirs = self._js(q)["top"]
            if mine != theirs:
                bad.append((q, mine, theirs))
        self.assertFalse(bad, "ranking mismatch: %r" % (bad[:3],))

    def test_peak_flag_matches(self):
        for q in QUERIES:
            _, peak, _, _ = vi.search_corpus(q, CORPUS)
            self.assertEqual(peak, self._js(q)["peak"], "peak differs for %r" % (q,))

    def test_speech_flag_matches(self):
        for q in QUERIES:
            _, _, speech, _ = vi.search_corpus(q, CORPUS)
            self.assertEqual(speech, self._js(q)["speech"], "speech differs for %r" % (q,))

    def test_fallback_flag_matches(self):
        for q in QUERIES:
            _, _, _, fb = vi.search_corpus(q, CORPUS)
            self.assertEqual(fb, self._js(q)["fallback"], "fallback differs for %r" % (q,))

    def _above_zero(self, q):
        rows, peak, speech, _ = vi.search_corpus(q, CORPUS)
        terms = vi.expand(q)
        return sum(1 for r in CORPUS if vi.score(r, terms, peak, speech) > 0), len(rows)

    def test_honesty_floor_cuts_a_generous_query_hard(self):
        # Synonym expansion is generous on purpose. Without the floor this
        # query would report 363 moments found when 43 are actually in reach
        # of the best one — and 'interview testimonial' would report all 1,762.
        above, kept = self._above_zero("what did they say about confidence")
        self.assertEqual(above, 363)
        self.assertEqual(kept, 43)
        self.assertEqual(kept, self._js("what did they say about confidence")["found"])

        above, kept = self._above_zero("interview testimonial")
        self.assertEqual(above, 1762)
        self.assertEqual(kept, 665)

    def test_floor_is_a_floor_not_a_cap(self):
        # A tight query must NOT be trimmed: every candlelight record is a
        # genuine answer, so all 34 survive. A floor that cut here would be
        # hiding real results, which is the opposite failure.
        above, kept = self._above_zero("candlelight")
        self.assertEqual(above, kept, "the floor must not trim a tight query")
        self.assertEqual(kept, self._js("candlelight")["found"])

    def test_floor_bites_on_most_real_queries(self):
        cut = 0
        for q in QUERIES:
            if not q.strip() or self._js(q)["fallback"]:
                continue
            above, kept = self._above_zero(q)
            if kept < above:
                cut += 1
        self.assertGreaterEqual(cut, 25, "floor is barely engaging — check 0.42")


class TestSchema(unittest.TestCase):
    """Event-agnostic is the whole reason this module exists."""

    def test_every_table_is_declared(self):
        ddl = " ".join(vi.DDL)
        for t in ("vi_event", "vi_session", "vi_card_range", "vi_record"):
            self.assertIn("CREATE TABLE IF NOT EXISTS %s" % t, ddl)

    def test_records_carry_an_event_key(self):
        rec = [d for d in vi.DDL if "vi_record" in d][0]
        self.assertIn("event_key", rec)
        self.assertIn("REFERENCES vi_event(event_key)", rec)

    def test_card_ranges_are_rows_not_code(self):
        # build_index.py hardcoded these in a Python list; that is exactly what
        # stopped the demo from ever holding a second event.
        rng = [d for d in vi.DDL if "vi_card_range" in d][0]
        for col in ("camera", "card", "id_kind", "lo", "hi"):
            self.assertIn(col, rng)

    def test_no_base64_column_anywhere(self):
        ddl = " ".join(vi.DDL).lower()
        self.assertNotIn("base64", ddl)
        self.assertIn("drive_id", ddl)
        self.assertIn("thumb", ddl)

    def test_corpus_columns_are_only_what_the_scorer_reads(self):
        cols = [c.strip() for c in vi.CORPUS_COLS.split(",")]
        self.assertEqual(len(cols), 10)
        for c in ("title", "category", "session", "blob", "weight", "quotable"):
            self.assertIn(c, cols)
        # the expensive fields must NOT be resident in memory
        for c in ("thumb", "media", "quote", "topics"):
            self.assertNotIn(c, cols)


class TestNeverRaises(unittest.TestCase):
    """Same contract as pg_store: this module cannot take production down."""

    def test_search_with_no_corpus_is_safe(self):
        vi.set_corpus([])
        out = vi.search("candlelight")
        self.assertTrue(out["ok"])
        self.assertEqual(out["found"], 0)

    def test_search_handles_none_query(self):
        vi.set_corpus(CORPUS)
        out = vi.search(None)
        self.assertTrue(out["ok"])

    def test_weird_input_does_not_explode(self):
        vi.set_corpus(CORPUS)
        for q in ["%%%", "\\", "'; DROP TABLE vi_record; --", " ", "?" * 500]:
            out = vi.search(q)
            self.assertTrue(out["ok"], "failed on %r" % (q,))

    def test_set_corpus_roundtrip(self):
        vi.set_corpus(CORPUS)
        self.assertEqual(vi.corpus_size(), 1873)


if __name__ == "__main__":
    unittest.main(verbosity=2)
