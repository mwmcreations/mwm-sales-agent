#!/usr/bin/env python3
"""test_calendar_sync.py — S28 acceptance tests for Google Calendar -> portal sync.

Zero dependencies, no network, no Google, no WordPress. Run:

    python3 test_calendar_sync.py

The two that matter most:

  * TEST 2 proves TERMINATION. Apply a drag, then run the sync three times over
    the same state. Runs 2 and 3 must make zero WordPress calls and zero
    calendar writes. A sync loop that ping-pongs fills a client's inbox with
    invites, and you find out from the client.

  * TEST 11 proves the syncToken is never advanced past a failure. Advancing on
    a failed write loses that change forever — and silence is the defect this
    whole project exists to kill.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

os.environ["MWM_GCAL_SYNC_ENABLED"] = "1"   # must be set before the module reads it

import calendar_sync as cs

_passed = _failed = 0
_FAILS = []

ET = timezone(timedelta(hours=-4))          # America/New_York in August
NOW = datetime(2026, 8, 14, 18, 0, 0, tzinfo=ET)


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  PASS  " + label)
    else:
        _failed += 1
        _FAILS.append(label)
        print("  FAIL  " + label + "\n          got={!r}\n         want={!r}".format(got, want))


def check_true(label, got):
    check(label, bool(got), True)


def section(title):
    print("\n" + title + "\n" + "-" * len(title))


# ══════════════════════════════════════════════════════════════════════
# fakes — a calendar that never rings Google, a portal that never rings WP
# ══════════════════════════════════════════════════════════════════════

class _Resp(object):
    def __init__(self, status):
        self.status = status


class HttpishError(Exception):
    """Shaped like googleapiclient.errors.HttpError enough for is_gone_error()."""
    def __init__(self, status, msg="error"):
        Exception.__init__(self, "<HttpError {} {}>".format(status, msg))
        self.resp = _Resp(status)


class _Exec(object):
    def __init__(self, result):
        self._r = result

    def execute(self, **kwargs):
        if isinstance(self._r, Exception):
            raise self._r
        return self._r


class _Events(object):
    def __init__(self, cal):
        self.cal = cal

    def list(self, **params):
        self.cal.list_calls.append(params)
        if self.cal.responses:
            return _Exec(self.cal.responses.pop(0))
        return _Exec({"items": [], "nextSyncToken": self.cal.token})

    # Any of these firing during a calendar-sourced change is the bug.
    def insert(self, **kwargs):
        self.cal.writes.append(("insert", kwargs))
        return _Exec({"id": "written"})

    def update(self, **kwargs):
        self.cal.writes.append(("update", kwargs))
        return _Exec({"id": "written"})

    def patch(self, **kwargs):
        self.cal.writes.append(("patch", kwargs))
        return _Exec({"id": "written"})

    def delete(self, **kwargs):
        self.cal.writes.append(("delete", kwargs))
        return _Exec({})


class FakeCalendar(object):
    def __init__(self, responses=None, token="TOKEN-NEXT"):
        self.responses = list(responses or [])
        self.token = token
        self.list_calls = []
        self.writes = []

    def events(self):
        return _Events(self)


class FakePortal(object):
    """Stands in for WordPress. Scripted answers, recorded questions."""
    def __init__(self, reply=None, raises=None):
        self.calls = []
        self.reply = reply
        self.raises = raises

    def __call__(self, payload):
        self.calls.append(payload)
        if self.raises:
            raise self.raises
        if callable(self.reply):
            return self.reply(payload)
        if self.reply is not None:
            return self.reply
        return {"ok": True, "state": "updated", "booking_id": payload.get("booking_id"),
                "client": "Jonathan Pineda", "warnings": []}


class Rig(object):
    """One fully wired machine: fake calendar, fake portal, in-memory pg, Slack log."""
    def __init__(self, calendar=None, portal=None, store=None):
        self.calendar = calendar or FakeCalendar()
        self.portal = portal if portal is not None else FakePortal()
        self.store = dict(store or {})
        self.slack = []
        self.errors = []
        cs._deps.clear()
        cs.configure(
            calendar_service=lambda: self.calendar,
            calendar_id="mwm@group.calendar.google.com",
            wp_post=self.portal,
            pg_load=lambda k, d=None: self.store.get(k, d),
            pg_save=self._save,
            post_slack=lambda ch, text: self.slack.append((ch, text)),
            report_error=lambda ctx, exc, detail="": self.errors.append((ctx, str(exc), detail)),
            heartbeat=lambda name: None,
            matt_channel="#matt",
            dev_channel="#dev",
            to_local=lambda dt: dt.astimezone(ET),
            now=lambda: NOW,
        )

    def _save(self, key, value):
        self.store[key] = value
        return True

    @property
    def slack_text(self):
        return "\n".join(t for _, t in self.slack)


def event(eid="ev1", bid_text="Studio Package portal booking #71", date="2026-08-20",
          start="14:15", end="15:15", status="confirmed"):
    return {
        "id": eid,
        "status": status,
        "description": bid_text,
        "summary": "\U0001f3ac Studio: Jonathan Pineda (1h)",
        "start": {"dateTime": "{}T{}:00-04:00".format(date, start)},
        "end": {"dateTime": "{}T{}:00-04:00".format(date, end)},
    }


def seeded(eid="ev1", bid=71, date="2026-08-20", start="14:15", end="15:15", token="TOKEN-1"):
    """A store that already knows this event — i.e. after bootstrap."""
    return {
        cs.KEY_SYNCTOKEN: {"token": token},
        cs.KEY_EVENT + eid: {"booking_id": bid},
        cs.KEY_CURRENT + str(bid): {"event_id": eid},
        cs.KEY_SEEN + eid: {"date": date, "start": start, "end": end, "booking_id": bid},
    }


# ══════════════════════════════════════════════════════════════════════
section("0 · the parts, on their own")

check("a portal booking id is read off the description",
      cs.booking_id_from_description("Studio Package portal booking #71\nClient: x"), 71)
check("an event with no booking marker resolves to nothing",
      cs.booking_id_from_description("Dentist"), None)
check("...and neither does an empty description",
      cs.booking_id_from_description(""), None)
check("a bare '#71' is NOT enough — Michael's own notes use hashes",
      cs.booking_id_from_description("call about #71"), None)

_r = Rig()
check("event times come back as studio-local date/start/end",
      cs.event_times(event()), ("2026-08-20", "14:15", "15:15"))
check("an all-day event has no times and is never treated as a booking",
      cs.event_times({"id": "x", "start": {"date": "2026-08-20"}, "end": {"date": "2026-08-21"}}), None)
check("a UTC 'Z' timestamp still parses (Python 3.8 fromisoformat will not)",
      cs.event_times({"id": "x", "start": {"dateTime": "2026-08-20T18:15:00Z"},
                      "end": {"dateTime": "2026-08-20T19:15:00Z"}}),
      ("2026-08-20", "14:15", "15:15"))
check("a 410 is recognised as an expired syncToken", cs.is_gone_error(HttpishError(410)), True)
check("...and a 404 is not", cs.is_gone_error(HttpishError(404)), False)


# ══════════════════════════════════════════════════════════════════════
section("1 · an event moved 14:15 -> 16:00 reaches the portal, once")

rig = Rig(FakeCalendar([{"items": [event(start="16:00", end="17:00")], "nextSyncToken": "TOKEN-2"}]),
          store=seeded())
s = cs.sync_once()
check("exactly one WordPress call", len(rig.portal.calls), 1)
check("...and zero calendar writes", len(rig.calendar.writes), 0)
_p = rig.portal.calls[0]
check("payload names the booking", _p["booking_id"], 71)
check("payload says moved", _p["action"], "moved")
check("payload carries the new date", _p["date"], "2026-08-20")
check("payload carries the new start", _p["start_time"], "16:00")
check("payload carries the new end", _p["end_time"], "17:00")
check("payload carries the event id so the audit entry can name it", _p["event_id"], "ev1")
check("the run counts one sync", s["synced"], 1)
check("the syncToken advanced", rig.store[cs.KEY_SYNCTOKEN], {"token": "TOKEN-2"})
check("the new position is remembered",
      rig.store[cs.KEY_SEEN + "ev1"]["start"], "16:00")
check_true("#matt is told the portal followed", "booking #71" in rig.slack_text)


# ══════════════════════════════════════════════════════════════════════
section("2 · THREE RUNS OVER THE SAME STATE — the loop must terminate")

moved = event(start="16:00", end="17:00")
rig = Rig(FakeCalendar([{"items": [moved], "nextSyncToken": "TOKEN-2"},
                        {"items": [moved], "nextSyncToken": "TOKEN-3"},
                        {"items": [moved], "nextSyncToken": "TOKEN-4"}]),
          store=seeded())
r1 = cs.sync_once()
after_first = len(rig.portal.calls)
r2 = cs.sync_once()
r3 = cs.sync_once()
check("run 1 makes the one call it should", after_first, 1)
check("runs 2 and 3 make ZERO further WordPress calls", len(rig.portal.calls) - after_first, 0)
check("...and ZERO calendar writes across all three runs", len(rig.calendar.writes), 0)
check("run 2 syncs nothing", r2["synced"], 0)
check("run 3 syncs nothing", r3["synced"], 0)
check("run 2 recognises the event as already agreed", r2["skipped"], 1)


# ══════════════════════════════════════════════════════════════════════
section("3 · an event that already matches the row (loop guard, layer 2)")

rig = Rig(FakeCalendar([{"items": [event()], "nextSyncToken": "TOKEN-2"}]), store=seeded())
s = cs.sync_once()
check("zero WordPress calls", len(rig.portal.calls), 0)
check("zero calendar writes", len(rig.calendar.writes), 0)
check("counted as skipped, not synced", (s["skipped"], s["synced"]), (1, 0))
check("the token still advances — nothing failed", rig.store[cs.KEY_SYNCTOKEN], {"token": "TOKEN-2"})


# ══════════════════════════════════════════════════════════════════════
section("4 · a self-write marker under 90s (loop guard, layer 3)")

store = seeded()
store[cs.KEY_SELFWRITE + "ev1"] = {"at": (NOW - timedelta(seconds=30)).isoformat()}
rig = Rig(FakeCalendar([{"items": [event(start="16:00", end="17:00")], "nextSyncToken": "TOKEN-2"}]),
          store=store)
s = cs.sync_once()
check("the echo of our own write is skipped", len(rig.portal.calls), 0)
check("...and counted as skipped", s["skipped"], 1)

store2 = seeded()
store2[cs.KEY_SELFWRITE + "ev1"] = {"at": (NOW - timedelta(seconds=600)).isoformat()}
rig = Rig(FakeCalendar([{"items": [event(start="16:00", end="17:00")], "nextSyncToken": "TOKEN-2"}]),
          store=store2)
cs.sync_once()
check("a marker older than 90s does NOT suppress a real drag", len(rig.portal.calls), 1)


# ══════════════════════════════════════════════════════════════════════
section("5 · an event with no booking id is ignored entirely")

rig = Rig(FakeCalendar([{"items": [event(eid="own1", bid_text="Michael — personal shoot")],
                         "nextSyncToken": "TOKEN-2"}]),
          store={cs.KEY_SYNCTOKEN: {"token": "TOKEN-1"}})
s = cs.sync_once()
check("no WordPress call", len(rig.portal.calls), 0)
check("no booking is invented for it", s["synced"], 0)
check("nothing is adopted for it either", s["adopted"], 0)
check("it is simply skipped", s["skipped"], 1)


# ══════════════════════════════════════════════════════════════════════
section("6 · '#61-r1' after an admin edit still means booking 61")

check("the digits before the '-' are the booking",
      cs.booking_id_from_description("Studio Package portal booking #61-r1"), 61)
rig = Rig(FakeCalendar([{"items": [event(eid="ev61", bid_text="Studio Package portal booking #61-r1",
                                         start="16:00", end="17:00")],
                         "nextSyncToken": "TOKEN-2"}]),
          store=seeded(eid="ev61", bid=61))
cs.sync_once()
check("...and the portal is told about booking 61", rig.portal.calls[0]["booking_id"], 61)


# ══════════════════════════════════════════════════════════════════════
section("7 · a mangled description cannot orphan a booking")

store = seeded(eid="ev9", bid=71)
store[cs.KEY_EVENT + "ev9"] = {"booking_id": 71}      # reverse index, written at create time
rig = Rig(FakeCalendar([{"items": [event(eid="ev9", bid_text="(Michael retyped this by hand)",
                                         start="16:00", end="17:00")],
                         "nextSyncToken": "TOKEN-2"}]),
          store=store)
cs.sync_once()
check("the reverse index resolves it anyway", len(rig.portal.calls), 1)
check("...to the right booking", rig.portal.calls[0]["booking_id"], 71)


# ══════════════════════════════════════════════════════════════════════
section("8 · stretching an event 1h -> 1.5h moves the hours too")

rig = Rig(FakeCalendar([{"items": [event(start="14:15", end="15:45")], "nextSyncToken": "TOKEN-2"}]),
          store=seeded())
cs.sync_once()
_p = rig.portal.calls[0]
check("the new end time is sent", (_p["start_time"], _p["end_time"]), ("14:15", "15:45"))
_dur = ((int(_p["end_time"][:2]) * 60 + int(_p["end_time"][3:]))
        - (int(_p["start_time"][:2]) * 60 + int(_p["start_time"][3:]))) / 60.0
check("...which WordPress reads as duration 1.5", _dur, 1.5)


# ══════════════════════════════════════════════════════════════════════
section("9 · a DELETED event asks a question — it never cancels anything")

rig = Rig(FakeCalendar([{"items": [{"id": "ev1", "status": "cancelled"}], "nextSyncToken": "TOKEN-2"}]),
          FakePortal({"ok": True, "state": "ask", "booking_id": 71, "client": "Jonathan Pineda",
                      "question": "Booking #71 · Jonathan Pineda · Thu Aug 20, 14:15-15:15",
                      "yes_url": "https://mwmcreations.com/?a=yes",
                      "no_url": "https://mwmcreations.com/?a=no"}),
          store=seeded())
s = cs.sync_once()
check("exactly one call to the portal", len(rig.portal.calls), 1)
check("it takes the DELETION branch", rig.portal.calls[0]["action"], "deleted")
check("it never takes the move branch", [c for c in rig.portal.calls if c["action"] == "moved"], [])
check("it carries no times — a deleted event has none to carry",
      "start_time" in rig.portal.calls[0], False)
check("the run records that a question was asked", s["asked"], 1)
check("nothing was counted as synced", s["synced"], 0)
check_true("both answers reach Michael", "?a=yes" in rig.slack_text and "?a=no" in rig.slack_text)
check_true("...and he is told nothing has changed yet",
           "Nothing has changed yet" in rig.slack_text)

# The machine's OWN deletions — every wp-admin edit performs one — must never
# be read back as "Michael deleted it on his phone".
store = seeded()
store[cs.KEY_SELFDELETE + "ev1"] = {"at": (NOW - timedelta(days=3)).isoformat()}
rig = Rig(FakeCalendar([{"items": [{"id": "ev1", "status": "cancelled"}], "nextSyncToken": "TOKEN-2"}]),
          store=store)
s = cs.sync_once()
check("a deletion the machine performed is ignored, however old", len(rig.portal.calls), 0)
check("...and asks Michael nothing", s["asked"], 0)

# A stale event from before a reschedule is not the booking's event any more.
store = seeded(eid="old1", bid=71)
store[cs.KEY_CURRENT + "71"] = {"event_id": "new1"}
rig = Rig(FakeCalendar([{"items": [{"id": "old1", "status": "cancelled"}], "nextSyncToken": "TOKEN-2"}]),
          store=store)
s = cs.sync_once()
check("a stale event's deletion asks nothing", (len(rig.portal.calls), s["asked"]), (0, 0))

# A deleted event nobody has ever mapped to a booking is not our business.
rig = Rig(FakeCalendar([{"items": [{"id": "stranger", "status": "cancelled"}], "nextSyncToken": "TOKEN-2"}]),
          store={cs.KEY_SYNCTOKEN: {"token": "TOKEN-1"}})
check("an unknown deleted event is ignored", cs.sync_once()["asked"], 0)


# ══════════════════════════════════════════════════════════════════════
section("10 · warnings are relayed, and the run still counts as successful")

rig = Rig(FakeCalendar([{"items": [event(start="16:00", end="17:00")], "nextSyncToken": "TOKEN-2"}]),
          FakePortal({"ok": True, "state": "updated", "booking_id": 71, "client": "Jonathan Pineda",
                      "warnings": ["Overlaps booking #68 (16:00-17:00) — saved anyway.",
                                   "Jonathan Pineda is now 1.50 hours OVER contract."]}),
          store=seeded())
s = cs.sync_once()
check("the write counted", s["synced"], 1)
check("nothing failed", s["failed"], 0)
check_true("the overlap reached #matt", "Overlaps booking #68" in rig.slack_text)
check_true("so did the over-contract warning", "OVER contract" in rig.slack_text)
check("the token advanced — warnings are not failures",
      rig.store[cs.KEY_SYNCTOKEN], {"token": "TOKEN-2"})

# A refusal is flagged once and does not re-fire every two minutes forever.
rig = Rig(FakeCalendar([{"items": [event(start="16:00", end="17:00")], "nextSyncToken": "TOKEN-2"}]),
          FakePortal({"ok": True, "state": "refused", "booking_id": 71,
                      "message": "Booking #71 could not follow the calendar: past midnight."}),
          store=seeded())
s = cs.sync_once()
check("a refusal is not a failure", s["failed"], 0)
check_true("...but it is said out loud", "could not follow the calendar" in rig.slack_text)


# ══════════════════════════════════════════════════════════════════════
section("11 · WordPress returns 500 — THE SYNCTOKEN MUST NOT ADVANCE")

rig = Rig(FakeCalendar([{"items": [event(start="16:00", end="17:00")], "nextSyncToken": "TOKEN-2"}]),
          FakePortal(raises=RuntimeError("WP calendar-sync HTTP 500: <html>fatal</html>")),
          store=seeded())
s = cs.sync_once()
check("the failure is counted", s["failed"], 1)
check("nothing is recorded as synced", s["synced"], 0)
check("THE TOKEN DID NOT ADVANCE", rig.store[cs.KEY_SYNCTOKEN], {"token": "TOKEN-1"})
check("the old position is still what we believe", rig.store[cs.KEY_SEEN + "ev1"]["start"], "14:15")
check("the failure is reported, not swallowed", len(rig.errors), 1)
check_true("#dev is told the row did not follow", "did NOT follow" in rig.slack_text)

# Next tick, same old token — the change is offered again and this time lands.
rig.calendar.responses.append({"items": [event(start="16:00", end="17:00")], "nextSyncToken": "TOKEN-2"})
rig.portal.raises = None
s2 = cs.sync_once()
check("the retry re-lists with the SAME token",
      rig.calendar.list_calls[-1].get("syncToken"), "TOKEN-1")
check("the change lands on the retry", s2["synced"], 1)
check("and only now does the token advance", rig.store[cs.KEY_SYNCTOKEN], {"token": "TOKEN-2"})


# ══════════════════════════════════════════════════════════════════════
section("12 · a 410 GONE falls back to a bounded re-list, and survives")

rig = Rig(FakeCalendar([HttpishError(410, "Sync token is no longer valid")]), store=seeded())
s = cs.sync_once()
check("the loop does not crash", s["failed"], 0)
check("the dead token is dropped", rig.store[cs.KEY_SYNCTOKEN], {})
check_true("a repair is armed for the next tick", rig.store[cs.KEY_REPAIR])
check_true("#dev is told, so an expiry is never silent", "token expired" in rig.slack_text)

# Next tick: the bounded window is re-listed, the drag we were blind to lands,
# and only then is a fresh token taken.
rig.calendar.responses.append({"items": [event(start="16:00", end="17:00")]})   # the repair re-list
rig.calendar.responses.append({"items": [event(start="16:00", end="17:00")],
                               "nextSyncToken": "TOKEN-FRESH"})                 # the re-bootstrap
s2 = cs.sync_once()
_relist = rig.calendar.list_calls[-2]
check("the re-list is bounded, not the whole calendar",
      ("timeMin" in _relist and "timeMax" in _relist), True)
check("it starts 7 days back", _relist["timeMin"][:10], (NOW - timedelta(days=7)).strftime("%Y-%m-%d"))
check("...and ends 90 days out", _relist["timeMax"][:10], (NOW + timedelta(days=90)).strftime("%Y-%m-%d"))
check("the change we were blind to is synced", s2["synced"], 1)
check("a fresh token is taken", rig.store[cs.KEY_SYNCTOKEN], {"token": "TOKEN-FRESH"})
check("the repair flag is cleared", rig.store[cs.KEY_REPAIR], {})

# If the portal is down during the repair, the repair stays armed.
rig = Rig(FakeCalendar([{"items": [event(start="16:00", end="17:00")]}]),
          FakePortal(raises=RuntimeError("connection refused")),
          store=dict(seeded(), **{cs.KEY_REPAIR: {"at": NOW.isoformat()}}))
s = cs.sync_once()
check("a repair that could not complete stays armed", bool(rig.store[cs.KEY_REPAIR]), True)


# ══════════════════════════════════════════════════════════════════════
section("13 · the first tick ever adopts the calendar — it does not replay it")

rig = Rig(FakeCalendar([{"items": [event(), event(eid="ev2", bid_text="Studio Package portal booking #72",
                                                 date="2026-08-21", start="10:00", end="12:00"),
                                   event(eid="own", bid_text="Michael — personal")],
                         "nextSyncToken": "TOKEN-FIRST"}]),
          store={})
s = cs.sync_once()
check("a bootstrap writes NOTHING to the portal", len(rig.portal.calls), 0)
check("it adopts only the events that are bookings", s["adopted"], 2)
check("it takes a token", rig.store[cs.KEY_SYNCTOKEN], {"token": "TOKEN-FIRST"})
check("and remembers where each booking's event sits",
      rig.store[cs.KEY_SEEN + "ev2"]["end"], "12:00")
check("the reverse index is filled in on the way past",
      rig.store[cs.KEY_EVENT + "ev2"], {"booking_id": 72})

# From there, a drag is a change — the adopted state is what makes it visible.
rig.calendar.responses.append({"items": [event(start="16:00", end="17:00")], "nextSyncToken": "TOKEN-2"})
check("the next drag after a bootstrap does reach the portal", cs.sync_once()["synced"], 1)


# ══════════════════════════════════════════════════════════════════════
section("14 · the switch is off by default")

_saved = os.environ.pop("MWM_GCAL_SYNC_ENABLED", None)
check("with the env var unset the rail is inert", cs.enabled(), False)
rig = Rig(FakeCalendar([{"items": [event(start="16:00", end="17:00")], "nextSyncToken": "T"}]),
          store=seeded())
s = cs.sync_once()
check("...and a tick does nothing at all", (len(rig.portal.calls), len(rig.calendar.list_calls)), (0, 0))
check("it says so plainly", s["mode"], "disabled")
os.environ["MWM_GCAL_SYNC_ENABLED"] = _saved or "1"
check("'0' is off", (os.environ.update({"MWM_GCAL_SYNC_ENABLED": "0"}), cs.enabled())[1], False)
check("'on' is on", (os.environ.update({"MWM_GCAL_SYNC_ENABLED": "on"}), cs.enabled())[1], True)


# ══════════════════════════════════════════════════════════════════════
section("15 · remember_event — the three writes the reverse direction needs")

rig = Rig()
cs.remember_event("71", "evNEW", date="2026-08-20", start="14:15", end="15:15")
check("event -> booking", rig.store[cs.KEY_EVENT + "evNEW"], {"booking_id": 71})
check("booking -> current event", rig.store[cs.KEY_CURRENT + "71"], {"event_id": "evNEW"})
check("and the position we just wrote", rig.store[cs.KEY_SEEN + "evNEW"]["start"], "14:15")
check_true("plus a self-write marker so our own echo dies", cs.is_self_write("evNEW"))
cs.remember_event("61-r1", "evR", date="2026-08-20", start="09:00", end="10:00")
check("a reschedule id maps back to the plain booking",
      rig.store[cs.KEY_EVENT + "evR"], {"booking_id": 61})


# A gate line the autodeploy runner can grep for exactly. "0 failed" is a
# substring of "10 failed", so the count alone is not a safe gate.
# ══════════════════════════════════════════════════════════════════════
section("16 · PATCH #99 — the tick can be asked what it did")

# Aug 15, 07:50 ET: the switch went on, a real event was dragged 12:00 -> 15:00
# on the live calendar, the booking row did not follow, and NOTHING could say
# why. No Slack, no error, no counter. Reconciliation could see the drift; the
# sync itself could not be questioned. These assertions exist so that never
# costs an hour again.

def _reset():
    cs._CONSECUTIVE_BOOTSTRAPS = 0
    cs._NO_PERSISTENCE_ALERTED = False

_reset()
os.environ["MWM_GCAL_SYNC_ENABLED"] = "1"
rig = Rig(FakeCalendar([{"items": [event(start="16:00", end="17:00")], "nextSyncToken": "T2"}]),
          store=seeded())
cs.sync_once()
check("an incremental tick records its mode", cs.last_run()["mode"], "incremental")
check("...and what it synced", cs.last_run()["synced"], 1)
check_true("...and when", cs.last_run()["at"])

_reset()
_saved = os.environ.pop("MWM_GCAL_SYNC_ENABLED", None)
rig = Rig(store=seeded())
cs.sync_once()
check("a disabled tick says so out loud rather than looking like silence",
      cs.last_run()["mode"], "disabled")
os.environ["MWM_GCAL_SYNC_ENABLED"] = _saved or "1"

# 🔴 The failure mode that cost the live test. pg_store NEVER raises — it
# returns the default on any failure. So a token that cannot be written means
# every tick bootstraps, re-adopts the calendar's CURRENT state, and applies
# nothing. A drag is absorbed rather than synced, and from outside that is
# identical to "nothing happened".
_reset()
rig = Rig(FakeCalendar([{"items": [event()], "nextSyncToken": "T1"},
                        {"items": [event()], "nextSyncToken": "T2"},
                        {"items": [event()], "nextSyncToken": "T3"}]),
          store={})
rig._save = lambda k, v: False          # writes silently go nowhere
cs.configure(pg_save=rig._save)
s1 = cs.sync_once()
check("tick 1 bootstraps", s1["mode"], "bootstrap")
check("...and notices the token did not come back", s1["token_persisted"], False)
check("one bootstrap alone does not cry wolf — a first run is a bootstrap",
      "inert" in rig.slack_text, False)
s2 = cs.sync_once()
check("tick 2 bootstraps AGAIN, which is the tell", s2["mode"], "bootstrap")
check("...and it is counted", s2["consecutive_bootstraps"], 2)
check_true("#dev is told the sync is inert", "Calendar sync is inert" in rig.slack_text)
check_true("...and told the consequence in plain words",
           "absorbed, not synced" in rig.slack_text)
check_true("...and where to look", "DATABASE_URL" in rig.slack_text)
_before = rig.slack_text.count("inert")
cs.sync_once()
check("it says it once, not every two minutes forever",
      rig.slack_text.count("inert"), _before)

# With a store that works, the same first tick is unremarkable.
_reset()
rig = Rig(FakeCalendar([{"items": [event()], "nextSyncToken": "T1"},
                        {"items": [event()], "nextSyncToken": "T2"}]), store={})
s1 = cs.sync_once()
check("a bootstrap that persists reports so", s1["token_persisted"], True)
s2 = cs.sync_once()
check("...and the next tick is incremental, not another bootstrap", s2["mode"], "incremental")
check("...so the counter is back to zero", cs._CONSECUTIVE_BOOTSTRAPS, 0)
check_true("nothing was cried about", "inert" not in rig.slack_text)


print("\nS28_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))

print("\n" + "=" * 60)
print("  TOTAL: {} passed, {} failed".format(_passed, _failed))
if _FAILS:
    for f in _FAILS:
        print("   -", f)
print("=" * 60)
sys.exit(1 if _failed else 0)
