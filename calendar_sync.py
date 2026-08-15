#!/usr/bin/env python3
"""calendar_sync.py — S28: Google Calendar -> portal sync.

THE ONE IDEA (spec Part 0)
==========================
The booking row stays the only source of truth. The calendar is an INPUT
DEVICE, not a second truth. A drag is Michael expressing an intention; that
intention is run through admin_write_booking() in WordPress and the row is what
comes out the other side.

And because the change CAME FROM the calendar, the calendar is already in the
target state. There is nothing to push back. So the WordPress write carries
`push_calendar => false`: the event does not blink, keeps its id, and no
cancellation notice or fresh invite reaches the client.

WHY POLLING AND NOT PUSH (spec Part 1)
======================================
Google push notifications need the receiving URL on a domain verified in the
Google Cloud project. The machine lives on railway.app, which Michael does not
own and cannot verify. Polling every 2 minutes costs 720 calls/day against a
quota in the millions, and with a syncToken almost every one of them returns an
empty change list. Push stays available later; only the trigger would change.

DEPENDENCIES: none beyond the standard library, on purpose. Everything that
needs the network — the Google client, the HTTP POST to WordPress, Slack — is
injected by app.py through configure(). That is what lets test_calendar_sync.py
run the whole rail with /usr/bin/python3 and no packages installed.

THE LOOP GUARD, THREE LAYERS (spec 3.1)
=======================================
1. DESIGN. A calendar-sourced write sets push_calendar => false, so it cannot
   cause a calendar write, so it cannot cause another change to notice.
2. COMPARE BEFORE ACTING. Never act on an event whose times already agree with
   what we last synced for it. The machine cannot read the booking row
   directly, so the comparison is against the snapshot WordPress returned on
   the last successful sync of that event -- and WordPress repeats the check
   against the real row and answers "unchanged" without writing. Two cheap
   checks, and the authoritative one is the one that owns the row.
3. SELF-WRITE MARKER. When the machine writes an event it stamps
   studio_gcal_selfwrite:{event_id}; changes inside 90s are ignored. Deletions
   the machine performs are stamped studio_gcal_selfdelete:{event_id} and
   ignored forever -- an admin edit in wp-admin deletes the old event and
   creates a new one, and that delete must never read as "Michael cancelled".

NOTHING HERE RUNS UNTIL MWM_GCAL_SYNC_ENABLED IS SET. Ships dark on purpose.
"""

import os
import re
from datetime import datetime, timedelta, timezone as _dt_timezone

HEARTBEAT_NAME = "gcal_sync"
CYCLE_SECONDS = 120
SELFWRITE_WINDOW_SECONDS = 90
RELIST_BACK_DAYS = 7
RELIST_FORWARD_DAYS = 90
PAGE_SIZE = 2500
MAX_PAGES = 40          # blast-radius bound on a runaway pagination loop

# pg_store keys. pg_store has no key scan and no delete, so every key is
# addressable by id and "cleared" by writing an empty dict (which loads falsy).
KEY_SYNCTOKEN = "studio_gcal_synctoken"
KEY_REPAIR = "studio_gcal_repair_pending"
KEY_SEEN = "studio_gcal_seen:"        # event_id  -> last synced {date,start,end}
KEY_EVENT = "studio_gcal_event:"      # event_id  -> {"booking_id": N}   (reverse index)
KEY_CURRENT = "studio_gcal_current:"  # booking_id-> {"event_id": "..."} (current event)
KEY_SELFWRITE = "studio_gcal_selfwrite:"
KEY_SELFDELETE = "studio_gcal_selfdelete:"

ACTION_MOVED = "moved"
ACTION_DELETED = "deleted"

_deps = {}

# PATCH #99 — what the last tick actually did. S28 shipped with no way to ask.
# Aug 15 07:50: the switch went on, a real event was dragged 12:00 -> 15:00, the
# row did not follow, and nothing anywhere said why: no Slack, no error, no
# counter. Reconciliation could see the drift; the sync could not be questioned.
# That is the same defect Patch #97 fixed in the lead rows, shipped by the same
# hand twelve hours later. An instrument is not optional.
_LAST = {"mode": "never run", "at": None}
_CONSECUTIVE_BOOTSTRAPS = 0
_NO_PERSISTENCE_ALERTED = False


def last_run():
    """Read by /health. Never raises, never empty."""
    return dict(_LAST)


def configure(**kwargs):
    """Inject app.py's collaborators.

    Required: calendar_service (callable -> Google service), calendar_id,
              wp_post (callable(payload dict) -> dict, raises on failure),
              pg_load, pg_save, post_slack, report_error, heartbeat,
              matt_channel, dev_channel
    Optional: to_local (callable(aware datetime) -> local aware datetime),
              now (callable -> aware datetime; tests inject a fixed clock)
    """
    _deps.update(kwargs)


# ── plumbing ────────────────────────────────────────────────────────────

def enabled():
    """Ships dark. Michael turns this on deliberately, after the code is live."""
    return os.getenv("MWM_GCAL_SYNC_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def _report(ctx, exc, detail=""):
    fn = _deps.get("report_error")
    if fn:
        try:
            fn("calendar_sync." + ctx, exc, detail)
            return
        except Exception:
            pass
    print("[GCAL SYNC] {}: {} {}".format(ctx, exc, detail))


def _slack(channel_key, text):
    fn = _deps.get("post_slack")
    ch = _deps.get(channel_key)
    if fn and ch:
        try:
            fn(ch, text)
        except Exception as exc:
            print("[GCAL SYNC] slack post failed: {}".format(exc))


def _load(key, default=None):
    fn = _deps.get("pg_load")
    if not fn:
        return default
    try:
        return fn(key, default)
    except Exception as exc:
        _report("pg_load", exc, key)
        return default


def _save(key, value):
    fn = _deps.get("pg_save")
    if not fn:
        return False
    try:
        return fn(key, value)
    except Exception as exc:
        _report("pg_save", exc, key)
        return False


def _now():
    fn = _deps.get("now")
    if fn:
        return fn()
    return datetime.now(_dt_timezone.utc)


# ── pure helpers (the unit-testable core) ───────────────────────────────

_BOOKING_RE = re.compile(r"portal\s+booking\s+#\s*(\d+)", re.IGNORECASE)


def booking_id_from_description(description):
    """Every event the machine has ever created carries
    'Studio Package portal booking #NN' on line 1. After an admin edit the id
    reads '#61-r1' -- the digits before the '-' are the booking. Anything with
    no such marker is Michael's own shoot, a studio visit, the Victory block:
    not a booking, and it must never be turned into one.
    """
    if not description:
        return None
    m = _BOOKING_RE.search(str(description))
    if not m:
        return None
    try:
        bid = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return bid if bid > 0 else None


def _parse_dt(raw):
    """Google returns '2026-08-20T14:15:00-04:00'. Python 3.8 fromisoformat
    chokes on a trailing 'Z', so normalise it. Returns an aware datetime."""
    if not raw:
        return None
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def _to_local(dt):
    fn = _deps.get("to_local")
    if fn:
        try:
            return fn(dt)
        except Exception as exc:
            _report("to_local", exc)
    # Fallback: the offset Google already put in the string. Every event on the
    # MWM CREATIONS calendar is written in America/New_York, so the wall clock
    # in the payload IS the studio's wall clock.
    return dt


def event_times(event):
    """(date, start HH:MM, end HH:MM) in studio-local time, or None.

    All-day events have 'date' rather than 'dateTime' and are ignored: a
    booking is never an all-day event, and treating one as a move would drag a
    real session onto midnight.
    """
    if not isinstance(event, dict):
        return None
    start = (event.get("start") or {}).get("dateTime")
    end = (event.get("end") or {}).get("dateTime")
    sdt = _parse_dt(start)
    edt = _parse_dt(end)
    if not sdt or not edt:
        return None
    sdt = _to_local(sdt)
    edt = _to_local(edt)
    return (sdt.strftime("%Y-%m-%d"), sdt.strftime("%H:%M"), edt.strftime("%H:%M"))


def resolve_booking_id(event):
    """Reverse index first (a human editing the description cannot orphan a
    booking), description second (covers 100% of existing events, no migration).
    """
    eid = (event or {}).get("id")
    if eid:
        rec = _load(KEY_EVENT + str(eid))
        if isinstance(rec, dict) and rec.get("booking_id"):
            try:
                return int(rec["booking_id"])
            except (TypeError, ValueError):
                pass
    return booking_id_from_description((event or {}).get("description"))


def _age_seconds(stamp):
    dt = _parse_dt(stamp)
    if not dt:
        return None
    try:
        return (_now() - dt).total_seconds()
    except Exception:
        return None


def is_self_write(event_id):
    """Layer 3 -- the narrow race where a change is processed while
    WordPress's own write is still in flight."""
    rec = _load(KEY_SELFWRITE + str(event_id))
    if not isinstance(rec, dict):
        return False
    age = _age_seconds(rec.get("at"))
    return age is not None and 0 <= age < SELFWRITE_WINDOW_SECONDS


def mark_self_write(event_id):
    _save(KEY_SELFWRITE + str(event_id), {"at": _now().isoformat()})


def mark_self_delete(event_id):
    """Permanent, not windowed. The machine deletes an event whenever wp-admin
    edits or cancels a booking; that deletion must never be read back as
    'Michael deleted the event on his phone'."""
    _save(KEY_SELFDELETE + str(event_id), {"at": _now().isoformat()})


def remember_event(booking_id, event_id, date=None, start=None, end=None):
    """Called by app.py every time the machine creates an event. Three tiny
    writes that make the reverse direction possible at all."""
    if not booking_id or not event_id:
        return
    try:
        bid = int(str(booking_id).split("-")[0])
    except (TypeError, ValueError):
        return
    eid = str(event_id)
    _save(KEY_EVENT + eid, {"booking_id": bid})
    _save(KEY_CURRENT + str(bid), {"event_id": eid})
    if date and start and end:
        _save(KEY_SEEN + eid, {"date": date, "start": start, "end": end, "booking_id": bid})
    mark_self_write(eid)


def _snapshot_matches(seen, times):
    if not isinstance(seen, dict):
        return False
    return (seen.get("date") == times[0]
            and seen.get("start") == times[1]
            and seen.get("end") == times[2])


def is_gone_error(exc):
    """Google says 410 GONE when a syncToken has expired."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is not None:
        try:
            return int(status) == 410
        except (TypeError, ValueError):
            pass
    text = str(exc)
    return "410" in text and ("gone" in text.lower() or "syncToken" in text)


# ── the sync itself ─────────────────────────────────────────────────────

def _blank_summary():
    return {"listed": 0, "synced": 0, "asked": 0, "adopted": 0,
            "skipped": 0, "failed": 0, "wp_calls": 0, "mode": ""}


def _service():
    fn = _deps.get("calendar_service")
    return fn() if fn else None


def _calendar_id():
    return _deps.get("calendar_id") or ""


def _list(svc, **params):
    """Page through events.list. Returns (items, next_sync_token)."""
    items = []
    token = None
    page = None
    for _ in range(MAX_PAGES):
        call = dict(params)
        if page:
            call["pageToken"] = page
        resp = svc.events().list(calendarId=_calendar_id(), **call).execute(num_retries=3)
        items.extend(resp.get("items", []) or [])
        token = resp.get("nextSyncToken") or token
        page = resp.get("nextPageToken")
        if not page:
            break
    return items, token


def _bootstrap(svc, summary):
    """No token yet: adopt the calendar's current state and take a token.

    Deliberately writes ZERO bookings. Without snapshots every event looks like
    a change, and a first tick that "syncs" the whole calendar into WordPress
    is how a quiet feature becomes a loud incident.
    """
    summary["mode"] = "bootstrap"
    items, token = _list(svc, singleEvents=True, showDeleted=False, maxResults=PAGE_SIZE)
    summary["listed"] += len(items)
    for ev in items:
        bid = resolve_booking_id(ev)
        if not bid:
            continue
        times = event_times(ev)
        if not times:
            continue
        eid = str(ev.get("id") or "")
        if not eid:
            continue
        _save(KEY_EVENT + eid, {"booking_id": bid})
        _save(KEY_SEEN + eid, {"date": times[0], "start": times[1],
                               "end": times[2], "booking_id": bid})
        summary["adopted"] += 1
    if token:
        _save(KEY_SYNCTOKEN, {"token": token})
    print("[GCAL SYNC] bootstrap adopted {} booking event(s) of {} listed".format(
        summary["adopted"], summary["listed"]))
    return summary


def _repair(svc, summary):
    """A syncToken expired. Re-list a BOUNDED window (spec: today-7 -> +90) and
    act on anything that moved while we were blind. Never a full-calendar sync:
    the calendar has years of history and none of it needs replaying."""
    summary["mode"] = "repair"
    now = _now()
    lo = (now - timedelta(days=RELIST_BACK_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    hi = (now + timedelta(days=RELIST_FORWARD_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    items, _ = _list(svc, singleEvents=True, showDeleted=False, maxResults=PAGE_SIZE,
                     timeMin=lo, timeMax=hi, orderBy="startTime")
    summary["listed"] = len(items)
    for ev in items:
        _handle_event(ev, summary, adopt_unknown=True)
    return summary


def _handle_event(event, summary, adopt_unknown=True):
    eid = str((event or {}).get("id") or "")
    if not eid:
        summary["skipped"] += 1
        return
    if (event or {}).get("status") == "cancelled":
        return _handle_deletion(eid, summary)

    bid = resolve_booking_id(event)
    if not bid:
        summary["skipped"] += 1      # Michael's own shoots, studio visits, the Victory block
        return
    times = event_times(event)
    if not times:
        summary["skipped"] += 1      # all-day or malformed: never a booking
        return
    if is_self_write(eid):
        summary["skipped"] += 1      # layer 3
        return

    seen = _load(KEY_SEEN + eid)
    if not isinstance(seen, dict) or not seen:
        # Never seen this event before. Adopt its position rather than assume it
        # moved -- see _bootstrap for why.
        if adopt_unknown:
            _save(KEY_EVENT + eid, {"booking_id": bid})
            _save(KEY_SEEN + eid, {"date": times[0], "start": times[1],
                                   "end": times[2], "booking_id": bid})
            summary["adopted"] += 1
            return
    elif _snapshot_matches(seen, times):
        summary["skipped"] += 1      # layer 2 -- this is the layer that must never be removed
        return

    payload = {
        "booking_id": bid,
        "event_id": eid,
        "action": ACTION_MOVED,
        "date": times[0],
        "start_time": times[1],
        "end_time": times[2],
    }
    try:
        summary["wp_calls"] += 1
        resp = _deps["wp_post"](payload) or {}
    except Exception as exc:
        summary["failed"] += 1
        _report("wp_post", exc, "booking={} event={}".format(bid, eid))
        _slack("dev_channel",
               ":red_circle: *Calendar sync could not reach WordPress* — booking #{} "
               "moved to {} {}–{} on the calendar and the row did NOT follow. "
               "The syncToken was not advanced, so this retries in {}s.\n`{}`".format(
                   bid, times[0], times[1], times[2], CYCLE_SECONDS, str(exc)[:200]))
        return

    if not resp.get("ok"):
        summary["failed"] += 1
        _report("wp_refused", resp.get("message") or resp.get("error") or "no reason given",
                "booking={} event={}".format(bid, eid))
        return

    state = resp.get("state") or "updated"
    row = resp.get("booking") or {}
    _save(KEY_EVENT + eid, {"booking_id": bid})
    _save(KEY_SEEN + eid, {
        "date": row.get("date") or times[0],
        "start": row.get("start") or times[1],
        "end": row.get("end") or times[2],
        "booking_id": bid,
    })
    if state == "updated":
        summary["synced"] += 1
        who = resp.get("client") or "booking #{}".format(bid)
        _slack("matt_channel",
               ":calendar: *Moved on Google Calendar — the portal followed.* {} · booking #{} "
               "is now {} {}–{}. Hours and the reminder moved with it.".format(
                   who, bid, times[0], times[1], times[2]))
    elif state == "refused":
        # Accepted-and-flagged is the policy; a refusal is the rare case where the
        # row physically cannot hold what the calendar now says. Say so once.
        summary["skipped"] += 1
        _slack("matt_channel", ":warning: *The portal could not follow the calendar.* {}".format(
            resp.get("message") or "Booking #{} was left where it was.".format(bid)))
    else:
        summary["skipped"] += 1      # WordPress found the row already correct

    for w in (resp.get("warnings") or []):
        _slack("matt_channel", ":warning: *Booking #{}* — {}".format(bid, w))


def _handle_deletion(event_id, summary):
    """A deletion is a QUESTION, not a command (spec 4.1). Nothing is cancelled,
    no hours move, no email reaches the client until Michael answers."""
    if _load(KEY_SELFDELETE + event_id):
        summary["skipped"] += 1      # we deleted it ourselves (admin edit or cancel)
        return
    if is_self_write(event_id):
        summary["skipped"] += 1
        return
    rec = _load(KEY_EVENT + event_id)
    if not isinstance(rec, dict) or not rec.get("booking_id"):
        summary["skipped"] += 1      # not a booking event
        return
    bid = int(rec["booking_id"])
    cur = _load(KEY_CURRENT + str(bid))
    if isinstance(cur, dict) and cur.get("event_id") and str(cur["event_id"]) != event_id:
        summary["skipped"] += 1      # a stale event from before a reschedule
        return

    try:
        summary["wp_calls"] += 1
        resp = _deps["wp_post"]({"booking_id": bid, "event_id": event_id,
                                 "action": ACTION_DELETED}) or {}
    except Exception as exc:
        summary["failed"] += 1
        _report("wp_post_delete", exc, "booking={} event={}".format(bid, event_id))
        return

    if not resp.get("ok"):
        summary["failed"] += 1
        _report("wp_refused_delete", resp.get("message") or "no reason given",
                "booking={}".format(bid))
        return

    if resp.get("state") != "ask":
        summary["skipped"] += 1      # already cancelled, or not a live booking
        return

    summary["asked"] += 1
    _save(KEY_SEEN + event_id, {})
    _slack("matt_channel",
           "{}\n\n<{}|✅ Yes, cancel it>     <{}|↩️ No, put it back>\n\n"
           "_Nothing has changed yet. Until you tap one, the booking stands and "
           "the morning drift check will keep flagging the missing event._".format(
               resp.get("question") or "You deleted the calendar event for booking #{}.".format(bid),
               resp.get("yes_url") or "", resp.get("no_url") or ""))


def sync_once():
    """One tick. Returns a summary dict; never raises."""
    summary = _blank_summary()
    if not enabled():
        summary["mode"] = "disabled"
        return _record(summary)
    svc = _service()
    if svc is None:
        summary["mode"] = "no-service"
        return _record(summary)

    try:
        if _load(KEY_REPAIR):
            _repair(svc, summary)
            if summary["failed"]:
                return _record(summary)      # retry the whole window next tick
            _save(KEY_REPAIR, {})

        rec = _load(KEY_SYNCTOKEN)
        token = rec.get("token") if isinstance(rec, dict) else None
        if not token:
            # No early return: the tail of this function is what records the
            # tick and checks that the token persisted. A bootstrap that skips
            # both is a bootstrap nobody can see — which is precisely how S28
            # spent its first hour live being unquestionable.
            _bootstrap(svc, summary)
        else:
            summary["mode"] = "incremental"
            try:
                items, new_token = _list(svc, syncToken=token, singleEvents=True,
                                         showDeleted=True)
            except Exception as exc:
                if is_gone_error(exc):
                    # Drop the token and arm a bounded repair for the next tick.
                    _save(KEY_SYNCTOKEN, {})
                    _save(KEY_REPAIR, {"at": _now().isoformat()})
                    print("[GCAL SYNC] syncToken expired (410) — bounded re-list armed")
                    _slack("dev_channel",
                           ":arrows_counterclockwise: *Calendar sync token expired* — "
                           "re-listing today\u2212{}d \u2192 +{}d on the next tick, then taking a "
                           "fresh token. No changes were lost.".format(
                               RELIST_BACK_DAYS, RELIST_FORWARD_DAYS))
                    summary["mode"] = "token-expired"
                    return _record(summary)
                raise

            summary["listed"] += len(items)
            for ev in items:
                _handle_event(ev, summary, adopt_unknown=True)

            # \U0001f534 THE RULE THAT MATTERS MOST (spec test 11): never advance the
            # token until WordPress has confirmed every write. Advancing past a
            # failure loses that change forever, and silence is the defect this
            # whole project exists to kill.
            if new_token and not summary["failed"]:
                _save(KEY_SYNCTOKEN, {"token": new_token})
    except Exception as exc:
        summary["failed"] += 1
        _report("sync_once", exc, "mode={}".format(summary["mode"]))
    try:
        _check_persistence(summary)
    except Exception as exc:
        _report("check_persistence", exc)
    return _record(summary)


def _record(summary):
    """Stamp the tick so /health can be asked what happened."""
    global _LAST
    rec = dict(summary)
    try:
        rec["at"] = _now().isoformat()
    except Exception:
        rec["at"] = None
    _LAST = rec
    return summary


def _check_persistence(summary):
    """A syncToken that does not come back is a sync that can never act.

    pg_store never raises — it returns the default on any failure. So if
    DATABASE_URL is unset, or Postgres is unreachable, or the write is refused,
    every tick reads no token, runs the bootstrap again, adopts the calendar's
    CURRENT state as the baseline, and writes nothing. Forever. Silently. A drag
    would be absorbed rather than applied, which is indistinguishable from
    'nothing happened' to anyone watching from outside.

    So the bootstrap now reads its own token back, and says so when it cannot.
    """
    global _CONSECUTIVE_BOOTSTRAPS, _NO_PERSISTENCE_ALERTED
    if summary.get("mode") != "bootstrap":
        _CONSECUTIVE_BOOTSTRAPS = 0
        return
    _CONSECUTIVE_BOOTSTRAPS += 1
    rec = _load(KEY_SYNCTOKEN)
    persisted = isinstance(rec, dict) and bool(rec.get("token"))
    summary["token_persisted"] = persisted
    summary["consecutive_bootstraps"] = _CONSECUTIVE_BOOTSTRAPS
    if persisted or _NO_PERSISTENCE_ALERTED or _CONSECUTIVE_BOOTSTRAPS < 2:
        return
    _NO_PERSISTENCE_ALERTED = True
    _report("no_persistence",
            "syncToken did not survive a save/load round trip",
            "bootstrapped {} ticks in a row".format(_CONSECUTIVE_BOOTSTRAPS))
    _slack("dev_channel",
           ":red_circle: *Calendar sync is inert.* It has bootstrapped {} ticks "
           "running because the syncToken will not persist — pg_store returns "
           "the default on any failure, so every tick re-adopts the calendar "
           "and applies nothing. *A drag will be absorbed, not synced.* Check "
           "DATABASE_URL and Postgres reachability on the service.".format(
               _CONSECUTIVE_BOOTSTRAPS))


def loop():
    """Background thread. Heartbeat name: gcal_sync."""
    import time as _time
    hb = _deps.get("heartbeat")
    if not enabled():
        print("[GCAL SYNC] MWM_GCAL_SYNC_ENABLED is not set — loop idle (shipped dark)")
    else:
        print("[GCAL SYNC] Started — {}s cycle (S28: a drag on the calendar moves "
              "the booking)".format(CYCLE_SECONDS))
    _time.sleep(45)   # let the app finish booting before the first Google call
    while True:
        try:
            if hb:
                hb(HEARTBEAT_NAME)
            if enabled():
                s = sync_once()
                if s["synced"] or s["asked"] or s["failed"]:
                    print("[GCAL SYNC] {}".format(s))
        except Exception as exc:
            _report("loop", exc)
        _time.sleep(CYCLE_SECONDS)
