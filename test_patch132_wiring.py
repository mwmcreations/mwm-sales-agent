"""PATCH #132 wiring — app.py routes the offer checkout and teaches Maya the offer.
Runs the behaviour tests (test_exclusive_offer.py) too, so one file gates the deploy."""
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
P = F = 0
def ok(c, l):
    global P, F
    if c: P += 1; print("  ok   " + l)
    else: F += 1; print("  FAIL " + l)

ok('SLACK_ROB_CHANNEL = "C0APLH98ANN"' in src, "#rob channel id defined")
ok("import exclusive_offer as _xo" in src, "module imported")
cfg = src[src.find("_xo.configure("):src.find("_xo.configure(") + 1200]
for k in ("post_slack=", "pg_load=", "pg_save=", "lead_data=lead_data", "lead_lookup_by_email=",
          "lead_lookup_by_phone=", "lead_lookup_by_name=", "update_sheet_status=",
          "lara_channel=SLACK_LARA_CHANNEL", "rob_channel=SLACK_ROB_CHANNEL", "now="):
    ok(k in cfg, f"configure passes {k}")
wh = src[src.find("def stripe_webhook():"):src.find("def stripe_webhook():") + 2500]
i_rent = wh.find("handle_studio_rental_paid(ev)")
i_xo = wh.find("_xo.handle_offer_paid(ev)")
i_pkg = wh.find("_studio.handle_stripe_event(ev)")
ok(0 < i_rent < i_xo < i_pkg, "webhook order: rental → exclusive offer → studio package")
ok(re.search(r"_xo_res = _xo\.handle_offer_paid\(ev\)\s+if _xo_res is not None:[\s\S]{0,160}return", wh) is not None,
   "an owned offer event returns before the package handler")
chat = src[src.find('system_prompt += f"\\n\\nThe visitor is currently on: {page_url}"'):][:300]
ok("_xo.maya_offer_context(page_url)" in chat, "Maya gets the offer context right after the page_url line")

r = subprocess.run([sys.executable, os.path.join(HERE, "test_exclusive_offer.py")],
                   capture_output=True, text=True)
last = (r.stdout.strip().splitlines() or [""])[-1]
m = re.match(r"(\d+) passed, (\d+) failed", last)
ok(bool(m) and m.group(2) == "0" and r.returncode == 0, f"behaviour tests green ({last})")
if m: P += int(m.group(1))
print(f"\n{P} passed, {F} failed")
sys.exit(1 if F else 0)
