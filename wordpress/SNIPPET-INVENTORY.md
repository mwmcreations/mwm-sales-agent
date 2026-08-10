# Code Snippets inventory — mwmcreations.com

**Captured live from wp-admin → Snippets on Aug 10 2026.** 18 snippets, 9 active.

🔴 **READ THIS BEFORE ADDING ANY UI TO A PAGE.** On Aug 9 I added a booking
calendar to the Studio Portal at the plugin level without checking that snippet
**17 already drew one**. Two calendars rendered for every client, and Juliane
hit it. The snippet was not in this repo, so reading `README.md` told me nothing
— but the repo was never the real check. **The live DOM is.**

## Filename rule
Files here are named `wp-snippet-<WP ID>-<slug>.php`. The number is the
**Code Snippets database ID**, not a sequence of ours. This matters: the AD_09
deep-link was filed as `snippet-17-…` because it was our 17th change, while WP
snippet 17 is something else entirely — the calendar that caused the collision.

## Active snippets (these run on the live site)

| WP ID | Scope | Name | In repo |
|---|---|---|---|
| 5 | global | MWM Contact Form AJAX Handler | ❌ |
| 6 | global | Maya Chat Widget Loader | ❌ |
| 7 | front-end | MWM Global Navigation Bar | ❌ |
| 9 | front-end | Maya Chat Balloon | ❌ |
| 10 | front-end | Book Studio Mobile Video Fix | ❌ |
| 11 | global | Studio Package - Book Your Hours Button | ❌ |
| 15 | global | MWM Studio Portal — Machine Provisioning Endpoint (S7) | ✅ |
| 16 | global | Studio Portal — bypass page caches (S7 fix) | ✅ |
| 19 | global | AD_09 Deep-Link — /book-studio/ hours + editing preselect | ✅ |

**Six active snippets are still unmirrored.** Any of them can inject markup into
a page we are about to change. Export them (Snippets → Edit → Export Code, the
file lands in Downloads) before the next front-end change.

## Inactive — kept for history
| WP ID | Name | Note |
|---|---|---|
| 1–4, 8 | misc WP tweaks | never used |
| 12 | July Hours Used - One-time Import | run once |
| 13 | Fix July Hours - Delete Duplicates | run once |
| 14 | MWM Studio Contract Migration (run once) | run once |
| 17 | Studio Portal — Inline Booking Calendar (S14) | **deactivated Aug 10 2026** — see below |

### Why 17 was deactivated
It hid the portal's native date input (`input.style.display='none'`) and drew
its own dark month grid, writing the chosen date back into `#mwm-book-date`.
It made **no availability calls at all** — it only greyed out past dates, so
every future day looked bookable including days the studio was already booked.
The client would pick one and then be told there were no times. Replaced by the
plugin-level calendar, which reads `mwm_studio_rental_month` — the same endpoint
`/book-studio/` uses, derived from `get_available_slots` (pending holds + Google
Calendar busy blocks).

⚠️ The Snippets edit screen's **"Save and Deactivate" button did not
deactivate** — it reported "Snippet updated" and left the snippet active. The
row-level activation toggle on the list screen worked. Always re-check the live
page, never trust the success notice.
