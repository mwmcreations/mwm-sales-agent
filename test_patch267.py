"""PATCH #267 gate — (1) WhatsApp-first first touch with the SMS backstop,
(2) the cold-lead Custom Audience fed daily, (3) a visit moved by hand reaches
the sheet. Pure rules in first_touch.py / meta_audience.py; app wiring checked
statically. Then the #266 gate (→ 265 → slots → 263 → …)."""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import first_touch as ft          # noqa: E402
import meta_audience as ma        # noqa: E402
import lead_form as lf            # noqa: E402
import wa_templates as wt         # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


TZ = pytz.timezone("America/New_York")
NOW = TZ.localize(datetime(2026, 11, 4, 9, 30))
SL = [{"id": "2026-11-09T10:00:00-05:00", "display": "Monday, November 09 at 10:00 AM EST"},
      {"id": "2026-11-10T15:00:00-05:00", "display": "Tuesday, November 10 at 03:00 PM EST"}]

# ── first_touch: params ─────────────────────────────────────────────────────
check("ft.params", ft.wa_params("Patricio TG", "Southlife", SL)
      == ["Patricio", "Southlife", "1) Mon Nov 9 at 10:00 AM 2) Tue Nov 10 at 3:00 PM"], ft.wa_params("Patricio TG", "Southlife", SL))
check("ft.params_fallbacks", ft.wa_params("", "", []) == ["there", "your business",
                                                         "1) this week 2) next week - just tell me the day that suits you"])
check("ft.params_one_slot", ft.wa_params("Dana Katz", "Katz Law", SL[:1])[2] == "1) Mon Nov 9 at 10:00 AM")
check("ft.first_name", ft.first_name("Dr. Lynda Barnes") == "Dr" or ft.first_name("Lynda Barnes") == "Lynda")
check("ft.name_unknown", ft.first_name("Unknown") == "there")
check("ft.no_empty_param", all(p for p in ft.wa_params(None, None, None)))

# ── first_touch: the plan ───────────────────────────────────────────────────
base = lf.first_touch_plan("yes", True, True, True)
check("lf.base_unchanged", [c for c, _ in base] == ["sms", "email"], base)
p = ft.plan(base, True, True, True)
check("ft.plan_wa_first", [c for c, _ in p] == ["whatsapp", "email"], p)
check("ft.plan_no_template", ft.plan(base, True, True, False) == base)
check("ft.plan_no_consent", ft.plan(base, True, False, True) == base)
check("ft.plan_not_dialable", ft.plan(lf.first_touch_plan("yes", True, False, True), False, True, True)
      == lf.first_touch_plan("yes", True, False, True))
check("ft.plan_email_only", [c for c, _ in ft.plan(lf.first_touch_plan("yes", False, False, True), False, False, True)] == ["email"])

# ── first_touch: the SMS that waits on WhatsApp ────────────────────────────
pend = ft.sms_pending_after_wa("core text", NOW, "wamid.1")
check("ft.pending_shape", pend["reason"] == "wa_wait" and pend["wamid"] == "wamid.1" and pend["core"] == "core text"
      and datetime.fromisoformat(pend["not_before"]) == NOW + timedelta(minutes=30))
check("ft.due_wait", ft.sms_due(pend, "sent", NOW + timedelta(minutes=10))[0] == "wait")
check("ft.due_wait_unknown", ft.sms_due(pend, None, NOW + timedelta(minutes=29))[0] == "wait")
check("ft.due_send_30", ft.sms_due(pend, "sent", NOW + timedelta(minutes=30))[0] == "send")
check("ft.due_drop_delivered", ft.sms_due(pend, "delivered", NOW + timedelta(minutes=5)) == ("drop", "whatsapp delivered"))
check("ft.due_drop_read", ft.sms_due(pend, "read", NOW + timedelta(minutes=60))[0] == "drop")
check("ft.due_send_failed", ft.sms_due(pend, "failed", NOW + timedelta(minutes=1))[0] == "send")
check("ft.due_old_pending", ft.sms_due({"since": NOW.isoformat(), "core": "x", "reason": "quiet_hours"}, None, NOW)[0] == "send")
check("ft.due_not_dict", ft.sms_due(None, None, NOW)[0] == "send")

rec = {"first_touch_wa": {"wamid": "wamid.1", "status": "sent"}}
check("ft.note_other_wamid", ft.note_status(rec, "wamid.2", "delivered", NOW) is False and rec["first_touch_wa"]["status"] == "sent")
check("ft.note_delivered", ft.note_status(rec, "wamid.1", "delivered", NOW) is True and rec["first_touch_wa"]["status"] == "delivered"
      and rec["first_touch_wa"]["delivered_at"] == NOW.isoformat())
check("ft.note_late_sent_ignored", ft.note_status(rec, "wamid.1", "sent", NOW) is True and rec["first_touch_wa"]["status"] == "delivered")
check("ft.note_failed_wins", ft.note_status(rec, "wamid.1", "failed", NOW) and rec["first_touch_wa"]["status"] == "failed")
check("ft.note_no_record", ft.note_status({}, "wamid.1", "delivered", NOW) is False)
check("ft.wamid", ft.wamid_from_response({"messages": [{"id": "wamid.HBg"}]}) == "wamid.HBg" and ft.wamid_from_response(None) == "")

wp = ft.wa_pending(["Patricio", "Southlife", "1) x"], "core", NOW)
check("ft.wa_pending", wp["params"][0] == "Patricio" and wp["core"] == "core")
check("ft.wa_pending_expiry", not ft.wa_pending_expired(wp, NOW + timedelta(hours=13)) and ft.wa_pending_expired(wp, NOW + timedelta(hours=15)))
check("ft.window", ft.in_window(TZ.localize(datetime(2026, 11, 4, 8, 0)), 8, 21) and not ft.in_window(TZ.localize(datetime(2026, 11, 4, 7, 59)), 8, 21)
      and not ft.in_window(TZ.localize(datetime(2026, 11, 4, 21, 0)), 8, 21))
s = ft.summary({"a": {"first_touch_wa_pending": wp}, "b": {"first_touch_sms_pending": pend, "first_touch_wa": {"wamid": "w", "status": "read"}},
                "c": {"first_touch_wa": {"wamid": "w2", "status": "sent"}}, "d": "junk"})
check("ft.summary", s == {"template": "mwm_form_reply_times", "wa_pending_window": 1, "sms_waiting_on_wa": 1, "wa_sent": 2, "wa_delivered": 1}, s)

# ── the template is judged by Meta's listing, not the rail's fixed set ─────
check("wt.rail_set_untouched", set(wt.TEMPLATES) == {"mwm_visit_confirm", "mwm_visit_today", "mwm_visit_rebook", "mwm_visit_reschedule"})
check("wt.rail_untouched", wt.STAGE_TEMPLATE == {24: "mwm_visit_confirm", 2: "mwm_visit_today"} and wt.REBOOK_TEMPLATE == "mwm_visit_reschedule")
check("ft.template_name", ft.WA_TEMPLATE == "mwm_form_reply_times" and ft.WA_LANG == "en_US")

# ── meta_audience: hashing ──────────────────────────────────────────────────
check("ma.phone_norm", ma.normalize_phone("+1 (702) 351-1773") == "17023511773" and ma.normalize_phone("7023511773") == "17023511773"
      and ma.normalize_phone("12") == "")
check("ma.email_norm", ma.normalize_email("  Pato@AlgoMas.com ") == "pato@algomas.com" and ma.normalize_email("nope") == "")
r = ma.row("+17023511773", "Pato@algomasonline.com")
check("ma.row", r == [ma.sha256("17023511773"), ma.sha256("pato@algomasonline.com")] and len(r[0]) == 64)
check("ma.row_phone_only", ma.row("+17023511773", "")[1] == "" and ma.row("", "") is None)
check("ma.payload", ma.payload([r]) == {"schema": ["PHONE_SHA256", "EMAIL_SHA256"], "data": [r]})
check("ma.batches", [len(b) for b in ma.batches([[1, 2]] * 1201)] == [500, 500, 201])

# ── meta_audience: who belongs ──────────────────────────────────────────────
old = (NOW - timedelta(days=20)).isoformat()
fresh = (NOW - timedelta(days=3)).isoformat()
check("ma.cold_stage", ma.decide({"phone": "+17025550100", "lead_temperature": "Cold", "created_at": fresh}, NOW, tz=TZ) == ("add", "cold"))
check("ma.cold_status_string", ma.decide({"phone": "+17025550100", "whatsapp_status": "Cold - Queued for Agent Maya + Retargeting", "created_at": fresh}, NOW, tz=TZ)[0] == "add")
check("ma.quiet_14d", ma.decide({"phone": "+17025550100", "created_at": old, "last_message_time": old}, NOW, tz=TZ)[0] == "add")
check("ma.active_recent", ma.decide({"phone": "+17025550100", "created_at": old, "last_message_time": fresh}, NOW, tz=TZ)[0] == "skip")
check("ma.booked_skip", ma.decide({"phone": "+17025550100", "created_at": old, "booked": True, "event_id": "e1"}, NOW, is_booked=True, tz=TZ) == ("skip", "booked"))
check("ma.booked_remove_if_synced", ma.decide({"phone": "+17025550100", "created_at": old, "booked": True, "event_id": "e1", "meta_audience_synced_at": old}, NOW, is_booked=True, tz=TZ) == ("remove", "booked"))
check("ma.client", ma.decide({"phone": "+17025550100", "created_at": old, "meta_audience_synced_at": old}, NOW, is_client=True, tz=TZ) == ("remove", "client"))
check("ma.dnc", ma.decide({"phone": "+17025550100", "created_at": old, "do_not_contact": True}, NOW, tz=TZ) == ("skip", "do not contact"))
check("ma.no_contact", ma.decide({"created_at": old, "lead_temperature": "Cold"}, NOW, tz=TZ) == ("skip", "no phone or email"))
check("ma.internal", ma.decide({"phone": "+18135031224", "test_lead": True, "created_at": old}, NOW, tz=TZ) == ("skip", "internal"))
check("ma.no_dates", ma.decide({"phone": "+17025550100"}, NOW, tz=TZ) == ("skip", "no dates on the record"))
check("ma.naive_dates_ok", ma.decide({"phone": "+17025550100", "created_at": "2026-10-01T10:00:00"}, NOW, tz=TZ)[0] == "add")

leads = {
    "whatsapp:+17025550101": {"phone": "+17025550101", "email": "a@x.com", "lead_temperature": "Cold", "created_at": old},
    "whatsapp:+17025550102": {"phone": "+17025550102", "created_at": old, "last_message_time": old},
    "whatsapp:+17025550103": {"phone": "+17025550103", "created_at": old, "last_message_time": old, "meta_audience_synced_at": old},
    "whatsapp:+17025550104": {"phone": "+17025550104", "created_at": old, "booked": True, "event_id": "e", "meta_audience_synced_at": old},
    "whatsapp:+17025550105": {"phone": "+17025550105", "created_at": fresh, "last_message_time": fresh},
    "client": {"phone": "+17025550106", "created_at": old, "paid_at": old},
    "junk": "not a record",
}
pl = ma.plan(leads, NOW, is_client=lambda k, r: k == "client", is_booked=lambda r: bool(r.get("booked")), tz=TZ)
check("ma.plan_add", sorted(k for k, _, _ in pl["add"]) == ["whatsapp:+17025550101", "whatsapp:+17025550102"], pl["add"])
check("ma.plan_remove", [k for k, _, _ in pl["remove"]] == ["whatsapp:+17025550104"], pl["remove"])
check("ma.plan_skipped", pl["skipped"].get("already synced") == 1 and pl["skipped"].get("active") == 1
      and pl["skipped"].get("client") == 1 and pl["skipped"].get("not a record") == 1, pl["skipped"])
pl2 = ma.plan(leads, NOW, is_client=lambda k, r: k == "client", is_booked=lambda r: bool(r.get("booked")), tz=TZ, force_all=True)
check("ma.plan_force_all", len(pl2["add"]) == 3)
rr = ma.stamp({"x": 1}, NOW)
check("ma.stamp", rr["meta_audience_synced_at"] == NOW.isoformat() and "meta_audience_removed_at" not in ma.stamp(rr, NOW))
check("ma.stamp_removed", ma.stamp({}, NOW, removed=True)["meta_audience_removed_at"] == NOW.isoformat())
check("ma.due_today", ma.due_today("", TZ.localize(datetime(2026, 11, 4, 7, 5))) and not ma.due_today("2026-11-04", TZ.localize(datetime(2026, 11, 4, 9, 0)))
      and not ma.due_today("2026-11-03", TZ.localize(datetime(2026, 11, 4, 6, 59))) and ma.due_today("2026-11-03", TZ.localize(datetime(2026, 11, 4, 18, 0))))

# ── app wiring (static) ─────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.imports", "import first_touch as _ft1" in SRC and "import meta_audience as _ma" in SRC)
check("app.intake_plan", "plan = _ftm.plan(plan, dialable, consent, bool(_ftr and _ftr()))" in SRC
      and 'if chan == "whatsapp":' in SRC and "_first_touch_wa_send(lr, sender_key, e164, name, rec[\"business\"], slots, _wcore, now)" in SRC)
check("app.wa_ready_rule", 'return _ft1.WA_TEMPLATE in (_WA_VISIT_TPL.get("approved_utility") or set())' in SRC
      and 'FIRST_TOUCH_WHATSAPP = os.getenv("FIRST_TOUCH_WHATSAPP", "1")' in SRC
      and '_WA_VISIT_TPL["approved_utility"] = {' in SRC and 'and str((r or {}).get("category") or "").upper() == "UTILITY"}' in SRC)
fire = SRC[SRC.index("def _first_touch_wa_fire("):SRC.index("def _first_touch_wa_send(")]
check("app.fire_sends_template", "send_wa_utility_template(e164, _ft1.WA_TEMPLATE, params, lang=_ft1.WA_LANG)" in fire)
check("app.fire_arms_sms", 'lr["first_touch_sms_pending"] = _ft1.sms_pending_after_wa(core, now, wamid)' in fire)
check("app.fire_falls_back", "res = _send_sms(e164, _sms_copy.compose(core), kind=SMS_KIND_TRANSACTIONAL) or {}" in fire
      and "fell back to sms (queued" in fire)
send = SRC[SRC.index("def _first_touch_wa_send("):SRC.index("def _first_touch_status(")]
check("app.send_holds_quiet", "if not _ft1.in_window(now, SMS_TXN_QUIET_START_H, SMS_TXN_QUIET_END_H):" in send
      and 'lr["first_touch_wa_pending"] = _ft1.wa_pending(params, core, now)' in send)
cp = SRC[SRC.index("def _chase_pass(now=None):"):SRC.index("def _chase_pass(now=None):") + 6000]
check("app.chase_wa_pending", 'wpend = rec.get("first_touch_wa_pending")' in cp and "_first_touch_wa_fire(rec, key, _we164, wpend[\"params\"], wpend.get(\"core\") or \"\", now)" in cp
      and "_ftm.wa_pending_expired(wpend, now)" in cp and '_ftm = globals().get("_ft1")' in cp)
check("app.chase_sms_waits", "_due, _dwhy = (_ftm.sms_due(pend, (rec.get(\"first_touch_wa\") or {}).get(\"status\"), now)" in cp
      and 'elif _due == "wait":' in cp and 'or _due == "drop":' in cp)
st = SRC[SRC.index("def _handle_wa_statuses(value):"):SRC.index("def _handle_wa_statuses(value):") + 3000]
check("app.status_noted", '_ftk = f"whatsapp:+{recipient}" if recipient else ""' in st and "_ftm.note_status(" in st)
cf = SRC[SRC.index('how="confirmed_by_hand"'):SRC.index('how="confirmed_by_hand"') + 2000]
check("app.confirm_sheet", 'update_lead_columns(key, {"Status": booking_status_for("studio_visit"),' in cf
      and 'old_stage="Rescheduling", new_stage="Booked"' in cf and 'plan["booked_display"] = _cw' in cf)
check("app.health", '"first_touch": _first_touch_status(),' in SRC and '"cold_audience": _cold_audience_status(),' in SRC)
cs = SRC[SRC.index("def _cold_audience_sync("):SRC.index("def _cold_audience_status(")]
check("app.sync_plan", "pl = _ma.plan(lead_data, now, is_client=lambda k, r: _chase_is_client(k)," in cs and "is_booked=_chase_booked" in cs)
check("app.sync_dry_default", "if not apply:\n        return out" in cs and 'out["errors"].append("META_COLD_AUDIENCE_ID not set")' in cs)
check("app.sync_batches", "_em.audience_users(aud, rows, _ma.SCHEMA, remove=(verb == \"remove\"))" in cs
      and "_ma.stamp(rec, now, removed=(verb == \"remove\"))" in cs)
check("app.sync_tells_eric", "S3b AUTO (daily): cold-lead audience sync" in cs and "SLACK_ERIC_CHANNEL" in cs)
check("app.loop", 'threading.Thread(target=_cold_audience_loop, daemon=True, name="cold_audience_sync").start()' in SRC
      and '_THREAD_STALE_OVERRIDES["cold_audience_sync"] = 30' in SRC and "time.sleep(600)" in SRC[SRC.index("def _cold_audience_loop"):SRC.index("def _cold_audience_loop") + 800])
check("app.route", "@app.route('/admin/cold-audience-sync', methods=['GET', 'POST'])" in SRC)
check("app.block_before_chase", SRC.index("def _first_touch_wa_fire(") < SRC.index("def _chase_pass(now=None):"))

# ── eric_meta ───────────────────────────────────────────────────────────────
EM = open(os.path.join(HERE, "eric_meta.py"), encoding="utf-8").read()
check("em.json_payload", '{"payload": json.dumps({"schema": ["PHONE_SHA256"], "data": [[hashed]]})}' in EM and "\nimport json\n" in EM)
check("em.audience_users", "def audience_users(audience_id, rows, schema, remove=False):" in EM
      and 'return _meta_delete(f"{audience_id}/users", body)' in EM and "def _meta_delete(" in EM)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch266.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #266 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("266: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE267 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
