#!/usr/bin/env python3
"""test_icp.py — S31. The rule existed three times and was enforced nowhere.

Michael, 25 Aug 2026: "We are one hundred percent aiming for small businesses.
Let's put that as our rule."

That rule was already written down in three places before today. MAYA.md §51
carried it from 29 July and lived in a notebook no code reads — twelve days
during which nothing enforced it. The WhatsApp prompt said "business owners and
entrepreneurs". The shared knowledge said "not hobbyist creators". And the
WEBSITE prompt asked "what type of content are you looking to create?" — a
question that tells a plumber he is in the wrong place and invites a hobbyist to
stay. Three statements of one policy, drifting, one of them recruiting the exact
people the other two excluded.

§2 is the test that matters: the banned opener must be absent from the SOURCE,
whitespace-normalised, so it cannot creep back in reformatted. §4 guards the
reversibility ERIC asked for — Michael may widen the rule again, and a verdict
a model wrote on one message must not be permanent.

Run: python3 test_icp.py
"""

import re
import sys

import icp

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


APP = open("app.py").read()
FLAT = re.sub(r"\s+", " ", APP).lower()

# ── §1 · the rule is real text and says the thing ───────────────────────────
r = icp.ICP_RULE.lower()
ok("small business owners" in r, "the rule names who we ARE for")
for who in ("realtor", "dentist", "lawyer", "contractor", "restaurant", "gym"):
    ok(who in r, "the rule gives a concrete example: %s" % who)
ok("hobbyist" in r and "musician" in r, "and names who we are NOT for")
ok("not bad people" in r or "not to be treated rudely" in r,
   "and says to be decent about it — a disqualified lead is still a person")
ok("open on the business" in r, "it instructs behaviour, not just policy")

# ── §2 · THE ONE THAT MATTERS · the banned opener cannot creep back ─────────
for b in icp.BANNED_OPENERS:
    ok(b not in FLAT,
       "banned opener absent from app.py (whitespace-normalised): %r" % b)
ok(len(icp.BANNED_OPENERS) >= 4, "several phrasings are banned, not just the one we found")
ok(all(x == x.lower() for x in icp.BANNED_OPENERS),
   "banned list is lowercase, so the check is case-insensitive by construction")

# ── §3 · both doors carry the rule ─────────────────────────────────────────
ok("import icp as _icp" in APP, "app.py imports the single source")
ok("_icp.ICP_RULE" in APP, "and splices it into a prompt")
shared = APP[APP.index("MAYA_SHARED_KNOWLEDGE = "):]
ok("_icp.ICP_RULE" in shared[:400], "the rule is in the SHARED block, so every prompt using it inherits")
web = APP[APP.index("MAYA_WEB_SYSTEM_PROMPT = "):]
web = web[:web.index("# Calendar tools available to web chat Maya")]
ok("MAYA_SHARED_KNOWLEDGE" in web, "the website prompt includes the shared block")
ok("what's your business" in re.sub(r"\s+", " ", web).lower(),
   "the website prompt now OPENS on the business")
ok("small business OWNER" in web or "business OWNER" in web,
   "and asks whether they are an owner, not merely a person with a project")

# ── §4 · disqualification is reversible, by construction ───────────────────
ok(icp.REASON_NOT_TARGET_MARKET in icp.DISQUALIFY_REASONS, "ERIC's reason code exists")
ok(icp.REASON_UNQUALIFIED_CALL in icp.DISQUALIFY_REASONS,
   "and is DISTINCT from 'unqualified founder call' — Santiago and Erving were "
   "closed correctly under the wrong stated reason")

lead = {"name": "Someone", "business": ""}
icp.mark_disqualified(lead, icp.REASON_NOT_TARGET_MARKET, at="2026-08-25", by="michael")
ok(icp.is_disqualified(lead) is True, "a lead can be marked")
ok(icp.disqualified_reason(lead) == icp.REASON_NOT_TARGET_MARKET, "with its reason readable")
ok(lead["disqualified"]["label"].startswith("Not our target market"), "and a human label")
ok(icp.is_disqualified(lead, icp.REASON_BUDGET) is False, "reason-specific checks work")

icp.clear_disqualified(lead)
ok(icp.is_disqualified(lead) is False, "REVERSIBLE — the whole point")
ok("disqualified" not in lead, "and it leaves NO residue, so the lead is genuinely restored")

ok(icp.mark_disqualified(lead, "made_up_reason") is not None
   and icp.is_disqualified(lead) is False,
   "an unknown reason is refused rather than silently written")
ok(icp.mark_disqualified(None, icp.REASON_BUDGET) is None, "a missing lead does not crash")
ok(icp.clear_disqualified(None) is None, "nor does clearing one")

_long = icp.mark_disqualified({}, icp.REASON_NOT_A_FIT, note="x" * 900)
ok(len(_long["disqualified"]["note"]) == 500, "a note is bounded, not unbounded free text")

# ── §5 · the measurement ERIC asked for ────────────────────────────────────
leads = {
    "a": {"business": "Ambruster Realty"},
    "b": {"business": "  "},
    "c": {},
    "d": {"business": "Pineda Fidelity"},
}
icp.mark_disqualified(leads["c"], icp.REASON_NOT_TARGET_MARKET)
cov = icp.business_coverage(leads)
ok(cov["total"] == 4 and cov["with_business"] == 2, "coverage counts only NAMED businesses")
ok(cov["without_business"] == 2, "whitespace does not count as a business name")
ok(cov["coverage_pct"] == 50.0, "and reports a percentage ERIC can track week to week")
ok(cov["disqualified"] == 1, "disqualified leads are counted separately")
ok(len(cov["sample_unnamed"]) == 2, "with a sample so the gap is actionable, not just a number")
ok(icp.business_coverage({})["coverage_pct"] == 0.0, "an empty book does not divide by zero")
ok(icp.business_coverage(None)["total"] == 0, "nor does None")

print("\nS31_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  ICP — SMALL BUSINESS OWNERS (S31): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
