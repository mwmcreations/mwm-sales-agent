"""PATCH #160 gate — (a) the SMS inbound window: a person who texted the
line first can be ANSWERED (transactional) inside 24 h without a consent
record; marketing still needs the box; STOP still wins. (b) the UTILITY
WhatsApp templates for the booking rail and the /admin/wa-templates route.
Prints "N passed, M failed", then runs the #158 gate (which chains #157 → …)."""
import ast
import os
import re
import subprocess
import sys
import types
from datetime import datetime

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sms_consent as sc      # noqa: E402
import wa_templates as wt     # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# ── (a) pure window ──────────────────────────────────────────────────────────
check("win.inside", sc.inbound_window_open(1000, 1000 + 3600) and sc.inbound_window_open(1000, 1000 + 24 * 3600))
check("win.outside", not sc.inbound_window_open(1000, 1000 + 24 * 3600 + 1))
check("win.missing", not sc.inbound_window_open(None, 5) and not sc.inbound_window_open("", 5) and not sc.inbound_window_open("x", 5)
      and not sc.inbound_window_open(0, 5))
check("win.future_stamp_closed", not sc.inbound_window_open(2000, 1000))
check("win.hours_const", sc.INBOUND_WINDOW_H == 24)

# ── (a) the gate, lifted from app.py and run against fakes ──────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
want = {"_sms_gates", "_sms_inbound_window_open", "_sms_inbound_stamp"}
code = "\n".join(ast.get_source_segment(SRC, n) for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name in want)
check("gate.lifted", code.count("def ") == 3)


class FakePG:
    def __init__(self):
        self.d = {}

    def enabled(self):
        return True

    def load_state(self, k, default=None):
        return self.d.get(k, default)

    def save_state(self, k, v):
        self.d[k] = v


fpg = FakePG()
sys.modules["pg_store"] = fpg
tz = pytz.timezone("America/New_York")
NOW = tz.localize(datetime(2026, 10, 12, 14, 0))
consent_db = {}
G = {"pytz": pytz, "datetime": datetime, "TIMEZONE": "America/New_York",
     "TWILIO_ACCOUNT_SID": "AC", "TWILIO_AUTH_TOKEN": "t", "TWILIO_MESSAGING_SERVICE_SID": "MG",
     "SMS_KIND_TRANSACTIONAL": "transactional", "SMS_KIND_MARKETING": "marketing",
     "_sms_policy": lambda kind: ({"consent_field": "transactional", "quiet_start": 0, "quiet_end": 24, "cap": None, "counter_field": "monthly_count_transactional"}
                                  if kind == "transactional" else
                                  {"consent_field": "marketing", "quiet_start": 10, "quiet_end": 20, "cap": 4, "counter_field": "monthly_count_marketing"}),
     "_sms_consent_get": lambda ph: dict(consent_db.get(ph) or {}),
     "print": lambda *a, **k: None}
exec(compile(code, "app_gates", "exec"), G)
gates, stamp, win = G["_sms_gates"], G["_sms_inbound_stamp"], G["_sms_inbound_window_open"]
PH = "+14075550100"
check("gate.no_consent_no_window", gates(PH, "transactional") == (False, "no_consent"))
import time as _time
stamp(PH)                                  # the real clock: the gate reads it too
check("gate.stamp_written", abs(float(fpg.d[f"sms_inbound_at:{PH}"]) - _time.time()) < 5)
check("gate.window_answers", gates(PH, "transactional") == (True, "inbound_window"))
stamp(PH, NOW)                             # an explicit clock is honoured
check("gate.stamp_explicit", abs(float(fpg.d[f"sms_inbound_at:{PH}"]) - NOW.timestamp()) < 1)
fpg.d[f"sms_inbound_at:{PH}"] = _time.time() - 3600
check("gate.window_not_marketing", gates(PH, "marketing") == (False, "no_consent"))
fpg.d[f"do_not_sms:{PH}"] = True
check("gate.stop_wins", gates(PH, "transactional") == (False, "do_not_sms"))
del fpg.d[f"do_not_sms:{PH}"]
fpg.d[f"sms_inbound_at:{PH}"] = NOW.timestamp() - 30 * 3600 - 10 ** 9   # long ago
check("gate.old_stamp_closed", gates(PH, "transactional") == (False, "no_consent"))
consent_db[PH] = {"status": "yes", "transactional": True}
check("gate.consent_still_ok", gates(PH, "transactional") == (True, "ok"))
consent_db[PH] = {"status": "yes", "marketing": True}
check("gate.wrong_box_named", gates(PH, "transactional") == (False, "no_consent_transactional"))

# ── (a) webhook wiring ───────────────────────────────────────────────────────
wh = SRC[SRC.index("def sms_inbound_webhook():"):SRC.index("def _sms_lead_context(rec):")]
stop_branch = wh[wh.index('if opt == "STOP"'):wh.index('elif opt == "START"')]
start_branch = wh[wh.index('elif opt == "START"'):wh.index("        else:\n")]
else_branch = wh[wh.index("        else:\n"):]
check("wire.stamp_not_on_stop", "_sms_inbound_stamp(" not in stop_branch)
check("wire.stamp_on_start_and_text", "_sms_inbound_stamp(frm)" in start_branch and "_sms_inbound_stamp(frm)" in else_branch
      and else_branch.index("_sms_inbound_stamp(frm)") < else_branch.index("_handle_incoming_sms"))
gt = SRC[SRC.index("def _sms_gates("):SRC.index("def _send_sms(")]
check("wire.gate_window_transactional_only", 'kind == SMS_KIND_TRANSACTIONAL and _sms_inbound_window_open(lead_phone, now)' in gt
      and 'return True, "inbound_window"' in gt and gt.index('return False, "do_not_sms"') < gt.index('"inbound_window"'))

# ── (b) templates ────────────────────────────────────────────────────────────
check("tpl.names", set(wt.TEMPLATES) == {"mwm_visit_confirm", "mwm_visit_today", "mwm_visit_rebook"})
for n, t in wt.TEMPLATES.items():
    b = wt.graph_body(n)
    text = b["components"][0]["text"]
    nvars = len(set(re.findall(r"\{\{(\d+)\}\}", text)))
    check(f"tpl.{n}.utility_en", b["category"] == "UTILITY" and b["language"] == "en_US" and b["name"] == n)
    check(f"tpl.{n}.examples_match", nvars == len(t["example"]) == len(b["components"][0]["example"]["body_text"][0])
          and sorted(int(x) for x in re.findall(r"\{\{(\d+)\}\}", text)) == sorted(set(range(1, nvars + 1))))
    check(f"tpl.{n}.no_edge_var", not text.startswith("{{") and not text.endswith("}}") and len(text) <= 1024)
    check(f"tpl.{n}.address_or_slots", (wt.STUDIO_ADDRESS in text) or (n == "mwm_visit_rebook" and "{{2}} or {{3}}" in text))
check("tpl.confirm_wording", "Reply YES to confirm or tell us a better time." in wt.TEMPLATES["mwm_visit_confirm"]["text"]
      and "Your studio visit with Michael Moraes is {{1}} on {{2}} at 1500 Park Center Dr, Suite 230, Orlando." in wt.TEMPLATES["mwm_visit_confirm"]["text"])
check("tpl.params_clean", wt.confirm_params(" 10:00\nAM ", "Tue,  Oct 13") == ["10:00 AM", "Tue, Oct 13"]
      and wt.rebook_params("Sarah", "A", "") == ["Sarah", "A", "another time this week"] and wt.today_params("") == ["-"])
summ = wt.status_summary([{"name": "mwm_visit_confirm", "status": "APPROVED", "category": "UTILITY", "language": "en_US"},
                          {"name": "other", "status": "APPROVED"}])
check("tpl.status_summary", summ["mwm_visit_confirm"]["status"] == "APPROVED" and summ["mwm_visit_rebook"]["status"] == "NOT SUBMITTED"
      and "other" not in summ)
rt = SRC[SRC.index("def admin_wa_templates():"):SRC.index("@app.route('/admin/reengage-oct12'")]
check("wire.tpl_route", "@app.route('/admin/wa-templates', methods=['GET'])" in SRC and '_admin_secret_ok(request.args.get("secret"))' in rt
      and 'if str(request.args.get("go") or "") != "1":' in rt and "_wt.graph_body(n)" in rt and "{META_WABA_ID}/message_templates" in rt
      and "_wt.status_summary(rows)" in rt and "META_ACCESS_TOKEN" in rt and "print(" not in rt)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch158.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL reengage gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("reengage: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
