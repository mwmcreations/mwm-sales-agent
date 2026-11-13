#!/usr/bin/env python3
"""GATE for PATCH #281 — one follow-up rail per pitched lead; the outcome rail
closes its own pitched duplicates, sends 7–18 ET, and has a stop switch.
Prints GATE281 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("TIMEZONE", "US/Eastern")
import event_rail as er  # noqa: E402
import outcome_sender as osn  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


# ── 1. the plan ──────────────────────────────────────────────────────────────
p = er.outcome_plan("studio_package_pitched", er.CH_WEB, has_email=True)
check("plan.pitched_email_no_steps", p["steps"] == [], p)
check("plan.pitched_email_why", "Studio Package" in p["why"] and "one sequence" in p["why"], p["why"])
check("plan.pitched_email_owner", p["owner"] == "SUSAN" and p["close_after_days"] == 10)
check("plan.pitched_email_not_internal", not p["internal_only"] and not p["suppress"])
check("plan.pitched_email_owned_by", p.get("owned_by") == "studio_package", p)
check("plan.others_not_owned", not er.outcome_plan("follow_up", er.CH_WEB, True).get("owned_by"))
TER = open(os.path.join(HERE, "test_event_rail.py"), encoding="utf-8").read()
check("ter.pins_updated", "#281" in TER and "[(1, STEP_RECAP), (48, STEP_VALUE), (144, STEP_NUDGE)]" not in TER)
p2 = er.outcome_plan("studio_package_pitched", er.CH_WHATSAPP, has_email=False)
check("plan.pitched_no_email_asks", p2["steps"] == [(1, er.CH_WHATSAPP, er.STEP_EMAIL_ASK)], p2)
p3 = er.outcome_plan("follow_up", er.CH_WEB, has_email=True)
check("plan.follow_up_untouched", [k for _, _, k in p3["steps"]] == [er.STEP_NUDGE, er.STEP_VALUE], p3)
p4 = er.outcome_plan("no_show", er.CH_WEB, has_email=True)
check("plan.no_show_untouched", [k for _, _, k in p4["steps"]] == [er.STEP_REBOOK, er.STEP_REBOOK], p4)
check("plan.lead_chase_window_default", er.SEND_WINDOW_START_HOUR == 8 and er.SEND_WINDOW_END_HOUR == 20)
check("sender.window_7_18", osn.OUTCOME_SEND_HOURS == (7, 18))

# ── 2. the sender ────────────────────────────────────────────────────────────
sent, slack = [], []
LD = {}
osn._deps.update({
    "lead_data": LD,
    "send_email": lambda to, subject, html: (sent.append((to, subject)) or {"ok": True}),
    "send_whatsapp": lambda phone, text: True,
    "send_instagram": lambda igsid, text: True,
    "post_slack": lambda ch, msg: slack.append((ch, msg)),
    "matt_channel": "#matt", "maya_channel": "#maya", "dev_channel": "#dev",
    "pg_save": lambda k, v: None,
    "report_error": lambda *a, **k: None,
})
NOW = datetime(2026, 11, 13, 10, 6)          # Fri 10:06 local, in window
loc = lambda **k: (NOW - timedelta(**k)).isoformat()  # noqa: E731


def pitched_seq(armed, next_step):
    return {"outcome": "studio_package_pitched", "armed_at": armed, "channel": "Website Chat",
            "email": None, "steps": [[1, er.CH_WEB, er.STEP_RECAP], [48, er.CH_WEB, er.STEP_VALUE],
                                     [144, er.CH_WEB, er.STEP_NUDGE]],
            "next_step": next_step, "close_after_days": 10, "owner": "SUSAN",
            "agreed_next": "", "done": False,
            "sent": [{"step": "recap", "channel": "Website Chat", "at": loc(hours=2)}] if next_step else []}


# Ayodele, as production has him: recap already sent, value due tomorrow night
LD["whatsapp:+10000000001"] = {"name": "Ayodele Pompey", "email": "ayo@x.com", "business": "SmartTerm Ltd",
                               "booked": True, "outcome_seq": pitched_seq(loc(hours=11), 1)}
# pitched 3 days ago, value already due -> must NOT send, must close
LD["whatsapp:+10000000002"] = {"name": "Due Value", "email": "due@x.com",
                               "outcome_seq": pitched_seq(loc(hours=60), 1)}
# pitched, no email on file: the email-ask variant is NOT a duplicate; left alone (waiting)
LD["whatsapp:+10000000003"] = {"name": "No Email", "phone": "10000000003",
                               "outcome_seq": {"outcome": "studio_package_pitched", "armed_at": loc(minutes=20),
                                               "channel": "WhatsApp", "email": "",
                                               "steps": [[1, er.CH_WHATSAPP, er.STEP_EMAIL_ASK]],
                                               "next_step": 0, "close_after_days": 10, "owner": "SUSAN", "done": False}}
# follow_up lead whose nudge is due -> still sends (the rail itself still works)
LD["whatsapp:+10000000004"] = {"name": "Follow Up", "email": "fu@x.com",
                               "outcome_seq": {"outcome": "follow_up", "armed_at": loc(hours=49),
                                               "channel": "Website Chat", "email": "fu@x.com",
                                               "steps": [[48, er.CH_WEB, er.STEP_NUDGE], [168, er.CH_WEB, er.STEP_VALUE]],
                                               "next_step": 0, "close_after_days": 14, "owner": "MAYA",
                                               "agreed_next": "", "done": False}}
# already done pitched seq -> untouched, no second report
LD["whatsapp:+10000000005"] = {"name": "Already Done", "email": "d@x.com",
                               "outcome_seq": dict(pitched_seq(loc(days=12), 3), done=True, closed_reason="all steps sent")}

out = osn._pass(NOW)
a = LD["whatsapp:+10000000001"]["outcome_seq"]
check("seq.ayodele_closed", a["done"] is True and a["closed_reason"].startswith("owned by the Studio Package rail"), a)
check("seq.ayodele_next_untouched", a["next_step"] == 1 and len(a["sent"]) == 1, a)
b = LD["whatsapp:+10000000002"]["outcome_seq"]
check("seq.due_value_closed_not_sent", b["done"] is True and all(t != "due@x.com" for t, _ in sent), (b, sent))
check("seq.no_email_variant_left_alone", LD["whatsapp:+10000000003"]["outcome_seq"]["done"] is False)
check("seq.follow_up_still_sends", [t for t, _ in sent] == ["fu@x.com"], sent)
check("seq.follow_up_subject", sent and sent[0][1].endswith("checking in"), sent)
check("seq.stopped_count", out["stopped"] == 2 and out["sent"] == 1, out)
dev = [m for ch, m in slack if ch == "#dev"]
check("seq.dev_told_twice", len(dev) == 2 and any("Ayodele Pompey" in m for m in dev), slack)
check("seq.dev_names_steps", any("value, nudge" in m for m in dev), dev)
check("seq.done_untouched", LD["whatsapp:+10000000005"]["outcome_seq"]["closed_reason"] == "all steps sent")

# second pass: nothing new happens (closed once, reported once)
slack.clear(); sent.clear()
out2 = osn._pass(NOW + timedelta(minutes=20))
check("seq.second_pass_quiet", out2["stopped"] == 0 and out2["sent"] == 0 and not slack and not sent, (out2, slack))

# ── 3. the window: 7–18 ET on this rail, every day ───────────────────────────
def fresh_follow_up(name, hours_ago, now):
    LD.clear()
    LD["whatsapp:+1999"] = {"name": name, "email": "w@x.com",
                            "outcome_seq": {"outcome": "follow_up", "armed_at": (now - timedelta(hours=hours_ago)).isoformat(),
                                            "channel": "Website Chat", "email": "w@x.com",
                                            "steps": [[48, er.CH_WEB, er.STEP_NUDGE]], "next_step": 0,
                                            "close_after_days": 14, "owner": "MAYA", "agreed_next": "", "done": False}}


for label, when, expect in (
        ("0630_holds", datetime(2026, 11, 13, 6, 30), 0),
        ("0700_sends", datetime(2026, 11, 13, 7, 0), 1),
        ("1759_sends", datetime(2026, 11, 13, 17, 59), 1),
        ("1800_holds", datetime(2026, 11, 13, 18, 0), 0),
        ("1900_holds_was_sendable", datetime(2026, 11, 13, 19, 0), 0),
        ("sat_1100_sends", datetime(2026, 11, 14, 11, 0), 1),
        ("sun_0800_sends", datetime(2026, 11, 15, 8, 0), 1),
        ("0006_holds", datetime(2026, 11, 13, 0, 6), 0)):
    fresh_follow_up(label, 49, when)
    sent.clear()
    o = osn._pass(when)
    check(f"window.{label}", o["sent"] == expect and (o["held_quiet_hours"] == (1 - expect)), (label, o))

# ── 4. app.py pins ───────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
i = SRC.index("def admin_lead_seq():")
seg = SRC[SRC.rfind("@app.route", 0, i):i + 7000]
check("app.route_post", "@app.route('/admin/lead-seq', methods=['GET', 'POST'])" in seg)
check("app.route_values", '_admin_secret_ok(request.values.get("secret"))' in seg and '(request.values.get("q") or "")' in seg)
check("app.route_action", 'if _action not in ("status", "stop"):' in seg)
check("app.route_stop_cap", 'if _action == "stop":' in seg and "len(_hits) > 3" in seg)
check("app.route_stop_persists", 'lead_data[_k] = _nr' in seg and '"stopped via /admin/lead-seq (Patch #281)"' in seg)
check("app.route_stop_tells_dev", "via /admin/lead-seq (Patch #281)" in seg and "_post_to_slack_async(SLACK_DEV_CHANNEL" in seg)
check("app.route_stop_skips_done", 'if not isinstance(_seq, dict) or _seq.get("done"):' in seg)
check("app.route_window_7_18", "*_outcome_seq.OUTCOME_SEND_HOURS" in seg and "held until 07:00" in seg)
check("app.route_old_window_gone", "held until 08:00" not in seg)
check("app.arm_guard_intact", 'if _p39_rec and _plan.get("steps") and plan_is_deliverable(_plan):' in SRC)
check("app.studio_rail_still_armed", "_studio.start_pitch_sequence(_p39_key, _p39_rec, service=service)   # PATCH #280" in SRC)
ER = open(os.path.join(HERE, "event_rail.py"), encoding="utf-8").read()
check("er.no_pitched_email_rail", "(24 * 6, CH_WEB, STEP_NUDGE)" not in ER)
check("er.lead_chase_window_untouched", "SEND_WINDOW_START_HOUR = 8\nSEND_WINDOW_END_HOUR = 20" in ER)
OS = open(os.path.join(HERE, "outcome_sender.py"), encoding="utf-8").read()
check("os.guard_before_stop_reason", OS.index("if _pitched_double_rail(seq):") < OS.index("stop = (seq_stop_reason(rec, seq)"))
check("os.window_call", "within_send_window(now, OUTCOME_SEND_HOURS[0], OUTCOME_SEND_HOURS[1])" in OS)

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 281) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE281 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
