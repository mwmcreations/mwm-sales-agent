#!/usr/bin/env python3
"""GATE for PATCH #274 — Instagram leads get a second word (DARK behind IG_CHASE_LIVE).
Pure checks (lead_chase, studio_visit), the arm helper lifted into a harness, source
pins, then the #273 gate. Prints GATE274 PASS/FAIL."""
import ast
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lead_chase as lc   # noqa: E402
import studio_visit as sv  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


TZ = pytz.timezone("America/New_York")
T0 = TZ.localize(datetime(2026, 11, 9, 10, 0))

# ── 1. the kind ──────────────────────────────────────────────────────────────
check("kind.const", lc.KIND_IG == "ig")
st = lc.arm(T0, channels=[lc.EMAIL], verdict="ig", kind=lc.KIND_IG)
check("kind.walks_form_table", lc.steps_for(st) is lc.STEPS)
check("kind.email_steps_only", [s[0] for s in lc.remaining(st)] == ["e1", "e2", "e3", "e4", "e5"])
check("kind.e1_day1", lc.next_step(st, T0 + timedelta(hours=24, minutes=1)) == ("e1", "email", 1))
check("kind.reply_stops", lc.stop_reason(st, {}, T0 + timedelta(hours=5), last_inbound=T0 + timedelta(hours=5)) == lc.STOP_REPLIED)
check("kind.booked_stops", lc.stop_reason(st, {"booked": True}, T0 + timedelta(hours=5)) == lc.STOP_BOOKED)

# ── 2. the copy ──────────────────────────────────────────────────────────────
for step in (1, 2, 3, 4, 5):
    s_ig, h_ig, t_ig = sv.ig_chase_email(step, "Carla", "Mendes Fit", "")
    s_sh, h_sh, t_sh = sv.sh_chase_email(step, "Carla", "Mendes Fit", "")
    check(f"copy.{step}.subject_same", s_ig == s_sh, (s_ig, s_sh))
    check(f"copy.{step}.no_applied", "applied" not in t_ig and "applied" not in h_ig, t_ig[:200])
    check(f"copy.{step}.no_price", "$" not in t_ig and "1,200" not in t_ig)
    if step in (1, 4):
        check(f"copy.{step}.ig_opening", "messaged us on Instagram" in t_ig and "messaged us on Instagram" in h_ig, t_ig[:300])
        check(f"copy.{step}.changed", t_ig != t_sh)
    else:
        check(f"copy.{step}.unchanged", t_ig == t_sh and h_ig == h_sh)
s1, _, t1 = sv.ig_chase_email(1, "Carla")
check("copy.1.sentence", "You messaged us on Instagram about the studio, so let me tell you exactly what a free 30-minute Studio Strategy Visit looks like." in t1, t1[:300])
check("copy.1.michael_first_person", t1.startswith("Hi Carla,") and "Michael Moraes here." in t1 and t1.rstrip().endswith("MWM Creations & Studios - Orlando"))
_, _, t4 = sv.ig_chase_email(4, "Carla")
check("copy.4.sentence", "Two weeks ago you messaged us on Instagram about the studio. The offer has not changed" in t4, t4[:300])
check("copy.openings_table", len(sv.IG_OPENINGS) == 2 and all(o[0] != o[1] for o in sv.IG_OPENINGS))
_, _, t3 = sv.ig_chase_email(3, "Karl", "K.T.M. TOYS & GrApHiCs", "")
check("copy.3.industry_rule_holds", sv.ig_chase_email(3, "Karl", "K.T.M. TOYS & GrApHiCs", "")[0] == "The three videos every business needs before the customer buys")

# ── 3. app.py: the switch, the arm helper (lifted), the pins ────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
want = {"_ig_chase_live", "_ig_arm_email_chase", "_chase_mask", "_switch_on"}   # #275: the switch helper
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
consts = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("IG_T1_HOURS", "SWITCHES") for t in n.targets)]
check("lift.found", len(fns) == 4 and len(consts) == 2, (len(fns), len(consts)))
slack, tally = [], []


class Tally:
    def bump(self, *a): tally.append(a)


LD = {}
G = dict(os=os, lead_data=LD, _chase=lc, _TALLY=Tally(), SLACK_DEV_CHANNEL="#dev",
         _pgs=type("PG", (), {"load_state": lambda self, k, d=None: d, "save_state": lambda self, k, v: True})(),   # #275
         _post_to_slack_async=lambda ch, msg: slack.append((ch, msg)),
         emails_in_field=lambda v: [x.strip().lower() for x in str(v or "").replace("/", ",").split(",") if "@" in x],
         email_is_suppressed=lambda e: ("nope" in e, ""),
         _chase_is_client=lambda k: k.endswith("client"))
exec(compile(ast.Module(body=consts + fns, type_ignores=[]), "app_274", "exec"), G)
os.environ.pop("IG_CHASE_LIVE", None)
check("switch.dark_by_default", G["_ig_chase_live"]() is False)
os.environ["IG_CHASE_LIVE"] = "1"
check("switch.on", G["_ig_chase_live"]() is True)
os.environ["IG_CHASE_LIVE"] = "off"
check("switch.off_word", G["_ig_chase_live"]() is False)
os.environ.pop("IG_CHASE_LIVE", None)
check("switch.t1_hours", G["IG_T1_HOURS"] == 20)
arm = G["_ig_arm_email_chase"]
check("arm.no_record", arm("instagram:1", "X", T0) == "no record")
LD["instagram:1"] = {"name": "Carla Mendes", "source": "Instagram", "last_message_time": T0 - timedelta(hours=25)}
check("arm.no_email", arm("instagram:1", "Carla", T0) == "no email" and "chase" not in LD["instagram:1"])
LD["instagram:1"]["email"] = "nope@x.com"
check("arm.suppressed", arm("instagram:1", "Carla", T0) == "suppressed")
LD["instagram:1"]["email"] = "carla@x.com"
LD["instagram:1"]["event_id"] = "evt"
check("arm.booked", arm("instagram:1", "Carla", T0) == "booked, blocked or client")
LD["instagram:1"].pop("event_id")
LD["instagram:1client"] = dict(LD["instagram:1"])
check("arm.client", arm("instagram:1client", "Carla", T0) == "booked, blocked or client")
r = arm("instagram:1", "Carla", T0)
ch = LD["instagram:1"].get("chase")
check("arm.armed", r == "armed" and ch and ch["kind"] == "ig" and ch["channels"] == ["email"] and ch["verdict"] == "ig" and ch["armed_at"] == T0.isoformat(), (r, ch))
check("arm.told_dev", slack and "IG lead" in slack[-1][1] and "ca…@x.com" in slack[-1][1] and "next e1 (email)" in slack[-1][1], slack)
check("arm.tally", ("ig_chase.armed", "gram:1") in tally)
check("arm.not_twice", arm("instagram:1", "Carla", T0 + timedelta(hours=1)) == "already armed")
LD["instagram:2"] = {"name": "Dnc", "email": "d@x.com", "do_not_contact": True}
check("arm.dnc_blocked", arm("instagram:2", "Dnc", T0) == "booked, blocked or client")
LD["instagram:3"] = {"name": "Two", "email": "First@X.com / second@y.com"}
check("arm.first_email", arm("instagram:3", "Two", T0) == "armed")

# source pins
check("app.enqueue_hour", '_enq_h = IG_T1_HOURS if (str(phone).startswith("instagram:") and _ig_chase_live()) else 24' in SRC
      and 'if hours_silent >= _enq_h and not data.get("reengagement_enqueued"):' in SRC)
check("app.enqueue_old_gone", 'if hours_silent >= 24 and not data.get("reengagement_enqueued"):' not in SRC)
check("app.t1_due", '_due_h = IG_T1_HOURS if (_is_ig and s == "T1" and _ig_chase_live()) else REENGAGEMENT_CADENCE[s]' in SRC
      and "if hours_since >= _due_h:" in SRC)
i_ig = SRC.index('_is_ig = phone.startswith("instagram:")')
check("app.is_ig_before_stages", i_ig < SRC.index("# Find next unsent stage"))
i_closed = SRC.index('if _ig_chase_live():   # PATCH #274 — when Instagram closes, email opens')
check("app.window_closed_arms", i_closed > SRC.index('marked Cold")') and "_ig_arm_email_chase(phone, name, now)" in SRC[i_closed:i_closed + 400]
      and SRC[i_closed:i_closed + 500].count("continue") == 1)
check("app.chase_loop_copy", 'elif state.get("kind") == _chase.KIND_IG:   # PATCH #274' in SRC and "_sv.ig_chase_email(copy_step, rec.get(\"name\")," in SRC)
check("app.health", '"ig_chase": {"live": _ig_chase_live(), "t1_hours": IG_T1_HOURS},' in SRC)
check("app.dark_everywhere", SRC.count("_ig_chase_live()") >= 4)
check("app.studio_hour_switch_intact", "def _studio_hour_track_live():" in SRC)
# old T1-T7 copy untouched this patch (the rewrite waits for Michael's OK)
check("app.copy_tables", 'IG_REENGAGEMENT_MESSAGES = {' in SRC and 'SMS_REENGAGEMENT_MESSAGES = {' in SRC)   # #275 rewrote the copy

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch273.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #273 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("273: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE274 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
