"""PATCH #148 gate — the studio-hour track (ERIC spec 1 Oct 13:14 ET, Michael's GO).

Owner under $50K/month -> `studio-hour`: same gates and speed, its own copy
(no price, no subscription, studio first), its own chain kind, counted as its
own pipeline, dark until STUDIO_HOUR_TRACK_LIVE=1 (held + flagged until then).
Prints "N passed, M failed".
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lead_form as lf          # noqa: E402
import lead_chase as lc         # noqa: E402
import studio_visit as sv       # noqa: E402
import sms_copy                 # noqa: E402

SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# ── 1. routing ─────────────────────────────────────────────────────────────
def q(role, rev):
    return lf.qualify(role, rev)[0]

check("route.owner_150", q("Owner/Founder/Partner", "$150K+") == lf.Q_YES)
check("route.owner_50_150", q("Owner/Founder/Partner", "$50-150K") == lf.Q_YES)
check("route.owner_20_50", q("Owner/Founder/Partner", "$20-50K") == lf.Q_STUDIO_HOUR)
check("route.owner_under_20", q("Owner/Founder/Partner", "Under $20K") == lf.Q_STUDIO_HOUR)
check("route.owner_no_rev", q("Owner", "") == lf.Q_REVIEW)
check("route.creator_any", q("Freelancer/Creator/Artist", "$150K+") == lf.Q_NO)
check("route.creator_low", q("Freelancer/Creator/Artist", "Under $20K") == lf.Q_NO)
check("route.marketing_under_20", q("Marketing lead", "Under $20K") == lf.Q_NO)
check("route.marketing_20_50", q("Marketing lead", "$20-50K") == lf.Q_REVIEW)
check("route.employee_150", q("Employee", "$150K+") == lf.Q_REVIEW)
check("route.reason_names_track", "studio-hour" in lf.qualify("Owner", "$20-50K")[1])

# ── 2. sheet / labels / pipeline ──────────────────────────────────────────
check("label.status", lf.status_label(lf.Q_STUDIO_HOUR) == "Qualified (studio-hour)")
check("label.temp", lf.temperature(lf.Q_STUDIO_HOUR) == "Warm")
check("track.sh", lf.track_for(lf.Q_STUDIO_HOUR) == "studio-hour")
check("track.main", lf.track_for(lf.Q_YES) == "subscription" and lf.track_for(lf.Q_REVIEW) == "subscription")
check("track.no", lf.track_for(lf.Q_NO) == "")
rec = {"name": "Ana Lima", "email": "ana@example.com", "business": "Lima Dental",
       "role_raw": "Owner", "revenue_raw": "$20-50K", "website": "", "must_understand": "x", "extra": {}}
upd = lf.sheet_updates(rec, True, "2026-10-01T13:00:00", lf.Q_STUDIO_HOUR, "owner + $20-50K/month: studio-hour track")
check("sheet.status", upd["Status"] == "Qualified (studio-hour)")
check("sheet.service", upd["Service Interest"] == "Studio Hour (ad form)")
check("sheet.notes_track", "track: studio-hour" in upd["Notes"])
upd_main = lf.sheet_updates(rec, True, "", lf.Q_YES, "owner + $50K+/month")
check("sheet.main_service_unchanged", upd_main["Service Interest"] == "Studio Strategy Visit (ad form)")
check("sheet.main_notes_track", "track: subscription" in upd_main["Notes"])
check("plan.same_gates", lf.first_touch_plan(lf.Q_STUDIO_HOUR, True, True, True) == lf.first_touch_plan(lf.Q_YES, True, True, True))

# ── 3. the chain kind ─────────────────────────────────────────────────────
from datetime import datetime, timezone
now = datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)
st = lc.arm(now, channels=["email", "sms"], verdict=lf.Q_STUDIO_HOUR, kind=lc.KIND_STUDIO_HOUR)
check("chain.kind", st["kind"] == "studio_hour")
check("chain.same_steps", lc.steps_for(st) is lc.STEPS)
check("chain.summary_names_kind", "studio_hour" in lc.summary(st, now))

# ── 4. copy: fits, clean, on-script ───────────────────────────────────────
BANNED_SH = ("$1,200", "1200", "subscription", "send us photos", "AI Wall", "$249", "$349",
             "too small", "45-minute", "one-hour", "directed for")
slots = [{"display": "Mon Oct 5, 10am", "start": "2026-10-05T10:00:00-04:00"},
         {"display": "Tue Oct 6, 3pm", "start": "2026-10-06T15:00:00-04:00"}]
long_name = "Maximiliano Alejandro"
for ai in (False, True):
    for nm in ("Ana Lima", long_name, ""):
        for sl in (slots, slots[:1], None):
            core = sv.sh_first_touch_sms(nm, "Lima Dental", ai=ai, slots=sl)
            try:
                body = sms_copy.compose(core)
                ok = True
            except ValueError:
                ok = False
            # the long-name + two-slot variant may not fit; the fallback chain covers it
            if nm != long_name or sl is not slots:
                check(f"sms.fits ai={ai} name={nm!r} slots={len(sl or [])}", ok, core)
            low = core.lower()
            check(f"sms.clean ai={ai} name={nm!r}", not any(b.lower() in low for b in BANNED_SH), core)
            check(f"sms.30min ai={ai} name={nm!r}", "30-minute" in core and "in projects with" in core, core)
            check(f"sms.not_banned ai={ai}", not sv.contains_banned(core), core)

for ai in (False, True):
    subj, html, text = sv.sh_first_touch_email("Ana Lima", "Lima Dental", "why implants beat dentures for anyone over fifty.", ai=ai, slots=slots, sms_sent=True)
    low = text.lower()
    check(f"email.first_touch_clean ai={ai}", not any(b.lower() in low for b in BANNED_SH), text)
    check(f"email.first_touch_script ai={ai}", "30-minute" in text and sv.CREDITS in text and sv.WE_DO in text)
    check(f"email.first_touch_sizing ai={ai}", "studio hour or a small package" in text)
    check(f"email.first_touch_slots ai={ai}", "Mon Oct 5, 10am" in text and "Tue Oct 6, 3pm" in text)
    check(f"email.first_touch_subject ai={ai}", subj.startswith("Ana, your Studio Strategy Visit"))

for step in range(1, 6):
    subj, html, text = sv.sh_chase_email(step, "Ana Lima", "Lima Dental", "why implants beat dentures", ai=False)
    low = text.lower()
    check(f"chase_email.{step}.clean", not any(b.lower() in low for b in BANNED_SH), text[:200])
    check(f"chase_email.{step}.voice", "Michael Moraes" in text and "Maya at" in text)
    check(f"chase_email.{step}.not_banned", not sv.contains_banned(text))
    check(f"chase_email.{step}.html", "<p" in html and "Ana" in html)
_, _, t1 = sv.sh_chase_email(1, "Ana", "Lima Dental", "", ai=True)
check("chase_email.1.ai_line", "AI ad" in t1 and "any scene" in t1)
_, _, t3 = sv.sh_chase_email(3, "Ana", "Lima Dental", "")
check("chase_email.3.single_session", "a single session" in t3)
_, _, t4 = sv.sh_chase_email(4, "Ana", "Lima Dental", "")
check("chase_email.4.sizing", "nothing bigger than you need" in t4)

for step in (1, 2):
    for sl in (slots, None):
        core = sv.sh_chase_sms(step, "Ana Lima", sl)
        check(f"chase_sms.{step}.fits slots={bool(sl)}", len(sms_copy.compose(core)) <= 306, core)
        check(f"chase_sms.{step}.clean", not any(b.lower() in core.lower() for b in BANNED_SH), core)

# ── 5. Maya's rule ────────────────────────────────────────────────────────
rule = sv.STUDIO_HOUR_RULE
check("rule.never_pitch", "Never pitch the Studio Subscription" in rule)
check("rule.prices_only_asked", "Prices only when asked" in rule and "$249/hour" in rule)
check("rule.visit_close", "Studio Strategy Visit is still the close" in rule)
check("rule.no_photos", "send us" in rule and "photos" in rule and "AI Wall" in rule)
check("rule.not_banned", not sv.contains_banned(rule))

# ── 6. static wiring in app.py ────────────────────────────────────────────
check("wire.flag_fn", "def _studio_hour_track_live():" in SRC and 'STUDIO_HOUR_TRACK_LIVE' in SRC)
check("wire.hold", 'sh_hold = (verdict == _lf.Q_STUDIO_HOUR and not _studio_hour_track_live())' in SRC)
check("wire.hold_no_touch", 'sms_note, email_note = "held", "held"' in SRC and '"note": "held: track not live"' in SRC)
check("wire.hold_before_no", SRC.index("if sh_hold:\n            # Held, not touched.") < SRC.index("elif verdict == _lf.Q_NO:"))
check("wire.sh_sms", "_sh_first_touch_sms_body(name, rec[\"business\"], ai, slots) if sh" in SRC)
check("wire.sh_email", "_ft_email = _sv.sh_first_touch_email if sh else _sv.form_first_touch_email" in SRC)
check("wire.sh_kind", "kind=(_chase.KIND_STUDIO_HOUR if sh else _chase.KIND_FORM)" in SRC)
check("wire.chase_email_kind", 'elif state.get("kind") == _chase.KIND_STUDIO_HOUR:\n                    subj, html, _ = _sv.sh_chase_email(' in SRC)
check("wire.chase_sms_kind", "lambda: _sv.sh_chase_sms(copy_step, rec.get(\"name\"), slots)" in SRC)
check("wire.track_on_record", 'upd["track"] = track' in SRC)
check("wire.eric_line", "Qualified: {verdict}{track_txt}" in SRC and "HELD: the studio-hour track is not live yet" in SRC)
check("wire.counter", '_TALLY.bump("lead_form.track", track' in SRC)
check("wire.health_flag", '"studio_hour_track_live": _studio_hour_track_live()' in SRC)
check("wire.health_kinds", '"kinds": counts.get("kinds", {})' in SRC)
check("wire.maya_rule", "_sys += \"\\n\\n\" + _sv.STUDIO_HOUR_RULE" in SRC)
check("wire.sms_ctx_track", 'bits.append(f"Track: {rec[\'track\']}")' in SRC)
check("wire.capi_still_sent", SRC.index("kind=(_chase.KIND_STUDIO_HOUR if sh else _chase.KIND_FORM)") < SRC.index("_capi_send_async(_capi.lead_event("))

print(f"static: {passed} passed, {failed} failed")

# ── 7. the whole rail still passes (#143 gate = static + behaviour) ──────
import subprocess
r = subprocess.run([sys.executable, os.path.join(HERE, "test_patch143.py")], capture_output=True, text=True)
tail = (r.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r.stdout[-1500:]); print(r.stderr[-800:])
    failed += 1; print("FAIL rail gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("rail: " + tail)

print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
