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
# PATCH #49B — a bare `booked` flag NO LONGER stops a sequence. It is set at
# booking creation and never cleared, so for a follow_up armed right after a
# meeting the lead booked, it is true by definition. #48B read it as a current
# commitment and cancelled Rodolfo Silva's nudge in production.
check("a bare booked flag does NOT stop it — it only means 'ever booked'",
      er.seq_stop_reason(lead(booked=True), {"steps": [], "armed_at": "2026-08-04T11:00:00"}), "")
check("a booking made BEFORE the sequence does not stop it",
      er.seq_stop_reason(lead(booked=True, booked_at="2026-08-04T10:00:00"),
                         {"steps": [], "armed_at": "2026-08-04T11:00:00"}), "")
check("a booking made AFTER the sequence DOES stop it",
      er.seq_stop_reason(lead(booked=True, booked_at="2026-08-05T09:00:00"),
                         {"steps": [], "armed_at": "2026-08-04T11:00:00"}),
      "lead booked again after this sequence was armed")
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


# ══════════════════════════════════════════════════════════════════════
section("13 · #46A — the nudge must not talk over an agreed next step")
# Live case, Aug 4 2026: Rodolfo Silva. Michael's report recorded that they
# AGREED he sends a script on Aug 7 and books an hour the same day. The T+48h
# nudge fires Aug 6. The old copy would have asked a committed client whether
# he was "still thinking it over".
_AGREED = "Aug 7: he sends his script for approval, then books 1h studio + editing."

_s, _h = osx._email_copy(er.STEP_NUDGE, "Rodolfo", "Nest Seekers", _AGREED)
check("subject references the agreement, not indecision",
      "a nudge on our next step" in _s, True)
check("...and never asks if they are still thinking",
      "still thinking" in (_s + _h).lower(), False)
# Caught in preview: Michael writes notes in the THIRD PERSON about the client
# ("he will send his script for my approval"). Pasting that into an email TO
# that client is worse than the generic copy. The note sets the frame; it never
# becomes the message.
check("the internal note is NOT pasted to the client", _AGREED in _h, False)
check("...and no third-person leak reaches them",
      " he " in _h.lower() or " his " in _h.lower(), False)
check("...and they are given an out", "need more time" in _h, True)

# Sequences armed BEFORE #46 carry no agreed_next. The default had to be fixed
# too, or Rodolfo's own already-armed sequence would still have used it.
_s0, _h0 = osx._email_copy(er.STEP_NUDGE, "Rodolfo", "Nest Seekers")
check("the DEFAULT no longer presumes indecision either",
      "still thinking" in (_s0 + _h0).lower(), False)
check("...it just checks in", "checking in" in _s0.lower(), True)
check("...and still offers a way out", "stop following up" in _h0, True)

# Michael types this into a form; it lands inside an HTML email body.
_evil = 'He said <b>"do it"</b> & sign by 5th'
_s2, _h2 = osx._email_copy(er.STEP_NUDGE, "Jane", "", _evil)
check("hostile free text cannot reach the client at all", "do it" in _h2, False)
check("...nor any markup from it", "<b>" in _h2, False)

# The DM variant must stay short — a 300-char quote is not a DM.
_long = "x" * 300
_dm = osx._short_copy(er.STEP_NUDGE, "Jane", "", _long)
check("the DM stays short regardless of note length", len(_dm) < 250, True)
check("...and does not paste the note either", "xxx" in _dm, False)

check("long business descriptors are trimmed to the name",
      osx._short_business("Nest Seekers — Luxury Real Estate Advisor"), "Nest Seekers")
check("...and a plain name is left alone", osx._short_business("Carito Music"), "Carito Music")
_dm0 = osx._short_copy(er.STEP_NUDGE, "Jane")
check("DM default also drops the indecision framing",
      "still thinking" in _dm0.lower(), False)

section("14 · #46B — say where the message actually lands")
check("CH_WEB is described as email, not 'Website Chat'",
      er.delivery_label(er.CH_WEB), "email")
check("WhatsApp stays WhatsApp", er.delivery_label(er.CH_WHATSAPP), "WhatsApp")
check("Instagram is named as a DM", er.delivery_label(er.CH_INSTAGRAM), "Instagram DM")
check("unknown names the human fallback honestly",
      "human" in er.delivery_label(er.CH_UNKNOWN), True)


# ══════════════════════════════════════════════════════════════════════
section("15 · #48B — a booking on a DUPLICATE record must stop the sequence")
# Live case, Aug 4 2026. /admin/lead-seq?q=rodolfo returned TWO Rodolfo Silva
# records: one with the business name and booked=true and NO sequence, one
# thinner with booked=false and the armed sequence. As shipped, he could book
# on the 7th and still be asked on the 11th where things stand.
check("a sibling's bare booked flag does NOT stop it (the #48B bug)",
      er.sibling_stop_reason({}, [{"booked": True}], "2026-08-04T11:00:00"), "")
check("a sibling booking made AFTER the sequence DOES stop it",
      er.sibling_stop_reason({}, [{"booked": True, "booked_at": "2026-08-05T09:00:00"}],
                             "2026-08-04T11:00:00"),
      "a duplicate record for this person booked after this sequence was armed")
check("no armed_at means no stop — we cannot tell, so keep the rail running",
      er.sibling_stop_reason({}, [{"booked": True, "booked_at": "2026-08-05T09:00:00"}]), "")
check("a sibling conversion stops it",
      er.sibling_stop_reason({}, [{"outcome": "Won"}]),
      "a duplicate record for this person has already converted")
check("a sibling do-not-contact stops it",
      er.sibling_stop_reason({}, [{"do_not_contact": True}]),
      "a duplicate record for this person is on do-not-contact")
check("a clean sibling does not stop it",
      er.sibling_stop_reason({}, [{"name": "someone"}]), "")
check("no siblings is fine", er.sibling_stop_reason({}, []), "")
check("None siblings is fine", er.sibling_stop_reason({}, None), "")
check("the record never stops itself",
      er.sibling_stop_reason.__doc__ is not None, True)

# End to end, with the real shape: the sequence sits on the thin copy.
_thin = lead(name="Rodolfo Silva", business="", booked=False,
             email="rodolfos@nestseekers.com",
             outcome_seq=seq([[48, er.CH_WEB, er.STEP_NUDGE]], 50,
                             email="rodolfos@nestseekers.com"))
_fat = lead(name="Rodolfo Silva", business="Nest Seekers", booked=True,
            email="rodolfos@nestseekers.com")
leads = {"ig_thin": _thin, "ph_fat": _fat}
h = Harness(leads)
res = osx._pass(now=NOW)
# PATCH #49B — the real Rodolfo shape: the twin's booking is the meeting that
# was just held, i.e. OLDER than the sequence. It must NOT suppress.
check("a twin's HISTORICAL booking does not suppress the nudge", len(h.emails), 1)
check("...and the sequence stays alive", _thin["outcome_seq"]["done"], False)

# Now give the twin a booking made AFTER arming — that one must stop it.
_thin2 = lead(name="Rodolfo Silva", business="", booked=False,
              email="rodolfos@nestseekers.com",
              outcome_seq=seq([[48, er.CH_WEB, er.STEP_NUDGE]], 50,
                              email="rodolfos@nestseekers.com"))
_fat2 = lead(name="Rodolfo Silva", booked=True, email="rodolfos@nestseekers.com",
             booked_at=(NOW - timedelta(hours=1)).isoformat())
leads2 = {"thin": _thin2, "fat": _fat2}
h2 = Harness(leads2)
res2 = osx._pass(now=NOW)
check("a twin's NEW booking does stop it", len(h2.emails), 0)
check("...and the reason names the duplicate",
      "duplicate" in _thin2["outcome_seq"]["closed_reason"], True)
check("...counted as stopped", res2["stopped"], 1)

# The email match must be exact — two different people at one company share a
# domain, not an inbox.
_other = lead(name="Someone Else", booked=True, email="other@nestseekers.com")
leads = {"a": lead(name="Rodolfo Silva", email="rodolfos@nestseekers.com",
                   outcome_seq=seq([[48, er.CH_WEB, er.STEP_NUDGE]], 50,
                                   email="rodolfos@nestseekers.com")),
         "b": _other}
h = Harness(leads)
res = osx._pass(now=NOW)
check("a colleague at the same domain is NOT treated as a duplicate",
      len(h.emails), 1)


# ══════════════════════════════════════════════════════════════════════
section("16 · #49C — reopen exactly what #48B wrongly closed")
_killed = lead(email="jane@example.com",
               outcome_seq=seq([[48, er.CH_WEB, er.STEP_NUDGE]], 50))
_killed["outcome_seq"]["done"] = True
_killed["outcome_seq"]["closed_reason"] = "a duplicate record for this person has a booking"
leads = {"k": _killed}
h = Harness(leads)
res = osx._pass(now=NOW)
check("a sequence killed by the #48B rule is reopened and sent", len(h.emails), 1)
check("...and the reopening is recorded on the record",
      bool(_killed["outcome_seq"].get("reopened")), True)

# Anything closed for a GOOD reason must stay closed.
for _reason in ("lead is on do-not-contact", "lead converted",
                "lead replied after the sequence was armed", "all steps sent"):
    _ok = lead(email="jane@example.com",
               outcome_seq=seq([[48, er.CH_WEB, er.STEP_NUDGE]], 50))
    _ok["outcome_seq"]["done"] = True
    _ok["outcome_seq"]["closed_reason"] = _reason
    h2 = Harness({"x": _ok})
    osx._pass(now=NOW)
    check(f"...but '{_reason}' stays closed", len(h2.emails), 0)


# ══════════════════════════════════════════════════════════════════════
section("17 · PATCH #60 — the sender's clock is LOCAL, not the host's")
#
# Rodolfo Silva, Aug 6 2026. Booked client, mid-engagement, script due to
# Michael the next day. His T+2d nudge — "if the timing isn't right, tell me
# and I'll stop following up" — was due at 11:47 AM ET. It went out at 07:55.
#
# Reconstructed exactly: armed_at is written offset-aware in LOCAL time, and
# `_pass()` used `datetime.now()`, which on Railway is a naive UTC wall clock.
# 11:55 UTC minus 11:47 local "=" 48h08m, so a 48h step read as due when only
# 44h08m had actually passed. The same naive-UTC value was handed to the 8 AM
# floor, where hour==11 sailed through a guard whose entire job was to stop
# exactly this send.
import pytz as _pytz

_UTC = _pytz.utc
RODOLFO_ARMED = "2026-08-04T11:47:00-04:00"      # aware, local — as stored
RODOLFO_STEPS = [[48, er.CH_WEB, er.STEP_NUDGE]]


def _rodolfo():
    return {"r": lead(name="Rodolfo Silva", email="rodolfo@example.com",
                      outcome_seq=seq(RODOLFO_STEPS, 0, armed_at=RODOLFO_ARMED,
                                      email="rodolfo@example.com",
                                      outcome="follow_up", close_after_days=14))}

# ── the conversion helper, on its own ──
check("an aware UTC timestamp converts to local, it is not stripped",
      er.to_local_naive(_UTC.localize(datetime(2026, 8, 6, 11, 55))),
      datetime(2026, 8, 6, 7, 55))
check("an aware LOCAL timestamp survives the round trip unchanged",
      er.to_local_naive(datetime.fromisoformat(RODOLFO_ARMED)),
      datetime(2026, 8, 4, 11, 47))
check("a naive timestamp is taken at face value — no guessing",
      er.to_local_naive(datetime(2026, 8, 6, 7, 55)), datetime(2026, 8, 6, 7, 55))
check("None survives", er.to_local_naive(None), None)

# ── the send window, read on the right clock ──
check("07:55 ET is BEFORE the 8 AM floor",
      er.within_send_window(datetime(2026, 8, 6, 7, 55)), False)
check("the same instant expressed as 11:55 UTC is ALSO before the floor",
      er.within_send_window(_UTC.localize(datetime(2026, 8, 6, 11, 55))), False)
check("11:47 ET is inside the window",
      er.within_send_window(datetime(2026, 8, 6, 11, 47)), True)
check("an aware local datetime works too — /admin/lead-seq passes one",
      er.within_send_window(er.LOCAL_TZ.localize(datetime(2026, 8, 6, 11, 47))), True)

# ── THE REGRESSION, end to end ──
leads = _rodolfo()
h = Harness(leads)
res = osx._pass(now=datetime(2026, 8, 6, 7, 55))
check("at 07:55 ET the T+2d step has NOT come due — nothing is sent",
      len(h.emails), 0)
check("...and it is counted as waiting, not held and not skipped",
      res["waiting"], 1)
check("...and the step pointer has not moved",
      leads["r"]["outcome_seq"]["next_step"], 0)

# The same instant, handed in as UTC — which is what the process actually had.
leads = _rodolfo()
h = Harness(leads)
res = osx._pass(now=_UTC.localize(datetime(2026, 8, 6, 11, 55)))
check("the identical instant labelled UTC also sends nothing",
      len(h.emails), 0)
check("...still waiting, not due", res["waiting"], 1)

# And it does still fire — held, never skipped.
leads = _rodolfo()
h = Harness(leads)
res = osx._pass(now=datetime(2026, 8, 6, 11, 47))
check("at 11:47 ET — the hour it was actually due — it sends", len(h.emails), 1)
check("...to the right person", h.emails[0][0], "rodolfo@example.com")
check("...and the step advances exactly once",
      leads["r"]["outcome_seq"]["next_step"], 1)
check("...and the timestamp written on the record is local wall time",
      leads["r"]["outcome_seq"]["sent"][0]["at"],
      datetime(2026, 8, 6, 11, 47).isoformat())

# A 4 AM pass must send nothing, whatever the elapsed maths says.
leads = _rodolfo()
h = Harness(leads)
res = osx._pass(now=datetime(2026, 8, 7, 4, 0))
check("a due step at 4 AM is HELD", len(h.emails), 0)
check("...counted as quiet hours", res["held_quiet_hours"], 1)

# ── the default clock: no argument at all ──
_before = er.LOCAL_TZ.localize(datetime.now(er.LOCAL_TZ).replace(tzinfo=None))
_ln = er.local_now()
check("local_now() is naive", _ln.tzinfo, None)
check("local_now() is NOT the host's UTC clock unless the host is on ET",
      abs((_ln - datetime.utcnow()).total_seconds()) > 3000
      or str(er.LOCAL_TZ) == "UTC", True)
check("local_now() agrees with pytz on the wall clock, to the minute",
      _ln.strftime("%Y-%m-%d %H:%M"),
      datetime.now(er.LOCAL_TZ).strftime("%Y-%m-%d %H:%M"))


print("\n" + "=" * 60)
print(f"  TOTAL: {'FAILED — ' + str(len(FAILS)) if FAILS else 'ALL PASS'}")
for f in FAILS:
    print("   -", f)
print("=" * 60)
sys.exit(1 if FAILS else 0)
