"""test_victory_routes.py — Patch #129: the /vi/* surface.

Runs against a bare Flask app with the same admin gate app.py uses, so the
routes are exercised without importing 24,825 lines of sales machine.

What these tests are really defending:

  * the gate FAILS CLOSED — no secret, wrong secret, or an unset UPLOAD_SECRET
    all refuse. This index is Victory's material.
  * a handler never leaks an exception to the caller as a stack trace.
  * /vi/search returns the demo's ranking through the HTTP layer, not just in
    the library.
"""
import os
import sys
import json
import hmac
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Flask is present in production and in the cloud workspace, but not in the
# Mini's system Python. Skip rather than fail there, so the whole repo suite
# stays green on every machine we run it on.
try:
    from flask import Flask
    HAVE_FLASK = True
except ImportError:                                   # pragma: no cover
    Flask = None
    HAVE_FLASK = False

import victory_index as vi
import victory_routes as vr
import victory_ingest as ing

SECRET = "test-secret-for-vi-routes"


def admin_ok(provided):
    """The same fail-closed shape as app.py's _admin_secret_ok."""
    expected = os.getenv("UPLOAD_SECRET", "")
    if not expected:
        return False
    return hmac.compare_digest(str(provided or ""), expected)


_, _, RECORDS = ing.build_rows("VWC26")
CORPUS = [{"id": r["id"], "ord": r["ord"], "event": r["event_key"], "k": r["kind"],
           "t": r["title"], "cat": r["category"], "ses": r["session"],
           "s": r["blob"], "w": r["weight"], "qb": r["quotable"]} for r in RECORDS]


def make_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    vr.register(app, admin_ok)
    return app.test_client()


@unittest.skipUnless(HAVE_FLASK, "flask not installed on this machine")
class VIRouteCase(unittest.TestCase):
    def setUp(self):
        os.environ["UPLOAD_SECRET"] = SECRET
        self.c = make_client()
        vi.set_corpus(CORPUS)

    def tearDown(self):
        os.environ.pop("UPLOAD_SECRET", None)

    def _j(self, resp):
        return json.loads(resp.data.decode("utf-8"))


class TestGate(VIRouteCase):
    def test_search_without_secret_is_401(self):
        r = self.c.get("/vi/search?q=candlelight")
        self.assertEqual(r.status_code, 401)

    def test_search_with_wrong_secret_is_401(self):
        r = self.c.get("/vi/search?q=candlelight&secret=nope")
        self.assertEqual(r.status_code, 401)

    def test_health_without_secret_is_401(self):
        self.assertEqual(self.c.get("/vi/health").status_code, 401)

    def test_ingest_without_secret_is_401(self):
        self.assertEqual(self.c.post("/vi/ingest", json={"event": "VWC26"}).status_code, 401)

    def test_unset_upload_secret_fails_closed(self):
        # the Patch #31 lesson: an unset variable must refuse, never fall back
        os.environ.pop("UPLOAD_SECRET", None)
        r = self.c.get("/vi/search?q=candlelight&secret=" + SECRET)
        self.assertEqual(r.status_code, 401)

    def test_secret_accepted_in_json_body(self):
        r = self.c.post("/vi/search", json={"q": "candlelight", "secret": SECRET})
        self.assertEqual(r.status_code, 200)

    def test_no_results_leak_in_a_401_body(self):
        r = self.c.get("/vi/search?q=candlelight")
        body = r.data.decode("utf-8").lower()
        self.assertNotIn("candlelight", body)
        self.assertNotIn("victory", body)


class TestSearch(VIRouteCase):
    def _search(self, q, **kw):
        params = {"q": q, "secret": SECRET}
        params.update(kw)
        qs = "&".join("%s=%s" % (k, v) for k, v in params.items())
        return self._j(self.c.get("/vi/search?" + qs))

    def test_returns_the_demo_count(self):
        out = self._search("candlelight")
        self.assertTrue(out["ok"])
        self.assertEqual(out["found"], 34)

    def test_default_limit_is_seven(self):
        self.assertEqual(self._search("candlelight")["shown"], 7)

    def test_limit_is_honoured_and_capped(self):
        self.assertEqual(self._search("candlelight", limit=3)["shown"], 3)
        self.assertLessEqual(self._search("interview+testimonial", limit=999)["shown"], 50)

    def test_bad_limit_falls_back_to_seven(self):
        self.assertEqual(self._search("candlelight", limit="banana")["shown"], 7)

    def test_peak_flag_is_reported(self):
        self.assertTrue(self._search("the+best+moments")["peak"])

    def test_speech_flag_is_reported(self):
        self.assertTrue(self._search("on+perseverance")["speech"])

    def test_fallback_is_flagged_not_faked(self):
        out = self._search("punctuality")
        self.assertTrue(out["fallback"], "a miss must be declared, not dressed up")

    def test_empty_query_is_safe(self):
        self.assertTrue(self._search("")["ok"])

    def test_timing_is_reported(self):
        self.assertIn("ms", self._search("candlelight"))

    def test_event_filter_narrows(self):
        self.assertGreater(self._search("candlelight", event="VWC26")["found"], 0)
        self.assertEqual(self._search("candlelight", event="NOPE")["found"], 0)

    def test_injection_in_query_is_just_a_query(self):
        out = self._search("'%3B+DROP+TABLE+vi_record%3B+--")
        self.assertTrue(out["ok"])

    def test_response_is_small(self):
        # the whole point of Phase 1: results, not a 45.8 MB payload
        r = self.c.get("/vi/search?q=candlelight&secret=" + SECRET)
        self.assertLess(len(r.data), 60_000)


class TestIngestRoute(VIRouteCase):
    def test_dry_run_reports_without_writing(self):
        out = self._j(self.c.post("/vi/ingest",
                                  json={"event": "VWC26", "dry_run": True, "secret": SECRET}))
        self.assertTrue(out["ok"])
        self.assertEqual(out["records"], 1873)
        self.assertEqual(out["written"], 0)

    def test_missing_event_is_400_and_lists_what_exists(self):
        r = self.c.post("/vi/ingest", json={"secret": SECRET})
        self.assertEqual(r.status_code, 400)
        self.assertIn("VWC26", self._j(r)["available"])

    def test_unknown_event_is_404(self):
        r = self.c.post("/vi/ingest", json={"event": "NOPE", "secret": SECRET})
        self.assertEqual(r.status_code, 404)

    def test_ingest_is_not_reachable_by_get(self):
        self.assertEqual(self.c.get("/vi/ingest?secret=" + SECRET).status_code, 405)


class TestHealth(VIRouteCase):
    def test_reports_corpus_size(self):
        out = self._j(self.c.get("/vi/health?secret=" + SECRET))
        self.assertTrue(out["ok"])
        self.assertEqual(out["corpus"], 1873)

    def test_lists_events_on_disk(self):
        out = self._j(self.c.get("/vi/health?secret=" + SECRET))
        self.assertIn("VWC26", out["events_on_disk"])

    def test_no_database_is_reported_not_fatal(self):
        out = self._j(self.c.get("/vi/health?secret=" + SECRET))
        self.assertIn("db", out)


class TestBoot(unittest.TestCase):
    def test_boot_without_a_database_is_non_fatal(self):
        self.assertEqual(vr.boot(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
