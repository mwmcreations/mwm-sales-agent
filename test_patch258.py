"""PATCH #258 gate — ONE text to Michael per form lead (Michael, 21 Oct 13:15:
"I don't need to receive those two text messages almost at the same time…
combine both"). The CALL NOW is the one text and now carries the email and
the website; "New lead captured by Maya" is skipped for a form lead (and
its linked WhatsApp number) and kept for organic WhatsApp / Instagram leads.
Then runs the #257 gate (→ 256 → 255 → …)."""
import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import call_now as cn      # noqa: E402
import lead_form as lf     # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()

# ── 1 · the one text ────────────────────────────────────────────────────────
sms, eric = cn.compose("Vicente Orellana", "Owning Your House", "+14077772350", "$50k_to_$150k",
                       "owner_/_founder_/_partner", "Our unique process", "yes",
                       ad_label="AD_15 | Room or brain | Video | Oct 2026", pretty=lf.pretty,
                       email="vicente7orellana@gmail.com", website="www.owningyourhouse.com")
L = sms.split("\n")
check("sms.order", L[0] == "CALL NOW - form lead (yes)" and L[1] == "Vicente Orellana - Owning Your House"
      and L[2] == "$50k to $150k / owner / founder / partner" and L[3] == "Must understand: Our unique process"
      and L[4] == "+14077772350" and L[5] == "vicente7orellana@gmail.com" and L[6] == "www.owningyourhouse.com"
      and L[7].startswith("ad AD_15") and L[8] == "First call inside the hour.", sms)
check("sms.short", len(sms) <= 400, len(sms))
check("eric.carries_both", "`+14077772350` · vicente7orellana@gmail.com · www.owningyourhouse.com · ad AD_15" in eric, eric)
sms0, eric0 = cn.compose("Ana", "", "4075551234", "", "", "", "no")
check("sms.unchanged_without", sms0 == "CALL NOW - form lead (no)\nAna\n4075551234\nFirst call inside the hour."
      and "·  ·" not in eric0 and eric0.count("·") == 1, sms0 + " | " + eric0)
long = cn.compose("x" * 200, "y" * 200, "z" * 50, "r" * 50, "q" * 50, "m" * 500, "yes", email="e" * 300, website="w" * 300)[0]
check("sms.capped_fields", len(long) < 650, len(long))

# ── 2 · the alert, lifted ───────────────────────────────────────────────────
tree = ast.parse(SRC)
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "notify_michael_maya_lead"]
check("lift.found", len(fns) == 1)
alerts, tally, errors = [], [], []


class OA:
    def alert(self, kind, body, eric_text=None): alerts.append((kind, body, eric_text)); return {"sms": "sent", "eric": True}


class Tally:
    def bump(self, *a): tally.append(a)


lead_data = {"whatsapp:+14077772350": {"name": "Vicente Orellana", "meta_lead_ad": True},
             "whatsapp:+14073614743": {"name": "Vicente Orellana", "linked_form_key": "whatsapp:+14077772350"},
             "whatsapp:+17864034823": {"name": "Melina"}}
G = dict(lead_data=lead_data, _operator_alert=OA(), _TALLY=Tally(),
         _report_error=lambda ctx, exc, detail="": errors.append((ctx, str(exc))))
exec(compile(ast.Module(body=fns, type_ignores=[]), "app_258", "exec"), G)
G["notify_michael_maya_lead"]("Name: Vicente", "whatsapp:+14077772350")
check("alert.form_lead_skipped", alerts == [] and tally[-1][0] == "lead_form.skipped_lead_alert")
G["notify_michael_maya_lead"]("Name: Vicente", "whatsapp:+14073614743")
check("alert.linked_skipped", alerts == [] and len(tally) == 2)
G["notify_michael_maya_lead"]("Name: Melina\nInterest: podcast", "whatsapp:+17864034823")
check("alert.organic_kept", len(alerts) == 1 and alerts[0][0] == "lead" and alerts[0][1].startswith("New lead captured by Maya\n+17864034823"))
G["notify_michael_maya_lead"]("Name: X", "whatsapp:+10000000000")
check("alert.unknown_sender_kept", len(alerts) == 2 and not errors)

# ── 3 · wiring ──────────────────────────────────────────────────────────────
check("wire.rail_passes_email_site", "ad_label=label, pretty=_lf.pretty,\n                            email=rec.get(\"email\"), website=rec.get(\"website\"))" in SRC)
check("wire.skip_reason_logged", "CALL NOW covers it; no second text" in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch257.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #257 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("257: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE258 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
