#!/usr/bin/env python3
"""GATE for PATCH #292 — Maya offers both ways (video call first, studio visit
beside it), in Michael's approved words, behind the both_ways switch.
Prints GATE292 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("TIMEZONE", "US/Eastern")
import first_touch as ft  # noqa: E402
import lead_reply as lrp  # noqa: E402
import slots as sl  # noqa: E402
import sms_copy  # noqa: E402
import studio_visit as sv  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:400]}")


tz = pytz.timezone("US/Eastern")
CALL = {"id": "2026-11-24T10:00:00-05:00", "display": "Tuesday, November 24 at 10:00 AM EST", "kind": "video_call"}
VISIT = {"id": "2026-11-30T14:00:00-05:00", "display": "Monday, November 30 at 02:00 PM EST", "kind": "studio_visit"}
PAIR = [CALL, VISIT]
OLD = [{"id": "2026-11-30T10:00:00-05:00", "display": "Monday, November 30 at 10:00 AM EST"},
       {"id": "2026-12-01T15:00:00-05:00", "display": "Tuesday, December 01 at 03:00 PM EST"}]

# ── 1. slots ────────────────────────────────────────────────────────────────
vt = sl.video_call_times()
check("slots.call_times", vt[0] == (9, 0) and vt[-1] == (16, 30) and len(vt) == 16 and (12, 30) in vt, vt)
check("slots.extra_no_4pm", (16, 0) not in sl.EXTRA_SLOT_TIMES and (16, 0) not in sl.all_slot_times(True)
      and (15, 0) in sl.all_slot_times(True) and (9, 0) in sl.all_slot_times(True), sl.all_slot_times(True))
sun = tz.localize(datetime(2026, 11, 22, 23, 30))
s1, fb = sl.video_call_slots(sun, [], tz)
check("slots.next_business_morning", len(s1) == 1 and s1[0]["id"] == "2026-11-23T09:00:00-05:00"
      and s1[0]["kind"] == "video_call" and fb is False, (s1, fb))
busy = [{"start": "2026-11-23T09:00:00-05:00", "end": "2026-11-23T09:30:00-05:00"}]
s2, _ = sl.video_call_slots(sun, busy, tz)
check("slots.busy_skips_with_buffer", s2[0]["id"] == "2026-11-23T10:00:00-05:00", s2)
mon_1040 = tz.localize(datetime(2026, 11, 23, 10, 40))
s3, _ = sl.video_call_slots(mon_1040, [], tz)
check("slots.two_hours_notice", s3[0]["id"] == "2026-11-23T13:00:00-05:00", s3)
fri_1600 = tz.localize(datetime(2026, 11, 27, 16, 0))
s4, fb4 = sl.video_call_slots(fri_1600, [], tz)
check("slots.weekend_skipped_fallback", s4[0]["id"] == "2026-11-30T09:00:00-05:00" and fb4 is True, (s4, fb4))
s5, _ = sl.video_call_slots(sun, [], tz, max_slots=2)
check("slots.one_per_day", [x["id"][:10] for x in s5] == ["2026-11-23", "2026-11-24"], s5)
allweek = [{"start": "2026-11-23T00:00:00-05:00", "end": "2026-12-20T00:00:00-05:00"}]
check("slots.nothing_when_all_busy", sl.video_call_slots(sun, allweek, tz) == ([], False))
c10 = tz.localize(datetime(2026, 11, 23, 10, 0))
b1030 = [{"start": "2026-11-23T10:30:00-05:00", "end": "2026-11-23T11:30:00-05:00"}]
check("slots.is_busy_minutes", sl.is_busy(c10, b1030, tz) is True and sl.is_busy(c10, b1030, tz, minutes=15) is False)
check("slots.closure", sl.is_closure_event({"summary": "⛔ STUDIO CLOSED — panel construction"}) and
      not sl.is_closure_event({"summary": "Studio Visit — Ana"}) and not sl.is_closure_event({}))

# ── 2. the approved texts ───────────────────────────────────────────────────
T1 = ("Hi William, Maya from Michael Moraes' team. Two ways to meet Michael (20+ yrs in projects with "
      "Disney, Universal): 1) 15-min video call Tue Nov 24, 10am or 2) free 30-min Studio Visit "
      "Mon Nov 30, 2pm. Reply 1 or 2.")
check("copy.first_sms", sv.form_first_touch_sms("William McBride", "Law", False, PAIR) == T1,
      sv.form_first_touch_sms("William McBride", "Law", False, PAIR))
T2 = ("Hi William, Maya from Michael Moraes' team. One studio shoot and we put your business in any scene. "
      "Meet Michael: 1) 15-min video call Tue Nov 24, 10am or 2) free 30-min Studio Visit Mon Nov 30, 2pm. "
      "Reply 1 or 2.")
check("copy.first_sms_ai", sv.form_first_touch_sms("William McBride", "Law", True, PAIR) == T2,
      sv.form_first_touch_sms("William McBride", "Law", True, PAIR))
T3 = ("Hi Jeff, Maya from Michael Moraes' team. One session can do a lot for a business your size. "
      "Meet Michael: 1) 15-min video call Tue Nov 24, 10am or 2) free 30-min Studio Visit Mon Nov 30, 2pm. "
      "Reply 1 or 2.")
check("copy.sh_first_sms", sv.sh_first_touch_sms("Jeff Bigby", "Producing Kings", False, PAIR) == T3,
      sv.sh_first_touch_sms("Jeff Bigby", "Producing Kings", False, PAIR))
T6a = ("Hi William, Maya from Michael Moraes' team. Still holding time for you with Michael: "
       "1) 15-min video call Tue Nov 24, 10am or 2) free 30-min Studio Visit Mon Nov 30, 2pm. Reply 1 or 2.")
T6b = ("Hi William, Michael has two openings for you: 1) 15-min video call Tue Nov 24, 10am or "
       "2) 30-min Studio Visit Mon Nov 30, 2pm. Reply 1, 2 or 'later'.")
check("copy.chase_1", sv.chase_sms(1, "William", PAIR) == T6a, sv.chase_sms(1, "William", PAIR))
check("copy.chase_2", sv.chase_sms(2, "William", PAIR) == T6b, sv.chase_sms(2, "William", PAIR))
check("copy.sh_chase", sv.sh_chase_sms(1, "William", PAIR) == T6a and sv.sh_chase_sms(2, "William", PAIR) == T6b)
for nm, core in (("t1", T1), ("t2", T2), ("t3", T3), ("t6a", T6a), ("t6b", T6b)):
    try:
        full = sms_copy.compose(core)
        ok = sms_copy.segments(full) <= sms_copy.MAX_SEGMENTS
    except Exception as e:
        ok, full = False, repr(e)
    check(f"copy.fits_two_segments.{nm}", ok, full)
check("copy.no_dashes", all("—" not in t and "–" not in t and " - " not in t for t in (T1, T2, T3, T6a, T6b)))
only_call = sv.form_first_touch_sms("William", "Law", False, [CALL])
check("copy.call_alone", "a 15-min video call Tue Nov 24, 10am. Reply YES to book it." in only_call
      and "Two ways" not in only_call, only_call)
# no call in the offer: every text is what it was before
check("copy.old_first_sms", "has Mon Nov 30, 10am or Tue Dec 1, 3pm. Which works?" in sv.form_first_touch_sms("Ana", "Bakery", False, OLD)
      and "video call" not in sv.form_first_touch_sms("Ana", "Bakery", False, OLD))
check("copy.old_chase", "Still happy to book" in sv.chase_sms(1, "Ana", OLD) and "video" not in sv.chase_sms(2, "Ana", OLD))
check("copy.old_no_slots", "Which day this week works" in sv.sh_first_touch_sms("Ana", "Bakery", False, None))

# the email
subj, html, text = sv.form_first_touch_email("William McBride", "William McBride Law Group", "", False, PAIR)
E5 = ("Michael can meet you two ways. A 15-minute video call on Tue Nov 24, 10am, or a visit to the studio on "
      "Mon Nov 30, 2pm, where you walk the sets and leave with a 90-day plan. Reply with 1 or 2, or a better "
      "time, and I will book it.")
check("email.line", E5 in text, text[-700:])
check("email.box", "Two ways to meet Michael" in html and "15-minute video call: Tue Nov 24, 10am" in html
      and "Studio visit: Mon Nov 30, 2pm" in html and "Michael has these times open" not in html)
_, html_o, text_o = sv.form_first_touch_email("Ana", "Bakery", "", False, OLD)
check("email.old_unchanged", "Michael has Mon Nov 30, 10am or Tue Dec 1, 3pm. Which works?" in text_o
      and "Michael has these times open" in html_o and "video call" not in text_o)
_, html_s, text_s = sv.sh_first_touch_email("Jeff Bigby", "Producing Kings", "", False, PAIR)
check("email.sh", "Michael can meet you two ways." in text_s and "Two ways to meet Michael" in html_s)

# ── 3. WhatsApp template parameter ──────────────────────────────────────────
tt = ft.times_text(PAIR)
check("wa.labels", tt.startswith("1) 15-min video call ") and " 2) studio visit " in tt, tt)
check("wa.old", "video" not in ft.times_text(OLD) and ft.times_text(OLD).startswith("1) "), ft.times_text(OLD))
check("wa.params", len(ft.wa_params("William McBride", "Law Group", PAIR)) == 3)

# ── 4. re-offer + confirmation ──────────────────────────────────────────────
rt = lrp.reoffer_text("William McBride", PAIR, video=True)
check("reoffer.text", rt.startswith("Hi William, it's Maya from Michael Moraes' team at MWM Creations. Michael opened new times for you: "
                                    "1) 15-min video call ") and " 2) studio visit " in rt
      and rt.endswith("Reply 1 or 2, or send a time that suits you.") and len(rt) <= 306, rt)
check("reoffer.old", "for your studio visit: 1)" in lrp.reoffer_text("Ana", OLD) and "video" not in lrp.reoffer_text("Ana", OLD))
_, rhtml, rtxt = lrp.reoffer_email("William", PAIR)
check("reoffer.email_labels", "15-minute video call: " in rtxt and "Studio visit: " in rtxt and "15-minute video call: " in rhtml)
m = lrp.match_offer("1 works for me", PAIR, tz.localize(datetime(2026, 11, 23, 9, 0)), tz)
check("reply.one_is_the_call", (m.get("slot") or {}).get("kind") == "video_call", m)
m2 = lrp.match_offer("2", PAIR, tz.localize(datetime(2026, 11, 23, 9, 0)), tz)
check("reply.two_is_the_visit", (m2.get("slot") or {}).get("kind") == "studio_visit", m2)
cs, ch, ct = lrp.confirmation_email("William", "Tue Nov 24, 10:00 AM", "", video=True)
check("confirm.video", cs.startswith("Confirmed: your Video Call") and "Google Meet" in ct and "at MWM Studios" not in ct and "Google Meet" in ch)
cs2, _, ct2 = lrp.confirmation_email("Ana", "Mon Nov 30, 2:00 PM", "1500 Park Center Dr")
check("confirm.visit_unchanged", cs2.startswith("Confirmed: your Studio Visit") and "at MWM Studios" in ct2)

# ── 5. app.py pins ──────────────────────────────────────────────────────────
APP = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.switch_default_off", '"both_ways": os.getenv("MAYA_BOTH_WAYS", "off")' in APP)
check("app.route_key", 'for k in ("video_call", "extended_hours", "both_ways"):' in APP)
check("app.pair_fn", "def _pair_from(visits):" in APP and "def get_video_call_slots(max_slots=1):" in APP)
check("app.sites_use_pair", APP.count('(globals().get("_pair_from") or (lambda v: v))(') == 3
      and "    slots = _pair_from(slots)   # PATCH #292" in APP)
check("app.kinds_remembered", APP.count('**({"kind": str(s["kind"])} if s.get("kind") else {})') == 4)
check("app.closure_skip", "if skip_closure and _slots.is_closure_event(event):" in APP
      and "and not (_video and _slots.is_closure_event(ev))" in APP)
check("app.prompt", "MEETING MICHAEL - ALWAYS OFFER BOTH" in APP and "def _video_call_times_line():" in APP
      and 'if _maya_offers().get("both_ways"):   # PATCH #292' in APP)
check("app.email_reader_kind", 'tool_input["appointment_type"] = "video_call"' in APP
      and "invite_sent=True, video=True)" in APP and "_o[\"kind\"] = _kinds[" in APP)
for f in ("app.py", "slots.py", "studio_visit.py", "lead_reply.py", "first_touch.py"):
    check(f"compiles.{f}", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, f)], capture_output=True).returncode == 0)

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 292) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
mm = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not mm:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(mm.group(1)); failed += int(mm.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(mm.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE292 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
