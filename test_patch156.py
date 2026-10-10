"""PATCH #156 gate — CALL NOW (speed to a human) + the re-engagement counts.

ERIC, 9 Oct 23:45 ET, items 1 and 3. Proves: the CALL NOW text carries name,
business, revenue band, role, the must-understand answer and the number, as
words (never a raw choice value); the 8 AM-8 PM ET window; an overnight
lead is queued and due at 8:00; the queue is capped; the intake fires the
alert for every verdict with a phone and never for Michael's own line; the
flush rides the chase loop; /health shows it. Re-engagement: a client, a
no, a disqualified lead, internal and test records are not candidates;
email / SMS / WhatsApp-window / Orlando flags; the summary adds up; the
count route is wired and read-only. Prints "N passed, M failed", then runs
the #155 gate (which chains #154 → … → #143).
"""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import call_now as cn      # noqa: E402
import reengage as rg      # noqa: E402
import lead_form as lf     # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


ET = pytz.timezone("America/New_York")

# ── the text ─────────────────────────────────────────────────────────────────
sms, eric = cn.compose("Duncan Wardle", "iD8", "+19293036598", "under_$20k", "owner_/_founder_/_partner",
                       "we can talk this", "studio-hour", ad_label="AD_15 | The room or the brain", pretty=lf.pretty)
check("sms.call_now", sms.startswith("CALL NOW - form lead (studio-hour)"), sms)
check("sms.name_business", "Duncan Wardle - iD8" in sms)
check("sms.band_words", "under $20k / owner / founder / partner" in sms, sms)
check("sms.no_raw", "_/_" not in sms and "under_$" not in sms)
check("sms.must", "Must understand: we can talk this" in sms)
check("sms.phone", "+19293036598" in sms)
check("sms.ad", "ad AD_15 | The room or the brain" in sms)
check("sms.rule", "First call inside the hour." in sms)
check("sms.short", len(sms) <= 400, len(sms))
check("eric.line", eric.startswith(":telephone_receiver: *CALL NOW — form lead* (studio-hour) · *Duncan Wardle* · iD8")
      and "`+19293036598`" in eric and "first call inside the hour" in eric, eric)
sms2, _ = cn.compose("", "", "4075551234", "", "", "", "no")
check("sms.minimal", sms2.startswith("CALL NOW - form lead (no)\nno name\n4075551234"), sms2)
long = cn.compose("x" * 200, "y" * 200, "z" * 50, "r" * 50, "q" * 50, "m" * 500, "yes")[0]
check("sms.capped_fields", len(long) < 520, len(long))

# ── the window ───────────────────────────────────────────────────────────────
for h, ok in ((7, False), (8, True), (12, True), (19, True), (20, False), (23, False), (0, False)):
    check(f"window.{h:02d}h", cn.in_window(ET.localize(datetime(2026, 10, 10, h, 30))) is ok)
n = ET.localize(datetime(2026, 10, 9, 23, 45))
check("next.tonight", cn.next_window_open(n) == ET.localize(datetime(2026, 10, 10, 8, 0)))
n2 = ET.localize(datetime(2026, 10, 10, 6, 10))
check("next.early_morning", cn.next_window_open(n2) == ET.localize(datetime(2026, 10, 10, 8, 0)))
check("note", cn.queued_note(n) == "text to Michael queued for 8 AM ET", cn.queued_note(n))

# ── the queue ────────────────────────────────────────────────────────────────
q = cn.enqueue([], "s1", "e1", "whatsapp:+1", n)
q = cn.enqueue(q, "s2", "e2", "whatsapp:+2", n)
check("queue.two", len(q) == 2 and q[0]["sms"] == "s1" and q[1]["lead_key"] == "whatsapp:+2" and q[0]["queued_at"] == n.isoformat())
to_send, rem = cn.due(q, ET.localize(datetime(2026, 10, 10, 7, 59)))
check("queue.not_yet", to_send == [] and len(rem) == 2)
to_send, rem = cn.due(q, ET.localize(datetime(2026, 10, 10, 8, 1)))
check("queue.due_at_8", len(to_send) == 2 and rem == [])
big = []
for i in range(60):
    big = cn.enqueue(big, f"s{i}", "e", "k", n)
check("queue.capped", len(big) == cn.MAX_QUEUE and big[-1]["sms"] == "s59")
check("queue.empty", cn.due([], ET.localize(datetime(2026, 10, 10, 9, 0))) == ([], []))

# ── re-engagement classification ─────────────────────────────────────────────
now = ET.localize(datetime(2026, 10, 10, 0, 0))
sup = lambda a: (a in ("dnc@x.com",) or a.endswith("@mwmcreations.com"), "")
internal = lambda d: d.endswith("8135031224")
base = {"name": "Ana", "email": "ana@x.com", "last_message_time": now - timedelta(days=20)}
r = rg.classify("whatsapp:+14075551234", base, now, consent={"status": "yes", "marketing": True},
                email_suppressed=sup, is_internal=internal)
check("rg.candidate", r and r["email"] and r["sms"] and r["orlando"] and not r["wa_open"] and not r["active_7d"] and r["reachable"], r)
r = rg.classify("whatsapp:+13215550000", dict(base, last_message_time=now - timedelta(hours=3)), now,
                consent={"status": "yes", "transactional": True}, email_suppressed=sup, is_internal=internal)
check("rg.wa_open_active_sms_without_marketing_flag_counts", r["wa_open"] and r["active_7d"] and r["sms"] and r["orlando"], r)
r = rg.classify("whatsapp:+13215550001", base, now, consent={"status": "yes", "marketing": False}, email_suppressed=sup, is_internal=internal)
check("rg.marketing_false_no_sms", r["sms"] is False and r["email"] is True)
r = rg.classify("whatsapp:+13525550000", dict(base, email="dnc@x.com"), now, consent={}, email_suppressed=sup, is_internal=internal)
check("rg.dnc_email_and_no_consent", r["email"] is False and r["sms"] is False and r["central_fl"] and not r["reachable"])
check("rg.client_out", rg.classify("whatsapp:+14075550002", dict(base, relationship="client"), now) is None)
check("rg.paid_out", rg.classify("whatsapp:+14075550003", dict(base, paid_at="2026-09-01"), now) is None)
check("rg.no_out", rg.classify("whatsapp:+14075550004", dict(base, outcome="not_interested"), now) is None)
check("rg.disqualified_out", rg.classify("whatsapp:+14075550005", dict(base, disqualified={"reason": "x"}), now) is None)
check("rg.dnc_out", rg.classify("whatsapp:+14075550006", dict(base, do_not_contact=True), now) is None)
check("rg.internal_out", rg.classify("whatsapp:+18135031224", base, now, is_internal=internal) is None)
check("rg.test_out", rg.classify("meta_lead_1", dict(base, name="<test lead: dummy"), now) is None
      and rg.classify("whatsapp:+14075550007", dict(base, test_lead=True), now) is None)
r = rg.classify("instagram:1234567890123456", {"name": "IG", "email": "", "last_message_time": now - timedelta(hours=1)}, now)
check("rg.ig_no_phone", r and not r["has_phone"] and not r["sms"] and not r["email"] and not r["wa_open"] and r["channel"] == "instagram" and r["active_7d"])
r = rg.classify("whatsapp:+14075550008", {"name": "Str", "email": "s@x.com", "last_message_time": "2026-10-01T10:00:00-04:00"}, now, email_suppressed=sup)
check("rg.iso_string_time", r and r["email"] and r["active_7d"] is False)
rows = [rg.classify("whatsapp:+14075551234", base, now, consent={"status": "yes"}, email_suppressed=sup),
        rg.classify("whatsapp:+13215550001", base, now, consent={"status": "yes", "marketing": False}, email_suppressed=sup),
        rg.classify("whatsapp:+13525550000", dict(base, email="dnc@x.com"), now, consent={}, email_suppressed=sup),
        None]
s = rg.summarize(rows)
check("rg.summary", s["candidates"] == 3 and s["with_email"] == 2 and s["with_sms_consent"] == 1 and s["orlando_area"] == 2
      and s["central_fl_outside_orlando"] == 1 and s["email_or_sms"] == 2 and s["both"] == 1 and s["email_only"] == 1
      and s["sms_only"] == 0 and s["with_phone_no_consent"] == 2 and s["by_channel"] == {"whatsapp": 3}, s)

# ── wiring (static) ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("wire.imports", "import call_now as _cn" in SRC and "import reengage as _rg" in SRC)
i = SRC.index("def _meta_lead_intake(")
blk = SRC[i:i + 30000]
check("wire.hook_before_first_touch", "call_now_note = _call_now_alert(sender_key, name, rec, verdict, label, _cn_phone, now)" in blk
      and blk.index("_call_now_alert(sender_key") < blk.index("# ── first touch ──"))
check("wire.hook_after_record", blk.index("lr.update(upd)") < blk.index("_call_now_alert(sender_key"))
check("wire.internal_skipped", 'call_now_note = "skipped (internal number)"' in blk)
check("wire.room_line", "CALL NOW to Michael: {call_now_note}" in blk)
fn = SRC[SRC.index("def _call_now_alert("):SRC.index("def _call_now_flush(")]
check("wire.alert_kind_lead", '_operator_alert.alert("lead", sms, eric_text=eric)' in fn and "pretty=_lf.pretty" in fn)
check("wire.alert_queues_outside_window", "if _cn.in_window(now):" in fn and "_cn.enqueue(" in fn and "_cn.queued_note(now)" in fn
      and "_post_to_slack_async(SLACK_ERIC_CHANNEL" in fn)
fl = SRC[SRC.index("def _call_now_flush("):SRC.index("# ── PATCH #111 — know who already pays us")]
check("wire.flush_due", "_cn.due(q, now)" in fl and "_call_now_queue_put(remaining)" in fl)
check("wire.flush_in_chase_loop", "_call_now_flush()             # PATCH #156" in SRC
      and SRC.index("_call_now_flush()             # PATCH #156") < SRC.index("counts = _chase_pass()"))
check("wire.health", '"call_now": {**_CALL_NOW_LAST' in SRC)
check("wire.never_a_lead_number", "operator_phone" not in fn and "_send_sms(" not in fn, "only operator_alert may text")
check("wire.count_route", "@app.route('/admin/reengage-oct12', methods=['GET'])" in SRC)
_rt_start = SRC.index("def _reengage_rows(now):") if "def _reengage_rows(now):" in SRC else SRC.index("def admin_reengage_oct12():")
rt = SRC[_rt_start:SRC.index("@app.route('/admin/lead-form-repair'")]
check("wire.count_secret", '_admin_secret_ok(request.args.get("secret"))' in rt)
_cnt = rt[rt.index("if _mode == \"count\":"):rt.index("if _mode == \"preview\":")] if "if _mode == \"count\":" in rt else rt
check("wire.count_readonly", "lead_data[" not in _cnt and "upsert" not in _cnt and "_email_send" not in _cnt and "_send_sms" not in _cnt)
check("wire.count_uses_module", ("_rg.classify(_k, _r, _now, consent=_consent, email_suppressed=email_is_suppressed" in rt
                                  or "_rg.classify(_k, _r, now, consent=_consent, email_suppressed=_sup" in rt)
      and "_rg.summarize(_rows)" in rt)
check("wire.count_masks", "mask_contact(r[\"key\"])" in rt)
check("wire.count_one_query", '_pgc.load_prefix("sms_consent:")' in rt and "_sms_consent_get(" not in rt, "350 consent reads must be one query (#156b)")
import pg_store as pgs
check("pg.load_prefix_exists", callable(getattr(pgs, "load_prefix", None)) and pgs.load_prefix("") == {})

print(f"static+behaviour: {passed} passed, {failed} failed")

r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch155.py")], capture_output=True, text=True)
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
