"""test_victory_ingest.py — the database path must not change the ranking.

test_victory_index.py proves the Python scorer matches the demo's JavaScript.
This file proves the other half: that the records arriving from
victory_source/ are the same records the demo scored, in the same order, so
the ranking survives the move into Postgres.

It exercises build_rows() only — no database required — because build_rows is
deliberately pure. The write path is a thin upsert over exactly these rows.
"""
import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import victory_index as vi
import victory_ingest as ing

HERE = os.path.dirname(os.path.abspath(__file__))
EVENT = "VWC26"


def _fix(name):
    with open(os.path.join(HERE, "victory_fixtures", name), encoding="utf-8") as f:
        return json.load(f)


DEMO = _fix("demo_records.json")
RANKING = _fix("demo_ranking.json")
QUERIES = _fix("demo_queries.json")

EVT, SESSIONS, RECORDS = ing.build_rows(EVENT)

# The corpus exactly as load_corpus() would hand it to the scorer.
CORPUS = [{"id": r["id"], "ord": r["ord"], "event": r["event_key"], "k": r["kind"],
           "t": r["title"], "cat": r["category"], "ses": r["session"],
           "s": r["blob"], "w": r["weight"], "qb": r["quotable"]} for r in RECORDS]


class TestSourceShape(unittest.TestCase):
    def test_event_folder_is_discoverable(self):
        self.assertIn(EVENT, ing.list_events())

    def test_event_key_matches_its_folder(self):
        self.assertEqual(EVT["event_key"], EVENT)

    def test_sessions_and_ranges_survived_the_migration(self):
        # build_index.py held 13 sessions and 30 camera-card ranges in a
        # hardcoded Python list. All of them must have become data.
        self.assertEqual(len(SESSIONS), 13)
        self.assertEqual(sum(len(s["ranges"]) for s in SESSIONS), 30)

    def test_every_range_names_a_real_camera_and_card(self):
        for s in SESSIONS:
            for r in s["ranges"]:
                self.assertTrue(r["camera"])
                self.assertTrue(r["card"])
                self.assertIn(r["id_kind"], ("C", "D"))
                self.assertLessEqual(r["lo"], r["hi"])

    def test_osmo_ranges_are_d_ids_and_sony_ranges_are_c_ids(self):
        # 'C' ids are the Sony bodies, 'D' ids the roaming Osmo. Getting this
        # backwards would silently attribute clips to the wrong session.
        for s in SESSIONS:
            for r in s["ranges"]:
                self.assertEqual(r["id_kind"], "D" if r["camera"] == "OSMO" else "C")

    def test_hero_sessions_are_marked(self):
        heroes = [s["session_label"] for s in SESSIONS if s["priority"] == "hero"]
        self.assertIn("Night of Champions", heroes)
        self.assertIn("Candlelight Finale", heroes)


class TestRecords(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(len(RECORDS), 1873)
        self.assertEqual(sum(1 for r in RECORDS if r["kind"] == "clip"), 111)
        self.assertEqual(sum(1 for r in RECORDS if r["kind"] == "quote"), 1762)

    def test_ids_are_unique_and_event_scoped(self):
        ids = [r["id"] for r in RECORDS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith(EVENT + ":") for i in ids))

    def test_colliding_natural_ids_get_a_deterministic_suffix(self):
        # Convention 2026 has eight quotes whose transcript+second is shared
        # with the next speaker turn. They must survive as distinct rows.
        suffixed = [r["id"] for r in RECORDS if "#" in r["id"]]
        self.assertEqual(len(suffixed), 8)
        for i in suffixed:
            self.assertTrue(i.endswith("#2"))
            self.assertIn(i.rsplit("#", 1)[0], [r["id"] for r in RECORDS])

    def test_ids_are_stable_across_runs(self):
        again = ing.build_rows(EVENT)[2]
        self.assertEqual([r["id"] for r in RECORDS], [r["id"] for r in again])

    def test_ord_is_dense_clips_then_quotes(self):
        self.assertEqual([r["ord"] for r in RECORDS], list(range(len(RECORDS))))
        kinds = [r["kind"] for r in RECORDS]
        self.assertEqual(kinds.index("quote"), 111,
                         "quotes must start immediately after the 111 clips")

    def test_every_clip_carries_a_drive_id(self):
        # this is what lets previews stream without a new CDN
        clips = [r for r in RECORDS if r["kind"] == "clip"]
        self.assertTrue(all(r["drive_id"] for r in clips))

    def test_no_base64_anywhere_in_the_rows(self):
        blob = json.dumps(RECORDS)
        self.assertNotIn("data:image", blob)
        self.assertLess(len(blob), 3_000_000, "rows should be pointers, not media")

    def test_quotable_is_a_real_boolean_on_quotes(self):
        for r in RECORDS:
            if r["kind"] == "quote":
                self.assertIsInstance(r["quotable"], bool)


class TestFidelityToTheDemo(unittest.TestCase):
    """Field-for-field against the records the client actually saw."""

    def test_same_length(self):
        self.assertEqual(len(RECORDS), len(DEMO))

    def test_every_scoreable_field_is_identical(self):
        bad = []
        pairs = (("title", "t"), ("category", "cat"), ("session", "ses"),
                 ("blob", "s"))
        for i, (r, d) in enumerate(zip(RECORDS, DEMO)):
            if r["kind"] != d["k"]:
                bad.append((i, "kind"))
            for a, b in pairs:
                if (r.get(a) or "") != (d.get(b) or ""):
                    bad.append((i, a))
            if abs((r.get("weight") or 0) - (d.get("w") or 0)) > 1e-9:
                bad.append((i, "weight"))
            if d["k"] == "quote" and bool(r["quotable"]) != bool(d.get("qb")):
                bad.append((i, "quotable"))
        self.assertFalse(bad, "source drifted from the shipped demo: %r" % (bad[:5],))


class TestRankingSurvivesIngest(unittest.TestCase):
    """The point of the whole file."""

    def test_counts_match_the_demo_for_every_query(self):
        bad = []
        for q in QUERIES:
            rows, _, _, _ = vi.search_corpus(q, CORPUS)
            if len(rows) != RANKING[q]["found"]:
                bad.append((q, len(rows), RANKING[q]["found"]))
        self.assertFalse(bad, "count mismatch: %r" % (bad,))

    def test_order_matches_the_demo_for_every_query(self):
        bad = []
        for q in QUERIES:
            rows, _, _, _ = vi.search_corpus(q, CORPUS)
            mine = [r["ord"] for r in rows[:12]]
            if mine != RANKING[q]["top"]:
                bad.append((q, mine, RANKING[q]["top"]))
        self.assertFalse(bad, "ranking mismatch: %r" % (bad[:3],))

    def test_records_are_reachable_by_id_after_ranking(self):
        rows, _, _, _ = vi.search_corpus("candlelight", CORPUS)
        by_id = {r["id"]: r for r in RECORDS}
        for r in rows[:7]:
            self.assertIn(r["id"], by_id)


class TestIngestContract(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        out = ing.ingest(EVENT, dry_run=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["written"], 0)
        self.assertEqual(out["records"], 1873)
        self.assertEqual(out["with_drive_id"], 111)

    def test_unknown_event_fails_cleanly(self):
        out = ing.ingest("NOPE_DOES_NOT_EXIST", dry_run=True)
        self.assertFalse(out["ok"])
        self.assertIn("source", out["error"])

    def test_record_columns_cover_every_row_key(self):
        for r in RECORDS[:50]:
            self.assertEqual(set(r.keys()), set(ing.RECORD_COLS))

    def test_json_columns_are_declared(self):
        self.assertEqual(ing._JSON_COLS, {"topics", "media"})


class TestBatchedInsert(unittest.TestCase):
    """The first version issued one INSERT per record and Railway killed the
    worker at two minutes. These tests are the regression."""

    class FakeCur(object):
        def __init__(self):
            self.executed = []

        def execute(self, sql, args=None):
            self.executed.append((sql, args))

    def _batched(self, rows, chunk=500):
        """Inject a stand-in execute_values so the batched path is exercised
        even where psycopg2 is not installed."""
        import sys, types
        calls = []

        def execute_values(cur, sql, argslist, page_size=None):
            calls.append((sql, list(argslist), page_size))

        mod = types.ModuleType("psycopg2.extras")
        mod.execute_values = execute_values
        pkg = sys.modules.get("psycopg2")
        made = False
        if pkg is None:
            pkg = types.ModuleType("psycopg2")
            sys.modules["psycopg2"] = pkg
            made = True
        old = sys.modules.get("psycopg2.extras")
        sys.modules["psycopg2.extras"] = mod
        pkg.extras = mod
        try:
            cur = self.FakeCur()
            n = ing._insert_many(cur, "INSERT INTO t (a) VALUES %s", rows, chunk=chunk)
            return n, calls, cur
        finally:
            if old is not None:
                sys.modules["psycopg2.extras"] = old
            else:
                sys.modules.pop("psycopg2.extras", None)
            if made:
                sys.modules.pop("psycopg2", None)

    def test_1873_records_become_four_statements_not_1873(self):
        rows = [(i,) for i in range(1873)]
        n, calls, cur = self._batched(rows, chunk=500)
        self.assertEqual(n, 1873)
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(cur.executed), 0, "nothing should go one row at a time")

    def test_every_row_is_sent_exactly_once(self):
        rows = [(i,) for i in range(1873)]
        _, calls, _ = self._batched(rows, chunk=500)
        sent = [r for _, batch, _ in calls for r in batch]
        self.assertEqual(sent, rows)

    def test_order_is_preserved_across_chunks(self):
        # ord order is what keeps the ranking identical to the demo
        rows = [(i,) for i in range(1200)]
        _, calls, _ = self._batched(rows, chunk=500)
        sent = [r[0] for _, batch, _ in calls for r in batch]
        self.assertEqual(sent, sorted(sent))

    def test_empty_rows_do_nothing(self):
        n, calls, cur = self._batched([])
        self.assertEqual(n, 0)
        self.assertEqual(calls, [])
        self.assertEqual(cur.executed, [])

    def test_fallback_still_inserts_everything(self):
        import sys
        saved = sys.modules.get("psycopg2.extras")
        sys.modules["psycopg2.extras"] = None      # force the ImportError path
        try:
            cur = self.FakeCur()
            n = ing._insert_many(cur, "INSERT INTO t (a) VALUES %s", [(1,), (2,), (3,)])
            self.assertEqual(n, 3)
            self.assertEqual(len(cur.executed), 3)
            self.assertNotIn("VALUES %s", cur.executed[0][0])
            self.assertIn("VALUES (%s)", cur.executed[0][0])
        finally:
            if saved is not None:
                sys.modules["psycopg2.extras"] = saved
            else:
                sys.modules.pop("psycopg2.extras", None)

    def test_chunk_size_is_sane(self):
        self.assertGreaterEqual(ing.INSERT_CHUNK, 100)
        self.assertLessEqual(ing.INSERT_CHUNK, 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
