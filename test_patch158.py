"""PATCH #158 gate — reengage-oct12: the one-off "three studio visit slots
this week" push (ERIC, 9 Oct 2026, item 3).

Proves: the email is Michael, first person, no price, three named slots,
reply or text Maya to book, "stop" honoured; the SMS composes inside two
segments with the longest plausible name; a send is armed for a time and
is due only once that time has passed; the route has count / preview / arm
/ disarm / status / send, `send` needs go=1, the done-key is claimed BEFORE
sending so it can never run twice, a tagged record is skipped, the tick
rides the chase loop, /health shows it. Prints "N passed, M failed", then
runs the #157 gate (which chains event_rail → #156 → … → #143).
"""
import os
import re
import subprocess
import sys
from datetime import datetime

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reengage as rg      # noqa: E402
import sms_copy as sc      # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


tz = pytz.timezone("America/New_York")
SLOTS = [{"display": "Monday, October 12 at 10:00 AM EST"}, {"display": "Tuesday, October 13 at 03:00 PM EST"},
         {"display": "Wednesday, October 14 at 11:00 AM EST"}]

s, h, t = rg.email_copy("Silvana Pampu", SLOTS)
check("email.subject", s == "Three studio visit slots this week")
check("email.first_person", "Michael Moraes here" in t and "I'd like to open the door again" in t and t.startswith("Hi Silvana,"))
check("email.three_slots", "1. Monday, October 12 at 10:00 AM" in t and "2. Tuesday, October 13 at 03:00 PM" in t
      and "3. Wednesday, October 14 at 11:00 AM" in t and "EST" not in t)
check("email.html_slots", h.count("<li>") == 3 and "<ol>" in h)
check("email.no_price", "$" not in t and "$" not in h and "price" not in t.lower())
check("email.book_via_maya", "text Maya on my team at +1 407-871-6473" in t and "she'll lock it in" in t)
check("email.stop", 'reply "stop"' in t and 'reply "stop"' in h)
check("email.free_visit_30", "30 minutes, free" in t)
check("email.signature", t.rstrip().endswith("1500 Park Center Dr, Suite 230, Orlando, FL"))
_, _, t0 = rg.email_copy("", [])
check("email.no_name_no_slots", t0.startswith("Hi there,") and "(reply with a day that works)" in t0)
_, _, t1 = rg.email_copy("maria@x.com", SLOTS[:1])
check("email.email_as_name", t1.startswith("Hi Maria,") and "  1. Monday" in t1 and "  2." not in t1)

core = rg.sms_copy("Silvana", SLOTS)
check("sms.two_slots_only", "Monday, October 12 at 10:00 AM or Tuesday, October 13 at 03:00 PM" in core and "Wednesday" not in core)
check("sms.first_person_maya_books", core.startswith("Hi Silvana, Michael Moraes (MWM Studios).") and "Maya books it" in core)
for nm in ("Maximiliano", "Christopher", "there", ""):
    body = sc.compose(rg.sms_copy(nm, SLOTS))
    check(f"sms.fits {nm!r}", sc.segments(body) <= 2 and "STOP" in body.upper(), (len(body), body))
check("sms.no_slots", "this week" in rg.sms_copy("A", []))

# ── #158c: what the first dry run (10 Oct 00:30 ET) showed ───────────────────
now = tz.localize(datetime(2026, 10, 12, 10, 0))
check("c.primary_email", rg.primary_email("kri.x@gmail.com / michael@michaelneeley.com") == "kri.x@gmail.com"
      and rg.primary_email(" A.B@X.COM, b@y.com") == "a.b@x.com" and rg.primary_email("nope") == "" and rg.primary_email(None) == "")
check("c.excluded_address", rg.excluded_address("t@meta.com") and rg.excluded_address("noreply@shop.com")
      and rg.excluded_address("x@mwmcreations.com") and not rg.excluded_address("info@simplysuccessgroup.net")
      and not rg.excluded_address("ana@x.com") and rg.excluded_address(""))
check("c.bot_name", rg.looks_like_bot("Success Bot (Simply Success Group)") and rg.looks_like_bot("Auto-Reply")
      and not rg.looks_like_bot("Abbot Smith") and not rg.looks_like_bot("Bottega Co"))
_b = {"name": "Ana", "email": "ana@x.com", "last_message_time": "2026-09-01T10:00:00-04:00"}
check("c.test_name_any_key", rg.classify("whatsapp:+14075550010", dict(_b, name="<test lead: dummy data for full_name>", email="t@meta.com"), now) is None)
check("c.bot_out", rg.classify("whatsapp:+14075550011", dict(_b, name="Success Bot (Simply Success Group)"), now) is None)
_r2 = rg.classify("whatsapp:+14075550012", dict(_b, email="kri.x@gmail.com / michael@michaelneeley.com"), now)
check("c.two_addresses_first_wins", _r2 and _r2["email"] and _r2["email_addr"] == "kri.x@gmail.com", _r2)
_r3 = rg.classify("whatsapp:+14075550013", dict(_b, email="noreply@shop.com"), now)
check("c.role_address_not_email", _r3 and not _r3["email"] and _r3["email_addr"] == "")
_rows = [{"key": "whatsapp:+14075550001", "email": True, "sms": True, "_email": "a@x.com", "_phone": "+14075550001"},
         {"key": "instagram:1", "email": True, "sms": False, "_email": "A@x.com", "_phone": ""},
         {"key": "whatsapp:+14075550002", "email": True, "sms": True, "_email": "b@x.com", "_phone": "+14075550001"},
         {"key": "whatsapp:+14075550003", "email": False, "sms": False, "_email": "", "_phone": ""}]
rg.dedupe(_rows)
check("c.dedupe_email", _rows[0]["email"] and _rows[0]["_dup_of"] == "" and not _rows[1]["email"] and _rows[1]["_dup_of"] == "whatsapp:+14075550001"
      and not _rows[1]["reachable"])
check("c.dedupe_phone", _rows[2]["email"] and not _rows[2]["sms"] and _rows[2]["_dup_of"] == "whatsapp:+14075550001" and _rows[2]["reachable"])
check("c.dedupe_untouched", _rows[3]["_dup_of"] == "" and not _rows[3]["reachable"])
for _d, _exp_start, _exp_h in ((12, (13, "Tue"), 4), (9, (12, "Mon"), 5), (10, (12, "Mon"), 5), (15, (16, "Fri"), 1), (16, (19, "Mon"), 5)):
    _st, _h = rg.week_window(tz.localize(datetime(2026, 10, _d, 10, 0)))
    check(f"c.week_window {_d}", (_st.day, _st.strftime("%a")) == _exp_start and _h == _exp_h and _st.hour == 0 and _st.tzinfo is not None
          and _st.utcoffset().total_seconds() == -4 * 3600, (_st, _h))
_, _, t2 = rg.email_copy("Ana", SLOTS[:2])
check("c.copy_counts_slots", "I have two slots open this week:" in t2 and "I have three slots open this week:" in t)
check("c.sms_no_slots_reads", "slots open this week. Reply with a time that works" in rg.sms_copy("Ana", []))

now = tz.localize(datetime(2026, 10, 12, 10, 0))
check("due.exact", rg.is_due("2026-10-12T10:00:00-04:00", now))
check("due.before", not rg.is_due("2026-10-12T10:05:00-04:00", now))
check("due.after", rg.is_due("2026-10-12T09:00:00-04:00", tz.localize(datetime(2026, 10, 12, 10, 3))))
check("due.naive_treated_local", rg.is_due("2026-10-12T10:00:00", now))
check("due.empty_or_bad", not rg.is_due("", now) and not rg.is_due("nope", now) and not rg.is_due(None, now))
check("keys", rg.SEND_AT_KEY == "reengage_oct12_send_at" and rg.DONE_KEY == "reengage_oct12_done" and rg.TAG == "reengage-oct12")

# ── wiring (static) ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
rt = SRC[SRC.index("def admin_reengage_oct12():"):SRC.index("@app.route('/admin/lead-form-repair'")]
for mode in ('"count"', '"preview"', '"arm"', '"disarm"', '"status"', '"send"'):
    check(f"wire.mode {mode}", f"if _mode == {mode}:" in rt)
check("wire.send_needs_go", 'if str(request.args.get("go") or "") != "1":' in rt)
check("wire.send_claims_done_first", rt.index('_pgr.save_state(_rg.DONE_KEY, {"started": _now.isoformat(), "by": "admin"})')
      < rt.index("_out = _reengage_send(_now, dry=False, limit=request.args.get(\"limit\"))"))
check("wire.arm_refuses_after_run", 'if _pgr.load_state(_rg.DONE_KEY, None):\n            return jsonify({"ok": False, "error": "already ran' in rt)
check("wire.arm_posts_eric", "*reengage-oct12 armed*" in rt)
sf = SRC[SRC.index("def _reengage_send(now, dry=True, limit=None, rows=None):"):SRC.index("def _reengage_tick(now=None):")]
check("wire.send_idempotent", 'if r["_already"]:' in sf and 'rec["reengage_oct12"] = stamp' in sf)
check("wire.send_email_via", 'via="reengage-oct12"' in sf and "SMS_KIND_MARKETING" in sf)
check("wire.send_tags_sheet", 'update_lead_columns(key, {"Ad Campaign": _rg.TAG})' in sf)
check("wire.send_dry_no_send", "if dry:\n            continue" in sf)
check("wire.send_throttle", "_t.sleep(0.4)" in sf)
tk = SRC[SRC.index("def _reengage_tick(now=None):"):SRC.index("@app.route('/admin/reengage-oct12'")]
check("wire.tick_claims_before_send", tk.index('_pgr.save_state(_rg.DONE_KEY, {"started": now.isoformat()})') < tk.index("_reengage_send(now, dry=False)"))
check("wire.tick_due_check", "_rg.is_due(armed, now)" in tk and "_pgr.load_state(_rg.DONE_KEY, None)" in tk)
check("wire.tick_posts", "SLACK_ERIC_CHANNEL" in tk and "SLACK_DEV_CHANNEL" in tk)
check("wire.tick_in_chase_loop", "_reengage_tick()              # PATCH #158" in SRC
      and SRC.index("_reengage_tick()              # PATCH #158") < SRC.index("counts = _chase_pass()"))
check("wire.health", '"reengage_oct12": dict(_REENGAGE_LAST)' in SRC)
rows = SRC[SRC.index("def _reengage_rows(now):"):SRC.index("def _reengage_send(")]
check("wire.rows_one_query", '_pgc.load_prefix("sms_consent:")' in rows and "_sms_consent_get(" not in rows
      and '_pgc.load_prefix("email_suppressed:")' in rows and "email_is_suppressed(e, dynamic=_dyn)" in rows)
sup = SRC[SRC.index("def email_is_suppressed(addr, dynamic=None):"):SRC.index("def email_is_suppressed(addr, dynamic=None):") + 1600]
check("wire.suppressed_dynamic_param", "if dynamic is not None:" in sup and 'return (True, "suppressed (dynamic list)") if e in dynamic else (False, "")' in sup
      and sup.index("if dynamic is not None:") > sup.index('"internal address"'), "static checks still run before the batch answer")
check("wire.preview_one_pass", "_out = _reengage_send(_now, dry=True, rows=_rows)" in SRC)
# #158c wiring
check("wire.c.rows_exclude_clients", "_kc.is_client_record(_r)" in rows and "_CLIENT_ROSTER.find(" in rows
      and 'if _f.get("booked"):' in rows and "_rg.dedupe(rows)" in rows and '_f["_email"] = _f.get("email_addr") or ""' in rows)
check("wire.c.send_week_slots", "slots = get_week_slots(now) or []" in sf and "get_available_slots()" not in sf)
check("wire.c.send_dup_tag_only", 'if r.get("_dup_of"):' in sf and sf.index('if r.get("_dup_of"):') < sf.index('if not (r["email"] or r["sms"]):')
      and "_email_send" not in sf[sf.index('if r.get("_dup_of"):'):sf.index('if not (r["email"] or r["sms"]):')])
check("wire.c.preview_lowercase_there", '_rg.email_copy("", slots)' in sf)
wk = SRC[SRC.index("def get_week_slots(now=None):"):SRC.index("def get_available_slots():")]
check("wire.c.week_slots", "_rg.week_window(now)" in wk and "_slots.compute_slots(start, busy_times, tz" in wk
      and "horizon_days=horizon" in wk and "max_slots=3" in wk and "_calendar_busy_times(" in wk)
ga = SRC[SRC.index("def get_available_slots():"):SRC.index("# ─── PATCH #104 — auto-cleanup identity matching")]
check("wire.c.slots_share_calendar_read", '_calendar_busy_times(now, days=21, who="get_available_slots")' in ga
      and "service.events().list(" not in ga and "service.events().list(" in SRC[SRC.index("def _calendar_busy_times("):SRC.index("def get_week_slots(")])
check("wire.c.preview_lists_dups", '_out["duplicate_rows"] = ' in rt and 'not r.get("_dup_of")]' in rt)

print(f"static+behaviour: {passed} passed, {failed} failed")

r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch157.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL rail gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("rail: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
