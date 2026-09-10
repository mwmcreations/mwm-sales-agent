"""test_victory_auth.py — Phase 2: the door.

This is the file where a mistake is expensive, so the tests are written
against the attacks rather than against the happy path: forged sessions,
expired links, replayed links, timing, enumeration, and the question that
matters most — can someone we have not granted anything actually see anything.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import victory_auth as va

SECRET = "a-test-signing-secret-that-is-long-enough"


class TestAddresses(unittest.TestCase):
    def test_normalises_case_and_space(self):
        self.assertEqual(va.normalize_email("  Jim@VictoryMA.com "), "jim@victoryma.com")

    def test_rejects_nonsense(self):
        for bad in ("", None, "jim", "jim@", "@victoryma.com", "a b@c.com", "jim@com"):
            self.assertEqual(va.normalize_email(bad), "", repr(bad))

    def test_does_not_strip_dots_or_tags(self):
        # 'a.b@' and 'ab@' may be two different people at a Workspace domain;
        # merging them would hand one person another's access.
        self.assertEqual(va.normalize_email("master-john.faett@victoryma.com"),
                         "master-john.faett@victoryma.com")
        self.assertEqual(va.normalize_email("jim+test@victoryma.com"),
                         "jim+test@victoryma.com")

    def test_only_two_domains_may_receive_a_link(self):
        self.assertTrue(va.is_allowed("jim@victoryma.com"))
        self.assertTrue(va.is_allowed("michael@mwmcreations.com"))
        for bad in ("someone@gmail.com", "attacker@victoryma.com.evil.net",
                    "x@notvictoryma.com", "x@sub.victoryma.com"):
            self.assertFalse(va.is_allowed(bad), bad)

    def test_lookalike_domains_are_refused(self):
        for bad in ("x@victoryma.co", "x@victorymma.com", "x@vlctoryma.com"):
            self.assertFalse(va.is_allowed(bad), bad)


class TestDefaultRole(unittest.TestCase):
    def test_our_own_domain_is_trusted(self):
        self.assertEqual(va.default_role("michael@mwmcreations.com"), va.ROLE_MWM)

    def test_an_unknown_victory_address_gets_nothing(self):
        # THE most important assertion in this file: signing in is not access.
        role = va.default_role("someone-new@victoryma.com")
        self.assertEqual(role, va.ROLE_PENDING)
        self.assertFalse(va.can_search(role))

    def test_a_stranger_has_no_role_at_all(self):
        self.assertEqual(va.default_role("x@gmail.com"), "")

    def test_only_granted_roles_can_search(self):
        self.assertTrue(va.can_search(va.ROLE_HQ))
        self.assertTrue(va.can_search(va.ROLE_SCHOOL))
        self.assertTrue(va.can_search(va.ROLE_MWM))
        self.assertFalse(va.can_search(va.ROLE_PENDING))
        self.assertFalse(va.can_search(""))
        self.assertFalse(va.can_search("admin"))


class TestTokens(unittest.TestCase):
    def test_tokens_are_unique_and_long(self):
        seen = set()
        for _ in range(200):
            t, h = va.new_token()
            self.assertGreaterEqual(len(t), 32)
            self.assertNotIn(t, seen)
            seen.add(t)

    def test_the_token_is_never_the_stored_value(self):
        t, h = va.new_token()
        self.assertNotEqual(t, h)
        self.assertNotIn(t, h)

    def test_hash_is_stable_and_matches(self):
        t, h = va.new_token()
        self.assertEqual(va.hash_token(t), h)
        self.assertTrue(va.token_matches(t, h))

    def test_a_wrong_token_does_not_match(self):
        t, h = va.new_token()
        other, _ = va.new_token()
        self.assertFalse(va.token_matches(other, h))
        self.assertFalse(va.token_matches("", h))
        self.assertFalse(va.token_matches(None, h))
        self.assertFalse(va.token_matches(t, ""))

    def test_links_expire(self):
        now = 1_000_000.0
        self.assertFalse(va.link_expired(now, now=now))
        self.assertFalse(va.link_expired(now, now=now + va.LINK_TTL_SECONDS - 1))
        self.assertTrue(va.link_expired(now, now=now + va.LINK_TTL_SECONDS + 1))

    def test_a_missing_issue_time_counts_as_expired(self):
        self.assertTrue(va.link_expired(None, now=time.time()))
        self.assertTrue(va.link_expired(0, now=time.time()))

    def test_ttl_is_short(self):
        self.assertLessEqual(va.LINK_TTL_SECONDS, 30 * 60)


class TestSessions(unittest.TestCase):
    def test_roundtrip(self):
        v = va.sign_session("jim@victoryma.com", va.ROLE_HQ, "", SECRET)
        got = va.verify_session(v, SECRET)
        self.assertEqual(got["email"], "jim@victoryma.com")
        self.assertEqual(got["role"], va.ROLE_HQ)

    def test_school_is_carried(self):
        v = va.sign_session("lakenona@victoryma.com", va.ROLE_SCHOOL, "Lake Nona", SECRET)
        self.assertEqual(va.verify_session(v, SECRET)["school"], "Lake Nona")

    def test_a_tampered_payload_is_refused(self):
        v = va.sign_session("x@victoryma.com", va.ROLE_PENDING, "", SECRET)
        body, sig = v.rsplit(".", 1)
        forged = va._b64(b"x@victoryma.com|hq||" + str(int(time.time())).encode()) + "." + sig
        self.assertIsNone(va.verify_session(forged, SECRET),
                          "escalating pending -> hq must fail the signature")

    def test_a_different_secret_is_refused(self):
        v = va.sign_session("jim@victoryma.com", va.ROLE_HQ, "", SECRET)
        self.assertIsNone(va.verify_session(v, SECRET + "x"))

    def test_no_secret_signs_nothing_and_trusts_nothing(self):
        self.assertEqual(va.sign_session("jim@victoryma.com", va.ROLE_HQ, "", ""), "")
        self.assertIsNone(va.verify_session("anything.atall", ""))

    def test_garbage_is_refused_not_raised(self):
        for bad in ("", None, "no-dot", ".", "a.b", "!!!.???", "x" * 5000,
                    "eyJ.abc", 12345, b"bytes.sig"):
            self.assertIsNone(va.verify_session(bad, SECRET), repr(bad)[:40])

    def test_sessions_expire(self):
        old = int(time.time()) - va.SESSION_TTL_SECONDS - 10
        v = va.sign_session("jim@victoryma.com", va.ROLE_HQ, "", SECRET, issued_at=old)
        self.assertIsNone(va.verify_session(v, SECRET))

    def test_a_session_from_the_future_is_refused(self):
        soon = int(time.time()) + 86400
        v = va.sign_session("jim@victoryma.com", va.ROLE_HQ, "", SECRET, issued_at=soon)
        self.assertIsNone(va.verify_session(v, SECRET))

    def test_an_unknown_role_cannot_be_signed(self):
        self.assertEqual(va.sign_session("jim@victoryma.com", "superuser", "", SECRET), "")

    def test_a_bad_address_cannot_be_signed(self):
        self.assertEqual(va.sign_session("not-an-email", va.ROLE_HQ, "", SECRET), "")

    def test_the_session_carries_no_secret(self):
        v = va.sign_session("jim@victoryma.com", va.ROLE_HQ, "", SECRET)
        self.assertNotIn(SECRET, v)


class TestRateLimiter(unittest.TestCase):
    def setUp(self):
        self.rl = va.RateLimiter(window=60)

    def test_allows_up_to_the_limit_then_refuses(self):
        for i in range(5):
            self.assertTrue(self.rl.allow("a@b.com", 5), i)
        self.assertFalse(self.rl.allow("a@b.com", 5))

    def test_keys_are_independent(self):
        for _ in range(5):
            self.rl.allow("a@b.com", 5)
        self.assertTrue(self.rl.allow("c@d.com", 5))

    def test_the_window_slides(self):
        now = 1_000_000.0
        for _ in range(5):
            self.rl.allow("a@b.com", 5, now=now)
        self.assertFalse(self.rl.allow("a@b.com", 5, now=now + 10))
        self.assertTrue(self.rl.allow("a@b.com", 5, now=now + 61))

    def test_an_empty_key_is_not_limited(self):
        for _ in range(50):
            self.assertTrue(self.rl.allow("", 5))

    def test_limits_are_set_low_enough_to_matter(self):
        self.assertLessEqual(va.LINK_MAX_PER_EMAIL, 10)
        self.assertLessEqual(va.LINK_MAX_PER_IP, 30)


class TestLinkEmail(unittest.TestCase):
    def test_contains_the_url_once(self):
        url = "https://example.com/vi/auth?token=abc"
        self.assertEqual(va.link_email_text(url).count(url), 1)
        self.assertEqual(va.link_email_html(url).count(url), 1)

    def test_states_the_expiry(self):
        self.assertIn("15 minutes", va.link_email_text("u"))

    def test_says_it_is_single_use(self):
        self.assertIn("once", va.link_email_text("u"))

    def test_tells_an_unexpecting_recipient_what_to_do(self):
        self.assertIn("ignore", va.link_email_text("u").lower())

    def test_subject_names_the_product(self):
        self.assertIn("Victory Intelligence", va.LINK_SUBJECT)


class TestNamedExternalAddresses(unittest.TestCase):
    """Victory's leadership is not all on victoryma.com.

    Three of the people on every leadership thread use me.com, yahoo.com and
    aol.com addresses. Refusing them would have quietly excluded senior people
    from their own platform — but trusting those DOMAINS would be reckless.
    The rule is: one named address, granted by a human.
    """

    def test_an_external_address_is_refused_by_default(self):
        self.assertFalse(va.is_allowed("lnery1@me.com"))
        self.assertFalse(va.is_allowed("rubenvon@yahoo.com"))
        self.assertFalse(va.is_allowed("victoryhvs@aol.com"))

    def test_a_known_external_address_is_allowed(self):
        self.assertTrue(va.is_allowed("lnery1@me.com", known=True))

    def test_knowing_one_address_does_not_trust_the_domain(self):
        self.assertTrue(va.is_allowed("victoryhvs@aol.com", known=True))
        self.assertFalse(va.is_allowed("someone-else@aol.com"))
        for d in ("aol.com", "me.com", "yahoo.com"):
            self.assertNotIn(d, va.ALLOWED_DOMAINS)

    def test_is_external_identifies_the_right_addresses(self):
        for e in ("lnery1@me.com", "rubenvon@yahoo.com", "victoryhvs@aol.com",
                  "ninja@cpcninja.com"):
            self.assertTrue(va.is_external(e), e)
        for e in ("gmvs@victoryma.com", "michael@mwmcreations.com"):
            self.assertFalse(va.is_external(e), e)

    def test_an_external_address_has_no_default_role(self):
        # it can only ever be here because a grant put it here
        self.assertEqual(va.default_role("lnery1@me.com"), "")
        self.assertFalse(va.can_search(va.default_role("lnery1@me.com")))

    def test_rubbish_is_not_external_it_is_nothing(self):
        self.assertFalse(va.is_external("not-an-email"))
        self.assertFalse(va.is_external(""))
        self.assertFalse(va.is_external(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
