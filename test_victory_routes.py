"""test_victory_routes.py — the /vi/* surface, including the door.

Runs against a bare Flask app with the same admin gate app.py uses, so the
routes are exercised without importing 24,825 lines of sales machine, and
against an in-memory stand-in for the store so no database is needed.

What these tests defend:

  * the admin gate FAILS CLOSED — no secret, wrong secret, or an unset
    UPLOAD_SECRET all refuse.
  * signing in is NOT access. A Victory address we have not been told about
    gets a session and sees nothing.
  * a sign-in link works exactly once.
  * /vi/login answers identically whatever address it is given, so the form
    cannot be used to find out who works at Victory.
  * a handler never leaks an exception to the caller as a stack trace.
"""
import os
import sys
import json
import hmac
import time
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
import victory_auth as va
import victory_store as vs
import victory_routes as vr
import victory_ingest as ing

SECRET = "test-secret-for-vi-routes"
SIGNING = "test-signing-secret-long-enough-for-hmac"

_, _, RECORDS = ing.build_rows("VWC26")
CORPUS = [{"id": r["id"], "ord": r["ord"], "event": r["event_key"], "k": r["kind"],
           "t": r["title"], "cat": r["category"], "ses": r["session"],
           "s": r["blob"], "w": r["weight"], "qb": r["quotable"]} for r in RECORDS]
RESIDENT = {r["id"]: {"id": r["id"], "kind": r["kind"], "title": r["title"],
                      "session": r["session"], "day_no": r["day_no"],
                      "camera": r["camera"], "duration": r["duration"],
                      "drive_id": r["drive_id"], "priority": r["priority"],
                      "quote": r["quote"], "file": r["file"]} for r in RECORDS}


def admin_ok(provided):
    """The same fail-closed shape as app.py's _admin_secret_ok."""
    expected = os.getenv("UPLOAD_SECRET", "")
    if not expected:
        return False
    return hmac.compare_digest(str(provided or ""), expected)


class FakeStore(object):
    """An in-memory stand-in with the same contract as victory_store.

    consume_link mirrors the SQL: it claims once and never again.
    """

    def __init__(self):
        self.links = {}      # token_hash -> [email, issued_at, used]
        self.people = {}     # email -> {role, school}
        self.searches = []
        self.requests = []
        self.feedback = []
        self.media = {}
        self.secret = SIGNING

    def init_schema(self):
        return True

    def session_secret(self, create=True):
        return self.secret

    def create_link(self, token_hash, email, ip=""):
        self.links[token_hash] = [email, time.time(), False]
        return True

    def consume_link(self, token_hash):
        row = self.links.get(token_hash)
        if not row or row[2]:
            return None
        row[2] = True                       # claimed, once
        return (row[0], row[1])

    def get_person(self, email):
        p = self.people.get(email)
        return {"email": email, "role": p["role"], "school": p.get("school", "")} if p else None

    def remember_person(self, email, role, school=""):
        self.people.setdefault(email, {"role": role, "school": school})
        return True

    def grant(self, email, role, school="", by="michael"):
        self.people[email] = {"role": role, "school": school}
        return True

    def list_people(self, limit=200):
        return [{"email": e, "role": p["role"], "school": p.get("school", ""),
                 "granted_by": None, "granted_at": None, "first_seen": None,
                 "last_seen": None} for e, p in self.people.items()]

    def log_search(self, email, role, q, event_key, found, ms, ip=""):
        self.searches.append({"email": email, "role": role, "q": q, "found": found})
        return True

    def recent_searches(self, limit=50):
        return []

    def purge_links(self, older_than_seconds=86400):
        return 0

    def create_request(self, email, role, school, note, items, length_s=30, text=None):
        self.requests.append({"id": len(self.requests) + 1, "at": "2026-09-14 20:00:00", "text": text,
                              "email": email, "role": role, "school": school,
                              "note": note, "items": items, "state": "asked",
                              "handled_at": None, "handled_by": None,
                              "length_s": length_s, "started_at": None, "finished_at": None,
                              "result_drive_id": None, "result_file": None,
                              "result_bytes": None, "result_seconds": None,
                              "summary": None, "error": None})
        return len(self.requests)

    def list_requests(self, limit=50, state=None):
        rows = [dict(r) for r in self.requests if not state or r["state"] == state]
        return list(reversed(rows))[:limit]

    def list_requests_for(self, email, limit=50):
        return [dict(r) for r in reversed(self.requests) if r["email"] == email][:limit]

    def get_request(self, rid):
        for r in self.requests:
            if r["id"] == int(rid):
                return dict(r)
        return None

    def claim_next_request(self, worker):
        for r in self.requests:
            if r["state"] == "asked":
                r["state"] = "rendering"; r["handled_by"] = worker
                r["handled_at"] = r["started_at"] = "2026-09-14 20:01:00"
                return dict(r)
        return None

    def finish_request(self, rid, state, drive_id=None, file_name=None, size=None,
                       seconds=None, summary=None, error=None):
        for r in self.requests:
            if r["id"] == int(rid):
                r["state"] = state; r["finished_at"] = "2026-09-14 20:02:00"
                if drive_id: r["result_drive_id"] = drive_id
                if file_name: r["result_file"] = file_name
                if size: r["result_bytes"] = size
                if seconds: r["result_seconds"] = seconds
                if summary is not None: r["summary"] = summary
                r["error"] = error
                return True
        return False

    def set_request_state(self, rid, state, by=""):
        for r in self.requests:
            if r["id"] == int(rid):
                r["state"] = state; r["handled_by"] = by or r["handled_by"]
                return True
        return False

    def requeue_stale(self, older_than_seconds=1800):
        return 0

    def queue_counts(self):
        out = {}
        for r in self.requests:
            out[r["state"]] = out.get(r["state"], 0) + 1
        return out

    def recent_music(self, email, limit=2):
        out = []
        for r in reversed(self.requests):
            if r["email"] == email and isinstance(r.get("summary"), dict) and r["summary"].get("music_id"):
                out.append(r["summary"]["music_id"])
        return out[:limit]

    def recent_clips(self, email, cuts=6):
        out = []
        for r in reversed(self.requests):
            if r["email"] == email and isinstance(r.get("summary"), dict):
                for sh in r["summary"].get("shots") or []:
                    if isinstance(sh, dict) and sh.get("id") and sh["id"] not in out:
                        out.append(sh["id"])
        return out

    def media_have(self):
        return {k for k, v in self.media.items() if v.get("poster") and v.get("preview")}

    def media_put(self, clip_id, poster, preview):
        m = self.media.setdefault(clip_id, {})
        if poster: m["poster"] = poster
        if preview: m["preview"] = preview
        return True

    def media_get(self, clip_id, kind):
        return self.media.get(clip_id, {}).get(kind)

    def put_extra_clips(self, event_key, items):
        self.extra = getattr(self, "extra", {})
        n = 0
        for it in items:
            if it.get("id"):
                self.extra[it["id"]] = (event_key, dict(it))
                n += 1
        return n

    def extra_clips(self, event_key, with_reframe=False):
        out = []
        for ev, it in getattr(self, "extra", {}).values():
            if ev == event_key:
                it = dict(it)
                if not with_reframe:
                    it.pop("reframe", None)
                out.append(it)
        return out

    def add_feedback(self, rid, email, text):
        self.feedback.append({"request_id": int(rid), "at": "2026-09-14 20:03:00",
                              "email": email, "text": text})
        return len(self.feedback)

    def list_feedback(self, rids):
        out = {}
        for f in self.feedback:
            if f["request_id"] in [int(r) for r in rids]:
                out.setdefault(f["request_id"], []).append(dict(f))
        return out


_REAL = {}


def install_fake_store(fake):
    """Swap victory_store's functions for the fake's bound methods."""
    for name in ("init_schema", "session_secret", "create_link", "consume_link",
                 "get_person", "remember_person", "grant", "list_people",
                 "log_search", "recent_searches", "purge_links",
                 "create_request", "list_requests", "list_requests_for", "get_request",
                 "claim_next_request", "finish_request", "set_request_state",
                 "requeue_stale", "queue_counts", "recent_music", "recent_clips",
                 "add_feedback", "list_feedback", "media_have", "media_put", "media_get",
                 "put_extra_clips", "extra_clips"):
        _REAL.setdefault(name, getattr(vs, name))
        setattr(vs, name, getattr(fake, name))


def restore_store():
    for name, fn in _REAL.items():
        setattr(vs, name, fn)


UPLOADS = []


def fake_drive_upload(name, data):
    """Stands in for victory_drive.upload_video: remembers what it was given."""
    UPLOADS.append({"name": name, "bytes": len(data)})
    return {"id": "drive-%d" % len(UPLOADS), "link": "https://drive.google.com/file/d/x/view",
            "download": "https://drive.google.com/uc?export=download&id=x"}


class FakeClaude:
    """Stands in for anthropic.Anthropic: answers every contact sheet the same."""
    answer = ('{"title": "Belt handed to a kneeling student", "category": "Belt & rank presentation", '
              '"keywords": ["belt", "kneeling", "master", "stage", "kids"], "people": "kids, masters", '
              '"interest": 5, "why": "the belt changes hands"}')

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


def make_client(notes=None):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["VI_DESCRIBE_CLIENT"] = FakeClaude()
    vr.register(app, admin_ok, notify=(notes.append if notes is not None else None),
                drive_upload=fake_drive_upload)
    c = app.test_client()
    c.fake_claude = app.config["VI_DESCRIBE_CLIENT"]
    return c


@unittest.skipUnless(HAVE_FLASK, "flask not installed on this machine")
class VICase(unittest.TestCase):
    def setUp(self):
        os.environ["UPLOAD_SECRET"] = SECRET
        self.store = FakeStore()
        install_fake_store(self.store)
        self.notes = []
        self.c = make_client(self.notes)
        vi.set_corpus(CORPUS, resident=RESIDENT)

    def tearDown(self):
        restore_store()
        os.environ.pop("UPLOAD_SECRET", None)

    def _j(self, r):
        return json.loads(r.data.decode("utf-8"))

    def _sign_in_as(self, email, role, school=""):
        """Walk the real flow: mint a link, spend it, keep the cookie."""
        if role != va.ROLE_PENDING:
            self.store.grant(email, role, school)
        token, h = va.new_token()
        self.store.create_link(h, email)
        r = self.c.get("/vi/auth?token=" + token)
        self.assertEqual(r.status_code, 302, "sign-in should redirect")
        return r


class TestAdminGate(VICase):
    def test_health_needs_the_secret(self):
        self.assertEqual(self.c.get("/vi/health").status_code, 401)

    def test_ingest_needs_the_secret(self):
        self.assertEqual(self.c.post("/vi/ingest", json={"event": "VWC26"}).status_code, 401)

    def test_grant_needs_the_secret(self):
        r = self.c.post("/vi/grant", json={"email": "x@victoryma.com", "role": "hq"})
        self.assertEqual(r.status_code, 401)

    def test_issue_link_needs_the_secret(self):
        r = self.c.post("/vi/issue-link", json={"email": "x@victoryma.com"})
        self.assertEqual(r.status_code, 401)

    def test_people_needs_the_secret(self):
        self.assertEqual(self.c.get("/vi/people").status_code, 401)

    def test_unset_upload_secret_fails_closed(self):
        os.environ.pop("UPLOAD_SECRET", None)
        self.assertEqual(self.c.get("/vi/health?secret=" + SECRET).status_code, 401)

    def test_search_still_accepts_the_admin_secret(self):
        r = self.c.get("/vi/search?q=candlelight&secret=" + SECRET)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._j(r)["found"], 50)


class TestSignInForm(VICase):
    def test_home_shows_the_form_when_signed_out(self):
        r = self.c.get("/vi/")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8")
        self.assertIn("Sign in", body)
        self.assertIn("you@victoryma.com", body)

    def test_signed_out_home_leaks_no_content(self):
        body = self.c.get("/vi/").data.decode("utf-8").lower()
        self.assertNotIn("candlelight", body)
        self.assertNotIn("night of champions", body)

    def test_login_answers_the_same_for_any_address(self):
        pages = []
        for email in ("jim@victoryma.com", "nobody@victoryma.com",
                      "attacker@gmail.com", "not-an-email", ""):
            r = self.c.post("/vi/login", data={"email": email})
            self.assertEqual(r.status_code, 200)
            pages.append(r.data.decode("utf-8"))
        self.assertEqual(len(set(pages)), 1,
                         "the response must not reveal which addresses exist")
        self.assertIn("Check your email", pages[0])

    def test_a_link_is_created_only_for_an_allowed_domain(self):
        os.environ[va.CLIENT_EMAIL_ENV] = "1"   # this test is about the door, not the lock
        self.addCleanup(os.environ.pop, va.CLIENT_EMAIL_ENV, None)
        self.c.post("/vi/login", data={"email": "jim@victoryma.com"})
        self.assertEqual(len(self.store.links), 1)
        self.c.post("/vi/login", data={"email": "attacker@gmail.com"})
        self.c.post("/vi/login", data={"email": "x@victoryma.com.evil.net"})
        self.assertEqual(len(self.store.links), 1, "no link for an untrusted domain")

    def test_repeated_requests_are_rate_limited(self):
        os.environ[va.CLIENT_EMAIL_ENV] = "1"   # this test is about the door, not the lock
        self.addCleanup(os.environ.pop, va.CLIENT_EMAIL_ENV, None)
        for _ in range(va.LINK_MAX_PER_EMAIL + 6):
            self.c.post("/vi/login", data={"email": "jim@victoryma.com"})
        self.assertLessEqual(len(self.store.links), va.LINK_MAX_PER_EMAIL)

    def test_login_is_not_reachable_by_get(self):
        self.assertEqual(self.c.get("/vi/login").status_code, 405)


class TestMagicLink(VICase):
    def test_a_valid_link_signs_you_in(self):
        self.store.grant("jim@victoryma.com", va.ROLE_HQ)
        token, h = va.new_token()
        self.store.create_link(h, "jim@victoryma.com")
        r = self.c.get("/vi/auth?token=" + token)
        self.assertEqual(r.status_code, 302)
        self.assertIn(vr.COOKIE, r.headers.get("Set-Cookie", ""))

    def test_a_link_works_exactly_once(self):
        self.store.grant("jim@victoryma.com", va.ROLE_HQ)
        token, h = va.new_token()
        self.store.create_link(h, "jim@victoryma.com")
        self.assertEqual(self.c.get("/vi/auth?token=" + token).status_code, 302)
        second = self.c.get("/vi/auth?token=" + token)
        self.assertEqual(second.status_code, 400)
        self.assertIn("already been used", second.data.decode("utf-8"))

    def test_an_unknown_token_is_refused(self):
        for bad in ("", "nope", "x" * 200):
            self.assertEqual(self.c.get("/vi/auth?token=" + bad).status_code, 400)

    def test_an_expired_link_is_refused_and_still_spent(self):
        self.store.grant("jim@victoryma.com", va.ROLE_HQ)
        token, h = va.new_token()
        self.store.create_link(h, "jim@victoryma.com")
        self.store.links[h][1] = time.time() - va.LINK_TTL_SECONDS - 60
        r = self.c.get("/vi/auth?token=" + token)
        self.assertEqual(r.status_code, 400)
        self.assertIn("expired", r.data.decode("utf-8"))
        self.assertTrue(self.store.links[h][2],
                        "an expired link must still be spent, not left replayable")

    def test_the_cookie_is_httponly_and_scoped(self):
        self.store.grant("jim@victoryma.com", va.ROLE_HQ)
        token, th = va.new_token()
        self.store.create_link(th, "jim@victoryma.com")
        raw = self.c.get("/vi/auth?token=" + token).headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", raw, "script must not be able to read the session")
        self.assertIn("Path=/vi", raw, "the cookie has no business on other routes")
        self.assertIn("SameSite=Lax", raw)

    def test_the_session_cookie_carries_no_secret(self):
        self.store.grant("jim@victoryma.com", va.ROLE_HQ)
        token, th = va.new_token()
        self.store.create_link(th, "jim@victoryma.com")
        raw = self.c.get("/vi/auth?token=" + token).headers.get("Set-Cookie", "")
        self.assertNotIn(SIGNING, raw)
        self.assertNotIn(token, raw)

    def test_a_forged_cookie_is_not_a_session(self):
        self.c.set_cookie("vi_session", "eyJ.forged", path="/vi")
        self.assertEqual(self.c.get("/vi/search?q=candlelight").status_code, 401)

    def test_logout_clears_the_cookie(self):
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        r = self.c.get("/vi/logout")
        self.assertEqual(r.status_code, 302)
        self.assertIn("Max-Age=0", r.headers.get("Set-Cookie", ""))
        self.assertEqual(self.c.get("/vi/search?q=candlelight").status_code, 401)


class TestSigningInIsNotAccess(VICase):
    """The assertion this whole phase turns on."""

    def test_an_unknown_victory_address_gets_in_but_sees_nothing(self):
        self._sign_in_as("someone-new@victoryma.com", va.ROLE_PENDING)
        home = self.c.get("/vi/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("not been told", home.data.decode("utf-8"))
        r = self.c.get("/vi/search?q=candlelight")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(self._j(r).get("pending"))

    def test_a_pending_person_leaks_no_results(self):
        self._sign_in_as("someone-new@victoryma.com", va.ROLE_PENDING)
        body = self.c.get("/vi/search?q=candlelight").data.decode("utf-8").lower()
        self.assertNotIn("candlelight", body)
        self.assertNotIn("champions", body)

    def test_dev_is_told_when_someone_new_arrives(self):
        self._sign_in_as("someone-new@victoryma.com", va.ROLE_PENDING)
        self.assertTrue(any("no access yet" in n for n in self.notes))

    def test_a_granted_person_can_search(self):
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        r = self.c.get("/vi/search?q=candlelight")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._j(r)["found"], 50)

    def test_a_granted_person_sees_the_app(self):
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        body = self.c.get("/vi/").data.decode("utf-8")
        self.assertIn("Search", body)
        self.assertIn("2,087", body)

    def test_a_search_is_logged_against_the_person(self):
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        self.c.get("/vi/search?q=candlelight")
        self.assertEqual(len(self.store.searches), 1)
        self.assertEqual(self.store.searches[0]["email"], "jim@victoryma.com")

    def test_a_granted_role_is_not_overwritten_on_a_later_sign_in(self):
        self.store.grant("jim@victoryma.com", va.ROLE_HQ)
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        self.assertEqual(self.store.people["jim@victoryma.com"]["role"], va.ROLE_HQ)


class TestSearchResults(VICase):
    def setUp(self):
        VICase.setUp(self)
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)

    def _s(self, q, **kw):
        params = {"q": q}
        params.update(kw)
        qs = "&".join("%s=%s" % (k, v) for k, v in params.items())
        return self._j(self.c.get("/vi/search?" + qs))

    def test_matches_the_demo_count(self):
        self.assertEqual(self._s("candlelight")["found"], 50)

    def test_results_carry_their_provenance(self):
        r = self._s("candlelight")["results"][0]
        self.assertTrue(r.get("session"))
        self.assertTrue(r.get("camera"))

    def test_clips_carry_a_drive_id(self):
        rows = [r for r in self._s("winner arm raised")["results"] if r["kind"] == "clip"]
        self.assertTrue(rows)
        self.assertTrue(all(r.get("drive_id") for r in rows))

    def test_a_miss_is_declared_not_dressed_up(self):
        self.assertTrue(self._s("punctuality")["fallback"])

    def test_limit_is_capped(self):
        self.assertLessEqual(self._s("interview+testimonial", limit=999)["shown"], 50)

    def test_injection_in_a_query_is_just_a_query(self):
        self.assertTrue(self._s("'%3B+DROP+TABLE+vi_record%3B+--")["ok"])

    def test_response_is_small(self):
        r = self.c.get("/vi/search?q=candlelight")
        self.assertLess(len(r.data), 60_000)


class TestGrant(VICase):
    def _grant(self, **kw):
        kw["secret"] = SECRET
        return self.c.post("/vi/grant", json=kw)

    def test_grants_a_role(self):
        r = self._grant(email="jim@victoryma.com", role="hq")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.store.people["jim@victoryma.com"]["role"], "hq")

    def test_refuses_an_unknown_role(self):
        self.assertEqual(self._grant(email="x@victoryma.com", role="admin").status_code, 400)
        self.assertEqual(self._grant(email="x@victoryma.com", role="").status_code, 400)

    def test_refuses_an_untrusted_domain(self):
        self.assertEqual(self._grant(email="x@gmail.com", role="hq").status_code, 400)

    def test_refuses_a_bad_address(self):
        self.assertEqual(self._grant(email="not-an-email", role="hq").status_code, 400)

    def test_a_school_role_needs_a_school(self):
        self.assertEqual(self._grant(email="x@victoryma.com", role="school").status_code, 400)
        self.assertEqual(self._grant(email="x@victoryma.com", role="school",
                                     school="Lake Nona").status_code, 200)

    def test_a_grant_is_announced(self):
        self._grant(email="jim@victoryma.com", role="hq")
        self.assertTrue(any("set to" in n for n in self.notes))


class TestIssueLink(VICase):
    def test_returns_a_working_link_without_emailing(self):
        # our own address: while the send lock is on, minting a CLIENT link is
        # forbidden even here, because a URL in a log is still a credential
        r = self.c.post("/vi/issue-link", json={"email": "michael@mwmcreations.com",
                                                "secret": SECRET})
        self.assertEqual(r.status_code, 200)
        url = self._j(r)["url"]
        self.assertIn("/vi/auth?token=", url)
        self.store.grant("michael@mwmcreations.com", va.ROLE_MWM)
        follow = self.c.get(url[url.index("/vi/auth"):])
        self.assertEqual(follow.status_code, 302)

    def test_refuses_an_untrusted_domain(self):
        r = self.c.post("/vi/issue-link", json={"email": "x@gmail.com", "secret": SECRET})
        self.assertEqual(r.status_code, 400)

    def test_the_link_it_mints_is_still_single_use(self):
        r = self.c.post("/vi/issue-link", json={"email": "michael@mwmcreations.com",
                                                "secret": SECRET})
        path = self._j(r)["url"]
        path = path[path.index("/vi/auth"):]
        self.store.grant("michael@mwmcreations.com", va.ROLE_MWM)
        self.assertEqual(self.c.get(path).status_code, 302)
        self.assertEqual(self.c.get(path).status_code, 400)


class TestNoSigningSecret(VICase):
    """No database means no signing secret, which must mean no sessions."""

    def test_auth_refuses_when_there_is_no_secret(self):
        self.store.secret = ""
        token, h = va.new_token()
        self.store.create_link(h, "jim@victoryma.com")
        r = self.c.get("/vi/auth?token=" + token)
        self.assertEqual(r.status_code, 503)


class TestBoot(unittest.TestCase):
    def test_boot_without_a_database_is_non_fatal(self):
        self.assertEqual(vr.boot(), 0)


class TestExternalGrants(VICase):
    """Granting an address off victoryma.com must be deliberate."""

    def _grant(self, **kw):
        kw["secret"] = SECRET
        return self.c.post("/vi/grant", json=kw)

    def test_an_external_grant_is_refused_without_saying_so(self):
        r = self._grant(email="victoryhvs@aol.com", role="hq")
        self.assertEqual(r.status_code, 400)
        body = self._j(r)
        self.assertTrue(body.get("external"))
        self.assertIn("allow_external", body["error"])
        self.assertNotIn("victoryhvs@aol.com", self.store.people)

    def test_an_external_grant_succeeds_when_stated(self):
        r = self._grant(email="victoryhvs@aol.com", role="hq", allow_external=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self._j(r)["external"])
        self.assertEqual(self.store.people["victoryhvs@aol.com"]["role"], "hq")

    def test_an_external_grant_is_flagged_in_the_announcement(self):
        self._grant(email="victoryhvs@aol.com", role="hq", allow_external=True)
        self.assertTrue(any("outside" in n for n in self.notes))

    def test_a_victoryma_grant_needs_no_flag(self):
        self.assertEqual(self._grant(email="gmvs@victoryma.com", role="hq").status_code, 200)

    def test_an_ungranted_external_address_gets_no_link(self):
        self.c.post("/vi/login", data={"email": "victoryhvs@aol.com"})
        self.assertEqual(len(self.store.links), 0)

    def test_a_granted_external_address_does_get_a_link(self):
        os.environ[va.CLIENT_EMAIL_ENV] = "1"   # this test is about the door, not the lock
        self.addCleanup(os.environ.pop, va.CLIENT_EMAIL_ENV, None)
        self.store.grant("victoryhvs@aol.com", va.ROLE_HQ)
        self.c.post("/vi/login", data={"email": "victoryhvs@aol.com"})
        self.assertEqual(len(self.store.links), 1)

    def test_a_granted_external_address_can_sign_in_and_search(self):
        self.store.grant("victoryhvs@aol.com", va.ROLE_HQ)
        self._sign_in_as("victoryhvs@aol.com", va.ROLE_HQ)
        r = self.c.get("/vi/search?q=candlelight")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._j(r)["found"], 50)

    def test_a_stranger_at_the_same_domain_still_gets_nothing(self):
        os.environ[va.CLIENT_EMAIL_ENV] = "1"   # this test is about the door, not the lock
        self.addCleanup(os.environ.pop, va.CLIENT_EMAIL_ENV, None)
        self.store.grant("victoryhvs@aol.com", va.ROLE_HQ)
        self.c.post("/vi/login", data={"email": "someone-else@aol.com"})
        self.assertEqual(len(self.store.links), 0,
                         "granting one aol address must not trust aol.com")


class TestSendLockLive(VICase):
    """The lock, through the actual routes."""

    def setUp(self):
        VICase.setUp(self)
        os.environ.pop(va.CLIENT_EMAIL_ENV, None)      # locked, as it ships

    def tearDown(self):
        os.environ.pop(va.CLIENT_EMAIL_ENV, None)
        VICase.tearDown(self)

    def test_no_link_is_even_created_for_a_victory_address(self):
        self.c.post("/vi/login", data={"email": "gmvs@victoryma.com"})
        self.assertEqual(len(self.store.links), 0,
                         "a link that exists is a link that can leak")

    def test_no_link_is_created_for_a_granted_external_address(self):
        self.store.grant("victoryhvs@aol.com", va.ROLE_HQ)
        self.c.post("/vi/login", data={"email": "victoryhvs@aol.com"})
        self.assertEqual(len(self.store.links), 0)

    def test_our_own_address_still_works(self):
        self.c.post("/vi/login", data={"email": "michael@mwmcreations.com"})
        self.assertEqual(len(self.store.links), 1)

    def test_the_locked_response_is_indistinguishable(self):
        a = self.c.post("/vi/login", data={"email": "gmvs@victoryma.com"}).data
        b = self.c.post("/vi/login", data={"email": "michael@mwmcreations.com"}).data
        self.assertEqual(a, b, "the lock must not become an enumeration oracle")

    def test_dev_is_told_when_the_lock_stops_something(self):
        self.c.post("/vi/login", data={"email": "gmvs@victoryma.com"})
        self.assertTrue(any("locked to internal testing" in n for n in self.notes))

    def test_issue_link_is_locked_too(self):
        r = self.c.post("/vi/issue-link", json={"email": "gmvs@victoryma.com",
                                                "secret": SECRET})
        self.assertEqual(r.status_code, 423)
        self.assertTrue(self._j(r)["locked"])
        self.assertEqual(len(self.store.links), 0)

    def test_issue_link_still_works_for_our_own_address(self):
        r = self.c.post("/vi/issue-link", json={"email": "michael@mwmcreations.com",
                                                "secret": SECRET})
        self.assertEqual(r.status_code, 200)

    def test_lifting_the_lock_restores_normal_behaviour(self):
        os.environ[va.CLIENT_EMAIL_ENV] = "1"
        self.c.post("/vi/login", data={"email": "gmvs@victoryma.com"})
        self.assertEqual(len(self.store.links), 1)

    def test_health_reports_the_lock_state(self):
        out = self._j(self.c.get("/vi/health?secret=" + SECRET))
        self.assertTrue(out["auth"]["send_lock"])
        self.assertFalse(out["auth"]["client_email_enabled"])


class TestAskForACut(VICase):
    """The answer to "I found things but don't know how to use it"."""

    def setUp(self):
        VICase.setUp(self)
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)

    def _ask(self, **kw):
        return self.c.post("/vi/request", json=kw)

    def test_a_request_is_stored(self):
        r = self._ask(items=[{"id": "VWC26:x", "title": "Kids cheering", "kind": "clip"}],
                      note="30s reel for Lake Nona")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.store.requests), 1)
        self.assertEqual(self.store.requests[0]["note"], "30s reel for Lake Nona")

    def test_it_records_who_asked(self):
        self._ask(items=[{"id": "a", "title": "t", "kind": "clip"}])
        self.assertEqual(self.store.requests[0]["email"], "jim@victoryma.com")

    def test_dev_is_told_what_was_asked_for(self):
        self._ask(items=[{"id": "a", "title": "Kids cheering", "kind": "clip"}],
                  note="for the lobby screen")
        joined = " ".join(self.notes)
        self.assertIn("requested", joined)
        self.assertIn("Kids cheering", joined)
        self.assertIn("for the lobby screen", joined)

    def test_a_note_is_optional(self):
        self.assertEqual(self._ask(items=[{"id": "a", "title": "t"}]).status_code, 200)

    def test_words_alone_are_enough_since_the_machine_finds_the_footage(self):
        # 14 Sep: "a real automated system that actually finds the footage"
        self.assertEqual(self._ask(items=[], note="best moments for parents").status_code, 200)
        self.assertEqual(self._ask(note="candlelight").status_code, 200)
        self.assertEqual(len(self.store.requests), 2)

    def test_nothing_at_all_is_refused(self):
        self.assertEqual(self._ask(items=[], note="").status_code, 400)
        self.assertEqual(self._ask().status_code, 400)

    def test_words_on_screen_and_the_end_card_are_kept(self):
        self._ask(note="x", lines="Four days.\nEvery school.\n\nOne floor.", cta="Enroll today")
        self.assertEqual(self.store.requests[0]["text"],
                         {"lines": ["Four days.", "Every school.", "One floor."], "cta": "Enroll today"})
        self._ask(note="x")
        self.assertIsNone(self.store.requests[1]["text"])
        self._ask(note="x", lines=["a", "b", "c", "d", "e", "f"], cta="z" * 200)
        self.assertEqual(len(self.store.requests[2]["text"]["lines"]), 4)
        self.assertEqual(len(self.store.requests[2]["text"]["cta"]), 60)

    def test_length_is_kept_and_kept_sane(self):
        self._ask(note="x", length=60)
        self._ask(note="x", length=7)
        self._ask(note="x", length="sixty")
        self.assertEqual([r["length_s"] for r in self.store.requests], [60, 30, 30])

    def test_a_silly_number_of_items_is_refused(self):
        many = [{"id": str(i), "title": "t"} for i in range(200)]
        self.assertEqual(self._ask(items=many).status_code, 400)

    def test_junk_shapes_do_not_get_through(self):
        self.assertEqual(self._ask(items=["not-a-dict", 42, None]).status_code, 400)

    def test_only_known_fields_are_kept(self):
        self._ask(items=[{"id": "a", "title": "t", "role": "hq", "evil": "x"}])
        self.assertEqual(set(self.store.requests[0]["items"][0].keys()),
                         {"id", "title", "kind", "file", "quote"})

    def test_a_signed_out_person_cannot_ask(self):
        self.c.get("/vi/logout")
        self.assertEqual(self._ask(items=[{"id": "a"}]).status_code, 401)

    def test_a_pending_person_cannot_ask(self):
        self.c.get("/vi/logout")
        self._sign_in_as("nobody-new@victoryma.com", va.ROLE_PENDING)
        self.assertEqual(self._ask(items=[{"id": "a"}]).status_code, 403)

    def test_the_queue_is_admin_only_to_read(self):
        self.assertEqual(self.c.get("/vi/requests").status_code, 401)
        self.assertEqual(self.c.get("/vi/requests?secret=" + SECRET).status_code, 200)


class TestThumbnailsAndPreviews(VICase):
    """15 Sep: "no option to preview the footage and not even a thumbnail".
    The worker makes them; the app keeps and serves them; the page shows them."""

    JPEG = b"\xff\xd8\xff" + b"j" * 2000
    MP4 = b"\x00\x00\x00\x1cftypisom" + b"v" * 20000

    def _put(self, cid, poster=JPEG, preview=MP4):
        import io as _io
        data = {"secret": SECRET}
        if poster is not None: data["poster"] = (_io.BytesIO(poster), "p.jpg")
        if preview is not None: data["preview"] = (_io.BytesIO(preview), "p.mp4")
        return self.c.post("/vi/media/%s" % cid, data=data, content_type="multipart/form-data")

    def test_the_worker_side_is_admin_only(self):
        self.assertEqual(self.c.get("/vi/media/missing").status_code, 401)
        self.assertEqual(self.c.post("/vi/media/x").status_code, 401)

    def test_missing_lists_every_clip_and_interview_piece_until_covered(self):
        m = self._j(self.c.get("/vi/media/missing?secret=%s&limit=500" % SECRET))
        self.assertEqual(m["total_missing"], 325 + 191)      # clips (111 selects + 214 long-recording moments) + interview pieces
        self.assertIn("VWC26_CROWD_01_kids-cheering_D0062", m["missing"])
        self.assertIn("M_ROAM_J24-2_full_0484", m["missing"])
        self.assertEqual(self._put("VWC26_CROWD_01_kids-cheering_D0062").status_code, 200)
        self.assertEqual(self._put("M_ROAM_J24-2_full_0484").status_code, 200)
        m = self._j(self.c.get("/vi/media/missing?secret=%s&limit=500" % SECRET))
        self.assertEqual(m["total_missing"], 325 + 191 - 2)
        self.assertNotIn("VWC26_CROWD_01_kids-cheering_D0062", m["missing"])
        self.assertNotIn("M_ROAM_J24-2_full_0484", m["missing"])

    def test_a_line_someone_said_knows_its_picture(self):
        """Michael, 16 Sep: "thumbnails for everything, even a phrase someone
        said." A quote result names the piece of the recording it was said in
        and the second the line starts, so the Library can show and play it."""
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        r = self._j(self.c.get("/vi/search?q=why parents enrolled&limit=50"))
        quotes = [x for x in r["results"] if x["kind"] == "quote"]
        self.assertTrue(quotes)
        with_pic = [x for x in quotes if x.get("moment")]
        self.assertGreaterEqual(len(with_pic), len(quotes) - 5, "nearly every line has its piece")
        for x in with_pic:
            self.assertTrue(x["moment"].startswith("M_"), x["moment"])
            self.assertGreaterEqual(x["offset"], 0)
        clips = [x for x in r["results"] if x["kind"] == "clip"]
        for x in clips:
            self.assertNotIn("moment", x)

    def test_junk_uploads_are_refused(self):
        self.assertEqual(self._put("x", poster=b"notajpeg" * 300).status_code, 400)
        self.assertEqual(self._put("x", poster=None, preview=b"tiny").status_code, 400)
        self.assertEqual(self._put("x", poster=None, preview=None).status_code, 400)

    def test_signed_in_people_get_the_pictures_and_nobody_else_does(self):
        self._put("clipA")
        self.assertEqual(self.c.get("/vi/thumb/clipA.jpg").status_code, 401)
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        r = self.c.get("/vi/thumb/clipA.jpg")
        self.assertEqual((r.status_code, r.headers["Content-Type"]), (200, "image/jpeg"))
        self.assertEqual(r.data, self.JPEG)
        self.assertEqual(self.c.get("/vi/thumb/nope.jpg").status_code, 404)
        r = self.c.get("/vi/preview/clipA.mp4")
        self.assertEqual((r.status_code, r.headers["Content-Type"]), (200, "video/mp4"))
        self.assertEqual(r.headers["Accept-Ranges"], "bytes")

    def test_iphone_style_range_requests_are_answered(self):
        self._put("clipA")
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        r = self.c.get("/vi/preview/clipA.mp4", headers={"Range": "bytes=0-1"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.data, self.MP4[:2])
        self.assertEqual(r.headers["Content-Range"], "bytes 0-1/%d" % len(self.MP4))
        r = self.c.get("/vi/preview/clipA.mp4", headers={"Range": "bytes=100-"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(len(r.data), len(self.MP4) - 100)
        r = self.c.get("/vi/preview/clipA.mp4", headers={"Range": "bytes=999999-"})
        self.assertEqual(r.status_code, 416)

    def test_the_library_shows_our_thumbnail_and_a_way_to_watch(self):
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        page = self.c.get("/vi/").data.decode("utf-8")
        self.assertIn("/vi/thumb/", page)
        self.assertIn("/vi/preview/", page)
        self.assertIn("Tap to watch", page)


class TestThePageHelps(VICase):
    """The page has to answer 'what do I type' and 'what do I do next'."""

    def setUp(self):
        VICase.setUp(self)
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        self.page = self.c.get("/vi/").data.decode("utf-8")

    def test_it_suggests_what_to_search_for(self):
        for chip in ("candlelight", "why parents enrolled", "night of champions"):
            self.assertIn(chip, self.page)

    def test_it_offers_a_way_to_act_on_results(self):
        self.assertIn("Make a video", self.page)
        self.assertIn("/vi/request", self.page)
        self.assertIn("/vi/queue", self.page)

    def test_it_offers_the_three_lengths(self):
        for v in ("value=\"15\"", "value=\"30\"", "value=\"60\""):
            self.assertIn(v, self.page)

    def test_it_separates_footage_from_talking(self):
        self.assertIn("Footage", self.page)
        self.assertIn("What people said", self.page)

    def test_clips_get_a_real_thumbnail(self):
        self.assertIn("drive.google.com/thumbnail", self.page)

    def test_ios_does_not_linkify_the_header(self):
        self.assertIn("format-detection", self.page)

    def test_it_asks_for_the_things_that_make_a_cut_possible(self):
        for hint in ("Name the moments", "How long", "who it is for"):
            self.assertIn(hint, self.page)


class TestTheMachineEditor(VICase):
    """Phase 3: the worker claims, delivers or fails; the person sees it and
    answers; nobody sees anyone else's video."""

    def setUp(self):
        VICase.setUp(self)
        del UPLOADS[:]
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        self.c.post("/vi/request", json={"note": "best moments for parents", "length": 30})
        self.c.post("/vi/request", json={"note": "candlelight", "length": 15})

    def _next(self):
        return self._j(self.c.get("/vi/jobs/next?worker=test&secret=" + SECRET))

    def _deliver(self, rid, size=250_000, summary=None):
        import io as _io
        data = {"secret": SECRET, "summary": json.dumps(summary or {"music_id": "01", "shots": [1, 2, 3]}),
                "seconds": "29.5", "video": (_io.BytesIO(b"v" * size), "VI_test_req%d.mp4" % rid)}
        return self.c.post("/vi/jobs/%d/deliver" % rid, data=data,
                           content_type="multipart/form-data")

    def test_the_worker_side_is_admin_only(self):
        self.assertEqual(self.c.get("/vi/jobs/next").status_code, 401)
        self.assertEqual(self.c.post("/vi/jobs/1/deliver").status_code, 401)
        self.assertEqual(self.c.post("/vi/jobs/1/fail", json={"error": "x"}).status_code, 401)
        self.assertEqual(self.c.post("/vi/drive-selftest").status_code, 401)

    def test_claiming_hands_out_the_oldest_first_and_only_once(self):
        a = self._next()["job"]; b = self._next()["job"]; c = self._next()["job"]
        self.assertEqual((a["id"], b["id"], c), (1, 2, None))
        self.assertEqual(self.store.requests[0]["state"], "rendering")
        self.assertEqual(a["length_s"], 30)
        self.assertIn("recent_music", a)

    def test_delivery_stores_the_file_in_drive_and_marks_it_ready(self):
        self._next()
        r = self._deliver(1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(UPLOADS[0]["bytes"], 250_000)
        row = self.store.get_request(1)
        self.assertEqual(row["state"], "ready")
        self.assertEqual(row["result_drive_id"], "drive-1")
        self.assertEqual(row["result_seconds"], 29.5)
        self.assertEqual(row["summary"]["music_id"], "01")
        self.assertIn("ready", " ".join(self.notes))

    def test_a_tiny_upload_is_not_a_video(self):
        self._next()
        self.assertEqual(self._deliver(1, size=10).status_code, 400)
        self.assertEqual(self.store.get_request(1)["state"], "rendering")

    def test_a_failed_drive_upload_is_a_failed_request_not_a_silent_one(self):
        self._next()
        c = Flask(__name__); c.config["TESTING"] = True
        vr.register(c, admin_ok, notify=self.notes.append, drive_upload=lambda n, d: None)
        tc = c.test_client()
        import io as _io
        r = tc.post("/vi/jobs/1/deliver", data={"secret": SECRET, "summary": "{}",
                    "video": (_io.BytesIO(b"v" * 300000), "x.mp4")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(self.store.get_request(1)["state"], "failed")
        self.assertIn("Drive", self.store.get_request(1)["error"])

    def test_the_worker_can_report_a_failure(self):
        self._next()
        r = self.c.post("/vi/jobs/1/fail?secret=" + SECRET, json={"error": "ffmpeg exploded", "worker": "test"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.store.get_request(1)["state"], "failed")
        self.assertIn("ffmpeg exploded", " ".join(self.notes))

    def test_admin_can_requeue_a_failed_cut(self):
        self._next()
        self.c.post("/vi/jobs/1/fail?secret=" + SECRET, json={"error": "x"})
        self.assertEqual(self.c.post("/vi/jobs/1/requeue").status_code, 401)
        self.assertEqual(self.c.post("/vi/jobs/1/requeue?secret=" + SECRET).status_code, 200)
        self.assertEqual(self._next()["job"]["id"], 1)
        self.assertEqual(self.c.post("/vi/jobs/99/requeue?secret=" + SECRET).status_code, 404)

    def test_the_music_this_person_already_heard_travels_with_the_next_job(self):
        self._next(); self._deliver(1, summary={"music_id": "05"})
        job = self._next()["job"]
        self.assertEqual(job["recent_music"], ["05"])

    def test_the_clips_this_person_already_saw_travel_with_the_next_job(self):
        self._next(); self._deliver(1, summary={"shots": [{"id": "A"}, {"id": "B"}]})
        job = self._next()["job"]
        self.assertEqual(job["recent_clips"], ["A", "B"])

    def test_the_page_offers_words_on_screen_and_an_end_card(self):
        page = self.c.get("/vi/").data.decode("utf-8")
        self.assertIn("Words on screen", page)
        self.assertIn("End card", page)

    def test_i_see_my_videos_and_only_mine(self):
        self._next(); self._deliver(1)
        mine = self._j(self.c.get("/vi/mine"))
        self.assertEqual(mine["count"], 2)
        self.assertEqual(mine["requests"][0]["state"], "asked")     # newest first
        self.assertIn("preview_url", mine["requests"][1])
        self.assertTrue(mine["busy"])
        # someone else at Victory sees nothing of Jim's
        self.c.get("/vi/logout")
        self._sign_in_as("ann@victoryma.com", va.ROLE_SCHOOL, "Lake Nona")
        self.assertEqual(self._j(self.c.get("/vi/mine"))["count"], 0)
        page = self.c.get("/vi/queue").data.decode("utf-8")
        self.assertNotIn("best moments for parents", page)

    def test_mwm_sees_everyone(self):
        self.c.get("/vi/logout")
        self._sign_in_as("michael@mwmcreations.com", va.ROLE_MWM)
        mine = self._j(self.c.get("/vi/mine"))
        self.assertEqual(mine["count"], 2)
        self.assertTrue(mine["all"])

    def test_the_page_plays_the_cut_and_asks_what_i_think(self):
        self._next(); self._deliver(1)
        page = self.c.get("/vi/queue").data.decode("utf-8")
        self.assertIn("drive.google.com/file/d/drive-1/preview", page)
        self.assertIn("Send feedback", page)
        self.assertIn("Approve", page)
        self.assertIn("Cut it again", page)
        self.assertIn("Download", page)

    def test_feedback_is_kept_and_dev_hears_it(self):
        self._next(); self._deliver(1)
        r = self.c.post("/vi/feedback", json={"id": 1, "text": "music too loud, and the wide shots drag"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.store.feedback[0]["email"], "jim@victoryma.com")
        self.assertIn("music too loud", " ".join(self.notes))
        page = self.c.get("/vi/queue").data.decode("utf-8")
        self.assertIn("music too loud", page)

    def test_feedback_on_someone_elses_video_is_refused(self):
        self.c.get("/vi/logout")
        self._sign_in_as("ann@victoryma.com", va.ROLE_SCHOOL, "Lake Nona")
        self.assertEqual(self.c.post("/vi/feedback", json={"id": 1, "text": "hi"}).status_code, 404)
        self.assertEqual(self.c.post("/vi/decide", json={"id": 1, "decision": "approved"}).status_code, 404)

    def test_empty_feedback_is_refused(self):
        self.assertEqual(self.c.post("/vi/feedback", json={"id": 1, "text": "  "}).status_code, 400)

    def test_redo_puts_it_back_in_the_queue(self):
        self._next(); self._deliver(1)
        r = self.c.post("/vi/decide", json={"id": 1, "decision": "redo"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.store.get_request(1)["state"], "asked")
        self.assertEqual(self._next()["job"]["id"], 1)

    def test_approve_and_a_nonsense_decision(self):
        self._next(); self._deliver(1)
        self.assertEqual(self.c.post("/vi/decide", json={"id": 1, "decision": "approved"}).status_code, 200)
        self.assertEqual(self.store.get_request(1)["state"], "approved")
        self.assertEqual(self.c.post("/vi/decide", json={"id": 1, "decision": "burn"}).status_code, 400)

    def test_health_reports_the_queue(self):
        h = self._j(self.c.get("/vi/health?secret=" + SECRET))
        self.assertEqual(h["queue"], {"asked": 2})

    def test_a_signed_out_person_sees_the_door_not_the_queue(self):
        self.c.get("/vi/logout")
        self.assertEqual(self.c.get("/vi/mine").status_code, 401)
        self.assertIn("Sign in", self.c.get("/vi/queue").data.decode("utf-8"))


class TestTimesAreEastern(unittest.TestCase):
    def test_a_utc_timestamp_reads_in_victory_time(self):
        import victory_page as vp
        self.assertEqual(vp._when("2026-09-17 01:15:12.300542+00:00"), "Sep 16, 9:15 PM")
        self.assertEqual(vp._when("2026-01-17 01:15:12"), "Jan 16, 8:15 PM")
        self.assertEqual(vp._when(None), "")


class TestNamingMoments(VICase):
    """Michael, 16 Sep: the long recordings must become many short, named
    moments people can pick. The naming goes through the app's Claude."""
    JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 400

    def _post(self, **kw):
        import io as _io
        data = {"sheet": (_io.BytesIO(self.JPEG), "s.jpg"), "context": "Night of Champions, Saturday"}
        data.update(kw)
        return self.c.post("/vi/moments/describe", data=data, content_type="multipart/form-data")

    def test_victory_staff_cannot_spend_model_calls(self):
        self.assertEqual(self._post().status_code, 401)
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        self.assertEqual(self._post().status_code, 401)

    def test_mwm_gets_a_name_a_category_and_a_rating(self):
        self._sign_in_as("dev@mwmcreations.com", va.ROLE_MWM)
        r = self._post()
        self.assertEqual(r.status_code, 200, r.data)
        d = self._j(r)
        self.assertEqual(d["title"], "Belt handed to a kneeling student")
        self.assertEqual(d["category"], "Belt & rank presentation")
        self.assertEqual(d["interest"], 5)
        self.assertIn("belt", d["keywords"])
        call = self.c.fake_claude.calls[-1]
        self.assertIn("Night of Champions", call["messages"][0]["content"][1]["text"])
        self.assertEqual(call["messages"][0]["content"][0]["type"], "image")

    def test_the_secret_works_too_and_junk_is_refused(self):
        import io as _io
        r = self.c.post("/vi/moments/describe?secret=%s" % SECRET,
                        data={"sheet": (_io.BytesIO(self.JPEG), "s.jpg")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        r = self.c.post("/vi/moments/describe?secret=%s" % SECRET,
                        data={"sheet": (_io.BytesIO(b"notajpeg"), "s.jpg")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_answers_are_normalised(self):
        import victory_describe as vd
        d = vd.parse_answer('Sure! {"title": "Kids   cheering.", "category": "crowd & parent reactions", '
                            '"keywords": "kids cheering mat medals", "interest": "4.6"} thanks')
        self.assertEqual(d["title"], "Kids cheering")
        self.assertEqual(d["category"], "Crowd & parent reactions")
        self.assertEqual(d["keywords"], ["kids", "cheering", "mat", "medals"])
        self.assertEqual(d["interest"], 5)
        self.assertIsNone(vd.parse_answer("no json here"))
        self.assertIsNone(vd.parse_answer('{"title": ""}'))
        self.assertEqual(vd.parse_answer('{"title": "x", "category": "Belts"}')["category"],
                         "Belt & rank presentation")


class TestPublishedMoments(VICase):
    """The Mini cuts and names moments on its own and hands them over; the
    Library grows without a deploy (Michael, 17 Sep: "do it")."""
    ITEM = {"id": "VWC26_NOC_900_test-moment_TEST00001", "title": "Test moment", "category": "Winning moments",
            "file": "long/VWC26_NOC_900_test-moment_TEST00001.mp4", "session": "Night of Champions", "day": 3,
            "seconds": 12.0, "priority": "high", "weight": 0.85, "text": "test moment night of champions",
            "reframe": {"duration": 12.0, "windows": [{"t": 0, "ax": 0.5, "energy": 1, "faces": 0}]}}

    def test_admin_only(self):
        self.assertEqual(self.c.post("/vi/moments/publish", json={"event": "VWC26", "clips": [self.ITEM]}).status_code, 401)
        self.assertEqual(self.c.get("/vi/moments/published?event=VWC26").status_code, 401)

    def test_published_moments_join_the_library_and_come_back_with_windows(self):
        r = self.c.post("/vi/moments/publish?secret=%s" % SECRET, json={"event": "VWC26", "clips": [self.ITEM]})
        self.assertIn(r.status_code, (200, 500))          # ingest needs Postgres; storing does not
        self.assertEqual(self._j(r)["stored"], 1)
        r = self._j(self.c.get("/vi/moments/published?secret=%s&event=VWC26" % SECRET))
        self.assertEqual(r["clips"][0]["id"], self.ITEM["id"])
        self.assertEqual(r["clips"][0]["reframe"]["duration"], 12.0)
        # the media list now wants a picture for it too
        m = self._j(self.c.get("/vi/media/missing?secret=%s&limit=500" % SECRET))
        self.assertIn(self.ITEM["id"], m["missing"])
        # and build_rows folds it in after the file's clips, once
        import victory_ingest as ing
        _, _, recs = ing.build_rows("VWC26", [self.ITEM, self.ITEM, {"id": "VWC26_BELT_01_hall-wide-flags_D0232"}])
        ids = [x["id"] for x in recs if x["kind"] == "clip"]
        self.assertEqual(ids.count("VWC26:" + self.ITEM["id"]), 1)
        self.assertEqual(len(ids), 326)

    def test_junk_is_refused(self):
        self.assertEqual(self.c.post("/vi/moments/publish?secret=%s" % SECRET, json={"event": "NOPE", "clips": [self.ITEM]}).status_code, 404)
        self.assertEqual(self.c.post("/vi/moments/publish?secret=%s" % SECRET, json={"event": "VWC26", "clips": []}).status_code, 400)


class TestQueuePageIsLightOnAPhone(VICase):
    """Twenty Drive players on one page crashed Safari on Michael's phone
    (17 Sep). Finished cuts show a Watch button; the player loads on a tap."""

    def test_finished_cuts_are_placeholders_not_players(self):
        self._sign_in_as("dev@mwmcreations.com", va.ROLE_MWM)
        for i in range(3):
            rid = self.store.create_request("dev@mwmcreations.com", "mwm", "", "test %d" % i, [], 30)
            self.store.set_request_state(rid, "rendering", "w")
            self.store.finish_request(rid, "ready", drive_id="drive%d" % i, file_name="x.mp4", size=10,
                                      seconds=30, summary={"shots": []})
        body = self.c.get("/vi/queue").data.decode("utf-8")
        self.assertNotIn("<iframe", body)
        self.assertEqual(body.count('class="player pl"'), 3)
        self.assertIn("openPlayer", body)


class TestTheFrontDoorIsOneBox(VICase):
    """Michael, 17 Sep: most people only describe what they want; clips are
    shown only to those who flip "I want to choose my own clips"."""

    def test_the_door_shows_no_clips_until_asked(self):
        self._sign_in_as("dev@mwmcreations.com", va.ROLE_MWM)
        body = self.c.get("/vi/").data.decode("utf-8")
        self.assertIn('id="note"', body)
        self.assertIn('id="pickmode"', body)
        self.assertIn("I want to choose my own clips", body)
        self.assertIn('id="picker" class="picker" hidden', body)
        self.assertIn('id="brief"', body)
        self.assertIn("Browse footage", body)
        self.assertIn('href="/vi/library"', body)

    def test_browse_footage_is_the_library_on_its_own(self):
        self._sign_in_as("dev@mwmcreations.com", va.ROLE_MWM)
        body = self.c.get("/vi/library").data.decode("utf-8")
        self.assertIn('id="q"', body)
        self.assertNotIn('id="note"', body)
        self.assertNotIn('id="pickmode"', body)
        self.assertIn('<main class="browse">', body)

    def test_the_brief_reads_the_sentence(self):
        self._sign_in_as("dev@mwmcreations.com", va.ROLE_MWM)
        d = self.c.get("/vi/brief?q=" + "a 15 second reel for students, very fast, from the Night of Champions "
                       "and some board breaks&length=30").get_json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["length"], 15)
        self.assertTrue(d["length_said"])
        self.assertIn("Night of Champions", d["text"])
        self.assertIn("board break", d["text"].lower())
        self.assertIn("students", d["text"])
        self.assertIn("fast", d["text"])
        d = self.c.get("/vi/brief?q=something%20nice&length=60").get_json()
        self.assertEqual(d["length"], 60)
        self.assertFalse(d["length_said"])

    def test_the_brief_needs_a_session(self):
        self.assertEqual(self.c.get("/vi/brief?q=x").status_code, 401)
        self.assertEqual(self.c.get("/vi/library").status_code, 200)   # the sign-in door
        self.assertIn("/vi/login", self.c.get("/vi/library").data.decode("utf-8"))

    def test_my_videos_says_what_was_understood(self):
        self._sign_in_as("dev@mwmcreations.com", va.ROLE_MWM)
        rid = self.store.create_request("dev@mwmcreations.com", "mwm", "",
                                        "15 seconds for students, fast, night of champions", [], 15)
        self.store.set_request_state(rid, "rendering", "w")
        self.store.finish_request(rid, "ready", drive_id="d1", file_name="x.mp4", size=10,
                                  seconds=15, summary={"shots": []})
        body = self.c.get("/vi/queue").data.decode("utf-8")
        self.assertIn("Understood as", body)
        self.assertIn("Night of Champions", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
