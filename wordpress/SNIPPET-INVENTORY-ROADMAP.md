# ROADMAP snippets — what is live, and why these mirrors are named differently

**Captured from wp-admin → Snippets, Aug 11 2026, ~13:30 ET.**

| WP ID | State | Name | Mirror |
|---|---|---|---|
| **28** | ACTIVE | MWM ROADMAP Portal — schema v1.2.0 | `wordpress/roadmap/schema.php` |
| **29** | ACTIVE | MWM ROADMAP — seed Zerlotini Brothers v2 | `wordpress/roadmap/seed-zbrothers.php` |
| **30** | ACTIVE | MWM ROADMAP Portal — login + render v1.0.2 | `wordpress/roadmap/portal.php` |
| 24 | inactive | one-shot bootstrap | `wordpress/wp-snippet-24-roadmap-bootstrap.php` |

Trashed on Aug 11 after being superseded: **21** (schema v1.1.0), **22** and **27**
(portal), **23** (seed v1), plus four temporary snippets (25, 26, 31 and an earlier
diagnostic) that existed only long enough to prove something.

## 🔴 Why these three mirrors do NOT carry their snippet ID

`SNIPPET-INVENTORY.md` says a mirror is named `wp-snippet-<ID>-<slug>.php`. That
rule assumed the ID is stable. **It is not.**

The Import screen offers *"Replace any existing snippets with a newly imported
snippet of the same name."* **It does not replace.** Selected twice, verified
twice: the import creates a **new snippet under a new ID** and leaves the old one
sitting there, inactive, with the same name. The portal was snippet 22, then 27,
then 30 — inside one afternoon.

Two consequences, both of which have already bitten:

1. **Renaming the mirror after every import litters the repo** with stale copies of
   the same code. Nobody can tell which one is live by looking.
2. 🔴 **Two copies of the same snippet must never be active at once.** They declare
   the same functions and WordPress fatals on redeclare — a white screen on a page a
   client is looking at. **Always deactivate the old one BEFORE activating the new
   one**, and confirm from the snippets list, never from the "Import Successful"
   notice.

So these three keep a stable filename and record their live ID in the header and in
the table above. **Verify the ID against the snippets list before trusting it.**

## Verifying the schema actually ran

"Snippet created" proves a save. "Active" proves a toggle. Neither proves the code
ran. Read `mwm_roadmap_db_version` from `/wp-admin/options.php` — the schema writes
that option only after its `dbDelta` loop completes. It should read **1.2.0**.
The seed writes `mwm_roadmap_seed_zb`, currently **2**.

## The portal page

`https://mwmcreations.com/roadmap-portal/` — page ID **1202**, slug `roadmap-portal`,
content is the single shortcode `[mwm_roadmap_portal]`. Created by snippet 24.
