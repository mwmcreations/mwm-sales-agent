#!/usr/bin/env python3
"""Tests for the rendered GOLD panel (wordpress/roadmap/gold-panel.php).

test_roadmap_entitlement.py proves the RULES. This file proves the PAGE — it
renders real markup and reads it back, because ROB's §2 rule is about what a
client sees, and a rule about a screen has to be tested on the screen.

  ROB, Sep 11: "a client will hold us to the screen, not the PDF."

TestNothingReadsAsABalanceOwed renders every state the panel has — nothing
delivered, some delivered, hours unknown, hours spent — and greps the output
for the shapes that create an obligation. It is deliberately a blacklist over
rendered HTML rather than an assertion about one function, because the failure
mode is a sentence someone adds later without thinking about the contract.
"""
import json
import os
import re
import subprocess
import unittest

# ── where these tests can actually run ────────────────────────────────────
# There is no PHP on the device VM, only in the cloud container. A test that
# cannot run should SAY SO, not fail — an error here would read as a
# regression in the repo sweep and train people to ignore a red result.
import shutil

PHP = shutil.which("php")
if PHP is None:
    # Exit 0 deliberately. The repo sweep runs each test file as a script and
    # reads its exit code, so raising here would mark a healthy file as failing.
    print("SKIPPED — php is not installed on this machine. These tests render "
          "real PHP, so they run in the cloud container, not on the device.")
    raise SystemExit(0)


HERE = os.path.dirname(os.path.abspath(__file__))

def _find(name):
    """The PHP lives in wordpress/roadmap/; the tests live at the repo root.

    Falls back to alongside the test so the same file runs from a scratch build
    directory — the two copies must never diverge, and a test that only runs in
    one place is how they do.
    """
    for p in (os.path.join(HERE, "wordpress", "roadmap", name),
              os.path.join(HERE, "docs", "roadmap-seed", name),
              os.path.join(HERE, name)):
        if os.path.exists(p):
            return p
    raise RuntimeError("cannot find %s" % name)
ENT = _find("entitlement.php")
PANEL = _find("gold-panel.php")
DATA = _find("luzia_data.json")


def render(used_location=0.0, used_studio=0.0, anchor=None, assets=None, campaigns=None):
    """Render the panel exactly as WordPress would, and hand back the HTML."""
    assets = assets if assets is not None else []
    code = """
    require '%s'; require '%s';
    $d = json_decode(file_get_contents('%s'), true);
    %s
    $hs = null;
    %s
    echo mwm_rm_gold_panel($d, $hs, json_decode('%s', true));
    """ % (
        ENT, PANEL, DATA,
        ("$d['campaigns'] = json_decode('%s', true);" % json.dumps(campaigns)) if campaigns is not None else "",
        ("""$cy = mwm_rm_cycle_window(%d, '2026-09-20');
            $hs = mwm_rm_hours_state('gold', %r, %r, $cy);""" % (anchor, used_location, used_studio))
        if anchor else "",
        json.dumps(assets).replace("'", "\\'"),
    )
    r = subprocess.run(["php", "-r", code], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError("php failed: %s%s" % (r.stdout, r.stderr))
    return r.stdout


DELIVERED = [
    {"title": "Institutional film", "kind": "hero", "qty": 1,
     "delivered_at": "2026-09-01", "url": "https://example.com/a"},
    {"title": "Vertical cuts", "kind": "short", "qty": 10, "delivered_at": "2026-09-02"},
    {"title": "Teaser (in edit)", "kind": "short", "qty": 3, "delivered_at": None},
]


# ── 🔴 the rule with money in it ──────────────────────────────────────────
class TestNothingReadsAsABalanceOwed(unittest.TestCase):

    # Phrases that turn a ceiling into a debt on screen. Each one is a sentence
    # a reasonable person might write while "improving" the page.
    FORBIDDEN = [
        r"\bremaining\b",
        r"\boutstanding\b",
        r"\bstill to (?:be )?(?:deliver|come)",
        r"\bowed\b",
        r"\byet to be delivered\b",
        r"\bshorts? left\b",
        r"\bvideos? left\b",
        r"\bepisodes? left\b",
        r"\bof (?:your )?\d+ (?:shorts|videos|episodes|films|cuts)\b",
        r"\b\d+\s*/\s*\d+\s*(?:shorts|videos|episodes|films|cuts)\b",
        r"\bup to \d+ (?:shorts|videos|episodes)\b.*\bleft\b",
    ]

    def _scan(self, html, label):
        low = html.lower()
        for pat in self.FORBIDDEN:
            m = re.search(pat, low)
            self.assertIsNone(
                m,
                "%s rendered %r — that is a balance owed against a ceiling, and "
                "the signed contract does not create one (ROB §2)"
                % (label, m.group(0) if m else pat))

    def test_empty_state(self):
        self._scan(render(), "the empty portal")

    def test_with_deliveries(self):
        self._scan(render(assets=DELIVERED, anchor=14, used_location=1.5), "the delivered state")

    def test_with_hours_fully_spent(self):
        self._scan(render(anchor=14, used_location=4, used_studio=4, assets=DELIVERED),
                   "the fully-spent state")

    def test_with_a_roadmap(self):
        self._scan(render(campaigns=[{"month_no": 1, "title": "Institutional", "status": "delivered"}],
                          assets=DELIVERED, anchor=14), "the roadmap state")

    def test_no_ceiling_number_appears_next_to_a_delivered_count(self):
        """The ceilings are 2, 20, 1 and 10. None may sit in the delivered section."""
        html = render(assets=DELIVERED, anchor=14)
        block = html.split('rm-delivered')[1].split('</section>')[0]
        for n in ("20", "2 videos", "10 shorts", "1 episode"):
            self.assertNotIn(n, block,
                             "the delivered section mentions %r — that is the ceiling "
                             "leaking into the place it must never appear" % n)

    def test_delivered_counts_only_what_is_delivered(self):
        html = render(assets=DELIVERED)
        self.assertIn("11 films delivered", html)   # 1 hero + 10 shorts; the 3 in edit excluded


# ── §1 · hours ────────────────────────────────────────────────────────────
class TestHoursAreShownBecauseTheyExpire(unittest.TestCase):

    def test_it_says_hours_do_not_carry_over(self):
        html = render(anchor=14, used_location=1.5)
        self.assertIn("do not carry over", html)

    def test_it_names_the_date_they_die(self):
        self.assertIn("13 October 2026", render(anchor=14, used_location=1.5))

    def test_it_shows_hours_left(self):
        html = render(anchor=14, used_location=1.5, used_studio=0.5)
        self.assertIn("2.5 h left", html)
        self.assertIn("3.5 h left", html)

    def test_it_says_travel_does_not_eat_the_window(self):
        self.assertIn("Travel never comes out of your hours", render(anchor=14))

    def test_an_unknown_cycle_says_so_instead_of_guessing(self):
        """🔴 Her contract has no start date. A guessed anchor expires her hours
        on the wrong day and nothing on screen would admit it."""
        html = render()   # no anchor
        self.assertIn("confirming that with you", html)
        self.assertNotIn("h left", html)


# ── spec §11.2 · the empty-year rule ─────────────────────────────────────
class TestEmptyStatesAreHonestNotPunishing(unittest.TestCase):

    def test_no_roadmap_yet_reads_as_being_built(self):
        html = render()
        self.assertIn("building your annual roadmap", html)

    def test_it_does_not_render_twelve_empty_boxes(self):
        """Spec §11.2 — twelve blank months is twelve reminders that nothing
        has happened, inside a product she already pays for."""
        html = render()
        self.assertLessEqual(html.count('class="rm-campaign"'), 0)
        for word in ("locked", "padlock", "upgrade to unlock"):
            self.assertNotIn(word, html.lower())

    def test_nothing_delivered_yet_is_a_promise_not_a_blank(self):
        self.assertIn("Everything we finish will appear here", render())


# ── §5 · nothing is booked without written approval ──────────────────────
class TestRequestsNeverReadAsBooked(unittest.TestCase):

    def test_a_held_date_says_it_is_not_booked(self):
        html = render()
        self.assertIn("nothing is booked until you confirm in writing", html)

    def test_the_miami_request_is_not_approved(self):
        html = render()
        self.assertIn('data-state="requested"', html)
        self.assertIn("Waiting for your go-ahead", html)

    def test_the_quoted_total_and_travel_are_both_shown(self):
        html = render()
        self.assertIn("$2,050", html)
        self.assertIn("$1,000 travel, zone 4", html)


# ── §3/§5 · prices on the page, before she acts ──────────────────────────
class TestPricesArePublishedUpFront(unittest.TestCase):

    def test_her_annual_rates_not_the_standalone_ones(self):
        html = render()
        self.assertIn("$249 / hour", html)      # annual studio hour
        self.assertNotIn("$349", html)          # standalone — not her price
        self.assertIn("$1,750", html)
        self.assertIn("$2,500", html)
        self.assertIn("$300 / hour", html)

    def test_editing_shows_as_included_not_as_zero(self):
        html = render()
        self.assertIn("Editing on add-ons", html)
        self.assertNotIn("$0", html)

    def test_the_travel_table_is_on_the_page(self):
        html = render()
        for fee in ("Included", "$300", "$600", "$1,000", "On request"):
            self.assertIn(fee, html)

    def test_it_says_what_travel_excludes(self):
        self.assertIn("tolls, parking, lodging", render())

    def test_it_says_addons_go_on_the_next_invoice(self):
        html = render()
        self.assertIn("next invoice", html)
        self.assertIn("No deposit", html)

    def test_it_says_availability_is_not_guaranteed(self):
        self.assertIn("subject to studio and crew availability", render())


class TestTerms(unittest.TestCase):

    def test_the_contract_numbers_appear(self):
        html = render()
        self.assertIn("3 rounds per campaign", html)
        self.assertIn("$250 each", html)
        self.assertIn("72 hours", html)
        self.assertIn("$25 per minute", html)

    def test_early_termination_is_stated_not_hidden(self):
        self.assertIn("two months", render().lower())

    def test_it_does_not_repeat_the_cancel_anytime_wording(self):
        """🔴 ROB §7 — /order/ says "Cancel or upgrade anytime", which
        contradicts ToS §13/§14. The portal must never inherit that sentence."""
        low = render().lower()
        self.assertNotIn("cancel anytime", low)
        self.assertNotIn("cancel or upgrade anytime", low)


class TestMarkupIsSafe(unittest.TestCase):

    def test_client_data_is_escaped(self):
        html = subprocess.run(
            ["php", "-r", """
             require '%s'; require '%s';
             $d = json_decode(file_get_contents('%s'), true);
             $d['client']['client_name'] = '<script>alert(1)</script>';
             echo mwm_rm_gold_panel($d, null, array());
            """ % (ENT, PANEL, DATA)],
            capture_output=True, text=True, timeout=30).stdout
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_an_asset_url_is_escaped(self):
        html = render(assets=[{"title": "x", "kind": "hero", "qty": 1,
                               "delivered_at": "2026-09-01",
                               "url": '"><script>alert(1)</script>'}])
        self.assertNotIn("<script>alert", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
