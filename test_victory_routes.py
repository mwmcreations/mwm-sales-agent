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


_REAL = {}


def install_fake_store(fake):
    """Swap victory_store's functions for the fake's bound methods."""
    for name in ("init_schema", "session_secret", "create_link", "consume_link",
                 "get_person", "remember_person", "grant", "list_people",
                 "log_search", "recent_searches", "purge_links"):
        _REAL.setdefault(name, getattr(vs, name))
        setattr(vs, name, getattr(fake, name))


def restore_store():
    for name, fn in _REAL.items():
        setattr(vs, name, fn)


def make_client(notes=None):
    app = Flask(__name__)
    app.config["TESTING"] = True
    vr.register(app, admin_ok, notify=(notes.append if notes is not None else None))
    return app.test_client()


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
        self.assertEqual(self._j(r)["found"], 34)


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
        self.assertEqual(self._j(r)["found"], 34)

    def test_a_granted_person_sees_the_app(self):
        self._sign_in_as("jim@victoryma.com", va.ROLE_HQ)
        body = self.c.get("/vi/").data.decode("utf-8")
        self.assertIn("Search", body)
        self.assertIn("1,873", body)

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
        self.assertEqual(self._s("candlelight")["found"], 34)

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
        self.assertEqual(self._j(r)["found"], 34)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
