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
