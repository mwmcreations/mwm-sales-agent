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
