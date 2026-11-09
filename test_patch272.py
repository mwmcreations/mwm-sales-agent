#!/usr/bin/env python3
"""GATE for PATCH #272 — Michael's three corrections from Karl Maiwaldt's chase
(Sun 8 Nov 22:40). Pure checks first (lead_chase, studio_visit), then the app.py
source pins, then the earlier gates (271 → 270 → …) so nothing older moved.
Prints GATE272 PASS or GATE272 FAIL."""
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

FAILS = []
N = 0


def check(name, ok, detail=""):
    global N
    N += 1
    if not ok:
        FAILS.append(f"{name}: {str(detail)[:300]}")
        print(f"  FAIL {name} {str(detail)[:200]}")


TZ = pytz.timezone("America/New_York")

# ── 1. industry_word: a noun or 'business', never the name ───────────────────
check("ind.ktm", sv.industry_word("K.T.M. TOYS & GrApHiCs") == "business", sv.industry_word("K.T.M. TOYS & GrApHiCs"))
check("ind.southlife", sv.industry_word("Southlife") == "business")
check("ind.id8", sv.industry_word("iD8") == "business")
check("ind.raw_choice", sv.industry_word("owner_/_founder_/_partner") == "business")
check("ind.empty", sv.industry_word("") == "business")
check("ind.roofing", sv.industry_word("Lee Roofing") == "roofing company")
check("ind.dental", sv.industry_word("Orlando Lifestyle Dentistry") == "dental practice")
check("ind.realty", sv.industry_word("Global Premier Real Estate") == "real estate brokerage")
check("ind.mortgage_before_broker", sv.industry_word("Sunshine Mortgage Brokers") == "mortgage business")
check("ind.alarm_before_dealer", sv.industry_word("Your Local Alarm Dealer") == "security company")
check("ind.law_not_lawn", sv.industry_word("Green Lawn Care") == "landscaping company")
check("ind.law", sv.industry_word("Peterson Law Group") == "law firm")
check("ind.spa_not_spanish", sv.industry_word("Spanish Lessons Orlando") == "academy")
check("ind.medspa", sv.industry_word("Glow Med Spa") == "practice")
check("ind.kitchen_restaurant", sv.industry_word("Mama's Kitchen") == "restaurant")
check("ind.ceramic", sv.industry_word("Ceramic pro") == "business")
check("ind.never_name", all(sv.industry_word(b) != b for b in
                            ("Lee Roofing", "Southlife", "Enzo Auto Service", "Victory Martial Arts")))
for fn_ in (sv.chase_email, sv.sh_chase_email):
    s3, _, t3 = fn_(3, "Karl", "K.T.M. TOYS & GrApHiCs", "we are a service")
    check(f"{fn_.__name__}.3.subject_generic", s3 == "The three videos every business needs before the customer buys", s3)
    check(f"{fn_.__name__}.3.no_name_in_subject", "K.T.M." not in s3)
    s3b, _, _ = fn_(3, "Marcus", "Lee Roofing", "")
    check(f"{fn_.__name__}.3.subject_industry", s3b == "The three videos every roofing company needs before the customer buys", s3b)
    s2, _, _ = fn_(2, "Karl", "K.T.M. TOYS & GrApHiCs", "")
    check(f"{fn_.__name__}.2.unchanged", s2.startswith("How ") and "uses the studio" in s2, s2)

# ── 3. note_touch pushes the schedule, not the arming clock ──────────────────
t0 = TZ.localize(datetime(2026, 10, 25, 4, 39))
st = lc.arm(t0, channels=("email", "sms"), verdict="studio-hour", kind=lc.KIND_STUDIO_HOUR)
# day 9 text sent; day 10 email would be due at +240h
for k in ("e1", "s1", "e2", "s2"):
    st["sent"][k] = (t0 + timedelta(hours=lc.STEP_BY_KEY[k][2])).isoformat()
t_reoffer = t0 + timedelta(hours=9 * 24 + 7)          # Nov 3, 11:39
check("touch.before", lc.next_step(st, t0 + timedelta(hours=240, minutes=1)) == ("e3", "email", 3))
lc.note_touch(st, t_reoffer, label="reoffer")
check("touch.recorded", st.get("touches") and st["touches"][0]["label"] == "reoffer" and st["push_h"] == 72.0, st.get("touches"))
check("touch.armed_at_unmoved", st["armed_at"] == t0.isoformat())
check("touch.e3_waits", lc.next_step(st, t0 + timedelta(hours=240, minutes=1)) is None)
check("touch.e3_after_push", lc.next_step(st, t0 + timedelta(hours=240 + 72, minutes=1)) == ("e3", "email", 3))
check("touch.e3_not_skipped", lc.next_step(st, t0 + timedelta(hours=240 + 72 + 24)) == ("e3", "email", 3))
# a reply the day after the re-offer still stops the chain
check("touch.reply_still_stops",
      lc.stop_reason(st, {}, t_reoffer + timedelta(days=1), last_inbound=t_reoffer + timedelta(days=1)) == lc.STOP_REPLIED)
# two touches accumulate
lc.note_touch(st, t_reoffer + timedelta(days=1), label="reoffer", push_h=24)
check("touch.accumulates", st["push_h"] == 96.0 and len(st["touches"]) == 2)
check("touch.summary", "pushed 4d after 2 touch(es)" in lc.summary(st, t_reoffer + timedelta(days=2)), lc.summary(st, t_reoffer + timedelta(days=2)))
check("touch.none_state", lc.note_touch(None, t0) is None)
# untouched chain unchanged
st2 = lc.arm(t0, channels=("email",))
check("touch.untouched_hours", abs(lc.hours_since_armed(st2, t0 + timedelta(hours=30)) - 30) < 1e-6)
check("touch.untouched_summary", "pushed" not in lc.summary(st2, t0 + timedelta(hours=1)))
check("touch.const", lc.PUSH_AFTER_TOUCH_H == 72)

# ── 4. app.py source pins ─────────────────────────────────────────────────────
with open(os.path.join(HERE, "app.py"), encoding="utf-8") as f:
    SRC = f.read()
check("app.overnight_consts", 'FIRST_TOUCH_EMAIL_QUIET_FROM_H = int(os.getenv("FIRST_TOUCH_EMAIL_QUIET_FROM_H", "22"))' in SRC
      and 'FIRST_TOUCH_EMAIL_QUIET_TO_H = int(os.getenv("FIRST_TOUCH_EMAIL_QUIET_TO_H", "7"))' in SRC)
check("app.overnight_fn", "def _first_touch_email_overnight(now):" in SRC
      and "return h >= FIRST_TOUCH_EMAIL_QUIET_FROM_H or h < FIRST_TOUCH_EMAIL_QUIET_TO_H" in SRC)
check("app.overnight_before_intake", SRC.index("def _first_touch_email_overnight(now):") < SRC.index("def _meta_lead_intake(value, lead_meta=None):"))
i_hold = SRC.find('if (globals().get("_first_touch_email_overnight") or (lambda _n: False))(now):')
check("app.intake_hold", i_hold > 0)
check("app.intake_hold_record", 'lr["first_touch_email_pending"] = {"since": now.isoformat(), "sh": bool(sh),' in SRC
      and '"ai": bool(ai)}' in SRC)
check("app.intake_hold_note", 'email_note = "queued (overnight, sends at 7 AM)"' in SRC)
check("app.intake_hold_continue", SRC[i_hold:i_hold + 600].count("continue") == 1
      and "_ft_email = _sv.sh_first_touch_email if sh else _sv.form_first_touch_email" in SRC[i_hold:i_hold + 700])
# the hold sits inside the email branch, before the send
seg = SRC[SRC.index('elif chan == "email":\n                    # PATCH #272 — held until 7 AM'):]
check("app.intake_hold_before_send", seg.index("_first_touch_email_overnight") < seg.index("_email_send(email, subj, html,"))
check("app.intake_hold_guarded", 'globals().get("_first_touch_email_overnight")' in SRC[i_hold - 10:i_hold + 120])
# the flush in the chase pass
i_flush = SRC.find("# ── PATCH #272: the first-touch email that waited for 7 AM ──")
i_sms = SRC.find("# ── the first-touch text that had to wait for the window ──")
i_chain = SRC.find("        # ── the chain ──\n        state = rec.get(\"chase\")")
check("app.flush_present", i_flush > 0 and i_sms > i_flush > SRC.find("def _chase_pass(now=None):"))
check("app.flush_before_chain", i_flush < i_chain)
fl = SRC[i_flush:i_sms]
check("app.flush_guarded", '_ovn = globals().get("_first_touch_email_overnight") or (lambda _n: False)' in fl)
check("app.flush_window", "if isinstance(pend_e, dict) and not _ovn(now):" in fl)
check("app.flush_drop_rules", "_ewaited > _chase.FIRST_TOUCH_SMS_MAX_WAIT_H" in fl and "_ereplied" in fl
      and "_chase_booked(rec)" in fl and 'isinstance(rec.get("disqualified"), dict)' in fl and "email_is_suppressed(_eaddr)[0]" in fl)
check("app.flush_builds_copy", "_eft = _sv.sh_first_touch_email if _esh else _sv.form_first_touch_email" in fl
      and 'sms_sent=bool(rec.get("first_touch_sms_at"))' in fl)
check("app.flush_fresh_slots", "_eslots = (get_available_slots() or [])[:2]" in fl and 'rec["offered_slots"]' in fl)
check("app.flush_via", 'via=("lead_form_first_touch_sh" if _esh else "lead_form_first_touch")' in fl)
check("app.flush_stamps", 'rec["first_touch_email_at"] = now.isoformat()' in fl and 'rec.pop("first_touch_email_pending", None)' in fl)
check("app.flush_suppressed_drops", '_eres.get("suppressed")' in fl and '"suppressed"' in fl)
check("app.flush_counts", 'counts["pending_first_touch"] += 1' in fl and 'counts["sent"] += 1' in fl)
check("app.flush_no_bare_global", "_first_touch_email_overnight(now)" not in fl.replace('globals().get("_first_touch_email_overnight")', ""))
# /admin/chase shows it
check("app.admin_row", '"first_touch_email_pending": bool(rec.get("first_touch_email_pending")),   # PATCH #272' in SRC
      and '"push_h": (st or {}).get("push_h", 0), "touches": (st or {}).get("touches", []),' in SRC)
check("app.admin_filter", 'if not st and not pend and not rec.get("first_touch_email_pending"):   # PATCH #272' in SRC)
# the re-offer hook
i_ro = SRC.find("# PATCH #272 — a hand-sent re-offer is a chase touch")
check("app.reoffer_hook", i_ro > SRC.find("@app.route('/admin/reoffer', methods=['POST'])"))
ro = SRC[i_ro:i_ro + 900]
check("app.reoffer_only_active", 'not _rst.get("stopped")' in ro and 'any(str(v) == "sent" for v in sent.values())' in ro)
check("app.reoffer_note", '_chase.note_touch(_rst, now, label="reoffer", push_h=_chase.PUSH_AFTER_TOUCH_H)' in ro)
check("app.reoffer_row", 'row["chase"] = _chase.summary(_rst, now)' in ro)
check("app.reoffer_after_sends", SRC.find('rec["reoffer_sent"] = sent') < i_ro < SRC.find("tw = _lead_twin(rec)", i_ro))
# the chain's own rules did not move
check("app.chain_window_intact", "if not event_rail.within_send_window(now):" in SRC)
check("app.sms_pending_intact", 'if isinstance(pend, dict) and pend.get("core"):' in SRC)
check("app.no_armed_at_shift", "armed_at\"] = " not in SRC[SRC.find("def _chase_pass"):SRC.find("def _chase_mask(")])
# #152's pin updated
with open(os.path.join(HERE, "test_patch152.py"), encoding="utf-8") as f:
    T152 = f.read()
check("t152.pin_updated", 'every business needs before the customer buys", s3b)   # #272' in T152 and "every iD8 needs" not in T152)

# ── 5. the held email, lifted into a harness (#256 style) ────────────────────
import ast  # noqa: E402
import sms_copy as _sms_copy      # noqa: E402
import event_rail                 # noqa: E402
import sms_consent as _sc         # noqa: E402
tree = ast.parse(SRC)
want = {"_chase_pass", "_chase_mask", "email_ok", "_chase_twin", "_chase_inbound", "_chase_booked",
        "_chase_aware", "_first_touch_email_overnight"}
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
check("lift.found", len(fns) == len(want), f"{len(fns)}/{len(want)}")
consts = [n for n in tree.body if isinstance(n, ast.Assign) and any(
    isinstance(t, ast.Name) and t.id in ("FIRST_TOUCH_EMAIL_QUIET_FROM_H", "FIRST_TOUCH_EMAIL_QUIET_TO_H") for t in n.targets)]
check("lift.consts", len(consts) == 2)
sms_calls, email_calls, tally = [], [], []


class Tally:
    def bump(self, *a): tally.append(a)


BL = {}
BG = dict(lead_data=BL, re=re, os=os, datetime=datetime, timedelta=timedelta, pytz=pytz, TIMEZONE="America/New_York",
          _chase=lc, _sc=_sc, _sv=sv, _sms_copy=_sms_copy, event_rail=event_rail,
          SMS_KIND_MARKETING="marketing", SMS_KIND_TRANSACTIONAL="transactional",
          _LEAD_CHASE_LAST={"last_send": ""}, _TALLY=Tally(),
          _chase_is_client=lambda k: False, email_is_suppressed=lambda e: ("nope" in e, ""),
          get_available_slots=lambda: [{"id": "2026-11-10T10:00:00-05:00", "display": "Tuesday, November 10 at 10:00 AM EST"},
                                       {"id": "2026-11-12T15:00:00-05:00", "display": "Thursday, November 12 at 03:00 PM EST"}],
          _sms_body_that_fits=lambda fns_: fns_[0](),
          _send_sms=lambda phone, body, kind="marketing": (sms_calls.append((phone, body)) or {"ok": True}),
          _email_send=lambda to, subject, html, via="", lead_key=None, **k: (email_calls.append((to, subject, via, html)) or
                                                                          ({"ok": False, "suppressed": True, "error": "x"} if "supp" in to else {"ok": True})),
          globals=lambda: BG)
exec(compile(ast.Module(body=consts + fns, type_ignores=[]), "app_272_pass", "exec"), BG)
check("harness.overnight", BG["_first_touch_email_overnight"](TZ.localize(datetime(2026, 10, 25, 4, 39)))
      and BG["_first_touch_email_overnight"](TZ.localize(datetime(2026, 10, 25, 22, 0)))
      and not BG["_first_touch_email_overnight"](TZ.localize(datetime(2026, 10, 25, 7, 0)))
      and not BG["_first_touch_email_overnight"](TZ.localize(datetime(2026, 10, 25, 21, 59))))
T0 = TZ.localize(datetime(2026, 10, 25, 4, 39))
K = "whatsapp:+14076928290"
BL[K] = {"name": "Karl Maiwaldt", "email": "ktmtoys@hotmail.com", "phone": "+14076928290", "business": "K.T.M. TOYS & GrApHiCs",
         "must_understand": "we are a service", "qualified": "studio-hour", "meta_lead_ad": True, "last_message_time": T0,
         "first_touch_email_pending": {"since": T0.isoformat(), "sh": True, "ai": False},
         "chase": lc.arm(T0, channels=("email", "sms"), verdict="studio-hour", kind=lc.KIND_STUDIO_HOUR)}
c = BG["_chase_pass"](T0 + timedelta(minutes=30))          # 5:09 AM — still night
check("held.not_yet", not email_calls and "first_touch_email_pending" in BL[K] and c["pending_first_touch"] == 1, str(c))
c = BG["_chase_pass"](TZ.localize(datetime(2026, 10, 25, 7, 2)))   # 7:02 AM
check("held.sent_at_7", len(email_calls) == 1 and email_calls[0][0] == "ktmtoys@hotmail.com"
      and email_calls[0][2] == "lead_form_first_touch_sh", str(email_calls))
check("held.copy_is_first_touch", email_calls and "Karl, your Studio Strategy Visit with Michael Moraes" == email_calls[0][1], email_calls and email_calls[0][1])
check("held.fresh_slots_in_copy", email_calls and "Tue Nov 10" in email_calls[0][3] and "Thu Nov 12" in email_calls[0][3])
check("held.slots_remembered", BL[K].get("offered_slots") and BL[K]["offered_slots"][0]["id"] == "2026-11-10T10:00:00-05:00")
check("held.stamped", "first_touch_email_pending" not in BL[K] and BL[K].get("first_touch_email_at", "").startswith("2026-10-25T07:02"))
check("held.chain_untouched", not BL[K]["chase"].get("stopped") and not BL[K]["chase"]["sent"], str(BL[K]["chase"]))
check("held.tally", ("lead_form.first_touch_email", "sent_7am") in tally)
# the form track picks the form copy
email_calls.clear()
BL[K]["first_touch_email_pending"] = {"since": T0.isoformat(), "sh": False, "ai": True}
BG["_chase_pass"](TZ.localize(datetime(2026, 10, 25, 7, 3)))
check("held.form_copy", len(email_calls) == 1 and email_calls[0][2] == "lead_form_first_touch", str([e[:3] for e in email_calls]))
# a reply overnight drops it
email_calls.clear()
BL[K]["first_touch_email_pending"] = {"since": T0.isoformat(), "sh": True, "ai": False}
BL[K]["last_message_time"] = T0 + timedelta(hours=1)
BG["_chase_pass"](TZ.localize(datetime(2026, 10, 25, 7, 3)))
check("held.reply_drops", not email_calls and BL[K].get("first_touch_email_dropped") == "replied" and "first_touch_email_pending" not in BL[K])
BL[K]["last_message_time"] = T0
# a booking overnight drops it
BL[K]["first_touch_email_pending"] = {"since": T0.isoformat(), "sh": True, "ai": False}
BL[K]["booked"] = True
BG["_chase_pass"](TZ.localize(datetime(2026, 10, 25, 7, 3)))
check("held.booked_drops", not email_calls and "first_touch_email_pending" not in BL[K])
BL[K].pop("booked")
# a suppressed address drops it, a refused send does not loop
BL[K]["chase"] = lc.arm(T0, channels=("email", "sms"), verdict="studio-hour", kind=lc.KIND_STUDIO_HOUR)
BL[K]["first_touch_email_pending"] = {"since": T0.isoformat(), "sh": True, "ai": False}
BL[K]["email"] = "nope@x.com"
BG["_chase_pass"](TZ.localize(datetime(2026, 10, 25, 7, 3)))
check("held.suppressed_address_drops", not email_calls and BL[K].get("first_touch_email_dropped") == "no sendable email")
BL[K]["email"] = "supp@x.com"
BL[K]["first_touch_email_pending"] = {"since": T0.isoformat(), "sh": True, "ai": False}
BG["_chase_pass"](TZ.localize(datetime(2026, 10, 25, 7, 3)))
check("held.send_suppressed_drops", len(email_calls) == 1 and BL[K].get("first_touch_email_dropped") == "suppressed"
      and "first_touch_email_pending" not in BL[K])
# too old is dropped, never sent two days late
email_calls.clear()
BL[K]["email"] = "ktmtoys@hotmail.com"
BL[K]["first_touch_email_pending"] = {"since": T0.isoformat(), "sh": True, "ai": False}
BG["_chase_pass"](T0 + timedelta(hours=40))
check("held.too_old_drops", not email_calls and BL[K].get("first_touch_email_dropped", "").startswith("waited"))
# the SMS pending block still works beside it
BL[K]["first_touch_sms_pending"] = {"since": T0.isoformat(), "core": "Hi Karl", "reason": "quiet_hours"}
BG["_chase_pass"](TZ.localize(datetime(2026, 10, 25, 8, 1)))
check("held.sms_block_intact", sms_calls and sms_calls[-1][0] == "+14076928290" and "first_touch_sms_pending" not in BL[K])

# ── the old gates still pass (compile + chain) ───────────────────────────────
try:
    import py_compile
    for m in ("app.py", "lead_chase.py", "studio_visit.py"):
        py_compile.compile(os.path.join(HERE, m), doraise=True)
    check("compile", True)
except Exception as _cx:
    check("compile", False, _cx)

passed = N - len(FAILS)
failed = len(FAILS)
print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch271.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #271 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("271: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
for f_ in FAILS:
    print("  -", f_)
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE272 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
