# WordPress side of the Studio Package automation — snapshots

The portal backend is the **`mwm-studio-booking` plugin** (single ~115KB file at
`wp-content/plugins/mwm-studio-booking/mwm-studio-booking.php`) plus two Code
Snippets (IDs 15, 16) — snapshots of the snippets are in this directory.

## ✅ Plugin IS in this repo (since Jul 8 2026)
`mwm-studio-booking.php` exported from the live site Jul 8 2026 (baseline
commit = pre-S8.5 live state incl. the S7.6 late-cancel patch). Live edits
must be mirrored here from now on.

### S8.5 — booking-window enforcement (Jul 8 2026, applied live, Michael approved)
1. `$max_date` capped at `$client->contract_end_date` in BOTH
   `mwm_studio_get_available_slots` and `mwm_studio_create_booking` —
   bookings can no longer be dated past the contract end (= 30-day grace deadline).
2. `mwm_studio_record_calendly_booking` removed from the `$ajax_actions`
   registration array (endpoint had zero contract/date/hours checks; portal-only
   policy). Function body + frontend `onCalendlyBooked` JS left in place, dormant.

## Live edits made to the plugin OUTSIDE version control (via wp-admin editor)
### S7.6 — 24h cancellation policy (Jul 6 2026, ~12:50 AM, Michael approved)
1. In `mwm_studio_cancel_booking()`, inserted before the `$wpdb->update(` call:
```php
// S7.6 (Michael, Jul 6 2026): 24h cancellation policy — sessions cancelled
// with <24h notice keep their hours charged ('cancelled_late' counts in the
// hours-used sums but frees the calendar slot).
$mwm_sess_ts     = strtotime( trim( $booking->booking_date . ' ' . ( isset( $booking->start_time ) && $booking->start_time ? $booking->start_time : '00:00:00' ) ) );
$mwm_late_cancel = ( $mwm_sess_ts && ( $mwm_sess_ts - current_time( 'timestamp' ) ) < DAY_IN_SECONDS );
```
2. `'status' => 'cancelled'` → `'status' => ( $mwm_late_cancel ? 'cancelled_late' : 'cancelled' )`
3. Success message wrapped: late cancels see the policy message (i18n domain `mwm-studio`).
4. All **5** hours-sum filters `status IN ('confirmed','completed')` →
   `IN ('confirmed','completed','cancelled_late')`.
5. History filter `status IN ('completed','cancelled')` → adds `'cancelled_late'`.

### Earlier known facts
- Tables: `wp_mwm_studio_clients` (access_code = wp_hash_password, UPPERCASE 6-char),
  `wp_mwm_studio_bookings` (booking_date DATE, start_time TIME, duration_hours, status).
- Plugin has its own Stripe webhook route `/wp-json/mwm-studio/v1/stripe-webhook` —
  its Stripe destination (`dynamic-breeze`) was DISABLED Jul 5; machine's
  `/webhook/stripe` is the single purchase handler.
- wp-admin plugin editor save = admin-ajax `action=edit-theme-plugin-file`, nonce field is `nonce`.

### S17 — AD_09 deep-link preselect (Aug 8 2026, LIVE, verified)
Added as **Code Snippets ID 19** — *"AD_09 Deep-Link — /book-studio/ hours +
editing preselect"*, scope **Run everywhere**, priority 10, **Active**.
Repo copy: `snippet-17-ad09-deeplink.php`.

`/book-studio/` now accepts `?hours=1..5` and `&editing=1`, so one link lands a
lead directly on a chosen configuration with the calendar already rendered.
The AD_09 link is `/book-studio/?hours=1&editing=1` → **$349**.

🔴 **Finding worth acting on separately: the booking widget is NOT in version
control.** It is a ~14KB inline `<script>` inside an Elementor HTML widget on
**page 741** (`elementor_canvas`), stored in `_elementor_data`. It is not in
`mwm-studio-booking.php`. If that page is edited or restored, the entire
`/book-studio/` checkout logic is lost with no copy. **Export page 741 into
this directory.**

Why a snippet rather than editing the widget: purely additive, reversible by
deactivating, and version-controllable. The snippet drives the widget's own
public controls (real `change` on `#bs-editing-checkbox`, real `click` on
`.bs-hour-card`) so `update()` / `loadPicker()` / `calRefresh()` run exactly as
they do for a human. No pricing logic is duplicated; the server still prices
canonically.

Guard that matters: the widget's hour-card handler **toggles**. Clicking an
already-`bs-active` card DESELECTS it, so the snippet checks for `bs-active`
before clicking.

Verified live, logged-out, after activation:
| URL | active card | editing | price | calendar |
|---|---|---|---|---|
| `/book-studio/` | none | false | STUDIO ONLY $249 | not rendered |
| `?hours=2` | 2 | false | STUDIO ONLY $498 | rendered |
| `?hours=1&editing=1` | 1 | true | **STUDIO + EDITING $349** | rendered, 18 days |
| bare + manual click 3h | 3 | false | STUDIO ONLY $747 | rendered |

Last row is the regression check: manual interaction is unchanged.

### S22 — Studio Portal full month calendar (Aug 9 2026) — ✅ **LIVE, VERIFIED**
Michael: the portal's "Book a Session" was showing a bare `mm/dd/yyyy` box, not
the full calendar he asked for.

Root cause, two faults in the same block:
1. There never was a calendar in the portal. `/book-studio/` got a month grid
   (S19) but the portal kept `<input type="date">`.
2. That whole section was styled for a DARK page. `.mwm-calendly-intro` and
   `.mwm-book-field label` were `rgba(255,255,255,.6/.7)` — **white text on the
   portal's white background**. That is the blank gap above the date box in the
   screenshot: the "Session date" label and the intro line were rendering, just
   invisible. The input looked like a dark pill because of `background:#12122a`.

Fix (4 hunks in `mwm-studio-booking.php`):
- month grid markup + light-theme CSS replacing the native date input;
  `#mwm-book-date` kept as a hidden input so `confirmBooking()` is untouched
- `initBooking` rewritten; added `monthName` / `moveMonth` / `loadMonth` / `renderCal`
- after a successful booking, clear the pick and re-fetch the month
- `.mwm-calendly-intro` colour → `#6b7280`

Availability calls **`mwm_studio_rental_month`** — the same endpoint
`/book-studio/` uses, derived from `get_available_slots` (pending holds + gcal
busy). One source of truth; no second availability rule to drift.
Registered nopriv, no nonce (S21), so a cached page can't 403 it.

Verified: JS `node --check` clean; diff is exactly 4 hunks; brace/paren/quote
balance identical to the pre-patch backup.
🔴 NOT the frozen surface — the Twilio A2P freeze covers `/book-studio/` and
`/privacy-policy/` only. Page 741 untouched.

DEPLOYED Aug 9 2026 via wp-admin Plugin File Editor. WordPress returned
"File edited successfully" (which also means its loopback fatal-error check
passed and did not roll back).

Deploy method worth reusing: rather than pasting a 197KB file, the live editor
content was hashed first (SHA-256 `c4e0cd44…`) and confirmed **byte-identical
to the repo baseline** — no live drift — then an index-based diff was replayed
in the page and the result re-hashed to `726f7203…`, matching the repo's
patched file exactly before Update File was clicked. Live and repo are the same
bytes, proven, not assumed.

POST-DEPLOY VERIFICATION (logged out, cache-busted):
| check | result |
|---|---|
| `/studio-portal/` HTTP | 200, 75,659 b, no PHP fatal |
| calendar markup + CSS present | yes (`mwm-cal-grid`, `.mwm-cal-open`) |
| old `<input type="date">` gone / hidden input present | yes / yes |
| `.mwm-calendly-intro` colour fixed | yes (`#6b7280`) |
| `mwm_studio_rental_month` (Aug 2026) | 18 open days, Aug 10 → Aug 31, horizon Oct 8 |
| REGRESSION `/book-studio/` | 200, 89,285 b, widget intact, no fatal |
| REGRESSION `mwm_studio_rental_slots` Aug 12 | 4 slots |

Backup of the pre-patch file: `/tmp/mwm-backup-1786312586.php` on the device VM.

### 🔴 S22b — TWO CALENDARS on /studio-portal/ (Aug 10 2026) — FIXED
Juliane reported the portal rendering **two** calendars stacked: my new light
one (S22, in the plugin) and a **dark** one directly beneath it.

**Root cause — mine.** A portal calendar ALREADY EXISTED as Code Snippets
**ID 17, "Studio Portal — Inline Booking Calendar (S14)"**, active, global
scope. It was NOT in this repo, so reading this README told me nothing about
it — but the real failure is that I never inspected the rendered portal DOM
before building a second calendar. Check the live page, not just the repo.

What S14 did (now exported here as
`snippet-17-studio-portal-inline-calendar-S14-DEACTIVATED.php`, 4,269 b):
- `input.style.display = 'none'` on `#mwm-book-date` — it HID the native date
  input and drew a dark month grid in its place
- on a day click: sets `input.value` + dispatches `change`, so the plugin's
  `loadSlots()` fired and real times appeared
- 🔑 **it made ZERO availability calls** — no `mwm_studio_rental_month`, no
  `mwm_studio_get_available_slots`. Only PAST days were disabled, so every
  future day looked bookable, including days the studio is fully booked.

After S22 replaced the native input with `<input type="hidden">`, S14's hide
became a no-op and its grid rendered alongside mine — two calendars.

**Fix:** deactivated snippet 17 via the list-row activation switch.
⚠️ The edit screen's "Save and Deactivate" button SAVED but left it ACTIVE —
verify state on the list page afterwards, never trust that button.

VERIFIED after the fix (logged out, cache-busted):
| check | result |
|---|---|
| `id="mwm-cal-grid"` in page | 1 |
| `id="mwm-cal"` wrapper | 1 |
| `mwmcal` / datepicker / flatpickr / pikaday | 0 |
| legacy `type="date" id="mwm-book-date"` | 0 |
| page weight | 75,659 b → 71,716 b |
| `mwm_studio_rental_month` (Aug) | 18 open days, from Aug 10, horizon Oct 8 |
| REGRESSION `/book-studio/` | 200, 89,285 b, widget intact, no `mwmcal`, no fatal |
| REGRESSION `mwm_studio_rental_slots` Aug 12 | 4 slots |

The portal template is ONE shortcode output shared by every client, so this is
fixed for all 12 portal clients at once, not just Juliane's account.

### S26 — ADMIN BOOKING CONTROL (Aug 13 2026) — ✅ **LIVE, VERIFIED** · v2.6.1

Michael: *"we need to be able to add hours, have more control… they wanna go over
and use more time, and we need to be able to have that flexibility to go into
their portal and adjust that… I don't want you to have to manually code times
like you had to do this time."*

Before this, wp-admin could **list** bookings and offer only *Mark Completed* /
*Cancel*. There was no way to create a booking and no way to edit one. The only
paths that created a booking were the client-facing portal and code.

#### 🔴 The design rule: ONE WRITE PATH

Every admin mutation goes through **`admin_write_booking()`**. In one operation
it writes the booking row, pushes the calendar to match, and records an audit
entry with the before value. Nothing else in the plugin may `UPDATE` the
bookings table from an admin screen.

The hours ledger is **derived, not stored** — `hours_used_in_contract()` SUMs
`duration_hours` over the contract window. Writing the row *is* moving the
ledger; there is no second number that can drift from it. That is why "three
things in one operation" is really two.

#### Why the calendar is removed-and-recreated, not updated

The machine webhook `/webhook/studio-booking` accepts only `booking_created` /
`booking_cancelled` / `booking_cancelled_late` and **400s on anything else.
There is no `booking_updated`.** The client-facing reschedule already solves
this with a bumped idempotency id (`61`, `61-r1`, `61-r2`…) via `event_bid()`;
S26 reuses that exact mechanism. **So S26 ships WordPress-side with no machine
deploy.**

The `client_name` sent with the removal carries a marker — `(admin edit —
moving)` vs `(cancelled in wp-admin)` — so the machine's Slack alert does not
read a move as a cancellation.

#### What was broken and is now closed

1. **Booking #61 (Jonathan Pineda, Aug 13 2026)** read `15:00` in the row and
   `14:15` on the calendar. The calendar event had been hand-edited Aug 12 and
   nothing reconciled the two. Reminder emails read the **row**, so the 1:46 PM
   reminder told the client 15:00 for a 14:15 session.
2. 🔴 **wp-admin Cancel and Mark Completed pushed nothing.** Cancelling from the
   Bookings list wrote the row and left the Google Calendar event in place,
   blocking the studio forever. Never hit in production only because every
   cancellation so far came through the portal. Both now route through
   `admin_write_booking()`.
3. ⚠️ **Rentals were invisible in wp-admin.** Both the Bookings list and the
   Dashboard "Upcoming Bookings" used `JOIN {clients} ON c.id = b.client_id`,
   and rentals carry `client_id = 0`. A real paid rental (Priti, Aug 29) existed
   on the calendar and nowhere in wp-admin. Both are now `LEFT JOIN`.

#### What was added

| | |
|---|---|
| `admin_write_booking()` | the single write path — row + calendar + audit |
| Add / Edit Booking screen | free-form duration (any ¼ hour, 0.25–12), any status, incl. already-Completed bookings |
| Repeat weekly | N extra weeks, each created through the same write path |
| Adjust hours | Add / Set total, inline on the Clients row; no hand-edited DB |
| Audit Trail screen | who · when · before · after · reason (`wp_mwm_studio_audit`) |
| Reconciliation screen | flags any row with no calendar block at exactly its start/end |
| Double-booking guard | blocks overlaps unless "allow overlap" is ticked; never silent |
| Client email | **OFF by default** — admin changes are silent so Michael sends one message himself |

**Ledger policy settled with Michael (Aug 13):** overage **draws from the
package** (Pineda: 1.5 drawn), and going past the contract total is **allowed
and flagged loudly** — the booking saves, the Clients row shows `OVER by N h`,
and an admin email fires. Never blocks you at 6pm on a Thursday.

`status_counts_hours()` is deliberately a different set from
`status_holds_calendar()`: `cancelled_late` charges the hours but frees the
studio (S7.6). Conflating the two is how a ledger double-counts.

#### Deploy method (better than the S22 in-page diff replay)

Built the file locally, `php -l` clean, packaged as a plugin zip, uploaded via
**Plugins → Add New → Upload Plugin → "Replace current with uploaded"**. No code
passes through the editor textarea and WordPress does its own fatal-error check.
Before replacing, the live file was hashed in-page and confirmed **byte-identical
to the repo baseline** (`726f7203…`) — no undocumented live drift. After
replacing, the live file was re-hashed and matched the built file exactly.

⚠️ **`remove_submenu_page()` broke the hidden edit screen** (v2.6.0). It strips
the `$submenu` entry that `user_can_access_admin_page()` walks to resolve the
parent, so every `?page=mwm-studio-booking-edit` hit returned *"Sorry, you are
not allowed to access this page."* Fixed in **v2.6.1** by keeping it as a real
submenu row (*Add / Edit Booking*). Do not re-hide it that way.

#### POST-DEPLOY VERIFICATION (Aug 13 2026)

| check | result |
|---|---|
| live file hash == built file | ✅ byte-identical, 243,261 b |
| `#61` corrected via the new screen | ✅ `14:15–15:45`, 1.5h |
| old gcal event `2qqgqr3bov…` | ✅ deleted (404 on fetch) |
| new gcal event `#61-r1` | ✅ Aug 13 14:15–15:45, "🎬 Studio: Jonathan Pineda (1.5h)", attendee + 30/60/1440 reminders |
| four Thursdays `#71–#74` | ✅ Aug 20 · Aug 27 · Sep 3 · Sep 10, all 14:15–15:15 |
| four gcal events | ✅ all present, attendee + correct reminders |
| Pineda hours | ✅ **5.5 / 12.0** |
| audit trail | ✅ 5 rows, before/after/reason all populated |
| Reconciliation (Jul 14 – Nov 11) | ✅ 17 checked, 0 disagree |
| Reconciliation negative control (Jun 30 – Jul 10) | ✅ 7 flagged — the July one-time-import rows and two early test rentals, all pre-S12 and expected. Proves the detector fires. **Do not "fix" these** — re-saving would push historical events and fire invites for past sessions. |
| REGRESSION `/studio-portal/` | ✅ 200, 71,716 b — same byte count as post-S22b, no fatal, one calendar |
| REGRESSION `/book-studio/` | ✅ 200, 92,990 b, widget intact, no fatal |
| REGRESSION `mwm_studio_rental_slots` Aug 20 | ✅ 16:00, 17:00 — the new 14:15 booking correctly blocks its slot |

🔑 **Google calendar invites DID go to the client** for all five events
(`sendUpdates="all"` on the machine side, unchanged behaviour). The WP branded
confirmation emails were suppressed as Michael asked, but Pineda still received
a cancellation notice for the old Aug 13 event plus five invites. Any human
email to him should acknowledge that.

### S27 — QUICK BOOK (phone) + DRIFT WATCH (Aug 13 2026) — ✅ **LIVE, VERIFIED** · v2.7.0

Michael: *"most of the time I'm on my phone… going to WordPress through my phone
is not very convenient."* A client asks him in the studio to book an hour; he
should not have to log into wp-admin on a phone to do it.

#### Quick Book — `/studio-quick-book/`

A **standalone page outside wp-admin**. `qb_maybe_standalone()` takes over
`template_redirect` for that one page and emits a bare document with the iOS
home-screen meta, so it opens full-screen with no theme, no nav bar, no browser
chrome. Three taps — client, day, time — a duration stepper, one button.

🔴 **It is a new DOOR, not a new write path.** It creates bookings through
`admin_write_booking()`, the same S26 path as the admin screens. That
distinction is the whole lesson of #61.

**Auth, since there is no WordPress session on that page:**

1. a 48-char token in the URL (`?k=…`), compared with `hash_equals` — the same
   pattern `/manage-booking/` already uses;
2. a 4-digit PIN **Michael sets himself on first open**. Only `wp_hash_password`
   of it is stored; DEV never sees or handles the value.

A pass sets an HMAC-signed, httpOnly cookie for 7 days, bound to both the PIN
hash and the token — so rotating either invalidates every live session. PIN
attempts are throttled 5 per 15 min per IP. `Settings → New link + reset PIN`
kills the old link and the PIN together: one button, the recovery path for a
lost phone or a forgotten PIN.

**What it deliberately cannot do:** cancel a booking, change hours, edit a
client, or show money. It creates a booking for a client who already exists.
Everything destructive stays behind a real wp-admin login.

Times come from `get_available_slots()`, so only genuinely free slots are
offered — but that generator steps on the hour, and real sessions are not always
on the hour (Pineda is 14:15). So there is an **"Other time"** field; the exact
overlap guard in `admin_write_booking()` is what actually protects the studio,
not the slot list. If the availability feed is down the page says so and still
lets him type a time, rather than showing an empty screen.

#### Drift Watch

The Reconciliation screen only tells the truth on the day you open it. #61
drifted Aug 12 and was found Aug 13 — by the client being told the wrong time.
`run_drift_check()` runs the same check daily at ~07:10 over −7/+60 days and
**speaks only when something disagrees.** Silence means clean. Emails
`admin_email`; also posts to Slack if an incoming-webhook URL is set in
Settings. The screen and the cron share one implementation,
`find_calendar_drift()` — there is no second definition of "drifted".

#### POST-DEPLOY VERIFICATION (Aug 13 2026, logged out, cache-busted)

| check | result |
|---|---|
| live file hash == built file | ✅ byte-identical, 275,371 b |
| `php -l` / `node --check` on the inline JS | ✅ both clean |
| no `?k=` | ✅ HTTP 200, renders **Not found** — does not confirm the page exists |
| wrong token, same length | ✅ **Not found** |
| valid token | ✅ **Choose a PIN** screen |
| page is the bare document | ✅ `web-app-capable` present, no theme markup |
| `mwm_qb_slots` — valid token, no PIN cookie | ✅ **HTTP 403** "Session expired" |
| `mwm_qb_create` — valid token, no PIN cookie | ✅ **HTTP 403** — the write is behind BOTH factors |
| Reconciliation after the refactor | ✅ 17 checked, 0 disagree |
| REGRESSION `/studio-portal/` | ✅ 200, 71,716 b, one calendar, no fatal |
| REGRESSION `/book-studio/` | ✅ 200, 92,990 b, widget intact |

The create test used `client_id = 999999` on purpose: had the guard failed, the
write path would still have refused on an unknown client and written nothing.
Test the lock without risking the door.

---

### S28 — GOOGLE CALENDAR → PORTAL SYNC (Aug 14 2026) — 🟡 **BUILT · NOT YET LIVE** · v2.8.0

Michael: *"if I need to change on Google Calendar the time for someone that has
booked… it's also now gonna move on the portal."*

Until now the sync was one-way: WordPress wrote, the calendar followed. A drag
in Google Calendar moved nothing — not the row, not the hours, not the reminder
email. That is exactly how booking #61 told Jonathan Pineda the wrong time.

Full design: `docs/Calendar_To_Portal_Sync_Spec.md`.

#### The one idea

The booking row stays the only source of truth. The calendar becomes an **input
device**, not a second truth. A drag is Michael expressing an intention, and it
goes through `admin_write_booking()` like every other change.

And because the change came **from** the calendar, the calendar is already in
the target state — so there is nothing to push back. That single observation is
what keeps this small: no delete-and-recreate, so the event does not blink and
does not change id; no cancellation notice and no fresh invite to the client for
a move Michael made with his thumb; and a loop guard that has nowhere to start.

#### What changed in the plugin (v2.7.0 → v2.8.0)

| Change | Where |
|---|---|
| `push_calendar` opt (default **true**) | `admin_write_booking()` — when false, skips both `push_booking_event()` calls and the `reschedule_count` bump. Validation, the overlap check, the hours maths and the audit entry all still run. |
| `calendar_recreate` opt (default **false**) | `admin_write_booking()` — create-only, for "No, put it back" after a deletion. There is nothing left to remove, and asking the machine to delete a deleted event posts a cancellation alert for a booking nobody cancelled. |
| `POST /wp-json/mwm-studio/v1/calendar-sync` | `handle_calendar_sync()` — `X-MWM-Portal-Secret`, same shared secret as the availability feed. Actions `moved` / `deleted`. |
| `?mwm_cal_answer=1&b=&a=&t=` | `cal_answer_handler()` on `template_redirect` — the two one-tap signed links from a deletion question. HMAC over `wp_salt('auth')` + a per-question nonce, **single use, consumed before the write**. |

🔴 `push_calendar => false` is reachable **only** from those two handlers.
It must never appear in a form, a query string, or the quick-book page.

#### Policy (settled with Michael, Aug 13–14)

| Situation | Behaviour |
|---|---|
| Drag to a free slot | Row follows. Silent. Audit entry records who/when/before. |
| Drag onto another booking | **Accepted, flagged loudly** in Slack. Never silently refused — Michael is standing in a studio, not reading a validation error. |
| Drag past the contract end / beyond remaining hours | Accepted, flagged. Ledger goes negative; the Clients row already shows `OVER by N h`. |
| Resize | Same as a move. Hours follow. |
| **Delete the event** | **Nothing is cancelled.** Two signed links go to Slack: *Yes, cancel it* / *No, put it back*. If he never answers, the booking stands and the daily drift check nags every morning — that nag *is* the fallback. |
| Event with no `booking #NN` | Ignored. Michael's own shoots are not bookings. |

#### Deploy

Build locally → `php -l` → zip as `mwm-studio-booking/mwm-studio-booking.php` →
**Plugins → Add New → Upload Plugin → Replace current with uploaded**, hash-verifying
live against the repo before and after. Then prove it with `curl`: a wrong
secret must 401, and a correct one must move a booking while leaving its
calendar event untouched.

The machine half (`calendar_sync.py`, polling every 2 min with a `syncToken`)
ships dark behind `MWM_GCAL_SYNC_ENABLED`, so the order of the two deploys does
not matter and rollback is that one variable.
