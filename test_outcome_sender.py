#!/usr/bin/env python3
"""Patch #44B — tests for the sender that executes what Patch #39 arms.

The bug these exist to prevent recurring: #39 stored a plan and everyone
believed storing it was doing it. So the assertions here are deliberately about
OBSERVABLE SIDE EFFECTS — what was actually sent, to whom, on which channel —
never about what the record says.

Run: python3 test_outcome_sender.py
"""
import sys
from datetime import datetime, timedelta

import event_rail as er
import outcome_sender as osx

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok else f"\n          got={got!r}\n         want={want!r}"))
    if not ok:
        FAILS.append(label)


def section(t):
    print(f"\n{t}\n" + "-" * len(t))


NOW = datetime(2026, 8, 4, 12, 0, 0)      # noon — inside the send window
NIGHT = datetime(2026, 8, 4, 0, 5, 0)     # 12:05 AM — the exact hour #44B shipped


def armed(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


class Harness:
    """Captures every outbound instead of sending it."""

    def __init__(self, leads):
        self.emails, self.wa, self.ig, self.slack = [], [], [], []
        self.leads = leads
        osx._deps.clear()
        osx.configure(
            report_error=lambda *a, **k: None,
            post_slack=lambda ch, txt: self.slack.append((ch, txt)),
            send_email=self._email,
            send_whatsapp=lambda p, b: (self.wa.append((p, b)) or {"ok": True}),
            send_instagram=lambda i, b: (self.ig.append((i, b)) or {"ok": True}),
            pg_load=lambda k, d=None: d,
            pg_save=lambda k, v: None,
            heartbeat=lambda n: None,
            lead_data=leads,
            matt_channel="#matt", maya_channel="#maya", dev_channel="#dev",
        )
        self.suppress = set()
        self.fail = set()

    def _email(self, to, subject, html):
        if to in self.suppress:
            return {"ok": False, "suppressed": True, "error": "suppressed: DNC"}
        if to in self.fail:
            return {"ok": False, "error": "smtp exploded"}
        self.emails.append((to, subject, html))
        return {"ok": True, "message_id": "m1"}


def lead(**kw):
    base = {"name": "Jane Doe", "business": "Doe Media",
            "email": "jane@example.com", "phone": "14075551234"}
    base.update(kw)
    return base


def seq(steps, hours_ago, **kw):
    s = {"outcome": "follow_up", "armed_at": armed(hours_ago),
         "channel": er.CH_WEB, "email": "jane@example.com",
         "steps": steps, "next_step": 0, "close_after_days": 14,
         "owner": "MAYA", "done": False}
    s.update(kw)
    return s


# ══════════════════════════════════════════════════════════════════════
section("1 · pure step selection (event_rail)")
S = [[48, er.CH_WEB, er.STEP_NUDGE], [168, er.CH_WEB, er.STEP_VALUE]]

check("before the delay -> waiting", er.next_due_step({"steps": S, "next_step": 0}, 10)[2], "waiting")
check("after the delay -> due", er.next_due_step({"steps": S, "next_step": 0}, 49)[2], "due")
check("long after -> stale", er.next_due_step({"steps": S, "next_step": 0}, 48 + 100)[2], "stale")
check("exactly at the boundary -> due", er.next_due_step({"steps": S, "next_step": 0}, 48)[2], "due")
check("at the stale boundary -> still due",
      er.next_due_step({"steps": S, "next_step": 0}, 48 + er.STEP_STALE_AFTER_HOURS)[2], "due")
check("past every step -> finished", er.next_due_step({"steps": S, "next_step": 2}, 999)[2], "finished")
check("never skips ahead — step 1 is chosen, not step 2",
      er.next_due_step({"steps": S, "next_step": 0}, 999)[0], 0)
check("malformed seq -> finished", er.next_due_step(None, 5)[2], "finished")
check("garbage next_step -> treated as 0",
      er.next_due_step({"steps": S, "next_step": "x"}, 49)[0], 0)

check("close window not reached", er.seq_should_close({"close_after_days": 14}, 3), False)
check("close window reached", er.seq_should_close({"close_after_days": 14}, 14), True)
check("no close window set -> never closes", er.seq_should_close({}, 999), False)


# ══════════════════════════════════════════════════════════════════════
section("2 · stop reasons beat timing, always")
check("booked stops it", er.seq_stop_reason(lead(booked=True), {"steps": []}), "lead has a booking")
check("won stops it", er.seq_stop_reason(lead(outcome="Won"), {"steps": []}), "lead converted")
check("do_not_contact stops it",
      er.seq_stop_reason(lead(do_not_contact=True), {"steps": []}), "lead is on do-not-contact")
check("a reply after arming stops it",
      er.seq_stop_reason(lead(last_message_time=armed(1)), seq([], 48)),
      "lead replied after the sequence was armed")
check("a reply BEFORE arming does not stop it",
      er.seq_stop_reason(lead(last_message_time=armed(80)), seq([], 48)), "")
check("a clean lead continues", er.seq_stop_reason(lead(), seq([], 48)), "")


# ══════════════════════════════════════════════════════════════════════
section("3 · the sender actually sends (the whole point of #44B)")
leads = {"14075551234": lead(outcome_seq=seq(
    [[48, er.CH_WEB, er.STEP_NUDGE]], 50))}
h = Harness(leads)
out = h._email and None
res = osx._pass(now=NOW)
check("one email went out", len(h.emails), 1)
check("...to the right person", h.emails[0][0], "jane@example.com")
check("...with a first-name subject", "Jane" in h.emails[0][1], True)
check("...counted as sent", res["sent"], 1)
check("...and the step advanced", leads["14075551234"]["outcome_seq"]["next_step"], 1)

# Second pass must NOT resend — the classic double-send bug.
res2 = osx._pass(now=NOW)
check("a second pass sends nothing", len(h.emails), 1)
check("...and reports waiting/closed, not sent", res2["sent"], 0)


# ══════════════════════════════════════════════════════════════════════
section("4 · channel routing")
leads = {"14075551234": lead(outcome_seq=seq(
    [[0, er.CH_WHATSAPP, er.STEP_REBOOK]], 1, outcome="no_show"))}
h = Harness(leads)
osx._pass(now=NOW)
check("WhatsApp step goes to WhatsApp", len(h.wa), 1)
check("...and not to email", len(h.emails), 0)
check("...with the booking link in the text", osx.BOOK_URL in h.wa[0][1], True)

leads = {"178901234567890": lead(igsid="178901234567890", phone="",
                                 outcome_seq=seq([[0, er.CH_INSTAGRAM, er.STEP_NUDGE]], 1))}
h = Harness(leads)
osx._pass(now=NOW)
check("Instagram step goes to IG", len(h.ig), 1)
check("...addressed by IGSID", h.ig[0][0], "178901234567890")


# ══════════════════════════════════════════════════════════════════════
section("5 · unreachable steps escalate to a human, never vanish")
leads = {"x": lead(email="", phone="", outcome_seq=seq(
    [[0, er.CH_UNKNOWN, er.STEP_NUDGE]], 1))}
h = Harness(leads)
res = osx._pass(now=NOW)
check("nothing was sent", len(h.emails) + len(h.wa) + len(h.ig), 0)
check("a human was told", len(h.slack), 1)
check("...in the owner's channel", h.slack[0][0], "#maya")
check("...with the suggested message included", "Michael from MWM" in h.slack[0][1], True)
check("...counted as escalated", res["escalated"], 1)


# ══════════════════════════════════════════════════════════════════════
section("6 · do-not-contact kills the WHOLE sequence, not one step")
leads = {"x": lead(outcome_seq=seq(
    [[48, er.CH_WEB, er.STEP_NUDGE], [168, er.CH_WEB, er.STEP_VALUE]], 50))}
h = Harness(leads)
h.suppress.add("jane@example.com")
res = osx._pass(now=NOW)
check("nothing sent", len(h.emails), 0)
check("sequence marked done", leads["x"]["outcome_seq"]["done"], True)
check("...with the reason recorded",
      "SUPPRESSED" in leads["x"]["outcome_seq"]["closed_reason"], True)
check("...counted as stopped", res["stopped"], 1)


# ══════════════════════════════════════════════════════════════════════
section("7 · a stale step is skipped, not fired late")
# #39's own argument: a same-day no-show offer converts, a day-3 one does not.
leads = {"x": lead(outcome_seq=seq(
    [[0, er.CH_WEB, er.STEP_REBOOK], [48, er.CH_WEB, er.STEP_REBOOK]],
    5 * 24, outcome="no_show", close_after_days=None))}
h = Harness(leads)
res = osx._pass(now=NOW)
check("the stale rebook was NOT sent", len(h.emails), 0)
check("...counted as stale", res["stale"], 1)
check("...and the sequence moved past it", leads["x"]["outcome_seq"]["next_step"], 1)


# ══════════════════════════════════════════════════════════════════════
section("8 · sequences end")
leads = {"x": lead(outcome_seq=seq([[48, er.CH_WEB, er.STEP_NUDGE]], 15 * 24))}
h = Harness(leads)
res = osx._pass(now=NOW)
check("past close_after_days -> closed", leads["x"]["outcome_seq"]["done"], True)
check("...nothing sent on the way out", len(h.emails), 0)
check("...counted as closed", res["closed"], 1)


# ══════════════════════════════════════════════════════════════════════
section("9 · a send failure escalates instead of retrying forever")
leads = {"x": lead(outcome_seq=seq([[48, er.CH_WEB, er.STEP_NUDGE]], 50))}
h = Harness(leads)
h.fail.add("jane@example.com")
res = osx._pass(now=NOW)
check("counted as failed", res["failed"], 1)
check("a human was told", len(h.slack), 1)
check("...and the step advanced so it cannot loop",
      leads["x"]["outcome_seq"]["next_step"], 1)


# ══════════════════════════════════════════════════════════════════════
section("10 · blast-radius cap")
leads = {str(i): lead(email=f"l{i}@x.com",
                      outcome_seq=seq([[48, er.CH_WEB, er.STEP_NUDGE]], 50))
         for i in range(40)}
h = Harness(leads)
res = osx._pass(now=NOW)
check("a single pass cannot exceed MAX_SENDS_PER_PASS",
      res["sent"] <= osx.MAX_SENDS_PER_PASS, True)
check("...and it did send up to the cap", res["sent"], osx.MAX_SENDS_PER_PASS)


# ══════════════════════════════════════════════════════════════════════
section("11 · copy details that have bitten us before")
check("joint-booking name greets the first person only",
      osx._first_name("Krista Neeley (with Michael Neeley)"), "Krista")
check("empty name degrades to 'there'", osx._first_name(""), "there")
check("None name degrades to 'there'", osx._first_name(None), "there")
_s, _h = osx._email_copy(er.STEP_REVIEW, "Jane", "Doe Media")
check("review email invites private negative feedback",
      "rather hear it from you directly" in _h, True)
_s2, _h2 = osx._email_copy(er.STEP_NUDGE, "Jane")
check("nudge offers an explicit way out", "stop following up" in _h2, True)
check("email_capture is never phrased as an email-only ask",
      "best email" in osx._short_copy(er.STEP_EMAIL_ASK, "Jane"), True)


# ══════════════════════════════════════════════════════════════════════
section("12 · quiet hours — nothing gets messaged at midnight")
check("noon is inside the window", er.within_send_window(NOW), True)
check("12:05 AM is outside it", er.within_send_window(NIGHT), False)
check("8:00 AM is the first sendable hour",
      er.within_send_window(datetime(2026, 8, 4, 8, 0)), True)
check("7:59 AM is not", er.within_send_window(datetime(2026, 8, 4, 7, 59)), False)
check("7:59 PM is still sendable",
      er.within_send_window(datetime(2026, 8, 4, 19, 59)), True)
check("8:00 PM is not", er.within_send_window(datetime(2026, 8, 4, 20, 0)), False)

# Armed at 10pm the night before, so the 0-hour rebook step is genuinely DUE
# at 12:05 AM. (Timing is relative to armed_at, not to NOW — an earlier test
# clock with a NOW-relative armed_at would put arming in the future.)
_armed_late = datetime(2026, 8, 3, 22, 0, 0).isoformat()
leads = {"x": lead(outcome_seq=seq([[0, er.CH_WEB, er.STEP_REBOOK]], 2,
                                   armed_at=_armed_late,
                                   outcome="no_show", close_after_days=5))}
h = Harness(leads)
res = osx._pass(now=NIGHT)
check("a due step at midnight is HELD, not sent", len(h.emails), 0)
check("...counted as held", res["held_quiet_hours"], 1)
check("...and NOT advanced — it is held, not skipped",
      leads["x"]["outcome_seq"]["next_step"], 0)

# Same lead, same sequence, come the morning.
res = osx._pass(now=datetime(2026, 8, 4, 9, 0))
check("the same step sends in the morning", len(h.emails), 1)
check("...and only then advances", leads["x"]["outcome_seq"]["next_step"], 1)

# Bookkeeping must still run overnight — an expired sequence should close
# even at 3am, because closing sends nothing.
leads = {"y": lead(outcome_seq=seq([[48, er.CH_WEB, er.STEP_NUDGE]], 20 * 24))}
h = Harness(leads)
res = osx._pass(now=NIGHT)
check("expired sequences still close overnight",
      leads["y"]["outcome_seq"]["done"], True)
check("...silently", len(h.emails), 0)

# A do-not-contact lead must be stopped at any hour.
leads = {"z": lead(do_not_contact=True,
                   outcome_seq=seq([[0, er.CH_WEB, er.STEP_REBOOK]], 2))}
h = Harness(leads)
res = osx._pass(now=NIGHT)
check("DNC stops the sequence even at midnight", res["stopped"], 1)


print("\n" + "=" * 60)
print(f"  TOTAL: {'FAILED — ' + str(len(FAILS)) if FAILS else 'ALL PASS'}")
for f in FAILS:
    print("   -", f)
print("=" * 60)
sys.exit(1 if FAILS else 0)
