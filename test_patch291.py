#!/usr/bin/env python3
"""GATE for PATCH #291 — personal titles never reach the Desk through a lead-name
match, and an old booking is not 'Booked'. Prints GATE291 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("TIMEZONE", "US/Eastern")
import desk  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


NOW = datetime(2026, 11, 20, 23, 0)


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


# ── 1. the calendar ─────────────────────────────────────────────────────────
LEADS = {
    "whatsapp:+13218886544": {"name": "Michael Santos", "business": "Orlando City Roofing"},
    "whatsapp:+14075550101": {"name": "Julie Carter", "business": "Carter Dental"},
    "whatsapp:+14075550102": {"name": "Ayodele Pompey", "business": "Pompey Fitness"},
}
SOCCER = "⚽ QUA/SEX — Michael Jr. · Futebol Orlando City Soccer School (17h–18h)"
MEET = [{"summary": SOCCER}, {"summary": "Studio visit — Julie Carter (Carter Dental)"},
        {"summary": "Ayodele Pompey"}, {"summary": "Julie Carter birthday"},
        {"summary": "MWM strategy call"}, {"summary": "Groceries"}]
check("pre.soccer_matches_a_lead", desk.event_matches_lead(SOCCER, desk._lead_names(LEADS)) == "whatsapp:+13218886544")
kept, hidden = desk.calendar_filter(MEET, LEADS)
titles = [m["summary"] for m in kept]
check("cal.soccer_hidden", SOCCER not in titles, titles)
check("cal.studio_visit_with_personal_name_shown", "Studio visit — Julie Carter (Carter Dental)" in titles, titles)
check("cal.lead_name_alone_shown", "Ayodele Pompey" in titles, titles)
check("cal.lead_birthday_hidden", "Julie Carter birthday" not in titles, titles)
check("cal.studio_word_shown", "MWM strategy call" in titles, titles)
check("cal.other_hidden", "Groceries" not in titles and hidden == 3, (titles, hidden))
allm, h2 = desk.calendar_filter(MEET, LEADS, show_all=True)
soc = [m for m in allm if m["summary"] == SOCCER][0]
check("cal.show_all_marks_personal_no_lead", h2 == 0 and soc["personal"] is True and soc["lead_key"] == "", soc)
jul = [m for m in allm if m["summary"].startswith("Studio visit")][0]
check("cal.kept_lead_key", jul["personal"] is False and jul["lead_key"] == "whatsapp:+14075550101", jul)

# ── 2. the Booked column ────────────────────────────────────────────────────
def st(rec):
    return desk.stage_of(rec, None, now=NOW)


future = (NOW + timedelta(days=3)).replace(hour=14, minute=0).isoformat()
check("bk.ahead", st({"event_id": "e1", "booked_slot_id": future, "booked_at": ago(1)}) == "Booked")
check("bk.yesterday_no_outcome", st({"event_id": "e2", "booked_slot_id": ago(1), "booked_at": ago(5)}) == "Booked")
check("bk.28_days_behind", st({"event_id": "e3", "booked_slot_id": ago(28), "booked_at": ago(30)}) == "Booked")
check("bk.45_days_behind_is_history", st({"event_id": "e4", "booked_slot_id": ago(45), "booked_at": ago(47)}) == "Paused",
      st({"event_id": "e4", "booked_slot_id": ago(45), "booked_at": ago(47)}))
check("bk.no_slot_fresh", st({"event_id": "e5", "booked_at": ago(3)}) == "Booked")
check("bk.no_slot_40_days", st({"event_id": "e6", "booked_at": ago(40)}) == "Booked")          # 14 + 30 not yet over
check("bk.no_slot_50_days_is_history", st({"event_id": "e7", "booked_at": ago(50)}) == "Paused")
check("bk.undated_quiet_is_history", st({"event_id": "e8", "last_message_time": ago(120)}) == "Paused",
      st({"event_id": "e8", "last_message_time": ago(120)}))
check("bk.undated_recent_talk_stays", st({"event_id": "e8b", "last_message_time": ago(5)}) == "Booked")
check("bk.undated_no_date_at_all_stays", st({"event_id": "e9"}) == "Booked")
check("bk.outcome_still_visited", st({"event_id": "e10", "booked_at": ago(90), "last_outcome": "follow_up", "last_outcome_at": ago(88)}) == "Visited")
check("bk.history_then_recent_talk", st({"event_id": "e11", "booked_at": ago(90), "last_inbound_at": ago(2), "last_message_time": ago(2)}) != "Booked")
check("bk.helper_false_when_ahead", not desk.booking_is_history({"event_id": "e1", "booked_slot_id": future}, None, NOW))

# ── 3. pins ─────────────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "desk.py"), encoding="utf-8").read()
check("pin.keep_days", "BOOKED_KEEP_DAYS = 30" in SRC)
check("pin.rule", 'if rec.get("event_id") and not booking_is_history(rec, turns, now):' in SRC)
check("pin.personal", 'm["lead_key"] = "" if m["personal"] else lk' in SRC)
check("pin.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "desk.py")], capture_output=True).returncode == 0)

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 291) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
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
print("GATE291 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
