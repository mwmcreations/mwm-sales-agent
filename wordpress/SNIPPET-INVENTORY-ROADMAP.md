# ROADMAP snippets — what is live

**Captured from wp-admin → Snippets, Aug 11 2026, ~15:00 ET.**

| WP ID | State | Name | Mirror |
|---|---|---|---|
| **28** | ACTIVE | Portal — schema v1.2.0 | `wordpress/roadmap/schema.php` |
| **34** | ACTIVE | Seed Zerlotini Brothers v3 | `wordpress/roadmap/seed-zbrothers.php` |
| **37** | ACTIVE | Portal v1.2.1 — login, render, pre-schedule | `wordpress/roadmap/portal.php` |
| 24 | inactive | one-shot bootstrap (created page 1202, mailed the code) | `wordpress/wp-snippet-24-roadmap-bootstrap.php` |

Trashed after being superseded: 21, 22, 23, 27, 29, 30, 32, 35, plus every `ZZ`
temporary snippet (25, 26, 31, 33, 36, 38, 39) that existed only long enough to
prove something.

## 🔴 Why the mirrors do NOT carry their snippet ID in the filename

The Import screen's *"Replace any existing snippets with a newly imported snippet
of the same name"* **does not replace.** Verified repeatedly: every import mints a
**new ID** and leaves the old snippet inactive under the same name. The portal was
22 → 27 → 30 → 32 → 35 → 37 in a single afternoon.

Two consequences:

1. Renaming a mirror per import litters the repo with stale copies of one file.
2. 🔴 **Two copies of the same snippet must never be active at once** — same
   function names, and WordPress fatals on redeclare, on a page a client is
   looking at. **Deactivate the old one BEFORE activating the new one**, and
   confirm from the snippets list, never from the "Import Successful" notice.

## Deploying without pasting 70 KB of PHP

Build a `.code-snippets.json` — `{generator, date_created, snippets:[{name, desc,
code, tags, scope, priority, active}]}`, with `code` **excluding** the `<?php`
line — then Snippets → Import → upload it.
🔑 `mcp__claude-in-chrome__file_upload` must be given the **cloud-container** path
(`/home/claude/…`). It proxies the bytes; it rejects a `/Users/…` device path.

## Proving it actually ran

"Snippet created" proves a save. "Active" proves a toggle. Neither proves the code
ran, and neither proves the page is right. Read the options:
`mwm_roadmap_db_version` = **1.2.0** · `mwm_roadmap_seed_zb` = **3**.
For the rendered page, activate a throwaway snippet that calls
`mwm_rm_portal_screen()` server-side and asserts on the markup — that works even
when you deliberately cannot read the client's access code.
⚠️ Anchor those assertions on the **meter markup**, not on a label. An early
version matched the words "Studio hours" in the rules table and reported the
campaign-days figure instead. *A diagnostic that disagrees with the thing it
diagnoses is worse than none.*

## The portal page

`https://mwmcreations.com/roadmap-portal/` — page **1202**, slug `roadmap-portal`,
content is the single shortcode `[mwm_roadmap_portal]`.
MWM-side confirm/decline: **wp-admin → ROADMAP requests**.
