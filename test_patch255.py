"""PATCH #255 — "AI Wall Spot" renamed FULL IMMERSION (Michael, 19 Oct 2026: the
two names were too close; AI Wall = the background, long videos; Full Immersion =
everything around you, even clothes, up to 30 s). Maya's menu, the app.py studio
pricing, studio_visit and the Instagram caption check use the new name; the old
names stay only as a mapping. Chains the #254 gate."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("AI_STUDIO_PAGE_LIVE", None)
import ai_studio as ai  # noqa: E402
import ig_publish as igp  # noqa: E402

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
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
SV = open(os.path.join(HERE, "studio_visit.py"), encoding="utf-8").read()

check("Maya: Full Immersion is the name", off.count("Full Immersion") >= 15)
check("Maya: old names only in the mapping line", off.count("AI Wall Spot") == 2
      and '"AI Wall Spot" (our name until 19 Oct)' in off)
check("Maya: no bare 'Spot' left outside the mapping",
      re.findall(r"\bSpots?\b", off.replace('"AI Wall Spot" (our name until 19 Oct)', "").replace('"AI Wall Spots Pack"', "")) == [])
check("Maya: one-line difference", "Full Immersion transforms everything around you, even your clothes, for videos up to 30 seconds." in off)
check("Maya: AI Wall keeps its name", "AI WALL = we replace the BACKGROUND" in off and "AI Wall Hour: $599" in off)
check("Maya: links unchanged", "https://buy.stripe.com/00weVdaKlgpI7incAG9EI1m" in off and "https://buy.stripe.com/aFa5kD6u54H07in0RY9EI1c" in off)
check("Maya: 'full immersion' starts the AI branch", ai.ai_lead(None, ["do you do full immersion videos?"], "")[0])
check("app.py: no AI Wall Spot except as earlier-name notes",
      all(("earlier names" in l or 'was "AI Wall Spot"' in l) for l in SRC.splitlines() if "AI Wall Spot" in l))
check("app.py: Full Immersion add-on + pack", "Full Immersion (add-on) — $397 per video" in SRC and "Full Immersion Pack — $1,497" in SRC)
check("studio_visit: Full Immersion Pack", "Full Immersion Pack" in SV and "AI Wall Spot" not in SV)
check("IG: Full Immersion caption OK", igp.caption_problems("Full Immersion: a whole new world", "reel") == [])
check("IG: AI Wall Spot flagged as retired", any("retired" in x for x in igp.caption_problems("New AI Wall Spot drop", "reel")))
check("IG: AI Wall Session still OK", igp.caption_problems("Book an AI Wall Session", "reel") == [])
check("IG: wrong casing flagged", len(igp.caption_problems("Full immersion now", "reel")) == 1)
check("module doc", "PATCH #255" in open(os.path.join(HERE, "ai_studio.py"), encoding="utf-8").read())

print("static: %d passed, %d failed" % (passed, failed))
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch254.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:])
    print(r_.stderr[-800:])
    failed += 1
    print("FAIL #254 gate did not report")
else:
    passed += int(m.group(1))
    failed += int(m.group(2))
    print("254: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE255 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
