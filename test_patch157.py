"""PATCH #157 gate — the booking rules (ERIC, 9 Oct 2026, item 2).

What Sessa actually received (6 Oct, from the sent log and Railway): three
WhatsApp TEMPLATE reminders (T-48, T-24, T-2 — the free-form sends were
prevented, his 24 h window was closed, and a template cannot ask for a YES
or carry the address), nothing same-day after the no-show (the rebook was
armed on WhatsApp with that closed window and died), one email two days
later. This gate proves the four rules: (a) Maya offers only slots inside
48 h, the two nearest as a flagged fallback; (b) T-24 asks "Reply YES …
with Michael tomorrow at {time}", a T-3 h watcher fires when nothing came
back; (c) T-2 carries the address and Michael's name, and when WhatsApp
only allowed a template the email with the real words goes beside it;
(d) no-show = same-day rebook with two slots inside 48 h on the lead's
channel (email at once when the window is closed), one more at 24 h, stop
at day 3. Prints "N passed, M failed", then runs test_event_rail and the
#156 gate (which chains #155 → … → #143).
"""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import slots as sl                    # noqa: E402
import event_rail as er               # noqa: E402
import outcome_sender as osd          # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


tz = pytz.timezone("America/New_York")
# Friday 9 Oct 2026, 09:00 ET
now = tz.localize(datetime(2026, 10, 9, 9, 0))


def busy(*ranges):
    rows = []
    for a, b in ranges:
        rows.append(sl.busy_row({"start": {"dateTime": a.isoformat()}, "end": {"dateTime": b.isoformat()},
                                 "summary": "x"}, tz))
    return [r for r in rows if r]


# ── (a) slots inside 48 h ────────────────────────────────────────────────────
free, fb = sl.offer_slots(now, [], tz)
check("slots.inside_48h", fb is False and len(free) == 3, (fb, free))
check("slots.chronological_today_first", free[0]["id"].startswith("2026-10-09T10:00") and free[1]["id"].startswith("2026-10-09T11:00")
      and free[2]["id"].startswith("2026-10-09T14:00"), [s["id"] for s in free])
# Friday evening: today is gone, Sat/Sun skipped, Monday 10 AM is 63 h away -> nothing inside 48 h -> fallback two nearest
fri_eve = tz.localize(datetime(2026, 10, 9, 18, 0))
near, fb = sl.offer_slots(fri_eve, [], tz)
check("slots.fallback_when_none", fb is True and len(near) == 2 and near[0]["id"].startswith("2026-10-12T10:00")
      and near[1]["id"].startswith("2026-10-13T15:00"), (fb, [s["id"] for s in near]))
# Thursday 09:00: today + Friday both inside 48 h; busy blocks skip
thu = tz.localize(datetime(2026, 10, 8, 9, 0))
b = busy((tz.localize(datetime(2026, 10, 8, 9, 30)), tz.localize(datetime(2026, 10, 8, 15, 30))))
w, fb = sl.offer_slots(thu, b, tz)
check("slots.busy_skipped", fb is False and [s["id"][:16] for s in w] == ["2026-10-08T15:00", "2026-10-09T10:00", "2026-10-09T11:00"]
      or [s["id"][:16] for s in w] == ["2026-10-09T10:00", "2026-10-09T11:00", "2026-10-09T14:00"], [s["id"] for s in w])
w2 = sl.compute_slots_window(thu, [], tz, within_hours=48, max_slots=10)
check("slots.window_bound", all(tz.localize(datetime.fromisoformat(s["id"]).replace(tzinfo=None)) <= thu + timedelta(hours=48) for s in w2)
      and len(w2) == 8, [s["id"] for s in w2])
cap, fb = sl.offer_slots(thu, [], tz, count_fn=lambda d: 9 if d == thu.date() else 0, max_per_day=4)
check("slots.capacity_day_skipped", fb is False and cap[0]["id"].startswith("2026-10-09"), [s["id"] for s in cap])
check("slots.never_past", all(datetime.fromisoformat(s["id"]) > now for s in free))
check("slots.weekend_skipped", all(datetime.fromisoformat(s["id"]).weekday() < 5 for s in near + free))
check("slots.constants", sl.WINDOW_HOURS_DEFAULT == 48 and sl.FALLBACK_SLOTS == 2 and sl.ALL_SLOT_TIMES == [(10, 0), (11, 0), (14, 0), (15, 0)])

# ── (d) reachability + the no-show plan ──────────────────────────────────────
check("reach.wa_closed_window_email", er._reachable(er.CH_WHATSAPP, True, 30) == er.CH_WEB)
check("reach.wa_open_window", er._reachable(er.CH_WHATSAPP, True, 3) == er.CH_WHATSAPP)
check("reach.wa_unknown_window", er._reachable(er.CH_WHATSAPP, True, None) == er.CH_WHATSAPP)
check("reach.wa_closed_no_email", er._reachable(er.CH_WHATSAPP, False, 30) == er.CH_WHATSAPP)
p = er.outcome_plan("no_show", er.CH_WHATSAPP, True, 2)
check("plan.steps", [(h, c, k) for h, c, k in p["steps"]] == [(0, er.CH_WHATSAPP, er.STEP_REBOOK), (24, er.CH_WEB, er.STEP_REBOOK)], p["steps"])
check("plan.close_3", p["close_after_days"] == 3 and "24 h" in p["why"])
p2 = er.outcome_plan("no_show", er.CH_WHATSAPP, True, 40)
check("plan.closed_window_email_now", p2["steps"][0] == (0, er.CH_WEB, er.STEP_REBOOK) and p2["steps"][1] == (24, er.CH_WEB, er.STEP_REBOOK), p2["steps"])
p3 = er.outcome_plan("no_show", er.CH_WHATSAPP, False, 40)
check("plan.no_email_stays_native", p3["steps"] == [(0, er.CH_WHATSAPP, er.STEP_REBOOK), (24, er.CH_WHATSAPP, er.STEP_REBOOK)], p3["steps"])
check("plan.ig_unchanged", er.outcome_plan("no_show", er.CH_INSTAGRAM, False, 99)["steps"][0][1] == er.CH_UNKNOWN)

# ── (b)/(c) the copy and the watcher ─────────────────────────────────────────
wa24, s24, h24 = er.confirmation_copy(24, "Michael", "Tuesday, October 06", "3:00 PM", "1500 Park Center Dr, Suite 230, Orlando, FL 32835")
check("copy.t24_yes", wa24.startswith("Hi Michael!") and "Reply YES to confirm your visit with Michael tomorrow at 3:00 PM" in wa24, wa24)
check("copy.t24_subject", s24 == "Reply YES to confirm — tomorrow at 3:00 PM with Michael", s24)
check("copy.t24_email", "<b>Reply YES</b>" in h24 and "with Michael tomorrow at" in h24 and "1500 Park Center" in h24)
wa2, s2, h2 = er.confirmation_copy(2, "Michael", "Tuesday, October 06", "3:00 PM", "1500 Park Center Dr, Suite 230, Orlando, FL 32835")
check("copy.t2_address_and_michael", "See you at 3:00 PM today for your visit with Michael Moraes — 1500 Park Center Dr" in wa2, wa2)
check("copy.t2_no_yes", "yes" not in wa2.lower())
check("copy.t2_email", "today at 3:00 PM" in h2 and "Michael Moraes" in h2 and "Address: 1500 Park Center" in h2 and "with Michael" in s2)
wa2n, _, _ = er.confirmation_copy(2, "", "Tuesday, October 06", "3:00 PM", "")
check("copy.t2_no_location_degrades", wa2n.startswith("Hi there! See you at 3:00 PM today for your visit with Michael Moraes. Reply here"), wa2n)
wa48, s48, _ = er.confirmation_copy(48, "Jane", "Tuesday, August 11", "10:00 AM")
check("copy.t48_unchanged", "Could you reply YES to confirm?" in wa48 and "August 11" in s48)
check("watch.due", er.unconfirmed_due(3.0) and er.unconfirmed_due(2.6) and er.unconfirmed_due(3.4) and not er.unconfirmed_due(2.0)
      and not er.unconfirmed_due(4.0) and not er.unconfirmed_due(None))
check("watch.text", er.unconfirmed_text("Michael Sessa", "3:00 PM", "Tuesday, October 06") == "unconfirmed: Michael Sessa 3:00 PM (Tuesday, October 06)"
      and er.unconfirmed_text("", "9:00 AM") == "unconfirmed: the lead 9:00 AM")

# ── (d) the rebook copy and the same-day email fallback ──────────────────────
SENT = {"wa": [], "email": []}
osd.configure(report_error=lambda *a, **k: None, post_slack=lambda *a, **k: None,
              send_email=lambda to, subject, html: (SENT["email"].append((to, subject, html)) or {"ok": True}),
              send_whatsapp=lambda phone, body: (SENT["wa"].append((phone, body)) or None),   # window closed: returns None
              send_instagram=lambda *a: None,
              slots=lambda: [{"display": "Friday, October 09 at 03:00 PM EST"}, {"display": "Monday, October 12 at 10:00 AM EST"}, {"display": "x"}],
              pg_load=lambda k, d=None: d, pg_save=lambda k, v: None, heartbeat=lambda n: None, lead_data={},
              matt_channel="#matt", maya_channel="#maya", dev_channel="#dev")
txt = osd._short_copy(er.STEP_REBOOK, "Michael")
check("rebook.two_slots", "Michael has Friday, October 09 at 03:00 PM or Monday, October 12 at 10:00 AM. Which works?" in txt and "EST" not in txt, txt)
subj, html = osd._email_copy(er.STEP_REBOOK, "Michael")
check("rebook.email_two_slots", "<b>Friday, October 09 at 03:00 PM</b> or <b>Monday, October 12 at 10:00 AM</b>" in html and "want to grab another time" in subj)
ok, note = osd._deliver(er.CH_WHATSAPP, er.STEP_REBOOK, {"name": "Michael Sessa", "phone": "14075905219", "email": "sessa@htsalb.com"}, "whatsapp:+14075905219", {})
check("rebook.wa_blocked_email_now", ok is True and note == "WhatsApp unavailable -> sent by email" and len(SENT["wa"]) == 1 and len(SENT["email"]) == 1
      and SENT["email"][0][0] == "sessa@htsalb.com" and "Friday, October 09" in SENT["email"][0][2], (ok, note, SENT))
SENT["wa"].clear(); SENT["email"].clear()
ok, note = osd._deliver(er.CH_WHATSAPP, er.STEP_REBOOK, {"name": "NoMail", "phone": "14075550000"}, "whatsapp:+14075550000", {})
check("rebook.wa_blocked_no_email_fails_honestly", ok is False and "whatsapp send returned nothing" in note and not SENT["email"])
osd._deps["send_whatsapp"] = lambda phone, body: (SENT["wa"].append((phone, body)) or {"ok": True})
SENT["wa"].clear(); SENT["email"].clear()
ok, note = osd._deliver(er.CH_WHATSAPP, er.STEP_REBOOK, {"name": "Open", "phone": "14075550001", "email": "o@x.com"}, "whatsapp:+14075550001", {})
check("rebook.wa_open_no_email", ok is True and note == "" and len(SENT["wa"]) == 1 and not SENT["email"])
osd._deps["slots"] = lambda: []
check("rebook.no_slots_fallback_link", osd.BOOK_URL in osd._short_copy(er.STEP_REBOOK, "A"))
osd._deps["slots"] = lambda: (_ for _ in ()).throw(RuntimeError("calendar down"))
check("rebook.slots_error_degrades", osd.BOOK_URL in osd._short_copy(er.STEP_REBOOK, "A"))

# ── wiring (static) ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
ga = SRC[SRC.index("def get_available_slots():"):SRC.index("# ─── PATCH #104 — auto-cleanup identity matching")]
check("wire.slots_offer", "_slots.offer_slots(" in ga and "if fallback:" in ga and "_post_to_slack_async(SLACK_ERIC_CHANNEL" in ga and "6 * 3600" in ga)
check("wire.slots_counters", '_TALLY.bump("slots.no_48h"' in ga and '_TALLY.bump("slots.inside_48h"' in ga)
check("wire.outcome_slots", "slots=lambda: get_available_slots(),     # PATCH #157" in SRC)
rl = SRC[SRC.index("def _lead_reminder_thread():"):SRC.index("def _lead_reminder_thread():") + 40000]
check("wire.watcher", "event_rail.unconfirmed_due(hours_until)" in rl and 'f"{event_id}:unconfirmed"' in rl
      and "event_rail.unconfirmed_text(_u_name, _t_str" in rl and '_operator_alert.alert(\n                                "booking",' in rl)
check("wire.watcher_reads_ask", 'f"confirm_asked:{event_id}"' in rl and "_last_in > _asked_dt" in rl)
check("wire.ask_stamped_at_t24", 'if _sent_via and stage_h == 24 and _pg.enabled():' in rl and '_pg.save_state(f"confirm_asked:{event_id}", now.isoformat())' in rl)
check("wire.email_beside_template", '_sent_via == "WhatsApp (approved template)" and stage_h in (24, 2)' in rl
      and 'via=f"confirmation-T{stage_h}h-beside-template"' in rl and '_sent_via += " + email"' in rl)
check("wire.watcher_before_stages", rl.index("event_rail.unconfirmed_due(hours_until)") < rl.index("for audience, stage_h in due_stages(kind, hours_until):"))
osr = open(os.path.join(HERE, "outcome_sender.py"), encoding="utf-8").read()
check("wire.sent_note", '**({"note": note} if note else {})' in osr)

print(f"static+behaviour: {passed} passed, {failed} failed")

for gate in ("test_event_rail.py", "test_patch156.py"):
    r_ = subprocess.run([sys.executable, os.path.join(HERE, gate)], capture_output=True, text=True)
    lines = r_.stdout.strip().splitlines() or [""]
    tail = next((ln for ln in reversed(lines) if re.search(r"(\d+) passed, (\d+) failed", ln)), lines[-1])
    m_ = re.search(r"(\d+) passed, (\d+) failed", tail)
    if r_.returncode != 0 or not m_:
        print(r_.stdout[-1500:]); print(r_.stderr[-800:])
        failed += 1; print(f"FAIL {gate} did not pass")
    else:
        passed += int(m_.group(1)); failed += int(m_.group(2))
        print(f"{gate}: {tail.strip()}")
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
