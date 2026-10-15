"""PATCH #251 gate — the five CRM lead stages back to Meta's Conversions API
(Lead / Qualified / StudioVisitBooked / StudioVisitCompleted / Converted),
keyed "<lead_key>:<Stage>", sent once (pg ledger), lead_id on every form lead,
hashed email/phone otherwise, the 7-day event_time rule, the backfill plan and
its admin route. Pure module first, then the sender lifted out of app.py with
pg and the wire stubbed, then the static wiring. Then runs the #250 gate
(→ 248 → 247 → …)."""
import ast
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import meta_capi as mc            # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


NOW = int(datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc).timestamp())

# ── 1 · stages, ids, time ───────────────────────────────────────────────────
check("stages.five", mc.STAGES == ("Lead", "Qualified", "StudioVisitBooked", "StudioVisitCompleted", "Converted"))
check("stages.order", mc.STAGE_ORDER["Lead"] < mc.STAGE_ORDER["Qualified"] < mc.STAGE_ORDER["StudioVisitBooked"]
      < mc.STAGE_ORDER["StudioVisitCompleted"] < mc.STAGE_ORDER["Converted"])
check("ids.event_id", mc.event_id_for("whatsapp:+14075551234", "StudioVisitBooked") == "whatsapp:+14075551234:StudioVisitBooked")
check("ids.ledger_key", mc.ledger_key("meta_lead_1", "Lead") == "capi_sent:meta_lead_1:Lead")
check("ids.parse_colon_key", mc.parse_event_id("whatsapp:+14075551234:StudioVisitBooked") == ("whatsapp:+14075551234", "StudioVisitBooked"))
check("ids.parse_plain_key", mc.parse_event_id("meta_lead_123:Lead") == ("meta_lead_123", "Lead"))
check("ids.parse_legacy", mc.parse_event_id("lead-123") == (None, None) and mc.parse_event_id("purchase-cs_1") == (None, None))
check("ids.parse_unknown_stage", mc.parse_event_id("x:Purchase") == (None, None) and mc.parse_event_id("") == (None, None))

check("time.epoch_passthrough", mc.to_epoch(1792000000) == 1792000000 and mc.to_epoch("1792000000") == 1792000000)
check("time.iso_aware", mc.to_epoch("2026-10-15T09:00:00-04:00") == int(datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc).timestamp()))
check("time.datetime_aware", mc.to_epoch(datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)) == NOW)
check("time.naive_is_utc", mc.to_epoch(datetime(2026, 10, 15, 13, 0)) == NOW)
check("time.garbage", mc.to_epoch("yesterday") is None and mc.to_epoch(None) is None and mc.to_epoch("") is None)
check("clamp.recent_kept", mc.clamp_time(NOW - 3600, NOW) == (NOW - 3600, False))
check("clamp.six_days_kept", mc.clamp_time(NOW - 6 * 86400, NOW) == (NOW - 6 * 86400, False))
check("clamp.eight_days_clamped", mc.clamp_time(NOW - 8 * 86400, NOW) == (NOW, True))
check("clamp.future_clamped", mc.clamp_time(NOW + 600, NOW) == (NOW, True))
check("clamp.none_is_now", mc.clamp_time(None, NOW) == (NOW, False))

# ── 2 · the stage event ─────────────────────────────────────────────────────
ev = mc.stage_event(mc.STAGE_LEAD, "meta_lead_4593113990973865", name="Ana Souza", email="Ana@Example.com ",
                    phone="(407) 555-1234", lead_id="4593113990973865", stage_time=NOW - 60, now=NOW,
                    extra={"ad_id": "9", "qualified": "yes", "content_name": "Smile", "empty": ""})
check("ev.name_time_source", ev["event_name"] == "Lead" and ev["event_time"] == NOW - 60 and ev["action_source"] == "system_generated")
check("ev.event_id", ev["event_id"] == "meta_lead_4593113990973865:Lead")
check("ev.lead_id_int", ev["user_data"]["lead_id"] == 4593113990973865)
check("ev.hashed_fallbacks", ev["user_data"]["em"] == [mc._sha("ana@example.com")] and ev["user_data"]["ph"] == [mc._sha("14075551234")]
      and ev["user_data"]["fn"] == [mc._sha("ana")] and ev["user_data"]["ln"] == [mc._sha("souza")])
check("ev.custom_base", ev["custom_data"]["event_source"] == "crm" and ev["custom_data"]["lead_event_source"] == "MWM Sales Machine"
      and ev["custom_data"]["stage"] == "Lead")
check("ev.custom_extra", ev["custom_data"]["ad_id"] == "9" and ev["custom_data"]["qualified"] == "yes" and "empty" not in ev["custom_data"])
check("ev.not_clamped", "stage_time_clamped" not in ev["custom_data"] and "stage_time" not in ev["custom_data"])
old = mc.stage_event(mc.STAGE_BOOKED, "whatsapp:+14075551234", phone="+14075551234", stage_time=NOW - 10 * 86400, now=NOW)
check("ev.old_clamped", old["event_time"] == NOW and old["custom_data"]["stage_time_clamped"] is True
      and old["custom_data"]["stage_time"] == datetime.fromtimestamp(NOW - 10 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
check("ev.no_lead_id_without_form", "lead_id" not in old["user_data"] and old["user_data"]["ph"] == [mc._sha("14075551234")])
try:
    mc.stage_event("Purchase", "k")
    check("ev.unknown_stage_raises", False)
except ValueError:
    check("ev.unknown_stage_raises", True)
for s in mc.STAGES:
    e = mc.stage_event(s, "k1", email="a@b.co", now=NOW)
    check(f"ev.{s}.custom_on_every_event", e["custom_data"]["event_source"] == "crm" and e["custom_data"]["lead_event_source"] == "MWM Sales Machine" and e["event_id"] == f"k1:{s}")

# ── 3 · what a record says happened ─────────────────────────────────────────
T0 = "2026-10-02T09:00:00-04:00"
rec_form = {"leadgen_id": "111", "qualified": "yes", "ad_id": "ad9", "business": "Smile", "lead_form_at": T0,
            "first_contact_time": datetime(2026, 10, 2, 9, 0, tzinfo=pytz.timezone("America/New_York"))}
st = mc.stages_from_record(rec_form)
check("rec.form_yes", [s for s, _, _ in st] == ["Lead", "Qualified"] and st[0][1] == T0 and st[0][2]["ad_id"] == "ad9" and st[0][2]["qualified"] == "yes")
check("rec.form_review", [s for s, _, _ in mc.stages_from_record(dict(rec_form, qualified="review"))] == ["Lead", "Qualified"])
check("rec.form_no", [s for s, _, _ in mc.stages_from_record(dict(rec_form, qualified="no"))] == ["Lead"])
check("rec.form_studio_hour_not_qualified", [s for s, _, _ in mc.stages_from_record(dict(rec_form, qualified="studio-hour"))] == ["Lead"])
check("rec.ig_lead_no_form_stages", mc.stages_from_record({"phone": "14075551234", "first_contact_time": T0}) == [])
booked = dict(rec_form, event_id="abc", booked_at="2026-10-05T10:00:00-04:00")
st = mc.stages_from_record(booked)
check("rec.booked_needs_event_id", [s for s, _, _ in st] == ["Lead", "Qualified", "StudioVisitBooked"] and st[2][1] == "2026-10-05T10:00:00-04:00")
check("rec.booked_flag_alone_is_not_a_booking", "StudioVisitBooked" not in [s for s, _, _ in mc.stages_from_record(dict(rec_form, booked=True))])
done = dict(booked, last_outcome="follow_up", last_outcome_at="2026-10-06T15:00:00-04:00")
check("rec.completed", [s for s, _, _ in mc.stages_from_record(done)][-1] == "StudioVisitCompleted"
      and mc.stages_from_record(done)[-1][2]["content_name"] == "follow_up")
check("rec.no_show_not_completed", "StudioVisitCompleted" not in [s for s, _, _ in mc.stages_from_record(dict(booked, last_outcome="no_show", last_outcome_at="x"))])
paid = dict(done, paid_at="2026-10-07T12:00:00-04:00", paid_value=1200, paid_product="Studio Subscription")
st = mc.stages_from_record(paid)
check("rec.converted_paid", st[-1][0] == "Converted" and st[-1][1] == "2026-10-07T12:00:00-04:00" and st[-1][2]["value"] == 1200.0
      and st[-1][2]["currency"] == "USD" and st[-1][2]["content_name"] == "Studio Subscription")
won = dict(done, won_at="2026-10-08T12:00:00-04:00", product="Studio Package")
check("rec.converted_won_no_value", mc.stages_from_record(won)[-1][0] == "Converted" and "value" not in mc.stages_from_record(won)[-1][2]
      and mc.stages_from_record(won)[-1][2]["content_name"] == "Studio Package")
check("rec.empty", mc.stages_from_record({}) == [] and mc.stages_from_record(None) == [])

# ── 4 · the backfill plan ───────────────────────────────────────────────────
LEADS = {
    "meta_lead_111": paid,                                                    # 5 stages, Oct 2
    "whatsapp:+14075550000": dict(rec_form, leadgen_id="222", qualified="no",
                                  lead_form_at="2026-09-20T09:00:00-04:00", first_contact_time="2026-09-20T09:00:00-04:00"),  # before since
    "whatsapp:+14075550001": {"phone": "14075550001", "event_id": "e1", "booked_at": "2026-10-10T10:00:00-04:00",
                              "first_contact_time": "2026-10-09T10:00:00-04:00"},   # IG lead, booked, no form
    "meta_lead_333": dict(rec_form, leadgen_id="333", test_lead=True),      # never
    "junk": "not a record",
}
sent = {("meta_lead_111", "Lead")}
plan = mc.backfill_plan(LEADS, lambda k, s: (k, s) in sent, since="2026-10-01T00:00:00-04:00", now=NOW)
check("plan.meta_only_since_ledger", [(p["lead_key"], p["stage"]) for p in plan] ==
      [("meta_lead_111", "Qualified"), ("meta_lead_111", "StudioVisitBooked"), ("meta_lead_111", "StudioVisitCompleted"), ("meta_lead_111", "Converted")],
      str([(p["lead_key"], p["stage"]) for p in plan]))
check("plan.rows_carry_identity", plan[0]["lead_id"] == "111" and plan[0]["extra"]["qualified"] == "yes" and plan[0]["stage_time"] == T0)
plan_all = mc.backfill_plan(LEADS, lambda k, s: False, since="2026-10-01T00:00:00-04:00", now=NOW, meta_only=False)
check("plan.all_includes_ig_booking", ("whatsapp:+14075550001", "StudioVisitBooked") in [(p["lead_key"], p["stage"]) for p in plan_all]
      and ("meta_lead_333", "Lead") not in [(p["lead_key"], p["stage"]) for p in plan_all])
check("plan.sorted_by_time_then_stage", [p["stage"] for p in plan_all if p["lead_key"] == "meta_lead_111"] ==
      ["Lead", "Qualified", "StudioVisitBooked", "StudioVisitCompleted", "Converted"])
check("plan.no_since", len(mc.backfill_plan(LEADS, lambda k, s: False, since=None, now=NOW)) == 6)   # 111 ×5 + 222 Lead
check("plan.empty", mc.backfill_plan({}, lambda k, s: False) == [] and mc.backfill_plan(None, lambda k, s: False) == [])

# ── 5 · the wire ────────────────────────────────────────────────────────────
posted = []
ok_, why = mc.send([ev], post=lambda u, j: (posted.append((u, j)) or (200, {"events_received": 1})), dataset_id="658880878344916", token="T", test_code="TEST9")
check("send.ok", ok_ and why == "received 1" and posted[0][0].endswith("/658880878344916/events") and posted[0][1]["test_event_code"] == "TEST9"
      and posted[0][1]["data"][0]["event_id"] == ev["event_id"])
check("send.counts_stage", mc.status()["by_stage"].get("Lead", 0) >= 1 and "Lead" in mc.status()["stages"])
check("send.dark", mc.send([ev], dataset_id="", token="")[1] == "unconfigured")
check("send.error_named", mc.send([ev], post=lambda u, j: (400, {"error": {"message": "Invalid parameter"}}), dataset_id="D", token="T", test_code="")[1].startswith("HTTP 400"))
check("send.exception_caught", mc.send([ev], post=lambda u, j: (_ for _ in ()).throw(RuntimeError("boom")), dataset_id="D", token="T", test_code="")[1].startswith("exception:"))
check("send.no_token_in_event", "access_token" not in ev and "access_token" in posted[0][1])

# ── 6 · the sender lifted out of app.py, pg + wire stubbed ──────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
want = {"_capi_stage", "_capi_ledger_has", "_capi_ledger_mark", "_capi_mask", "_capi_send_now", "_capi_send_async"}
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
check("lift.found", len(fns) == len(want), str(sorted(n.name for n in fns)))


class PG:
    def __init__(self): self.d = {}
    def load_state(self, k, default=None): return self.d.get(k, default)
    def save_state(self, k, v): self.d[k] = v; return True


class Tally:
    def __init__(self): self.calls = []
    def bump(self, *a): self.calls.append(a)


pg = PG()
slack = []
errors = []
lead_data = {}
G = dict(lead_data=lead_data, datetime=datetime, pytz=pytz, TIMEZONE="America/New_York", threading=__import__("threading"),
         _capi=mc, _pgs=pg, _TALLY=Tally(), SLACK_DEV_CHANNEL="#dev",
         _post_to_slack_async=lambda ch, text, **k: slack.append((ch, text)),
         _report_error=lambda ctx, exc, detail="": errors.append((ctx, str(exc), detail)))
exec(compile(ast.Module(body=fns, type_ignores=[]), "app_251", "exec"), G)

# dark: nothing marked, status says so
os.environ.pop("META_CAPI_DATASET_ID", None); os.environ.pop("META_CAPI_TOKEN", None)
lead_data["meta_lead_777"] = {"name": "Duncan Wardle", "email": "d@example.com", "phone": "14075559999", "leadgen_id": "777"}
st, why = G["_capi_stage"]("meta_lead_777", lead_data["meta_lead_777"], "Lead", stage_time=NOW, sync=True)
check("dark.skipped_unmarked", st == "skipped" and why == "unconfigured" and not pg.d and "capi_stages" not in lead_data["meta_lead_777"] and not slack)

# configured: sent once, ledger written, #dev told with lead_id only
os.environ["META_CAPI_DATASET_ID"] = "658880878344916"; os.environ["META_CAPI_TOKEN"] = "T"
real_send = mc.send
wire = []
mc.send = lambda events, **k: (wire.append(events) or (True, "received %d" % len(events)))
st, why = G["_capi_stage"]("meta_lead_777", lead_data["meta_lead_777"], "Lead", stage_time=NOW, sync=True)
check("live.sent", st == "sent" and why == "received 1" and wire[-1][0]["event_id"] == "meta_lead_777:Lead" and wire[-1][0]["user_data"]["lead_id"] == 777)
check("live.ledger_pg", pg.d.get("capi_sent:meta_lead_777:Lead", {}).get("event_time") == NOW)
check("live.ledger_record", lead_data["meta_lead_777"]["capi_stages"]["Lead"])
check("live.dev_line_no_pii", slack and slack[-1][0] == "#dev" and "lead_id 777" in slack[-1][1] and "Duncan" not in slack[-1][1]
      and "example.com" not in slack[-1][1] and "`Lead`" in slack[-1][1])
st, why = G["_capi_stage"]("meta_lead_777", lead_data["meta_lead_777"], "Lead", stage_time=NOW, sync=True)
check("live.second_send_skipped", st == "skipped" and why == "already sent" and len(wire) == 1)
# ledger survives a restart (record wiped, pg kept)
lead_data["meta_lead_777"].pop("capi_stages")
check("live.ledger_from_pg", G["_capi_ledger_has"]("meta_lead_777", "Lead") is True and G["_capi_ledger_has"]("meta_lead_777", "Qualified") is False)
# a Meta error: not marked, #dev warned, masked
mc.send = lambda events, **k: (False, "HTTP 400 Invalid parameter")
lead_data["whatsapp:+14075550123"] = {"name": "Ana", "phone": "14075550123"}
st, why = G["_capi_stage"]("whatsapp:+14075550123", lead_data["whatsapp:+14075550123"], "StudioVisitBooked", stage_time=NOW, sync=True)
check("fail.not_marked", st == "failed" and why.startswith("HTTP 400") and "capi_sent:whatsapp:+14075550123:StudioVisitBooked" not in pg.d)
check("fail.dev_warned_masked", slack[-1][1].startswith(":warning: capi `StudioVisitBooked`") and "+14075550123" not in slack[-1][1] and "…0123" in slack[-1][1])
# a lead without a form: hashed phone, no lead_id, #dev says so
mc.send = lambda events, **k: (wire.append(events) or (True, "received 1"))
st, why = G["_capi_stage"]("whatsapp:+14075550123", lead_data["whatsapp:+14075550123"], "StudioVisitBooked", stage_time=NOW, sync=True)
check("ig.hashed_only", st == "sent" and "lead_id" not in wire[-1][0]["user_data"] and wire[-1][0]["user_data"]["ph"] == [mc._sha("14075550123")]
      and "email/phone match" in slack[-1][1])
# guards
check("guard.test_lead", G["_capi_stage"]("k", {"test_lead": True, "leadgen_id": "1"}, "Lead", sync=True) == ("skipped", "test lead"))
check("guard.no_record", G["_capi_stage"]("k", None, "Lead", sync=True)[0] == "skipped" and G["_capi_stage"]("", {}, "Lead", sync=True)[0] == "skipped")
check("guard.unknown_stage", G["_capi_stage"]("k", {"phone": "1"}, "Purchase", sync=True)[0] == "skipped")
# async path hands the same event to the thread
st, why = G["_capi_stage"]("meta_lead_777", lead_data["meta_lead_777"], "Qualified", stage_time=NOW)
check("async.queued", st == "queued" and why == "meta_lead_777:Qualified")
time.sleep(0.3)
check("async.landed", any(e[0]["event_id"] == "meta_lead_777:Qualified" for e in wire) and "capi_sent:meta_lead_777:Qualified" in pg.d)
check("mask", G["_capi_mask"]("whatsapp:+14075550123") == "what…0123" and G["_capi_mask"]("meta_lead_5") == "meta_lead_5" and G["_capi_mask"]("") == "?")
mc.send = real_send
os.environ.pop("META_CAPI_DATASET_ID", None); os.environ.pop("META_CAPI_TOKEN", None)

# ── 7 · wiring in app.py ────────────────────────────────────────────────────
check("wire.form_lead_then_qualified", "_capi_stage(sender_key, lr, _capi.STAGE_LEAD, stage_time=now," in SRC
      and "if verdict in _capi.QUALIFIED_VERDICTS:" in SRC
      and SRC.index("_capi_stage(sender_key, lr, _capi.STAGE_LEAD") < SRC.index("_capi_stage(sender_key, lr, _capi.STAGE_QUALIFIED"))
check("wire.form_before_verdict_branches", SRC.index("_capi_stage(sender_key, lr, _capi.STAGE_LEAD") < SRC.index("if verdict == _lf.Q_NO:\n            _icp.mark_disqualified(lr"))
check("wire.old_lead_event_gone", "_capi.lead_event(" not in SRC and "_capi.schedule_event(" not in SRC and "_capi.purchase_event(" not in SRC)
check("wire.booked_maya_tool", "_capi_stage(sender, lead_data[sender], _capi.STAGE_BOOKED," in SRC)
check("wire.booked_web_chat", "_capi_stage(_wb_key, lead_data.get(_wb_key), _capi.STAGE_BOOKED," in SRC)
check("wire.booked_portal", SRC.count("_capi.STAGE_BOOKED, extra={\"content_name\": \"studio_visit\"}") == 2)
check("wire.completed_and_converted_from_report", "if outcome in _capi.VISIT_OUTCOMES:" in SRC
      and "_capi_stage(key, rec, _capi.STAGE_COMPLETED, stage_time=now, extra={\"content_name\": outcome})" in SRC
      and "_capi_stage(key, rec, _capi.STAGE_CONVERTED, stage_time=now," in SRC)
check("wire.converted_from_stripe", "_capi_stage(key, rec, _capi.STAGE_CONVERTED, stage_time=now, extra=_conv_extra)" in SRC
      and "f\"stripe:{obj.get('id') or ev.get('id')}\"" in SRC)
check("wire.health", '"capi": _capi.status()' in SRC)
check("wire.backfill_route", "@app.route('/admin/capi-backfill', methods=['GET'])" in SRC and "def admin_capi_backfill():" in SRC
      and 'dry = str(request.args.get("dry_run", "1")).strip() not in ("0", "false", "no")' in SRC
      and "_capi.backfill_plan(lead_data, _capi_ledger_has, since=since_e, meta_only=meta_only)" in SRC
      and "nothing sent, nothing marked" in SRC)
check("wire.backfill_admin_gated", SRC.index("def admin_capi_backfill():") < SRC.index('if not _admin_secret_ok(request.args.get("secret")):\n        return jsonify({"ok": False, "error": "unauthorized"}), 401\n    since = (request.args.get("since") or "2026-10-01").strip()'))
check("wire.sender_marks_only_on_ok", SRC.index("    if ok:\n        if key and stage:\n            _capi_ledger_mark(key, stage, event.get(\"event_time\"), why)") > SRC.index("def _capi_send_now(event):"))
check("wire.send_async_uses_send_now", "def _capi_send_async(event):" in SRC and SRC.index("_capi_send_now(event)\n        except Exception as _cx:") > SRC.index("def _capi_send_async(event):"))
check("wire.module_doc", "PATCH #251" in open(os.path.join(HERE, "meta_capi.py"), encoding="utf-8").read())

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch250.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #250 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("250: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE251 " + ("PASS" if not failed else "FAIL"))   # the watcher's expect string: only on a clean run
sys.exit(1 if failed else 0)
