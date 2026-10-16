"""PATCH #252 — Maya's AI Wall menu, shipped with the new #ai-prices section on
/ai-studio (ROB #dev 16 Oct FINAL STUDIO PRICING; Michael: "Go ahead and do
those steps yourself. I approve it.").

Checks ai_studio.py (names, plans, one-offs, the eight page links, founding
date page-only, private offers never named), the app.py base prompts and
studio_visit.py naming, re-runs the #140 and #141 suites (updated to the new
names), then chains the #251 gate."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("AI_STUDIO_PAGE_LIVE", None)
import ai_studio as ai  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print("  ok   " + label)
    else:
        failed += 1
        print("  FAIL " + label)


on = ai.maya_ai_context("https://mwmcreations.com/ai-studio/")
off = ai.maya_ai_context("", "asked")
wa = ai.maya_ai_context("", "ad_id")

print("== names")
for k in ("AI Wall Spot", "AI Wall Spots Pack", "AI Wall Hour", "MWM Worlds", "Orlando's first AI Wall studio"):
    check("name: " + k, k in off)
check("old names only as a mapping", off.count("Hybrid AI") == 2 and '"Hybrid AI video" = AI Wall Spot' in off
      and '"Hybrid AI Pack" = AI Wall Spots Pack' in off)
check("no 'Florida's first' claim allowed", "Never say \"Florida's first\"" in off)
check("no LED / no green screen line", "No LED wall. No green screen." in off)

print("== plans (founding / regular)")
for name, f, r in (("AI Starter", "$1,297", "$1,497"), ("AI Growth", "$1,697", "$1,997"),
                   ("AI Pro", "$2,497", "$2,997"), ("Studio Only", "$1,200", "$1,497")):
    line = next((l for l in off.splitlines() if l.startswith("- " + name)), "")
    check("plan %s %s founding, %s regular" % (name, f, r), (f + "/month founding price") in line and ("regular " + r) in line)
check("AI Growth is the most popular", "AI Growth (the most popular)" in off)
check("252e: called subscription plans", "SUBSCRIPTION PLANS" in off and "MONTHLY PLANS" not in off)
check("3-month minimum; start this week on real sets, AI Wall Nov 2 (252b)", "3-month minimum" in off and "Start this week on our real sets; the AI Wall opens November 2" in off
      and "The month starts on the day they pay" in off and "plans start November 2" not in off and "Apply now" not in off)
check("252b base prompt: start this week", "start this week on our real sets (the AI Wall opens November 2)" in open(os.path.join(HERE, "app.py"), encoding="utf-8").read())
check("10 shorts or 1 podcast per hour", "up to 10 edited short videos, or 1 podcast episode with 10 short cuts" in off)
check("plan contents", "2 studio hours a month (1 on real sets + 1 on the AI Wall) + 1 AI Wall Spot" in off
      and "up to 2 of them on the AI Wall" in off and "4 AI Wall hours + 2 AI Wall Spots" in off
      and "4 hours on real sets, no AI" in off)
check("move up anytime, founding price comes with them", "move up anytime; the founding price comes with them" in off)

print("== one-offs")
check("252c: Spot $997 filming included, plan line", "AI Wall Spot: $997, filming included" in off and "On a monthly plan, Spots are included or added for $397." in off)
check("252c: no $597 left", "$597" not in on and "eVq4gzaKlb5o6ej8kq9EI1l" not in on)
check("Add a Spot $397", "Add a Spot: $397 per Spot" in off)
check("Pack $1,497 = 1 h + 4 Spots", "AI Wall Spots Pack: $1,497 = 1 studio hour + 4 AI Wall Spots" in off)
check("AI Wall Hour $599 = $349 + $250, from Nov 2", "AI Wall Hour: $599 ($349 studio hour with editing + $250 for the AI Wall), from November 2" in off)
check("252f: MWM Worlds off the menu, no $197", "$197" not in off and "NOT on the menu right now" in off)
check("$6 per second custom, never computed", "from $6 per second" in off and "NEVER work out a per-second price" in off)

print("== links")
LINKS = ("cNiaEXg4F1uOdGL3069EI1e", "aFa4gzcStehAfOT1W29EI1i", "cNi14ng4F3CWgSX7gm9EI1j", "eVq14n19LgpI9qveIO9EI1k",
         "00weVdaKlgpI7incAG9EI1m", "9B65kDf0BehAfOT44a9EI1b", "aFa5kD6u54H07in0RY9EI1c", "14AaEX7y9c9sfOT7gm9EI1h")
urls = re.findall(r"https://buy\.stripe\.com/[A-Za-z0-9]+", off)
check("exactly the eight page links", sorted(u.rsplit("/", 1)[1] for u in urls) == sorted(LINKS))
check("links only on a clear request", "never offer one first" in off and "clearly says they want to buy" in off)
check("plan link: first month charged, 3-month minimum said first", "charges the first month at checkout, with a 3-month minimum" in off)
for gone in ("5kQ3cv19Lddw1Y39ou9EI1d", "28E7sL7y92yS1Y30RY9EI1f", "fZu7sL19L1uObyDfMS9EI1g"):
    check("private-offer link absent: " + gone, gone not in on)

print("== private / retired offers")
for k in ("$1,097", "$2,197", "$749", "+$250", "Want early access?", "NO date, NO price"):
    check("not in prompt: " + k, k not in on)
check("never name them", "no 2-hour plans (Studio Duo, AI Wall Duo)" in off and "no AI Wall Sessions monthly plan" in off)

print("== founding date is a website line")
check("on /ai-studio: commit by November 1, 2026", "commit by November 1, 2026" in on)
check("ad channels: no date", "November 1" not in off and "November 1" not in wa)
check("same menu otherwise", on.split("═══", 2)[2].replace(ai._FOUNDING_ON_PAGE, "") == off.split("═══", 2)[2])
check("AI Wall hours not before Nov 2", "Never book an AI Wall hour before that" in off)

print("== branch triggers")
check("'AI wall' triggers", ai.ai_lead(None, ["do you have an AI wall?"], "")[0])
check("'AI Wall Spot' triggers", ai.ai_lead(None, ["how much is an AI Wall Spot"], "")[0])
check("'MWM Worlds' triggers", ai.ai_lead(None, ["tell me about MWM Worlds"], "")[0])
check("'email' still does not", not ai.ai_lead(None, ["I said I'd email you"], "")[0])
check("podcast price stays off", not ai.ai_lead(None, ["hi, how much is a podcast?"], "")[0])

print("== languages / length")
check("PT + ES key lines", "primeiro estúdio com AI Wall de Orlando" in off and "primer estudio con AI Wall de Orlando" in off)
check("names stay in English", "Product names stay in English in every language" in off)
check("block stays compact", len(on) < 9500)

print("== app.py + studio_visit.py")
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
SV = open(os.path.join(HERE, "studio_visit.py"), encoding="utf-8").read()
check("no Hybrid AI name left in app.py prompts", "Hybrid AI Video (add-on)" not in SRC and "Hybrid AI Pack —" not in SRC
      and "add a Hybrid AI video" not in SRC)
check("base prompt: Spot $397 / $597, Pack, plans from $1,297", "AI Wall Spot (add-on) — $397 per Spot" in SRC
      and "On its own, filming included: $997 (on a monthly plan, Spots are included or added for $397)." in SRC and "$597." not in SRC.split("AI Wall Spot (add-on)")[1][:600] and "from $1,297/month at the founding price" in SRC)
check("studio_visit names", "Hybrid AI" not in SV and "the AI Wall Spots Pack if they ask" in SV and "in the AI Wall block" in SV)
check("module doc", "PATCH #252" in open(os.path.join(HERE, "ai_studio.py"), encoding="utf-8").read())

print("static: %d passed, %d failed" % (passed, failed))
for t in ("test_patch140.py", "test_patch141.py"):
    r_ = subprocess.run([sys.executable, os.path.join(HERE, t)], capture_output=True, text=True)
    m = re.search(r"(\d+) passed, (\d+) failed", (r_.stdout.strip().splitlines() or [""])[-1])
    if not m:
        failed += 1
        print("FAIL %s did not report" % t)
        print(r_.stdout[-800:], r_.stderr[-800:])
    else:
        passed += int(m.group(1))
        failed += int(m.group(2))
        print("%s: %s passed, %s failed" % (t, m.group(1), m.group(2)))

r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch251.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])
tline = next((l for l in reversed(tail) if l.startswith("TOTAL ")), "")
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tline)
if not m:
    print(r_.stdout[-1500:])
    print(r_.stderr[-800:])
    failed += 1
    print("FAIL #251 gate did not report")
else:
    passed += int(m.group(1))
    failed += int(m.group(2))
    print("251: " + tline)
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE252 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
