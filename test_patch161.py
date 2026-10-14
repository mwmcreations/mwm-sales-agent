"""PATCH #161 gate — (a) a YES by email counts (Gmail is asked before the
"unconfirmed" text goes to Michael); (b) Michael texting the line gets
Command Mode by operator SMS, and "He is confirmed" marks the event;
(c) a reply inside the inbound window skips quiet hours.
Prints "N passed, M failed", then runs the #160 gate (which chains #158 → …)."""
import ast
import os
import re
import subprocess
import sys
import time as _time
from datetime import datetime

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import operator_cmd as oc     # noqa: E402
import susan_gmail as sg      # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


tz = pytz.timezone("America/New_York")
NOW = tz.localize(datetime(2026, 10, 14, 6, 31))
# ── operator_cmd (pure) ─────────────────────────────────────────────────────
for t, want in (("He is confirmed", True), ("confirmed", True), ("Good morning", False), ("He is not confirmed", False),
                ("cancel it", False), ("ok confirmado", True), ("she will be there", True), ("unconfirmed", False), ("", False)):
    check(f"oc.is_confirmation {t!r}", oc.is_confirmation(t) == want)
ALERTS = [{"event_id": "e1", "name": "Gisele Kolbrich", "time": "3:00 PM", "date": "Tuesday, October 13", "at": "2026-10-13T06:41:00-04:00"},
          {"event_id": "e2", "name": "Dr. Scott Robinson", "time": "9:30 AM", "date": "Wednesday, October 14", "at": "2026-10-14T06:14:55-04:00"}]
check("oc.target_latest", [a["event_id"] for a in oc.targets("He is confirmed", ALERTS, NOW)] == ["e2"])
check("oc.target_named", [a["event_id"] for a in oc.targets("Gisele confirmed", ALERTS, NOW)] == ["e1"])
check("oc.target_all", [a["event_id"] for a in oc.targets("both confirmed", ALERTS, NOW)] == ["e1", "e2"])
check("oc.target_stale", oc.targets("confirmed", ALERTS, tz.localize(datetime(2026, 10, 16, 6, 0))) == [])
check("oc.target_bad_at", oc.targets("confirmed", [{"event_id": "x", "at": "nope"}], NOW) == [])
check("oc.reply_one", oc.reply_for(ALERTS[-1:]).startswith("Got it - Dr. Scott Robinson at 9:30 AM (Wednesday, October 14) is marked confirmed."))
check("oc.reply_many", "Gisele Kolbrich 3:00 PM" in oc.reply_for(ALERTS) and "Dr. Scott Robinson 9:30 AM" in oc.reply_for(ALERTS))
check("oc.reply_none", oc.reply_for([]) == "")
ch = oc.split_sms("one two. " * 120, 450)
check("oc.split", all(len(c) <= 450 for c in ch) and " ".join(ch).replace("  ", " ").strip() == ("one two. " * 120).strip() and len(ch) >= 3)
check("oc.split_short", oc.split_sms("hi") == ["hi"] and oc.split_sms("") == [])


# ── susan_gmail.inbound_from with a fake service ────────────────────────────
class _Exec:
    def __init__(self, v):
        self.v = v

    def execute(self):
        return self.v


class FakeMsgs:
    def __init__(self):
        self.q = None

    def list(self, userId, q, maxResults):
        self.q = q
        return _Exec({"messages": [{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t2"}]})

    def get(self, userId, id, format, metadataHeaders):
        return _Exec({"id": id, "threadId": "t" + id[-1], "snippet": f"snip {id}", "internalDate": "1760400000000" if id == "m1" else "1760500000000",
                      "payload": {"headers": [{"name": "Subject", "value": "Re: Reply YES"}, {"name": "Date", "value": "Tue"},
                                              {"name": "From", "value": "Scott <scott@x.com>"}]}})


class FakeSvc:
    def __init__(self):
        self.m = FakeMsgs()

    def users(self):
        return self

    def messages(self):
        return self.m


svc = FakeSvc()
rows = sg.inbound_from("Scott@X.com", 1760390000.9, mailbox="info", service=svc)
check("gm.query", svc.m.q == "from:scott@x.com after:1760390000", svc.m.q)
check("gm.rows_newest_first", [r["id"] for r in rows] == ["m2", "m1"] and rows[0]["subject"] == "Re: Reply YES" and rows[0]["snippet"] == "snip m2")
check("gm.bad_inputs", sg.inbound_from("", 1, service=svc) == [] and sg.inbound_from("a@b.c", "x", service=svc) == [])

# ── app.py wiring ───────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
wh = SRC[SRC.index("def sms_inbound_webhook():"):SRC.index("def _is_michael_phone(phone):")]
eb = wh[wh.index("        else:\n"):]
check("wire.michael_before_lead_path", "if _is_michael_phone(frm):" in eb and "_handle_michael_sms, args=(frm, body)" in eb
      and eb.index("_is_michael_phone(frm)") < eb.index("_sms_inbound_stamp(frm)") < eb.index("_handle_incoming_sms"))
hm = SRC[SRC.index("def _handle_michael_sms(frm, body):"):SRC.index("def _handle_incoming_sms(frm, body):")]
check("wire.michael_operator_kind_only", hm.count("kind=SMS_KIND_OPERATOR") >= 2 and "SMS_KIND_TRANSACTIONAL" not in hm and "SMS_KIND_MARKETING" not in hm)
check("wire.michael_marks", '_pg.save_state(f"confirmed:{a.get(\'event_id\')}"' in hm and '_pg.save_state("unconfirmed_alerts", [a for a in alerts if a.get("event_id") not in ids])' in hm
      and "get_command_reply(snap)" in hm and "_oc.split_sms(clean, 450)[:3]" in hm)
wt = SRC[SRC.index("# ── PATCH #157 · T-3 h: no reply to the YES ask -> Michael ──"):SRC.index("# ── S-3 · which confirmations are due right now ─────")]
check("wire.watch_confirmed_mark", '_pg.load_state(f"confirmed:{event_id}", None)' in wt and wt.index('"confirmed:{event_id}"') < wt.index("_operator_alert.alert("))
check("wire.watch_email_reply", '_susan_gmail_mod.inbound_from(_u_email, _asked_dt.timestamp(), mailbox="info", limit=3)' in wt
      and 'mailbox="michael"' in wt and wt.index("inbound_from(") < wt.index("_operator_alert.alert(") and '"via": "email"' in wt)
check("wire.watch_remembers_alert", '_pg.save_state("unconfirmed_alerts", _al[-20:])' in wt and 'text me \\"confirmed\\"' in wt)
gt = SRC[SRC.index("def _sms_gates("):SRC.index("def _send_sms(")]
check("wire.gate_window_before_consent_and_quiet", 'if kind == SMS_KIND_TRANSACTIONAL and _sms_inbound_window_open(lead_phone, now):' in gt
      and gt.index("_sms_inbound_window_open(lead_phone, now)") < gt.index('if consent.get("status") != "yes":')
      and gt.index("_sms_inbound_window_open(lead_phone, now)") < gt.index('return False, "quiet_hours"')
      and gt.index('return False, "do_not_sms"') < gt.index("_sms_inbound_window_open(lead_phone, now)"))

# ── gate behaviour: consented but quiet hours, with the window open ─────────
tree = ast.parse(SRC)
want = {"_sms_gates", "_sms_inbound_window_open", "_sms_inbound_stamp"}
code = "\n".join(ast.get_source_segment(SRC, n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want)


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
consent_db = {}
G = {"pytz": pytz, "datetime": datetime, "TIMEZONE": "America/New_York",
     "TWILIO_ACCOUNT_SID": "AC", "TWILIO_AUTH_TOKEN": "t", "TWILIO_MESSAGING_SERVICE_SID": "MG",
     "SMS_KIND_TRANSACTIONAL": "transactional", "SMS_KIND_MARKETING": "marketing",
     "_sms_policy": lambda kind: ({"consent_field": "transactional", "quiet_start": 23, "quiet_end": 23, "cap": None, "counter_field": "c"}  # always quiet
                                  if kind == "transactional" else
                                  {"consent_field": "marketing", "quiet_start": 23, "quiet_end": 23, "cap": 4, "counter_field": "m"}),
     "_sms_consent_get": lambda ph: dict(consent_db.get(ph) or {}), "print": lambda *a, **k: None}
exec(compile(code, "app_gates", "exec"), G)
gates = G["_sms_gates"]
PH = "+14075550199"
consent_db[PH] = {"status": "yes", "transactional": True}
check("gate.quiet_without_window", gates(PH, "transactional") == (False, "quiet_hours"))
fpg.d[f"sms_inbound_at:{PH}"] = _time.time() - 600
check("gate.window_beats_quiet", gates(PH, "transactional") == (True, "inbound_window"))
check("gate.window_not_marketing", gates(PH, "marketing") == (False, "no_consent_marketing"))
fpg.d[f"do_not_sms:{PH}"] = True
check("gate.stop_still_wins", gates(PH, "transactional") == (False, "do_not_sms"))

# ── _handle_michael_sms behaviour ──────────────────────────────────────────
del fpg.d[f"do_not_sms:{PH}"]
code2 = "\n".join(ast.get_source_segment(SRC, n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"_handle_michael_sms", "_is_michael_phone"})
sent, slack = [], []
G2 = {"pytz": pytz, "datetime": datetime, "TIMEZONE": "America/New_York", "re": re, "os": os,
      "michael_command_history": [], "SMS_KIND_OPERATOR": "operator", "SLACK_ERIC_CHANNEL": "#eric",
      "_send_sms": lambda to, body, kind=None: (sent.append((to, body, kind)) or {"ok": True}),
      "_post_to_slack_async": lambda ch, msg: slack.append((ch, msg)),
      "_mirror_to_maya_shadow_async": lambda *a, **k: None, "_report_error": lambda *a, **k: None,
      "_TALLY": type("T", (), {"bump": staticmethod(lambda *a, **k: None)})(),
      "get_command_reply": lambda snap: ("Morning Michael. Two visits today; Robinson 9:30 is confirmed.", snap + [{"role": "assistant", "content": "x"}]),
      "clean_response": lambda t: t, "_sms_copy": type("S", (), {"ascii_fold": staticmethod(lambda t: t)})(), "print": lambda *a, **k: None}
os.environ["MICHAEL_PHONE"] = "+18135031224"
exec(compile(code2, "app_msms", "exec"), G2)
check("michael.phone_match", G2["_is_michael_phone"]("+18135031224") and G2["_is_michael_phone"]("8135031224") and not G2["_is_michael_phone"]("+14075550199"))
fpg.d["unconfirmed_alerts"] = [dict(a) for a in ALERTS]
fpg.d["unconfirmed_alerts"][-1]["at"] = datetime.now(tz).isoformat()
G2["_handle_michael_sms"]("+18135031224", "He is confirmed")
check("michael.confirm_marks", fpg.d.get("confirmed:e2", {}).get("via") == "michael-sms" and "confirmed:e1" not in fpg.d
      and [a["event_id"] for a in fpg.d["unconfirmed_alerts"]] == ["e1"], fpg.d)
check("michael.confirm_reply", len(sent) == 1 and sent[0][2] == "operator" and sent[0][1].startswith("Got it - Dr. Scott Robinson") and slack and "Michael confirmed by text" in slack[0][1])
sent.clear()
G2["_handle_michael_sms"]("+18135031224", "Good morning")
check("michael.command_mode_reply", len(sent) == 1 and sent[0][2] == "operator" and "Morning Michael" in sent[0][1]
      and G2["michael_command_history"] and G2["michael_command_history"][0]["content"] == "[via SMS] Good morning")

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch160.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #160 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("160: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
