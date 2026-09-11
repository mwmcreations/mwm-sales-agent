#!/usr/bin/env python3
"""Tests for the GOLD ROADMAP entitlement model (wordpress/roadmap/entitlement.php).

WHY THESE RUN PHP
The portal renders in PHP, so the rules live in PHP. Duplicating them in Python
to make them testable would create two sources of truth that drift — and the
thing most worth testing here is a rule about what may appear ON A PAGE. So the
tests drive the real file through the php CLI. What is asserted is what ships.

THE ONE THAT MATTERS
ROB, Sep 11: "THE PORTAL MUST NEVER RENDER THESE AS A BALANCE OWED... a client
will hold us to the screen, not the PDF." TestCeilingsAreNeverABalance is that
rule made executable. It is deliberately structural: it asserts that the
delivered-count function has no way to accept a ceiling, so the subtraction has
nowhere to happen. A rule you can only honour by remembering is a rule that
gets broken by the next person in the file.
"""
import json
import os
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
              os.path.join(HERE, name)):
        if os.path.exists(p):
            return p
    raise RuntimeError("cannot find %s" % name)
ENT = _find("entitlement.php")


def php(expr_body):
    """Run PHP against the real entitlement file, return the decoded JSON."""
    code = "require '%s'; %s" % (ENT, expr_body)
    r = subprocess.run(["php", "-r", code], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError("php failed: %s%s" % (r.stdout, r.stderr))
    out = r.stdout.strip()
    return json.loads(out) if out else None


def php_lit(v):
    """Python value -> PHP literal.

    json.dumps is almost right and quietly wrong: `{"a": 1}` is valid JSON and a
    parse error in PHP. Lists and scalars pass through; maps become array(...).
    """
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return "array(" + ", ".join(php_lit(x) for x in v) + ")"
    if isinstance(v, dict):
        return "array(" + ", ".join("%s => %s" % (php_lit(k), php_lit(x))
                                    for k, x in v.items()) + ")"
    raise TypeError(type(v))


def call(fn, *args):
    a = ", ".join(php_lit(x) for x in args)
    return php("echo json_encode(%s(%s));" % (fn, a))


# ── 🔴 the rule with money in it ───────────────────────────────────────────
class TestCeilingsAreNeverABalance(unittest.TestCase):

    def test_delivered_summary_takes_no_ceiling(self):
        """Structural: there is no parameter to subtract from.

        This is the whole defence. If someone later adds a $ceiling argument so
        they can render "18 of 20", this test is what stops it.
        """
        src = open(ENT).read()
        sig = src.split("function mwm_rm_delivered_summary(")[1].split(")")[0]
        self.assertEqual(sig.strip(), "$assets",
                         "delivered_summary grew an argument — if it is a ceiling, "
                         "the portal can now render a debt the contract does not create")

    def test_delivered_summary_never_returns_a_remainder(self):
        out = call("mwm_rm_delivered_summary", [
            {"kind": "short", "qty": 8, "delivered_at": "2026-09-01"},
            {"kind": "hero", "qty": 1, "delivered_at": "2026-09-01"},
        ])
        self.assertEqual(out["total"], 9)
        for banned in ("remaining", "left", "outstanding", "of", "ceiling", "max", "allowed"):
            self.assertNotIn(banned, out, "delivered summary leaked a %r key" % banned)

    def test_undelivered_assets_are_not_counted(self):
        """A promised asset is not a delivered one, and must not inflate the count."""
        out = call("mwm_rm_delivered_summary", [
            {"kind": "hero", "qty": 1, "delivered_at": "2026-09-01"},
            {"kind": "hero", "qty": 1, "delivered_at": None},
            {"kind": "short", "qty": 5},
        ])
        self.assertEqual(out["total"], 1)

    def test_ceilings_are_flagged_internal(self):
        out = call("mwm_rm_delivery_ceilings", "location_day", 1)
        self.assertTrue(out["internal_only"])
        self.assertTrue(out["is_ceiling"])

    def test_ceiling_and_delivered_never_meet_in_one_function(self):
        """No function may see both a ceiling and a delivered count."""
        src = open(ENT).read()
        for block in src.split("\nfunction ")[1:]:
            name = block.split("(")[0]
            body = block
            has_ceiling = "mwm_rm_delivery_ceilings" in body or "is_ceiling" in body
            has_delivered = "mwm_rm_delivered_summary" in body or "delivered_at" in body
            self.assertFalse(
                has_ceiling and has_delivered,
                "%s sees a ceiling AND a delivered count — that is where "
                "'2 still owed' gets computed" % name)


# ── §1 · hours: a real allowance, and it expires ──────────────────────────
class TestHoursDoNotRollOver(unittest.TestCase):

    def test_gold_is_four_and_four(self):
        inc = call("mwm_rm_included_hours", "gold")
        self.assertEqual(inc["location_hours"], 4)
        self.assertEqual(inc["studio_hours"], 4)
        self.assertEqual(inc["total_hours"], 8)
        self.assertEqual(inc["monthly_cents"], 249700)

    def test_rolls_over_is_false_and_must_stay_false(self):
        cyc = call("mwm_rm_cycle_window", 14, "2026-09-20")
        st = php("echo json_encode(mwm_rm_hours_state('gold', 1.5, 0, %s));" % php_lit(cyc))
        self.assertFalse(st["rolls_over"], "contract §1 — hours are não cumulativas")

    def test_unused_hours_are_reported_as_left_not_banked(self):
        cyc = call("mwm_rm_cycle_window", 14, "2026-09-20")
        st = php("echo json_encode(mwm_rm_hours_state('gold', 1.5, 0.5, %s));" % php_lit(cyc))
        self.assertEqual(st["location"]["left"], 2.5)
        self.assertEqual(st["studio"]["left"], 3.5)
        self.assertEqual(st["expires_on"], cyc["end"])

    def test_overuse_does_not_go_negative(self):
        cyc = call("mwm_rm_cycle_window", 14, "2026-09-20")
        st = php("echo json_encode(mwm_rm_hours_state('gold', 9, 9, %s));" % php_lit(cyc))
        self.assertEqual(st["location"]["left"], 0)
        self.assertEqual(st["studio"]["left"], 0)

    def test_hours_count_from_crew_arrival(self):
        cyc = call("mwm_rm_cycle_window", 14, "2026-09-20")
        st = php("echo json_encode(mwm_rm_hours_state('gold', 0, 0, %s));" % php_lit(cyc))
        self.assertEqual(st["counts_from"], "crew arrival on location")


class TestCycleWindow(unittest.TestCase):

    def test_anchor_mid_month(self):
        c = call("mwm_rm_cycle_window", 14, "2026-09-20")
        self.assertEqual(c["start"], "2026-09-14")
        self.assertEqual(c["end"], "2026-10-13")

    def test_before_the_anchor_is_the_previous_cycle(self):
        c = call("mwm_rm_cycle_window", 14, "2026-09-03")
        self.assertEqual(c["start"], "2026-08-14")
        self.assertEqual(c["end"], "2026-09-13")

    def test_anchor_31_clamps_and_does_not_double_up(self):
        """A 31st anchor in a 30-day month must not produce two cycles in one month."""
        c = call("mwm_rm_cycle_window", 31, "2026-11-15")
        self.assertEqual(c["start"], "2026-10-31")
        self.assertEqual(c["end"], "2026-11-29")
        self.assertEqual(c["next_start"], "2026-11-30")

    def test_december_rolls_the_year(self):
        c = call("mwm_rm_cycle_window", 14, "2026-12-20")
        self.assertEqual(c["next_start"], "2027-01-14")

    def test_a_bad_anchor_refuses(self):
        self.assertIsNone(call("mwm_rm_cycle_window", 0, "2026-09-20"))
        self.assertIsNone(call("mwm_rm_cycle_window", 32, "2026-09-20"))


# ── §3 · travel ───────────────────────────────────────────────────────────
class TestTravelZones(unittest.TestCase):

    def test_the_five_zones_match_the_contract(self):
        z = call("mwm_rm_travel_zones")
        fees = [(x["zone"], x["fee_cents"]) for x in z["zones"]]
        self.assertEqual(fees, [(1, 0), (2, 30000), (3, 60000), (4, 100000), (5, None)])

    def test_boundaries(self):
        for miles, zone in ((0, 1), (30, 1), (31, 2), (75, 2), (76, 3),
                            (150, 3), (151, 4), (250, 4), (251, 5), (3000, 5)):
            self.assertEqual(call("mwm_rm_zone_for_miles", miles)["zone"], zone,
                             "%s miles" % miles)

    def test_zone_one_is_included(self):
        self.assertTrue(call("mwm_rm_zone_for_miles", 12)["included"])

    def test_miami_is_zone_four_at_one_thousand(self):
        z = call("mwm_rm_zone_for_miles", 235)
        self.assertEqual(z["zone"], 4)
        self.assertEqual(z["fee_cents"], 100000)

    def test_zone_five_is_quote_only_not_free(self):
        z = call("mwm_rm_zone_for_miles", 900)
        self.assertTrue(z["quote_only"])
        self.assertIsNone(z["fee_cents"])

    def test_an_unknown_distance_refuses_rather_than_defaulting_to_included(self):
        """🔴 Failing to zone 1 on a bad input is a $1,000 mistake wearing a default."""
        for bad in (None, "", "abc", -5):
            self.assertIsNone(call("mwm_rm_zone_for_miles", bad), repr(bad))

    def test_lodging_is_excluded(self):
        z = call("mwm_rm_travel_zones")
        for x in ("tolls", "parking", "lodging"):
            self.assertIn(x, z["excludes"])


# ── §5 · rate card, priced historically ───────────────────────────────────
class TestRateCard(unittest.TestCase):

    def test_prices_match_the_signed_contract(self):
        c = call("mwm_rm_rate_card", "2026-09")
        i = c["items"]
        self.assertEqual(i["studio_hour"]["annual_cents"], 24900)
        self.assertEqual(i["studio_hour"]["standalone_cents"], 34900)
        self.assertEqual(i["location_day_4h"]["annual_cents"], 175000)
        self.assertEqual(i["location_day_8h"]["annual_cents"], 250000)
        self.assertEqual(i["location_hour"]["annual_cents"], 30000)
        self.assertEqual(i["location_hour"]["standalone_cents"], 40000)

    def test_editing_is_waived_on_the_annual_plan(self):
        p = call("mwm_rm_price_addon", "2026-09", "editing", 3, True)
        self.assertEqual(p["total_cents"], 0)
        self.assertTrue(p["waived"])

    def test_editing_is_not_free_off_plan(self):
        p = call("mwm_rm_price_addon", "2026-09", "editing", 3, False)
        self.assertEqual(p["total_cents"], 30000)
        self.assertFalse(p["waived"])

    def test_a_line_not_offered_standalone_returns_null_not_zero(self):
        """A missing price must never fall through to free."""
        self.assertIsNone(call("mwm_rm_price_addon", "2026-09", "location_day_4h", 1, False))

    def test_an_unknown_rate_card_version_refuses(self):
        self.assertIsNone(call("mwm_rm_rate_card", "2025-01"))
        self.assertIsNone(call("mwm_rm_price_addon", "2025-01", "studio_hour", 1, True))

    def test_quantity_multiplies(self):
        p = call("mwm_rm_price_addon", "2026-09", "studio_hour", 4, True)
        self.assertEqual(p["total_cents"], 99600)

    def test_a_zero_or_negative_quantity_refuses(self):
        self.assertIsNone(call("mwm_rm_price_addon", "2026-09", "studio_hour", 0, True))
        self.assertIsNone(call("mwm_rm_price_addon", "2026-09", "studio_hour", -2, True))

    def test_the_card_carries_its_version_so_pricing_is_historical(self):
        p = call("mwm_rm_price_addon", "2026-09", "studio_hour", 1, True)
        self.assertEqual(p["rate_card"], "2026-09")

    def test_quote_only_lines_are_named_not_priced(self):
        c = call("mwm_rm_rate_card", "2026-09")
        self.assertTrue(any("Multi-day" in x for x in c["quote_only"]))
        self.assertTrue(any("flight" in x for x in c["quote_only"]))


# ── §5 · the state machine ────────────────────────────────────────────────
class TestAddonStateMachine(unittest.TestCase):

    def test_the_happy_path(self):
        ctx = {"approved_by": "luzia@example.com", "approved_at": "2026-09-12 10:00:00"}
        self.assertTrue(php("echo json_encode(mwm_rm_addon_transition('requested','approved',%s));" % php_lit(ctx))["ok"])
        for a, b in (("approved", "scheduled"), ("scheduled", "delivered"), ("delivered", "billed")):
            self.assertTrue(call("mwm_rm_addon_transition", a, b)["ok"], "%s->%s" % (a, b))

    def test_approval_without_a_written_record_is_refused(self):
        """🔴 'mediante aprovação prévia por escrito'. The record IS the rule."""
        r = call("mwm_rm_addon_transition", "requested", "approved")
        self.assertFalse(r["ok"])
        self.assertIn("approved_by", r["error"])

    def test_approval_needs_a_timestamp_too(self):
        r = php("echo json_encode(mwm_rm_addon_transition('requested','approved',%s));"
                % php_lit({"approved_by": "x@y.com"}))
        self.assertFalse(r["ok"])

    def test_nothing_is_scheduled_before_it_is_approved(self):
        self.assertFalse(call("mwm_rm_addon_transition", "requested", "scheduled")["ok"])

    def test_nothing_is_billed_before_it_is_delivered(self):
        self.assertFalse(call("mwm_rm_addon_transition", "approved", "billed")["ok"])
        self.assertFalse(call("mwm_rm_addon_transition", "scheduled", "billed")["ok"])

    def test_billed_is_terminal(self):
        for s in ("requested", "approved", "scheduled", "delivered", "billed"):
            self.assertFalse(call("mwm_rm_addon_transition", "billed", s)["ok"])

    def test_a_decline_must_carry_a_reason(self):
        self.assertFalse(call("mwm_rm_addon_transition", "requested", "declined")["ok"])
        r = php("echo json_encode(mwm_rm_addon_transition('requested','declined',%s));"
                % php_lit({"reason": "crew unavailable"}))
        self.assertTrue(r["ok"])


class TestBilling(unittest.TestCase):

    def test_an_addon_bills_on_the_next_invoice_not_separately(self):
        b = call("mwm_rm_billing_cycle_for", "2026-09-20", 14)
        self.assertEqual(b["invoiced_on"], "2026-10-14")
        self.assertFalse(b["separate_charge"])
        self.assertFalse(b["deposit"])

    def test_approved_hours_are_used_inside_the_same_cycle(self):
        b = call("mwm_rm_billing_cycle_for", "2026-09-20", 14)
        self.assertEqual(b["used_within"]["start"], "2026-09-14")
        self.assertEqual(b["used_within"]["end"], "2026-10-13")


# ── §6 · terms, and ROB §8a ───────────────────────────────────────────────
class TestTerms(unittest.TestCase):

    def test_the_numbers_match_the_contract(self):
        t = call("mwm_rm_terms")
        self.assertEqual(t["revision_rounds"], 3)
        self.assertEqual(t["revision_window_days"], 30)
        self.assertEqual(t["extra_revision_cents"], 25000)
        self.assertEqual(t["cancel_notice_hours"], 72)
        self.assertEqual(t["raw_footage_cents_per_minute"], 2500)

    def test_it_says_availability_is_not_guaranteed(self):
        self.assertIn("availability", call("mwm_rm_terms")["availability_rule"].lower())


class TestUpgradeSignal(unittest.TestCase):

    def test_the_threshold_is_seven_point_six(self):
        s = call("mwm_rm_upgrade_signal", 0)
        self.assertAlmostEqual(s["threshold"], 7.63, places=2)

    def test_eight_hours_flags(self):
        self.assertTrue(call("mwm_rm_upgrade_signal", 8)["flag"])
        self.assertFalse(call("mwm_rm_upgrade_signal", 7)["flag"])

    def test_it_is_internal_only(self):
        self.assertTrue(call("mwm_rm_upgrade_signal", 9)["internal_only"])


class TestRateCardIsData(unittest.TestCase):
    """ROB: "make this data, versioned, never hardcoded."

    The shipped array is the seed and the offline fallback; in WordPress a
    resolver reads the table instead. These prove the swap works and, more
    importantly, that an empty table cannot make everything free.
    """

    def test_a_resolver_overrides_the_shipped_card(self):
        out = php("""
            mwm_rm_set_card_resolver(function($v){
                return array('version'=>$v,'items'=>array(
                    'studio_hour'=>array('label'=>'x','unit'=>'hour',
                        'standalone_cents'=>50000,'annual_cents'=>40000)));
            });
            echo json_encode(mwm_rm_price_addon('2027-01','studio_hour',1,true));
        """)
        self.assertEqual(out["unit_cents"], 40000)
        self.assertEqual(out["rate_card"], "2027-01")

    def test_an_empty_table_falls_back_instead_of_pricing_at_zero(self):
        """🔴 The failure mode that would quietly give the work away."""
        out = php("""
            mwm_rm_set_card_resolver(function($v){ return array('items'=>array()); });
            echo json_encode(mwm_rm_price_addon('2026-09','studio_hour',1,true));
        """)
        self.assertEqual(out["unit_cents"], 24900)

    def test_a_broken_resolver_falls_back(self):
        out = php("""
            mwm_rm_set_card_resolver(function($v){ return null; });
            echo json_encode(mwm_rm_price_addon('2026-09','studio_hour',1,true));
        """)
        self.assertEqual(out["unit_cents"], 24900)


class TestRateCardVersionAlias(unittest.TestCase):
    """ROB stamped rate_card_version = "MWM-LC-2026-02-Rev5" on the live Stripe
    subscription before this file existed. The subscription is the record of
    what she is on, so its spelling has to resolve — a lookup that misses would
    return null and a caller that shrugs would price at list."""

    def test_robs_spelling_resolves(self):
        for v in ("MWM-LC-2026-02-Rev5", "MWM-LC-2026-02", "2026-09"):
            c = call("mwm_rm_rate_card", v)
            self.assertIsNotNone(c, v)
            self.assertEqual(c["items"]["studio_hour"]["annual_cents"], 24900, v)

    def test_pricing_through_the_alias_matches(self):
        a = call("mwm_rm_price_addon", "MWM-LC-2026-02-Rev5", "studio_hour", 4, True)
        b = call("mwm_rm_price_addon", "2026-09", "studio_hour", 4, True)
        self.assertEqual(a["total_cents"], b["total_cents"])

    def test_a_genuinely_unknown_version_still_refuses(self):
        self.assertIsNone(call("mwm_rm_rate_card", "MWM-LC-2099-99-Rev1"))


class TestPlanPhase(unittest.TestCase):
    """Her GOLD term starts 2026-10-03. Today she is still on the $600 podcast
    package she is upgrading from, and Stripe's 3 Sep invoice proves it."""

    def test_before_the_term_she_is_not_on_the_plan(self):
        self.assertEqual(call("mwm_rm_plan_phase", "2026-10-03", "2027-10-02", "2026-09-11"),
                         "pending")

    def test_on_the_first_day_she_is(self):
        self.assertEqual(call("mwm_rm_plan_phase", "2026-10-03", "2027-10-02", "2026-10-03"),
                         "active")

    def test_after_the_term_it_has_ended(self):
        self.assertEqual(call("mwm_rm_plan_phase", "2026-10-03", "2027-10-02", "2027-10-03"),
                         "ended")

    def test_the_last_day_is_still_active(self):
        self.assertEqual(call("mwm_rm_plan_phase", "2026-10-03", "2027-10-02", "2027-10-02"),
                         "active")

    def test_no_start_date_is_unknown_not_active(self):
        """🔴 Defaulting an unset term to 'active' would hand out hours nobody
        has been charged for."""
        self.assertEqual(call("mwm_rm_plan_phase", None, None, "2026-09-11"), "unknown")
        self.assertEqual(call("mwm_rm_plan_phase", "", None, "2026-09-11"), "unknown")


class TestHerRealCycle(unittest.TestCase):
    """The cycle Stripe actually bills: anchor day 3."""

    def test_her_first_gold_cycle(self):
        c = call("mwm_rm_cycle_window", 3, "2026-10-05")
        self.assertEqual(c["start"], "2026-10-03")
        self.assertEqual(c["end"], "2026-11-02")

    def test_hours_expire_on_the_second(self):
        cyc = call("mwm_rm_cycle_window", 3, "2026-10-05")
        st = php("echo json_encode(mwm_rm_hours_state('gold', 0, 0, %s));" % php_lit(cyc))
        self.assertEqual(st["expires_on"], "2026-11-02")

    def test_the_miami_day_falls_before_her_term(self):
        """26 Sep is inside the OLD package, not the first GOLD cycle. It must
        never be counted against a cycle that has not begun."""
        self.assertEqual(call("mwm_rm_plan_phase", "2026-10-03", "2027-10-02", "2026-09-26"),
                         "pending")


if __name__ == "__main__":
    unittest.main(verbosity=2)
