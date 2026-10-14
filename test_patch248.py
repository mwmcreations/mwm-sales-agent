"""PATCH #248 gate — Maya's own outbound SMS tool (send_sms_to_lead, Command
Mode): the kind follows the inbound window, the words go through sms_copy
(brand + STOP for outreach, bare reply inside the window), every refusal
from _sms_gates comes back with what to do instead, internal numbers are
refused, nothing is sent twice. Then runs the #247 gate (→ 246 → …)."""
import ast
import os
import re
import subprocess
import sys
from datetime import datetime

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sms_copy as sc   # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
code = "\n".join(ast.get_source_segment(SRC, n) for n in tree.body
                 if (isinstance(n, ast.FunctionDef) and n.name == "_maya_sms_tool")
                 or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_SMS_REFUSAL_HINTS" for t in n.targets)))
check("lift", "def _maya_sms_tool(" in code and "_SMS_REFUSAL_HINTS = {" in code)

sent, slack, mirrored = [], [], []
state = {"window": False, "gate": (True, "ok")}
lead_db = {"whatsapp:+14075550123": {"name": "Ana"}}


def fake_send(phone, body, kind=None):
    sent.append((phone, body, kind))
    ok, reason = state["gate"]
    return {"ok": True, "sid": "SM1"} if ok else {"ok": False, "reason": reason}


G = {"pytz": pytz, "datetime": datetime, "TIMEZONE": "America/New_York", "re": re,
     "SMS_KIND_TRANSACTIONAL": "transactional", "SMS_KIND_MARKETING": "marketing", "SLACK_MAYA_CHANNEL": "#maya",
     "_sms_copy": sc, "_send_sms": fake_send,
     "_sms_inbound_window_open": lambda ph: state["window"],
     "_is_internal_number": lambda ph: ph.endswith("8135031224"), "_is_michael_phone": lambda ph: False,
     "_find_lead_by_phone": lambda ph: ("whatsapp:" + ph, lead_db.get("whatsapp:" + ph)),
     "lead_data": lead_db, "_mirror_to_maya_shadow_async": lambda ident, d, t: mirrored.append((ident, d, t)),
     "_post_to_slack_async": lambda ch, msg: slack.append((ch, msg)),
     "_TALLY": type("T", (), {"bump": staticmethod(lambda *a, **k: None)})()}
sys.modules.setdefault("sms_consent", __import__("sms_consent"))
exec(compile(code, "maya_sms", "exec"), G)
tool = G["_maya_sms_tool"]

r = tool("(407) 555-0123", "Michael has Thursday 10 AM open for your studio visit - want it?", "Ana")
check("send.outreach", r.get("success") and r["kind"] == "marketing" and sent[-1][0] == "+14075550123"
      and sent[-1][1].startswith(sc.PREFIX) and "STOP" in sent[-1][1].upper() and "Thursday 10 AM" in sent[-1][1], r)
check("send.records", lead_db["whatsapp:+14075550123"].get("last_outbound_sms") and slack and "Text Sent" in slack[-1][1]
      and mirrored and mirrored[-1][2].startswith("[SMS] "))
check("send.result_masks", r["sent_to"] == "...0123" and "+1407" not in str(r.get("sent_to")))

state["window"] = True
r = tool("+14075550123", "Yes - 10 AM Thursday works, see you then.", "Ana")
check("send.reply_in_window", r.get("success") and r["kind"] == "transactional" and not sent[-1][1].startswith(sc.PREFIX) and "STOP" not in sent[-1][1].upper())
state["window"] = False

n_before = len(sent)
for reason, hint_word in (("no_consent", "send_email_to_lead"), ("quiet_hours", "10 AM-8 PM"), ("monthly_cap", "4 outreach"),
                          ("do_not_sms", "STOP"), ("no_consent_marketing", "booking texts"), ("twilio_env_missing", "Michael")):
    state["gate"] = (False, reason)
    r = tool("+14075550123", "hello there", "Ana")
    check(f"refused.{reason}", "error" in r and reason in r["error"] and hint_word in r.get("what_to_do", ""), r)
state["gate"] = (True, "ok")
check("refused.nothing_sent_twice", len(sent) == n_before + 6)

r = tool("+18135031224", "hi", "Michael")
check("refuse.internal", "internal number" in r.get("error", "") and len(sent) == n_before + 6)
r = tool("not a number", "hi")
check("refuse.bad_number", "not a mobile number" in r.get("error", ""))
r = tool("+14075550123", "   ")
check("refuse.empty", "message" in r.get("error", ""))
r = tool("+14075550123", "word " * 120)
check("refuse.too_long", "does not fit" in r.get("error", "") and "280" in r["error"] and len(sent) == n_before + 6)

# static wiring
tools = SRC[SRC.index("COMMAND_TOOLS = ["):SRC.index("def get_command_reply(")]
check("wire.tool_defined", '"name": "send_sms_to_lead"' in tools and '"required": ["phone", "message"]' in tools[tools.index('"name": "send_sms_to_lead"'):tools.index('"name": "send_reengagement_template"')])
check("wire.dispatch", 'elif tool_name == "send_sms_to_lead":' in SRC and '_maya_sms_tool(tool_input.get("phone", ""), tool_input.get("message", "")' in SRC)
prm = SRC[SRC.index('COMMAND_SYSTEM_PROMPT = """'):SRC.index('COMMAND_SYSTEM_PROMPT = """') + 6000]
check("wire.prompt", "send_sms_to_lead" in prm and "4-per-month cap" in prm and "text first (send_sms_to_lead)" in prm)
check("wire.gates_untouched", "def _sms_gates(lead_phone, kind=SMS_KIND_MARKETING):" in SRC and "_send_sms(e164, body, kind=kind)" in code
      and "kind=SMS_KIND_OPERATOR" not in code)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch247.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #247 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("247: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
