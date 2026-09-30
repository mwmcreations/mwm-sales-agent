"""PATCH #141 — Maya + the final Hybrid AI menu (ROB brief 30 Sep 13:19, Michael:
"Maya is not there to sell packages... the visit is always the best thing,
but she needs to understand pricing and give general information")."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ai_studio as ai
PASS = FAIL = 0
def ok(c, label):
    global PASS, FAIL
    if c: PASS += 1; print("  ok   " + label)
    else: FAIL += 1; print("  FAIL " + label)

on = ai.maya_ai_context("https://mwmcreations.com/ai-studio/")
off = ai.maya_ai_context("", "asked")
print("\n== Michael's rule")
ok("NOT here to sell a package" in on, "Maya is not a closer")
ok("ALWAYS the best next step" in on and "30-minute Studio Strategy Visit" in on, "the 30-minute visit is always the next step")
ok("general information" in on and "PREPARED" in on, "general info so the lead comes prepared")
ok("never offer one first" in on and "clearly says they want to buy" in on, "payment links only on a clear request, never pushed")
ok("https://buy.stripe.com/aFa5kD6u54H07in0RY9EI1c" in on and "https://buy.stripe.com/9B65kDf0BehAfOT44a9EI1b" in on and on.count("buy.stripe.com") == 2, "exactly the two ROB links, written in full")
ok("google.com/url" not in on, "no Gmail-wrapped links")
ok("NEVER work out a per-second price" in on, "no self-built per-second quotes")
print("\n== the menu")
for k in ("$249", "$349", "$1,200/month", "3-month minimum", "30 days' notice", "$397 per video",
          "Up to 30 seconds", "up to 3 AI scenes", "1 revision round", "$1,497", "$374", "from $6 per second"):
    ok(k in on, "menu has " + k)
for k in ("$749", "$2,197", "+$250"):
    ok(k not in on, "off-market price not in the prompt: " + k)
ok("Want early access?" in on and "NO date, NO price" in on, "AI Sets: early access, no date, no price")
print("\n== guardrails, objections, hand-offs")
ok("MAX 30 seconds and MAX 3 scenes" in on and "2-minute video like the demo" in on, "30 s / 3 scenes cap, 2-minute = custom")
ok("identical results twice" in on, "no exact looks promised")
ok("$2,497 for one location" in on and "NO discounts, NO promo codes" in on, "too expensive: compare, never discount")
ok("send us your photos" in on and "NEVER" in on, "never photo-to-AI")
ok("100% real" in on, "is it fake: you're 100% real")
ok("anything over $1,497" in on and "10+ locations" in on and "any complaint" in on, "hand-offs to Michael")
ok("ALREADY A CLIENT" in on, "client mode respected")
print("\n== languages")
ok("PT:" in on and "Visita de Estratégia gratuita de 30 minutos" in on, "Portuguese key lines")
ok("ES:" in on and "Visita de Estrategia gratuita de 30 minutos" in on, "Spanish key lines")
ok(ai.ai_lead(None, ["¿hacen video con IA?"], "")[0], "Spanish AI question triggers the branch")
ok(ai.ai_lead(None, ["I want a hybrid AI video"], "")[0], "'hybrid AI' triggers the branch")
ok(not ai.ai_lead(None, ["hi, how much is a podcast?"], "")[0], "normal podcast lead stays off")
print("\n== base prompts (app.py)")
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
ok("$200" not in SRC and SRC.count("$196") >= 6, "savings are $196 everywhere ($1,396 - $1,200)")
ok("Hybrid AI Video (add-on) — $397 per video" in SRC and "You are not selling it; Michael closes in the studio." in SRC, "general studio pricing knows the AI add-on")
ok(SRC.count("Package clients can add a Hybrid AI video to any session: $397 per video") == 2, "package clients know the add-on")
print("\n== 141b (after the live test transcripts)")
ok("do NOT add up a total" in on and "More than 4 videos" in on, "141b: no totals past the pack, hand off")
ok("KEEP IT SHORT" in on and "Never paste the whole menu" in on, "141b: short answers (the PT reply was cut off at 600 tokens)")
print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
