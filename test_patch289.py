#!/usr/bin/env python3
"""GATE for PATCH #289 — client-facing plan copy speaks monthly, never in
totals (Michael, 18 Nov 10:31). Prints GATE289 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import datetime

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("TIMEZONE", "US/Eastern")
import studio_package as sp  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


today = datetime.now(pytz.timezone("America/New_York")).date()
BAD = ("12 hours", "12-hour", "twelve hours", "hours of professional studio time every month",
       "studio hours every month", "hold up to 8 hours", "hold up to 4 hours", "hours at a time",
       "for 3 months", "× 3", "total)", "total across", "must be used within")

# ── 1. the ongoing welcome, every monthly plan ──────────────────────────────
for pid, spec in sp.PLANS.items():
    if spec.get("plan") != "monthly":
        continue
    h = sp._welcome_email_html("Ana", "ABC123", spec, sp.package_term(spec, today))
    n = spec["name"]
    check(f"welcome[{spec['kind']}].headline", f"Your <strong>{n}</strong> is active: an ongoing creative partnership with MWM Studios, renewed every month." in h)
    check(f"welcome[{spec['kind']}].monthly_line", f"Your monthly studio time: {spec['monthly_hours']} hours, refreshed every month" in h)
    check(f"welcome[{spec['kind']}].continues", "Your plan continues month after month, and your portal always shows the studio time you have available to book" in h)
    check(f"welcome[{spec['kind']}].rollover", "Unused studio time rolls over to the next month (you can hold up to two months' worth)" in h)
    check(f"welcome[{spec['kind']}].disclaimer", "This is a 3-month minimum agreement; after that your plan is recurring month to month, and you can stop at any time with 30 days&#x27; notice." in h
          or "This is a 3-month minimum agreement; after that your plan is recurring month to month, and you can stop at any time with 30 days' notice." in h, h[-900:])
    for bad in BAD:
        check(f"welcome[{spec['kind']}].no[{bad}]", bad not in h)
rs = sp.REAL_SETS_FOUNDING
h = sp._welcome_email_html("Ana", "ABC123", rs, sp.package_term(rs, today))
check("welcome[real_sets_founding].headline", "Your <strong>Real Sets Plan</strong> is active: an ongoing creative partnership with MWM Studios, renewed every month." in h)
check("welcome[real_sets_founding].monthly_line", "Your monthly studio time: 4 hours, refreshed every month (on our real sets)" in h)
check("welcome[real_sets_founding].founding_lock", "Your Founding price stays locked" in h and "$1,200/month" in h)
for bad in BAD:
    check(f"welcome[real_sets_founding].no[{bad}]", bad not in h)
check("welcome.fi_every_month", sp._FI1 == "Your plan includes 1 Full Immersion video every month" and sp._FI2 == "Your plan includes 2 Full Immersion videos every month")
hg = sp._welcome_email_html("Ana", "ABC123", sp.spec_by_kind("plan_ai_growth"), sp.package_term(sp.spec_by_kind("plan_ai_growth"), today))
check("welcome.growth_fi_line", "<li>Your plan includes 1 Full Immersion video every month</li>" in hg)
hp = sp._welcome_email_html("Ana", "ABC123", sp.spec_by_kind("plan_ai_pro"), sp.package_term(sp.spec_by_kind("plan_ai_pro"), today))
check("welcome.pro_fi_line", "<li>Your plan includes 2 Full Immersion videos every month</li>" in hp)
AI = open(os.path.join(HERE, "ai_studio.py"), encoding="utf-8").read()
check("maya.fi_every_month", AI.count("Full Immersion video every month") == 2 and "2 Full Immersion videos every month" in AI)
PD = open(os.path.join(HERE, "pitch_drafts.py"), encoding="utf-8").read()
check("pitch.fi_every_month", PD.count("Full Immersion video every month") == 2 and "two Full Immersion videos every month" in PD)
check("welcome.footer_note_constant", sp.PLAN_FOOTER_NOTE == "This is a 3-month minimum agreement; after that your plan is recurring month to month, and you can stop at any time with 30 days' notice.")

# ── 2. the hours-added email for a monthly plan ─────────────────────────────
g = sp.spec_by_kind("plan_ai_growth")
ha = sp._hours_added_email_html("Ana", g, sp.package_term(g, today), {"available": 4})
check("added.lead", "Your <strong>AI Growth Plan</strong> is active: an ongoing creative partnership with MWM Studios, renewed every month. This month's studio time is already in your portal." in ha)
check("added.available_kept", "You have <strong>4 hours</strong> available to book right now." in ha)
for bad in BAD:
    check(f"added.no[{bad}]", bad not in ha)

# ── 3. one-offs and the annual prepay keep their copy ───────────────────────
one = sp.PLANS["price_1UR0ixDAWlnEb9Rfw5I1cFJX"]
ho = sp._welcome_email_html("Ana", "ABC123", one, sp.package_term(one, today))
check("oneoff.unchanged", "is confirmed: 1 studio hour ready to book in your portal." in ho and "Book any time in the next 60 days" in ho)
ann = sp.PLANS["price_1UZaCCDAWlnEb9RfKpoeJTAI"]
han = sp._welcome_email_html("Ana", "ABC123", ann, sp.package_term(ann, today))
check("annual.unchanged", "4 hours of professional studio time every month for the next 12 months" in han and "48 hours of your year" in han)

# ── 4. pins ─────────────────────────────────────────────────────────────────
SP = open(os.path.join(HERE, "studio_package.py"), encoding="utf-8").read()
check("sp.no_old_headline", "professional studio time every month, as an ongoing partnership" not in SP)
check("sp.no_old_total_li", 'total_li = (f"{_m} studio hours every month"\n' not in SP)
check("sp.no_old_rollover", "hours at a time" not in SP)
check("sp.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "studio_package.py")], capture_output=True).returncode == 0)
for t, s in (("test_patch277.py", "renewed every month"), ("test_patch278.py", "two months' worth"), ("test_patch287.py", "renewed every month"), ("test_patch282.py", "two Full Immersion videos every month")):
    check(f"pins.{t}", s in open(os.path.join(HERE, t), encoding="utf-8").read())

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 289) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE289 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
