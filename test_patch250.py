"""PATCH #250 gate — the booking rail sends its OWN WhatsApp templates
(mwm_visit_confirm at T-24, mwm_visit_today at T-2, mwm_visit_reschedule on a
no-show) but only while Meta lists each one APPROVED *and* UTILITY —
mwm_visit_rebook came back approved as MARKETING, which does not deliver to US
numbers, so it is retired. Everything not usable falls through to exactly what
the rail did before (#157). Then runs the #248 gate (→ 247 → 246 → …)."""
import ast
import os
import re
import subprocess
import sys
import time
from datetime import datetime

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wa_templates as wt         # noqa: E402
import outcome_sender as osd      # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# ── wa_templates: pure ──────────────────────────────────────────────────
t = wt.TEMPLATES["mwm_visit_reschedule"]
check("tpl.reschedule_defined", t["stage"] == "no-show" and len(t["example"]) == 4)
check("tpl.reschedule_placeholders", sorted(set(re.findall(r"\{\{(\d)\}\}", t["text"]))) == ["1", "2", "3", "4"])
check("tpl.reschedule_words", "was marked as missed" in t["text"] and "To reschedule, reply with one of these times" in t["text"])
check("tpl.rebook_retired", wt.TEMPLATES["mwm_visit_rebook"].get("retired") and "MARKETING" in wt.TEMPLATES["mwm_visit_rebook"]["retired"])
for n, d in wt.TEMPLATES.items():
    check(f"tpl.{n}.examples_match", len(set(re.findall(r"\{\{(\d)\}\}", d["text"]))) == len(d["example"]))
    check(f"tpl.{n}.graph_body", wt.graph_body(n)["category"] == "UTILITY" and wt.graph_body(n)["name"] == n)
check("tpl.stage_template", wt.stage_template(24) == "mwm_visit_confirm" and wt.stage_template(2) == "mwm_visit_today"
      and wt.stage_template(48) is None and wt.stage_template(168) is None and wt.stage_template("x") is None)
check("tpl.stage_params_24", wt.stage_params(24, "10:00 AM", "Tuesday, October 13") == ["10:00 AM", "Tuesday, October 13"])
check("tpl.stage_params_2", wt.stage_params(2, "3:00 PM", "whatever") == ["3:00 PM"])
check("tpl.stage_params_48", wt.stage_params(48, "3:00 PM", "x") == [])
p = wt.reschedule_params("Sarah", "Tuesday, October 13", "Thursday, October 15 at 10:00 AM", "")
check("tpl.reschedule_params_fallback", p == ["Sarah", "Tuesday, October 13", "Thursday, October 15 at 10:00 AM", wt.SECOND_SLOT_FALLBACK])
p = wt.reschedule_params("  Ana\nMaria ", "d", "a", "b")
check("tpl.reschedule_params_clean", p[0] == "Ana Maria" and p[3] == "b")
check("tpl.sent_via_label", wt.SENT_VIA != "WhatsApp (approved template)" and "visit template" in wt.SENT_VIA)

ROWS = [{"name": "mwm_visit_confirm", "status": "APPROVED", "category": "UTILITY"},
        {"name": "mwm_visit_today", "status": "APPROVED", "category": "UTILITY"},
        {"name": "mwm_visit_rebook", "status": "APPROVED", "category": "MARKETING"},
        {"name": "mwm_visit_reschedule", "status": "PENDING", "category": "UTILITY"},
        {"name": "mwm_lara_shoot_reminder", "status": "APPROVED", "category": "UTILITY"}]
check("tpl.usable", wt.usable(ROWS) == {"mwm_visit_confirm", "mwm_visit_today"})
check("tpl.usable_approved_later", wt.usable(ROWS[:3] + [{"name": "mwm_visit_reschedule", "status": "APPROVED", "category": "UTILITY"}])
      == {"mwm_visit_confirm", "mwm_visit_today", "mwm_visit_reschedule"})
check("tpl.usable_rebook_never", "mwm_visit_rebook" not in wt.usable([{"name": "mwm_visit_rebook", "status": "APPROVED", "category": "UTILITY"}]))
check("tpl.usable_empty", wt.usable(None) == set() and wt.usable([{}]) == set())
ss = wt.status_summary(ROWS)
check("tpl.status_summary", ss["mwm_visit_confirm"]["usable"] is True and ss["mwm_visit_rebook"]["usable"] is False
      and "retired" in ss["mwm_visit_rebook"] and ss["mwm_visit_reschedule"]["usable"] is False)

# ── app.py: the usable-cache and the guarded sender ──────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
WANT = {"_wa_visit_templates_usable", "_wa_visit_template_send", "_wa_visit_templates_status", "_rebook_template_send"}
code = "\n".join(ast.get_source_segment(SRC, n) for n in tree.body
                 if (isinstance(n, ast.FunctionDef) and n.name in WANT)
                 or (isinstance(n, ast.Assign) and any(getattr(tg, "id", "") in ("_WA_VISIT_TPL", "_WA_VISIT_TPL_TTL", "_WA_VISIT_TPL_RETRY") for tg in n.targets)))
check("lift", all(f"def {w}(" in code for w in WANT) and "_WA_VISIT_TPL = {" in code)

http_calls, sends = [], []
state = {"rows": ROWS, "status": 200, "raise": False}


class _Resp:
    def __init__(self, status, rows):
        self.status_code = status
        self.content = b"x"
        self._rows = rows

    def json(self):
        return {"data": self._rows} if self.status_code == 200 else {"error": {"message": "boom"}}


class _Http:
    @staticmethod
    def get(url, headers=None, params=None, timeout=None):
        http_calls.append(url)
        if state["raise"]:
            raise RuntimeError("down")
        return _Resp(state["status"], state["rows"])


G = {"time": time, "datetime": datetime, "pytz": pytz, "re": re, "TIMEZONE": "America/New_York",
     "META_ACCESS_TOKEN": "tok", "META_WABA_ID": "436", "http_requests": _Http, "_wt": wt,
     "send_wa_utility_template": lambda to, name, params: sends.append((to, name, list(params))) or {"ok": True}}
exec(compile(code, "p250", "exec"), G)
usable, send, status, rebook = G["_wa_visit_templates_usable"], G["_wa_visit_template_send"], G["_wa_visit_templates_status"], G["_rebook_template_send"]

check("cache.first_read", usable() == {"mwm_visit_confirm", "mwm_visit_today"} and len(http_calls) == 1)
check("cache.hit", usable() == {"mwm_visit_confirm", "mwm_visit_today"} and len(http_calls) == 1)
check("cache.force", usable(force=True) and len(http_calls) == 2)
st = status()
check("status.rail", st["rail"] == {"T-24": "mwm_visit_confirm", "T-2": "mwm_visit_today", "no-show": "email"} and st["error"] == "" and st["refreshed_at"])
state["raise"] = True
check("cache.error_keeps_last", usable(force=True) == {"mwm_visit_confirm", "mwm_visit_today"} and "down" in status()["error"])
G["_WA_VISIT_TPL"]["checked_at"] = 0
state["raise"] = False; state["status"] = 500
check("cache.http_error_keeps_last", usable() == {"mwm_visit_confirm", "mwm_visit_today"} and status()["error"].startswith("HTTP 500"))
check("cache.retry_sooner", time.time() - G["_WA_VISIT_TPL"]["checked_at"] > G["_WA_VISIT_TPL_TTL"] - G["_WA_VISIT_TPL_RETRY"] - 5)
state["status"] = 200
G["_WA_VISIT_TPL"]["checked_at"] = 0
usable()

check("send.usable", send("whatsapp:+14075550123", "mwm_visit_confirm", ["10:00 AM", "Tue"]) and sends[-1] == ("whatsapp:+14075550123", "mwm_visit_confirm", ["10:00 AM", "Tue"]))
n = len(sends)
check("send.not_usable", send("whatsapp:+14075550123", "mwm_visit_reschedule", ["a"]) is None and len(sends) == n)
check("send.retired", send("whatsapp:+14075550123", "mwm_visit_rebook", ["a"]) is None and len(sends) == n)
check("send.none_name", send("whatsapp:+14075550123", None, []) is None and len(sends) == n)
G["META_ACCESS_TOKEN"] = ""
G["_WA_VISIT_TPL"]["checked_at"] = 0
check("cache.no_token", usable() == set() and "not set" in status()["error"])
G["META_ACCESS_TOKEN"] = "tok"

# rebook sender: not usable yet -> None, nothing sent
G["_WA_VISIT_TPL"]["checked_at"] = 0
state["rows"] = ROWS
usable(force=True)
check("rebook.not_yet", rebook("14075550123", "Sarah", ["Thu Oct 15 10:00 AM", "Fri 3 PM"], "2026-10-13T15:28:00-04:00") is None and len(sends) == n)
state["rows"] = ROWS[:3] + [{"name": "mwm_visit_reschedule", "status": "APPROVED", "category": "UTILITY"}]
usable(force=True)
check("rebook.sends", rebook("+1 (407) 555-0123", "Sarah", ["Thu Oct 15 10:00 AM", "Fri 3 PM"], "2026-10-13T15:28:00-04:00")
      and sends[-1] == ("whatsapp:+14075550123", "mwm_visit_reschedule", ["Sarah", "Tuesday, October 13", "Thu Oct 15 10:00 AM", "Fri 3 PM"]))
check("rebook.one_slot", rebook("14075550123", "Sarah", ["Thu Oct 15 10:00 AM"], "2026-10-13T15:28:00-04:00")
      and sends[-1][2][3] == wt.SECOND_SLOT_FALLBACK)
n = len(sends)
check("rebook.no_slots", rebook("14075550123", "Sarah", [], "2026-10-13T15:28:00-04:00") is None and len(sends) == n)
check("rebook.bad_armed_at", rebook("14075550123", "Sarah", ["a"], "garbage") and sends[-1][2][1] == "your scheduled day")

# ── outcome_sender: the rebook step takes the template, nothing else does ──
calls = {"wa": [], "tpl": [], "email": []}
osd.configure(report_error=lambda *a: None, post_slack=lambda *a: None,
              send_email=lambda to, subject, html: calls["email"].append(to) or {"ok": True},
              send_whatsapp=lambda phone, body: calls["wa"].append((phone, body)) or None,
              send_whatsapp_template=lambda phone, first, slots, armed_at: calls["tpl"].append((phone, first, slots, armed_at)) or True,
              slots=lambda: [{"display": "Thursday, October 15 at 10:00 AM EDT"}, {"display": "Friday, October 16 at 3:00 PM EDT"}],
              send_instagram=lambda *a: None, pg_load=lambda *a, **k: None, pg_save=lambda *a, **k: None,
              heartbeat=lambda *a, **k: None, lead_data={}, matt_channel="#m", maya_channel="#y", dev_channel="#d")
rec = {"name": "Sarah Lee", "phone": "+14075550123", "email": "s@x.com"}
seq = {"armed_at": "2026-10-13T15:28:00-04:00", "email": "s@x.com"}
ok, note = osd._deliver(osd.CH_WHATSAPP, osd.STEP_REBOOK, rec, "whatsapp:+14075550123", seq)
check("os.rebook_template", ok and "visit template" in note and calls["tpl"] == [("14075550123", "Sarah", ["Thursday, October 15 at 10:00 AM", "Friday, October 16 at 3:00 PM"], "2026-10-13T15:28:00-04:00")]
      and calls["email"] == [], f"{ok} {note} {calls}")
ok, note = osd._deliver(osd.CH_WHATSAPP, osd.STEP_NUDGE, rec, "whatsapp:+14075550123", seq)
check("os.nudge_untouched", ok and "sent by email" in note and len(calls["tpl"]) == 1 and calls["email"] == ["s@x.com"], f"{ok} {note}")
# template not usable yet -> the #157 email path, unchanged
osd._deps["send_whatsapp_template"] = lambda *a: None
ok, note = osd._deliver(osd.CH_WHATSAPP, osd.STEP_REBOOK, rec, "whatsapp:+14075550123", seq)
check("os.rebook_falls_to_email", ok and "sent by email" in note and calls["email"] == ["s@x.com", "s@x.com"], f"{ok} {note}")
# the template raising must not kill the step
osd._deps["send_whatsapp_template"] = lambda *a: (_ for _ in ()).throw(RuntimeError("x"))
ok, note = osd._deliver(osd.CH_WHATSAPP, osd.STEP_REBOOK, rec, "whatsapp:+14075550123", seq)
check("os.rebook_template_raises", ok and "sent by email" in note)
# no dep at all (older configure) -> unchanged
osd._deps.pop("send_whatsapp_template", None)
ok, note = osd._deliver(osd.CH_WHATSAPP, osd.STEP_REBOOK, rec, "whatsapp:+14075550123", seq)
check("os.rebook_no_dep", ok and "sent by email" in note)

# ── static wiring ────────────────────────────────────────────────────────
check("wire.import", "\nimport wa_templates as _wt" in SRC)
i_ff = SRC.index('_sent_via = "WhatsApp (free-form)"')
i_new = SRC.index("elif _wt.stage_template(stage_h) and _wa_visit_template_send(", i_ff)
i_lara = SRC.index('"mwm_lara_shoot_reminder",', i_new)
check("wire.rail_order", i_ff < i_new < i_lara and i_lara - i_new < 900)
seg = SRC[i_new:i_lara]
check("wire.rail_params", "_wt.stage_params(stage_h, _time_str, _when_long)" in seg and "_sent_via = _wt.SENT_VIA" in seg)
check("wire.beside_email_unchanged", '_sent_via == "WhatsApp (approved template)" and stage_h in (24, 2)' in SRC)
check("wire.confirm_asked_unchanged", "if _sent_via and stage_h == 24 and _pg.enabled():" in SRC)
check("wire.configure", "send_whatsapp_template=_rebook_template_send," in SRC
      and SRC.index("def _rebook_template_send(") < SRC.index("send_whatsapp_template=_rebook_template_send,"))
check("wire.health", '"wa_visit_templates": _wa_visit_templates_status(),' in SRC)
check("wire.route", '"rail": _wa_visit_templates_status()' in SRC and 'if str(request.args.get("refresh") or "") == "1":' in SRC
      and 'or [n for n, t in _wt.TEMPLATES.items() if not t.get("retired")]' in SRC)
check("wire.route_no_local_import", "    import wa_templates as _wt\n    _mode = " not in SRC)
check("wire.order", SRC.index("def _wa_visit_templates_usable(") < SRC.index("elif _wt.stage_template(stage_h)")
      and SRC.index("def send_wa_utility_template(") < SRC.index("def _wa_visit_template_send("))

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch248.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #248 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("248: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
