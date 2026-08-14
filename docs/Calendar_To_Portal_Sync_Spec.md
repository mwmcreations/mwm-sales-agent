# S28 — Google Calendar → Portal sync · BUILD PACK

**Written Thu Aug 13 2026, ~11 PM ET · for the build session tomorrow, which starts cold**
**Owner: DEV · Approved by Michael Aug 13 · Estimated: half a day**

Michael: *"if I need to change on Google Calendar the time for someone that has
booked… it's also now gonna move on the portal."*

Today the sync is one-way — WordPress writes, the calendar follows. Drag an event
in Google Calendar and the booking row does not move, the hours do not move, and
the reminder email still reads the old time. That is exactly how booking #61 told
Jonathan Pineda the wrong time. This closes the loop.

---

## PART 0 · READ THIS FIRST — THE ONE IDEA

**The booking row stays the only source of truth. The calendar becomes an INPUT
DEVICE, not a second truth.**

A drag is not "the calendar is now right." A drag is *Michael expressing an
intention*. That intention is run through the same rules every other change goes
through — `admin_write_booking()` — and the row is what comes out the other side.

🔑 **And here is the thing that makes this simple: when the change came FROM the
calendar, the calendar is already in the target state. There is nothing to push
back.** Update the row, move the ledger, write the audit entry — and stop.

That single observation removes almost all of the difficulty:

- no delete-and-recreate, so **the event does not blink** and does not change id;
- **no cancellation notice and no fresh invite to the client** for a simple move;
- the loop guard becomes nearly trivial, because in the happy path the machine
  never writes the calendar in response to a calendar change.

Build it any other way and you get an event that ping-pongs and a client whose
inbox fills with invites. Do not skip this section.

---

## PART 1 · 🔴 A FINDING THAT CHANGES THE DESIGN — POLL, DON'T PUSH

Yesterday I described this to Michael as Google *pushing* a notification to the
machine (`events.watch`). Having read the constraints properly, **polling is the
better engineering choice here, and I recommend it.**

Google Calendar push notifications require the receiving URL to be on a domain
**verified in the Google Cloud project**. The machine lives at
`mwm-sales-agent-production.up.railway.app`. Michael does not own `railway.app`
and therefore cannot verify it. Push would first require pointing a custom
domain — `machine.mwmcreations.com` — at Railway and verifying it. That is
doable (`mwmcreations.com` is already verified in Search Console) but it is a DNS
change, a TLS cert, and a verification step *before any of this feature works*.

Polling needs none of that, and it also deletes:

- channel registration,
- the channel-renewal loop (channels expire and must be re-registered),
- webhook authentication for Google's callback,
- replay/duplicate-delivery handling.

**Cost of polling every 2 minutes:** 720 API calls/day against a quota measured
in the millions, and with a `syncToken` each call returns an empty change list
when nothing has happened. It is nearly free.

**What Michael gives up:** a drag reflects in the portal in *up to 2 minutes*
instead of instantly. For "I moved someone's session," that is invisible.

**Decision: build polling. Push stays available** — Appendix A has what it would
take — and can be added later without changing anything else, because the sync
logic is identical; only the trigger differs.

---

## PART 2 · WHAT ALREADY EXISTS (verified in the code, Aug 13)

| Thing | Where | Notes |
|---|---|---|
| `admin_write_booking()` | plugin v2.7.0 | THE single write path. Row + calendar + audit in one operation. |
| `find_calendar_drift()` | plugin v2.7.0 | Shared by the Reconciliation screen and the daily cron. |
| `/webhook/studio-booking` | `app.py:15947` | WP → machine. Accepts **only** `booking_created` / `booking_cancelled` / `booking_cancelled_late`; **400s on anything else**. |
| `/studio-availability` | `app.py:15853` | machine → WP read feed. Already returns busy blocks per date. |
| `X-MWM-Portal-Secret` | both ends | Shared secret, already used in both directions. Reuse it. |
| `get_calendar_service(impersonate=…)` | `app.py` | **Must impersonate** `GOOGLE_DELEGATE_EMAIL` — a bare service account may not invite attendees (Patch #69). |
| `CALENDAR_ID`, `TIMEZONE`, `STUDIO_ADDRESS` | `app.py` | MWM CREATIONS calendar, America/New_York. |
| `pg_store.save_state / load_state` | `pg_store.py` | Simple KV. **No key scan, no prefix query** — design around that. |
| `studio_booking_gcal:{bid}` → `{event_id}` | pg_store | The **forward** map, written on every portal booking. |
| Recurring work on the machine | `app.py:18056`, `18166` | `threading.Thread(target=…_loop, daemon=True).start()` at import, `while True:` + sleep. **No APScheduler.** Follow this pattern; add no dependency. |
| Deploy pipeline | `.deploy/mwm_autodeploy.sh` | Write a `.patch` + `DEPLOY_REQUEST.json`; runs as Michael via launchd with SSH + network. **Tests gate the commit.** |

---

## PART 3 · ARCHITECTURE

```
  ┌────────────────────┐   every 2 min, syncToken
  │  Google Calendar   │◄──────────────────────────┐
  │  (MWM CREATIONS)   │                           │
  └─────────┬──────────┘                    ┌──────┴───────┐
            │ changed events                │ machine      │
            └──────────────────────────────►│ _gcal_sync   │
                                            │  _loop()     │
                                            └──────┬───────┘
                        POST /wp-json/mwm-studio/v1/calendar-sync
                        X-MWM-Portal-Secret               │
                                            ┌─────────────▼──────────────┐
                                            │ WordPress                  │
                                            │ admin_write_booking(       │
                                            │   push_calendar => false ) │
                                            │  → row + ledger + audit    │
                                            └────────────────────────────┘
```

### 3.1 The loop guard — three layers, in order of strength

**Layer 1 — the design (strongest).** A calendar-sourced change sets
`push_calendar => false`, so the machine's write does not cause a calendar write,
so it cannot cause another notification. In the happy path the loop has nowhere
to start.

**Layer 2 — compare before acting (state-free).** Before doing anything with a
changed event, read the booking row and compare `date / start / end`. **If they
already agree, return.** This catches every echo of the machine's own writes
(a cancel-and-recreate from an admin edit, for example) without storing anything.
This is the layer that must never be removed.

**Layer 3 — a self-write marker (belt and braces).** When the machine writes an
event, `save_state("studio_gcal_selfwrite:{event_id}", {"at": ts})`. Ignore any
change to that event within 90 seconds. Covers the narrow race where a
notification is processed while WordPress's own write is still in flight.

🔴 A test must prove termination: apply a drag, run the sync loop **three times**
in a row against the same state, and assert that runs 2 and 3 make **zero** WP
calls and **zero** calendar writes.

### 3.2 Mapping an event back to a booking

`pg_store` has no key scan, so a reverse index cannot be built by walking the
forward keys.

**Primary: parse the description.** Every event the machine has ever created
carries `Studio Package portal booking #NN` on line 1 (`#61-r1` form after an
edit — take the digits before the `-`). This covers **100% of existing events
with zero migration.** Verified against live events today.

**Hardening (do it, it is three lines): write the reverse key going forward.**
Whenever the machine creates an event, also
`save_state("studio_gcal_event:{event_id}", {"booking_id": bid})`. Look this up
first and fall back to the description, so a human editing the description text
cannot orphan a booking.

**Events with no booking id** — Michael's own shoots, studio visits, the Victory
block — are **ignored entirely**. They are not bookings and must never be turned
into one.

### 3.3 The new WordPress route

```
POST /wp-json/mwm-studio/v1/calendar-sync
Header: X-MWM-Portal-Secret: <shared secret>
Body:   { booking_id, event_id, action: "moved"|"deleted",
          date: "YYYY-MM-DD", start_time: "HH:MM", end_time: "HH:MM" }
```

Registered next to the existing Stripe webhook (`register_stripe_webhook()` is
the pattern to copy). It resolves the booking and calls:

```php
$this->admin_write_booking( $booking_id, array(
    'booking_date'   => $date,
    'start_time'     => $start_time,
    'duration_hours' => ( strtotime($end) - strtotime($start) ) / 3600,
), array(
    'action'         => 'booking.calendar_drag',
    'reason'         => 'Moved on Google Calendar',
    'actor'          => 'google-calendar',
    'push_calendar'  => false,   // ← NEW OPT, see 3.4
    'allow_conflict' => true,    // policy: accept and flag, never refuse
    'notify_client'  => false,
) );
```

Returns `{ok, booking_id, warnings[]}`. The machine relays `warnings` to Slack.

### 3.4 The one change to S26 — `push_calendar`

`admin_write_booking()` gains a single new option, `push_calendar` (default
**true**). When false it skips the two `push_booking_event()` calls and does not
bump `reschedule_count`. Everything else — validation, the overlap check, the
hours maths, the audit entry — runs exactly as before.

**Why this does not undo "one write path."** It is not skipping reconciliation;
it is recognising the reconciliation has already happened. The calendar is
*already* in the target state — that is where the change came from. Pushing
would delete the event Michael just dragged and replace it with an identical one
under a new id, e-mailing the client a cancellation and a fresh invite for no
reason.

⚠️ `push_calendar => false` must be reachable **only** from the calendar-sync
route. It must never be exposed in a form, a query string, or the quick-book
page. Add a comment saying so, because the next person will be tempted.

---

## PART 4 · POLICY — settled with Michael Aug 13

| Situation | Behaviour |
|---|---|
| Drag to a free slot | Row follows. Silent. Audit entry records who/when/before. |
| Drag onto another booking | **Accepted, flagged loudly** in Slack + email. Never silently refused — Michael is standing in a studio, not reading a validation error. |
| Drag past the client's contract end | Accepted, flagged. |
| Drag/stretch beyond remaining hours | Accepted, flagged. Ledger goes negative; Clients row already shows `OVER by N h` (S26). |
| Resize an event (duration change) | Same as a move. Hours follow. |
| **Delete the event** | **Booking is NOT cancelled — it asks first.** See 4.1. |
| Event with no `booking #NN` | Ignored. |
| Event on any other calendar | Ignored. Only `CALENDAR_ID`. |

### 4.1 Deletion — SETTLED (Michael, Aug 14)

**First, who can even do this.** The client is only an *attendee* on the event —
they do not own it. A client deleting it from their own calendar removes it from
*their* view and marks them **declined** on our copy; the studio calendar is
untouched. That is a different signal and the sync ignores it. A real deletion
means someone with write access to MWM CREATIONS deleted it, which in practice
means **Michael, on his phone**. So the realistic cases are "I meant to cancel
this" and "I fat-fingered it" — not a stranger doing something unexpected.

**Decision: treat the deletion as a QUESTION, not a command.**

The event stays gone. Nothing is cancelled, no hours move, no email goes to the
client. Michael gets asked:

> Booking #71 · Jonathan Pineda · Thu Aug 20, 2:15–3:15
> You deleted the calendar event. Cancel the booking and return the hour?
> **[ Yes, cancel it ]   [ No, put it back ]**

- **Yes** → cancel through `admin_write_booking()` like any other cancellation:
  row, ledger, audit entry. (The event is already gone, so `push_calendar` stays
  false here too.)
- **No** → re-create the event from the row and carry on.

This makes deleting on the calendar a genuine shortcut for cancelling — the
gesture he would naturally reach for, since he lives in the calendar — while a
slip of the thumb can never quietly hand an hour back to a client.

**🔑 Implementation note: confirm with two signed links, not Slack buttons.**
Slack interactive buttons need an interactivity request URL configured on the
Slack app; the machine only holds a bot token and posts with `chat.postMessage`.
Two one-tap signed URLs into WordPress — the same HMAC pattern as
`/manage-booking/?b=…&t=…` — work from his phone with no login, no Slack app
change, and no new infrastructure. Each link is single-use: consume it by
storing the answer, so a stale link in Slack scrollback cannot re-fire.

**If he never answers:** nothing happens. The booking stands, the calendar has a
gap, and the daily drift check flags it each morning until it is resolved. That
nag *is* the fallback — no timeout logic needed, and no state expires into a
silent wrong answer.

## PART 5 · BUILD ORDER

1. **WordPress first, deployed and testable on its own.**
   - `push_calendar` option in `admin_write_booking()`.
   - `register_rest_route( 'mwm-studio/v1', '/calendar-sync', … )` + handler.
   - Bump to **v2.8.0**. Deploy by plugin zip + *Replace current with uploaded*,
     hash-verifying live against the repo before and after (the S26/S27 method).
   - Prove it with `curl`: a wrong secret 401s; a correct one moves booking #71
     and leaves its calendar event untouched.

2. **Machine second.**
   - `_gcal_sync_loop()` daemon thread, 120 s, `syncToken` in
     `pg_store("studio_gcal_synctoken")`.
   - On `410 Gone` (token expired): drop the token, do one full re-list over
     **today −7 → +90 days**, and log it. Do not attempt a full-calendar sync.
   - Layers 1–3 of the loop guard.
   - `POST` to the WP route; relay warnings to `SLACK_MATT_CHANNEL`, failures to
     `SLACK_DEV_CHANNEL`.
   - Write the reverse index key on every event the machine creates.
   - `MWM_GCAL_SYNC_ENABLED` env var, **default off**, so the code can ship dark
     and be switched on deliberately.

3. **Ship via the autodeploy runner** — `.deploy/Patch_96_calendar_to_portal_sync.patch`
   plus `DEPLOY_REQUEST.json` naming `test_calendar_sync.py` and `expect: "0 failed"`.

4. **Switch on and watch.** Turn the env var on, then drag a real event and watch
   it land. Leave it running with the daily drift alert as the safety net for a
   few days before trusting it.

---

## PART 6 · TESTS (the runner gates the commit on these)

`test_calendar_sync.py` — no live Google, no live WordPress; stub both.

| # | Test | Asserts |
|---|---|---|
| 1 | event moved 14:15 → 16:00 | exactly one WP call, correct payload |
| 2 | **run the loop 3× on the same state** | runs 2–3 make **zero** WP calls, **zero** calendar writes |
| 3 | event already matches the row | zero WP calls (layer 2) |
| 4 | self-write marker < 90 s old | skipped (layer 3) |
| 5 | event with no `booking #NN` | ignored |
| 6 | description says `#61-r1` | resolves to booking **61** |
| 7 | reverse index present but description mangled | still resolves |
| 8 | duration change 1h → 1.5h | payload carries `duration 1.5` |
| 9 | deleted event | takes the deletion branch, never the cancel branch |
| 10 | WP returns warnings | relayed to Slack, run still counted successful |
| 11 | WP returns 500 | logged, syncToken **not** advanced, retried next tick |
| 12 | `410 Gone` on syncToken | falls back to a bounded re-list, does not crash the loop |

🔑 Test 11 matters most: **never advance the syncToken until WordPress has
confirmed the write.** Advancing on failure silently loses a change forever —
and silence is the defect this whole project exists to kill.

---

## PART 7 · ROLLBACK

Set `MWM_GCAL_SYNC_ENABLED=0` on Railway. The loop goes inert on its next tick.
Nothing else needs touching: the WP route is passive, `push_calendar` defaults to
true, and the one-way sync that has worked since S12 is unaffected. No data
migration to unwind.

---

## PART 8 · EXPLICITLY OUT OF SCOPE (Phase 2, discuss first)

**Creating a booking by making a calendar event** — typing "Studio: Jonathan
Pineda 1h" on the calendar and having a booking appear. Michael was interested
and it is the natural next step, but it is a different problem: it needs to
resolve a free-text name to a client record, and 🔑 **this account mangles client
names constantly** — "Jonathan Peneira" for Pineda, "Cologne" for Kalum, both on
Aug 13 alone. There are two Jonathans in the client table, one on a package and
one pay-per-session. Guessing wrong books the wrong man and draws the wrong
person's hours.

If it is built, it must **propose and wait for confirmation** — a Slack message
reading *"Create a booking for **Jonathan Pineda** · john.pineda@fidelityfl.com ·
Thu Aug 20 2:15–3:15 · leaves 4.5 h?"* with a confirm button — never write on a
guess. That is a separate build, not a stretch goal of this one.

---

## APPENDIX A · If instant beats simple (push instead of polling)

Only if Michael says two minutes is too slow.

1. Point `machine.mwmcreations.com` at Railway (CNAME + Railway custom domain,
   TLS auto).
2. Verify that domain in the Google Cloud project — `mwmcreations.com` is already
   verified in Search Console, so this is a subdomain add, not a fresh
   verification. ⚠️ While you are there: the domain still carries **two**
   `google-site-verification` TXT records differing only by a capital-i vs a
   lowercase-L. One is a hand-typed copy that verifies nothing. Delete the one
   Search Console is not holding *before* relying on verification.
3. `events.watch(calendarId=CALENDAR_ID, body={id, type:"web_hook", address:…})`.
4. Read `expiration` **off the API response** — do not hard-code a TTL — and
   re-register at 80% of it from a daemon loop.
5. New route `/webhook/gcal-change`; treat the ping as "something changed" only
   and then run the exact same `syncToken` sync as the polling path.

The sync logic is unchanged. Push replaces the timer, nothing else. Keep polling
as the fallback if a channel lapses.
