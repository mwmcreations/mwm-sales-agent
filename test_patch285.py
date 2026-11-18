#!/usr/bin/env python3
"""GATE for PATCH #285 — the quiet-lead rail: who is on it, the 5/10/15/20-day
cadence with a one-time escalation to Michael, the reset on new activity, the
channel choice, the copy rules, the dark switch and the admin window.
Prints GATE285 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import quiet_lead as ql  # noqa: E402
import sms_copy  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


ET = pytz.timezone("US/Eastern")
NOW = ET.localize(datetime(2026, 11, 17, 10, 0, 0))


def d(days):
    return (NOW - timedelta(days=days)).isoformat()


# ── 1. who is on the rail ────────────────────────────────────────────────────
replied = {"name": "Vicente Orellana", "email": "v@x.com", "phone": "4073614743",
           "chase": {"armed_at": d(20), "stopped": "replied", "stopped_at": d(19), "sent": {"e1": d(19)}}}
check("elig.replied", ql.eligible(replied, "Replied")[0] is True)
check("elig.replied_why", "replied" in ql.eligible(replied, "Replied")[1])
check("elig.replied_no_chase", ql.eligible({"name": "x"}, "Replied") == (True, "replied"))
check("elig.client", ql.eligible(dict(replied, paid_at=d(1)), "Replied")[0] is False)
check("elig.client_stage", ql.eligible(replied, "Client") == (False, "client"))
check("elig.lost_stage", ql.eligible(replied, "Lost")[0] is False)
check("elig.dnc", ql.eligible(dict(replied, do_not_contact=True), "Replied")[0] is False)
check("elig.not_interested", ql.eligible(dict(replied, last_outcome="not_interested"), "Replied")[0] is False)
check("elig.cold", ql.eligible(dict(replied, cold_fired=True), "Replied") == (False, "cold audience"))
check("elig.other_rail", ql.eligible(replied, "Replied", other_rail_active=True) == (False, "another rail is live"))
armed = dict(replied, chase={"armed_at": d(3), "stopped": ""})
check("elig.chase_armed", ql.eligible(armed, "Contacted") == (False, "chase still armed"))
check("elig.new", ql.eligible({"name": "n"}, "New") == (False, "never talked to us"))
check("elig.paused_is_reengagement", ql.eligible(replied, "Paused")[0] is False and "re-engagement" in ql.eligible(replied, "Paused")[1])
check("elig.booked_ahead", ql.eligible(replied, "Booked", {"passed": False}) == (False, "booked ahead"))
check("elig.booked_passed_unreported", ql.eligible(replied, "Booked", {"passed": True})[0] is False)
visited = dict(replied, last_outcome="follow_up", last_outcome_at=d(16),
               chase={"armed_at": d(16), "stopped": "closed", "kind": "post_visit", "sent": {"e3": d(2)}})
check("elig.visited_follow_up_chain_done", ql.eligible(visited, "Visited")[0] is True)
pv_running = dict(visited, chase={"armed_at": d(3), "stopped": "", "kind": "post_visit"})
check("elig.visited_chain_running", ql.eligible(pv_running, "Visited") == (False, "chase still armed"))
check("elig.visited_pitched", ql.eligible(dict(visited, last_outcome="studio_package_pitched"), "Visited")[0] is False)
manual = dict(replied, chase={"armed_at": d(9), "stopped": "manual", "stopped_at": d(8)})
check("elig.contacted_manual", ql.eligible(manual, "Contacted")[0] is True)
check("elig.contacted_chain_owns", ql.eligible(dict(replied, chase={"armed_at": d(9), "stopped": "closed"}), "Contacted")[0] is False)
check("elig.contacted_replied_verdict", ql.eligible(dict(replied, chase={"armed_at": d(9), "stopped": "replied"}), "Contacted")[0] is True)
check("elig.replied_lost_stop", ql.eligible(dict(replied, chase={"armed_at": d(9), "stopped": "disqualified"}), "Replied")[0] is False)
check("elig.unknown_stage", ql.eligible(replied, "Weird")[0] is False)

# ── 2. activity, arming, reset ──────────────────────────────────────────────
stamps = ql.activity_stamps(dict(replied, last_message_time=d(6), reoffer_at=d(7),
                                 last_outbound_sms={"at": d(8)}))
check("act.collects", d(6) in stamps and d(7) in stamps and d(8) in stamps and d(19) in stamps)
check("act.latest", ql.latest(stamps, like=NOW).isoformat() == d(6))
check("act.latest_none", ql.latest([], like=NOW) is None and ql.latest([None, "", "garbage"]) is None)
check("act.quiet_touch_not_activity", "quiet_rail" not in " ".join(str(s) for s in stamps))
check("act.hand_touch_counts", d(3) in ql.activity_stamps(dict(replied, hand_touches=[{"at": d(3), "by": "michael"}])))   # #285b
st = ql.arm(NOW, ql.latest([d(6)], like=NOW))
check("arm.shape", st["since"] == d(6) and st["touches"] == [] and st["stopped"] == "" and st["armed_at"] == NOW.isoformat())
check("days.quiet", abs(ql.days_quiet(st, NOW) - 6.0) < 1e-6)
st2 = ql.note_touch(dict(st), NOW, 1, "sms")
st2["escalated_at"] = NOW.isoformat()
ql.refresh(st2, NOW - timedelta(days=1))                 # the lead wrote yesterday
check("reset.on_new_activity", st2["touches"] == [] and st2["escalated_at"] == "" and st2["since"] == d(1) and st2["reset_at"] == d(1))
st3 = ql.note_touch(dict(ql.arm(NOW, ql.latest([d(6)], like=NOW))), NOW, 1, "sms")
ql.refresh(st3, ql.latest([d(6)], like=NOW))
check("reset.same_activity_keeps_count", len(st3["touches"]) == 1)
ql.refresh(st3, ql.latest([d(6)], like=NOW) + timedelta(seconds=30))
check("reset.minute_tolerance", len(st3["touches"]) == 1)
stopped = ql.stop(dict(st), NOW, "manual stop")
ql.refresh(stopped, NOW - timedelta(hours=1))
check("reset.clears_stop_when_lead_moves", stopped["stopped"] == "")

# ── 3. the cadence ──────────────────────────────────────────────────────────
def state(quiet_days, touches=0, escalated=False):
    s = ql.arm(NOW, NOW - timedelta(days=quiet_days))
    for i in range(touches):      # touch i went out on day 5*i of the quiet
        ql.note_touch(s, NOW - timedelta(days=quiet_days - ql.QUIET_DAYS * (i + 1)), i + 1, "sms")
    if escalated:
        s["escalated_at"] = NOW.isoformat()
    return s


check("cad.day4_nothing", ql.next_actions(state(4.9), NOW) == [])
check("cad.day5_touch1", ql.next_actions(state(5.0), NOW) == [("touch", 1)])
check("cad.day7_after_touch1_nothing", ql.next_actions(state(7, touches=1), NOW) == [])
check("cad.day10_touch2_and_escalate", ql.next_actions(state(10, touches=1), NOW) == [("touch", 2), ("escalate",)])
check("cad.day10_escalate_once", ql.next_actions(state(10, touches=2, escalated=True), NOW) == [])
check("cad.day12_escalate_still_due", ql.next_actions(state(12, touches=2), NOW) == [("escalate",)])
check("cad.day15_touch3", ql.next_actions(state(15, touches=2, escalated=True), NOW) == [("touch", 3)])
check("cad.day20_touch4", ql.next_actions(state(20, touches=3, escalated=True), NOW) == [("touch", 4)])
check("cad.after_4_closes", ql.next_actions(state(25, touches=4, escalated=True), NOW) == [("close", "quiet 20d")])
check("cad.stopped_nothing", ql.next_actions(ql.stop(state(30), NOW, "x"), NOW) == [])
check("cad.first_pass_backlog_one_touch", ql.next_actions(state(18), NOW) == [("touch", 1), ("escalate",)])
_bl = ql.note_touch(state(18), NOW, 1, "sms")
_bl["escalated_at"] = NOW.isoformat()
check("cad.backlog_second_touch_waits_5d", ql.next_actions(_bl, NOW + timedelta(minutes=5)) == []
      and ql.next_actions(_bl, NOW + timedelta(days=4)) == []
      and ql.next_actions(_bl, NOW + timedelta(days=5)) == [("touch", 2)])
check("cad.constants", (ql.QUIET_DAYS, ql.ESCALATE_DAY, ql.MAX_TOUCHES, ql.SEND_HOURS) == (5, 10, 4, (8, 18)))
check("cad.summary_due", "due now" in ql.summary(state(5.5), NOW) and "0 touch" in ql.summary(state(5.5), NOW))
check("cad.summary_not_on", ql.summary(None, NOW) == "not on the rail" and ql.summary({}, NOW) == "not on the rail")
check("cad.summary_stopped", ql.summary(ql.stop(state(5), NOW, "client"), NOW) == "stopped: client")
check("hours.window", ql.within_hours(ET.localize(datetime(2026, 11, 17, 8, 0))) and not ql.within_hours(ET.localize(datetime(2026, 11, 17, 18, 0)))
      and not ql.within_hours(ET.localize(datetime(2026, 11, 17, 7, 59))))

# ── 4. the road to the lead ─────────────────────────────────────────────────
check("ch.odd_sms_first", ql.channel_for(1, True, True) == "sms" and ql.channel_for(3, True, True) == "sms")
check("ch.even_email_first", ql.channel_for(2, True, True) == "email" and ql.channel_for(4, True, True) == "email")
check("ch.no_consent_email", ql.channel_for(1, True, False) == "email")
check("ch.no_email_sms", ql.channel_for(2, False, True) == "sms")
check("ch.no_road", ql.channel_for(1, False, False) == "")

# ── 5. the copy: Michael's rules ────────────────────────────────────────────
for n in (1, 2, 3, 4):
    s = ql.touch_sms(n, "Vicente Orellana")
    check(f"sms{n}.comma_after_name", s.startswith("Hi Vicente, "), s)
    check(f"sms{n}.no_dash_symbols", "—" not in s and "–" not in s, s)
    check(f"sms{n}.asks_still_interested", "Still interested" in s, s)
    check(f"sms{n}.compose_fits", sms_copy.segments(sms_copy.compose(s)) <= 2, sms_copy.compose(s))
    check(f"sms{n}.compose_has_brand_and_stop", sms_copy.compose(s).startswith("MWM Creations & Studios: ") and "STOP" in sms_copy.compose(s))
    subj, lines = ql.touch_email(n, "Vicente Orellana", "Owning Your House")
    body = "\n".join(lines)
    check(f"email{n}.greeting", lines[0] == "Hi Vicente," and subj)
    check(f"email{n}.no_dash_symbols", "—" not in body and "–" not in body and "—" not in subj, body)
    check(f"email{n}.signed", "Michael Moraes" in body and "MWM Creations & Studios" in body)
    check(f"email{n}.short", len(body) < 700, len(body))
check("sms.fallback_name", ql.touch_sms(1, "").startswith("Hi there, "))
check("sms.long_name_still_fits", sms_copy.segments(sms_copy.compose(ql.touch_sms(1, "Maximilian-Alexander"))) <= 2)
check("email.business_long_dropped", " for " not in ql.touch_email(1, "Ana", "A" * 60)[1][2])
check("email.business_kept", "for Owning Your House" in ql.touch_email(1, "Ana", "Owning Your House")[1][2])
esc = ql.escalation_text("Vicente Orellana", "Owning Your House", 10.6, "sms")
check("esc.text", esc.startswith("MWM: Vicente Orellana (Owning Your House) has been quiet 10 days") and "stop" in esc)

# ── 6. app.py pins ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.import", "import quiet_lead as _ql" in SRC)
check("app.switch_registered", 'SWITCHES["quiet_rail_live"] = "QUIET_RAIL_LIVE"' in SRC)
check("app.switch_literal_untouched", 'SWITCHES = {\n    "ig_chase_live": "IG_CHASE_LIVE",' in SRC
      and SRC.index('SWITCHES["quiet_rail_live"]') > SRC.index('"wa_reengage_v3": "WA_REENGAGE_V3"'))
blk = SRC[SRC.index("# PATCH #285 — THE QUIET-LEAD RAIL"):SRC.index("def _lead_chase_loop():")]
check("app.block_before_loop", "def _quiet_pass(now=None):" in blk and "def _quiet_tick():" in blk and "def _quiet_status():" in blk)
check("app.live_switch", "def _quiet_rail_live():" in blk and 'return _switch_on("quiet_rail_live")' in blk)
check("app.dark_holds", 'item["held"] = "switch off"' in blk and "if not live:" in blk)
check("app.stamp_before_send", blk.index("_ql.note_touch(st, now, n, ch)            # stamp BEFORE the send") < blk.index("res = _email_send(email, subj, _sv._as_html(lines)"))
check("app.sms_marketing_kind", "res = _send_sms(e164, body, kind=SMS_KIND_MARKETING)" in blk)
check("app.sms_gate_dry", "ok, why = _sms_gates(e164, SMS_KIND_MARKETING)" in blk and '("quiet_hours", "monthly_cap")' in blk)
check("app.window", "if not _ql.within_hours(now):" in blk)
check("app.daily_cap", 'if _QUIET_LAST["sent_today"] >= QUIET_RAIL_DAILY_CAP:' in blk and 'QUIET_RAIL_DAILY_CAP = int(os.getenv("QUIET_RAIL_DAILY_CAP", "8") or 8)' in blk)
check("app.twins_once", "losers = set(desk.twin_losers(views) or ())" in blk and "key in losers" in blk)
check("app.tests_skipped", 'v.get("test")' in blk)
check("app.other_rails", 'rec.get("outcome_seq")' in blk and 'rec.get("studio_pitch")' in blk and "_quiet_other_rail(rec)" in blk)
check("app.stages", 'QUIET_RAIL_STAGES = ("Replied", "Visited", "Contacted")' in blk)
check("app.uses_desk_facts", "desk._views(lead_data, conversation_history, ig_conversation_history" in blk
      and "desk.turns_for(key, rec, conversation_history, ig_conversation_history)" in blk)
check("app.escalate_once_batched", '_operator_alert.alert("quiet", text)' in blk and 'st["escalated_at"] = now.isoformat()' in blk
      and "names[:6]" in blk)
check("app.escalate_only_live", blk.index("if live:\n            text = (") > 0 and "_post_to_slack_async(SLACK_MATT_CHANNEL" in blk)
check("app.close_tells_susan", "quiet rail closed for" in blk and "SLACK_SUSAN_CHANNEL" in blk)
check("app.no_sms_road_remembered", 'st["no_sms"] = res.get("reason")' in blk and 'if st.get("no_sms"):' in blk)
check("app.dark_never_mutates", 'if not live:                              # #285b: a dry pass changes nothing' in blk
      and '_ql.note_touch(st, now, n, "none")' not in blk)
check("app.no_channel_lets_go", '_ql.stop(st, now, "no channel (Michael told)")' in blk)
check("app.touched_action", 'if action not in ("status", "stop", "resume", "touched"):' in blk
      and 'r.setdefault("hand_touches", []).append({"at": touched_at.isoformat(), "by": "michael",' in blk
      and "_ql.refresh(st, touched_at)" in blk)
check("app.route", '@app.route("/admin/quiet-rail", methods=["GET", "POST"])' in blk and 'def admin_quiet_rail():' in blk
      and 'if action not in ("status", "stop", "resume", "touched"):' in blk and "stopped via /admin/quiet-rail (Patch #285)" in blk)
check("app.route_masks", "_chase_mask_key(k)" in blk and "_chase_mask(str(r.get(\"email\") or \"\"))" in blk)
check("app.route_shows_copy", '"copy": {"sms": [_ql.touch_sms(n, "Ana") for n in (1, 2, 3, 4)]' in blk)
loop = SRC[SRC.index("def _lead_chase_loop():"):SRC.index('threading.Thread(target=_lead_chase_loop, daemon=True, name="lead_chase").start()')]
check("app.tick_in_loop", "counts = _chase_pass()\n            _quiet_tick()               # PATCH #285" in loop)
check("app.health", '"quiet_rail": _quiet_status(),                  # PATCH #285' in SRC)
check("app.cycle", 'QUIET_RAIL_CYCLE_S = int(os.getenv("QUIET_RAIL_CYCLE_S", "3600") or 3600)' in blk and "if age < QUIET_RAIL_CYCLE_S:" in blk)
check("app.block_once", SRC.count("def _quiet_pass(now=None):") == 1 and SRC.count("import quiet_lead as _ql") == 1)
check("app.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "app.py")], capture_output=True).returncode == 0)
OA = open(os.path.join(HERE, "operator_alert.py"), encoding="utf-8").read()
check("oa.quiet_kind", '"quiet":    {"eric": False},' in OA)
import operator_alert as oa  # noqa: E402
check("oa.quiet_kind_loaded", oa.KINDS.get("quiet") == {"eric": False} and oa.KINDS.get("decision") == {"eric": False})
T275 = open(os.path.join(HERE, "test_patch275.py"), encoding="utf-8").read()
check("t275.untouched", "#285" not in T275)

# ── 7. the lifted pass against the real desk module (test_patch285_smoke.py) ──
_sm = subprocess.run([sys.executable, os.path.join(HERE, "test_patch285_smoke.py"), HERE], capture_output=True, text=True)
_mm = re.search(r"smoke: (\d+) passed, (\d+) failed", _sm.stdout)
if not _mm:
    failed += 1
    print("  FAIL smoke harness did not report", _sm.stdout[-800:], _sm.stderr[-800:])
else:
    passed += int(_mm.group(1)); failed += int(_mm.group(2))
    if int(_mm.group(2)):
        print(_sm.stdout[-2000:])

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 285) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
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
print("GATE285 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
