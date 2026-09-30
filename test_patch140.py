"""PATCH #140 — Maya knows the AI Studio offers. Unit checks on ai_studio.py
plus source checks that app.py wires it into web chat, WhatsApp and Instagram."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ai_studio as ai
PASS = FAIL = 0
def ok(c, label):
    global PASS, FAIL
    if c: PASS += 1; print("  ok   " + label)
    else: FAIL += 1; print("  FAIL " + label)

print("\n== who is on the AI branch")
ok(ai.ai_lead(None, ["Do you do AI videos?"], "")[0], "asks about AI videos")
ok(ai.ai_lead(None, ["can you film me without a green screen?"], "")[0], "green screen question")
ok(ai.ai_lead(None, ["I saw the film once ad"], "")[0], "mentions the Film once ad")
ok(ai.ai_lead(None, ["vocês fazem vídeo com IA?"], "")[0], "Portuguese AI question")
ok(not ai.ai_lead(None, ["hi, how much is a podcast?"], "")[0], "normal podcast lead stays off")
ok(not ai.ai_lead(None, ["I said I'd email you"], "")[0], "the letters 'ai' inside words do not trigger")
ok(not ai.ai_lead(None, ["what's the price for the studio"], "")[0], "studio price question stays off")
ok(ai.ai_lead("123", [], "", ad_ids={"123"}) == (True, "ad_id"), "an AI ad id triggers")
ok(ai.ai_lead(None, [], "Film once, go anywhere")[1] == "ad_headline", "an AI ad headline triggers")
ok(not ai.ai_lead(None, [], "Business owners: one hour, filmed and edited.")[0], "the $349-style headline does not")

print("\n== what Maya is told")
on = ai.maya_ai_context("https://mwmcreations.com/ai-studio/")
off = ai.maya_ai_context("", "asked")
ok(ai.maya_ai_context("https://mwmcreations.com/", "") == "", "no block for a normal conversation")
ok("$749" in on and "$2,497" in on and "$6" in on and "$2,197" in on, "on the AI page: the printed prices")
ok("$749" not in off and "$2,497" not in off and "$6 " not in off and "$24" not in off, "off the page: no prices at all")
ok("30-minute" in on and "30-minute" in off, "the 30-minute Strategy Visit is the next step")
ok("send us your photos" in off.lower() and "NEVER" in off, "never photo-to-AI")
ok("green screens" in off, "no green screens is allowed")
ok("Do NOT take bookings or payments" in off, "coming-soon offers are not sold")
ok("ALREADY A CLIENT" in off, "clients are not pitched the visit")
os.environ.pop("AI_STUDIO_PAGE_LIVE", None)
ok("mwmcreations.com/ai-studio" not in ai.maya_ai_context("", "asked"), "draft page: no link to a 404")
os.environ["AI_STUDIO_PAGE_LIVE"] = "1"
ok("mwmcreations.com/ai-studio/" in ai.maya_ai_context("", "asked"), "live page: the link is offered")
os.environ.pop("AI_STUDIO_PAGE_LIVE", None)

print("\n== app.py wiring")
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
ok("import ai_studio as _ai" in SRC, "module imported")
web = SRC.split("PATCH #132: on /exclusive-offer Maya knows the offer")[1][:1500]
ok("_ai.maya_ai_context(page_url" in web and "_m.get('role') == 'user'" in web, "web chat: page + visitor's own words")
wa = SRC.split("PATCH #140: AI Studio branch (WhatsApp leg)")[1][:1400]
ok("_ai.ai_lead(" in wa and '_lead_ctx = (_lead_ctx or "") + _ai.maya_ai_context("", _ai_why)' in wa, "WhatsApp: branch adds the block")
ok('if _m.get("role") == "user"' in wa, "WhatsApp: only the lead's words")
ig = SRC.split("PATCH #140: AI Studio branch (Instagram leg)")[1][:1400]
ok("_ai.ai_lead(" in ig and "_ai.maya_ai_context(" in ig, "Instagram: branch adds the block")
i_wa = SRC.index("PATCH #140: AI Studio branch (WhatsApp leg)")
ok(i_wa < SRC.index("PATCH #111: client mode", i_wa), "WhatsApp: AI block sits before client mode, like AD_09")
ok(SRC.count("except Exception as _aie") == 3, "every hook is non-fatal")
ok("HYBRID AI studio" in ai.maya_ai_context("", "asked") and "NOT 100% AI" in ai.maya_ai_context("https://mwmcreations.com/ai-studio/", ""), "hybrid framing in every AI block")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
