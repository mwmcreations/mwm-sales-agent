# page 741 (`/book-studio/`) — EMERGENCY SNAPSHOT

Captured Aug 8 2026 from the live page, anonymously (`curl`, no cookies).

## Why this exists
The entire `/book-studio/` checkout — hour cards, editing toggle, pricing,
calendar, slot fetch, reserve/pay call — lives as an **inline `<script>` inside
an Elementor HTML widget on page 741**, stored in `_elementor_data`. It is not
in `mwm-studio-booking.php` and was not in version control until this snapshot.
It is the only revenue-taking checkout in the business. One Elementor mangle or
one backup restore and it was gone with nothing to restore from.

MATT's addition, and it is the sharper point: **snippet 17 (the AD_09 deep link)
drives controls that only exist inside this widget** — `#bs-editing-checkbox`
and `.bs-hour-card`. So losing page 741 does not just kill checkout, it kills
the AD_09 funnel too. The snippet is versioned; the thing it drives was not.

## Files
| file | bytes | what |
|---|---|---|
| `book-studio-widget.html` | 4,270 | the `#bs-book` widget markup |
| `book-studio-widget.js` | 15,765 | the widget's inline JS (14,462) + snippet 17's injected script (1,258) |
| `book-studio-widget.css` | 20,116 | the two `bs-*` style blocks |
| `page-741-rendered-snapshot.html` | 89,513 | the whole rendered page, anonymous |

`book-studio-widget.js` contains TWO scripts separated by
`/* ==== next script ==== */`. The FIRST is the widget and is the irreplaceable
one. The SECOND is snippet 17, which is already versioned at
`wordpress/snippet-17-ad09-deeplink.php` — do not restore it from here or it
will be applied twice.

## This is a RENDERED snapshot, not the Elementor source
It is enough to rebuild the widget by hand into a fresh Elementor HTML widget.
It is NOT a one-click Elementor import. **The proper export of
`_elementor_data` for page 741 is still outstanding** and should be done from
wp-admin (Elementor → Templates → Export, or the page's post meta). Treat this
file as the floor, not the finished job.

## Known widget internals (from reading the JS)
- state: `selectedHours`, `editingEnabled`, `selectedDate`, `selectedSlot`
- pricing is DISPLAY ONLY — `studio` $249/hr, `editing` $349/hr. The server
  prices canonically; do not treat these numbers as authoritative.
- AJAX actions used: `mwm_studio_rental_month`, `mwm_studio_rental_slots`,
  and the reserve call behind `#bs-rs-pay`
- ⚠️ the hour-card click handler **TOGGLES**: clicking an already-`bs-active`
  card DESELECTS it. Anything driving these controls must check first.

## 🔴 Compliance note — READ BEFORE EDITING THIS PAGE
`/book-studio/` and `/privacy-policy/` were frozen on Aug 1 2026 pending A2P
10DLC approval (campaign `CM87b39e12beba8e7816460e18178dae38`). A Meta/Twilio
reviewer loads the **bare canonical URL, cold, with no query string**. Confirm
the campaign's status before changing anything a reviewer can see.
