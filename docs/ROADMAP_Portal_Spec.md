# MWM ROADMAP™ CLIENT PORTAL — SPEC v0.5

**Author:** DEV · Aug 9 2026 · **Status:** prototype delivered, buildable
**Prototype:** `roadmap-portal.html` (also a Cowork artifact: `roadmap-client-portal`)

**v0.2** (Michael, Aug 9): login screen, live delivery approval workflow,
propose-and-confirm scheduling.
**v0.3** (Michael, Aug 9, same day): scheduling reversed again — the client DOES
get a calendar with our availability and CAN pick a day, but the pick is a
**pre-schedule** that MWM confirms. Hard notice rules set: **48h studio,
7 days on-location.** See §6.
**v0.4** (Michael, Aug 9): notifications — a pre-schedule emails
**info@mwmcreations.com**, and the confirm/decline happens FROM that email.
See §7.
**v0.5** (Aug 9): decisions locked — Michael alone confirms; reschedule policy
mirrors the notice rules; 48h hold expiry; Sundays closed. Real ROADMAP client
roster read from Stripe (§9). Phase 1 shipped to the repo:
`wordpress/snippet-20-roadmap-schema.php`.

---

## 0 · What ROADMAP actually is — read from the real artefacts, not assumed

Sources: `app.py:2013–2040` (plan tiers) and a real signed client roadmap,
*Annual Branding Roadmap – Z Brothers Construction (2025/26)*.

| Plan | Price | Campaigns / yr | Filming |
|---|---|---|---|
| Silver | $1,997/mo | up to 6 | curated sessions |
| **Gold** (most popular) | $2,497/mo | up to 12 | **monthly** |
| Platinum | $4,397/mo | up to 24 | frequent |
| Enterprise | $6,997/mo | unlimited | custom |

**The unit of work is a CAMPAIGN, and a campaign is a MONTH.** Each one has a
theme, one hero film (~3:00–3:30, or ~15:00 for a podcast month) and a set of
reels cut from it. Z Brothers' year runs Institucional → Diferenciais →
Histórias Reais → Bastidores → Podcast → Brasil×EUA → Realtor Series →
Histórias Reais → Cultural → Luxury Showcase → Partner Podcast → Retrospectiva.

🔑 **This is why the studio portal cannot be reused as-is.** The studio portal
answers *"how many hours do I have left and when am I booked?"* A ROADMAP client
asks a different question: **"where are we in my year, what was delivered, what
is being filmed next, and what do you need from me?"** Hours are not the unit.
Campaigns are.

## 1 · What the portal must show

0. **Login** — email + 6-character access code, identical to the studio portal
   (`mwmcreations.com/studio-portal/`). Same mechanism, same welcome-email copy,
   same "codes cannot be recovered, we reissue" support answer. A ROADMAP client
   should not have to learn a second way in.
1. **Plan header** — client, tier, contract window, allowance, strategist.
2. **At a glance** — campaigns delivered / allowance, videos delivered (hero +
   reels), **files awaiting the client's review** (live counter), renewal date.
3. 🔑 **Next filming session** — date, time, location, the campaign it belongs
   to, its confirmation state, and **what MWM needs from the client before it**
   (guest confirmed, release signed, questions approved, assets sent).
   *This is the single most valuable panel — it is where annual plans stall.*
4. **Needs your attention** — open approvals and decisions, with age. Items
   disappear the moment the client resolves them.
5. **The annual roadmap** — all 12 campaigns, each expandable: theme, concept,
   shoot date, status, deliverables with links **and approval controls**.
6. **Deliverables library** — flat, sortable, everything delivered this year,
   each row carrying its approval status.

**Campaign status ladder:** `planned → scheduled → filmed → editing → delivered`
(mirrors the studio Event Rail vocabulary — do not invent a second one).

## 2 · Data model — additive, alongside the studio tables

```sql
wp_mwm_roadmap_clients
  id, client_name, company, email, access_code (wp_hash_password),
  plan            ENUM('silver','gold','platinum','enterprise'),
  campaigns_allowed INT,          -- 6 / 12 / 24 / 0=unlimited
  contract_start DATE, contract_end DATE,
  strategist VARCHAR, status ENUM('active','paused','ended')

wp_mwm_roadmap_campaigns
  id, client_id, month_no INT, title, theme_desc TEXT,
  hero_spec VARCHAR,              -- "Hero ~3:30"
  status ENUM('planned','scheduled','filmed','editing','delivered'),
  shoot_date DATETIME NULL, shoot_location VARCHAR NULL,
  shoot_state ENUM('none','proposed','pre_scheduled','confirmed','rebooking')
                  DEFAULT 'none',
  shoot_kind  ENUM('studio','location') NULL,   -- drives the notice rule
  requested_by VARCHAR NULL, requested_at DATETIME NULL,
  hold_expires_at DATETIME NULL,
  confirmed_by VARCHAR NULL, confirmed_at DATETIME NULL,
  delivered_at DATE NULL, sort_order INT

wp_mwm_roadmap_assets
  id, campaign_id, title, kind ENUM('hero','reels','captions','stills','other'),
  url TEXT, qty INT DEFAULT 1, delivered_at DATE,
  -- §5 approval state
  review_state ENUM('review','approved','fix') DEFAULT 'review',
  revision_no INT DEFAULT 1,
  reviewed_by VARCHAR NULL, reviewed_at DATETIME NULL

wp_mwm_roadmap_asset_events     -- append-only audit trail, never updated
  id, asset_id, event ENUM('delivered','approved','changes_requested',
                           'revision_delivered'),
  actor VARCHAR,                 -- client email, or 'MWM:<user>'
  note TEXT NULL, created_at DATETIME

wp_mwm_roadmap_actions          -- "needs your attention"
  id, client_id, campaign_id NULL, title, detail TEXT,
  due_date DATE NULL, resolved TINYINT, created_at DATETIME
```

## 3 · Reuse, do not rebuild
- **Auth:** same email + 6-char access code as the studio portal
  (`wp_hash_password`, provisioned via the snippet-15 endpoint pattern).
  A client on BOTH products should log in once and see both.
- **Provisioning:** clone `studio_package.provision_portal_client()` shape.
- **Shoot dates:** already live in Google Calendar and the Event Rail. The
  portal should READ them, not hold a second copy that can drift.
- **Deliverable links:** LARA already maintains these in a Google Sheet. 🔑
  **Phase 1 should SYNC FROM that sheet, not replace it** — LARA owns that
  surface and taking it away before the portal is proven is how the data stops
  being maintained.

## 4 · Build order
1. Schema migration (additive, `dbDelta`).
2. Login + read-only portal page rendering from the tables — no editing UI yet.
3. Admin screen for Michael/LARA to set campaigns + paste asset links.
4. Sheet sync (LARA's sheet → `roadmap_assets`), one-way, idempotent.
5. Calendar read for shoot dates.
6. **Approval workflow (§5)** — the first place the client writes to the DB.
7. **Availability calendar + pre-schedule requests (§6)** — Google Calendar
   read, notice-rule enforcement, admin confirm/decline.

---

## 5 · Delivery approval workflow  🔑 *new in v0.2*

Michael: *"have the approval section almost like a live kind of thing where we
can change from delivery to, if we are doing an adjustments, or if it's already
approved."*

**State machine — per ASSET, not per campaign.** A month can be half approved.

```
        (MWM uploads)
            ↓
        [ review ] ──── client clicks Approve ────→ [ approved ]  (terminal)
            │  ▲
            │  └──────── MWM uploads revision ──────────┐
            │                                           │
            └── client clicks Request adjustments ──→ [ fix ]
                        (note is REQUIRED)
```

- `review` — *"Awaiting your review."* Blue. Counts toward the header stat and
  raises a **Needs your attention** row.
- `approved` — *"Approved."* Green, terminal, stamped `Approved by you · <when>`.
  Notifies LARA + the editor.
- `fix` — *"Adjustments requested."* Gold. The note is mandatory — a bare
  "change it" is the thing that costs a round trip. Notifies the editor,
  creates an internal task, and shows the client an expected turnaround.
- MWM uploading a revision bumps `revision_no` and returns the asset to
  `review` as *"Revision delivered — awaiting review."*

**Rules**
- Everything is appended to `wp_mwm_roadmap_asset_events`. State is derived,
  history is never overwritten — when someone asks *"who approved this and
  when,"* the answer must exist.
- The client sees the whole thread inline: delivered → their note → revision →
  approved. That thread is the reason they stop emailing about it.
- A campaign's status shows `delivered` only when **every** asset on it is
  `approved`. Otherwise it reads `Awaiting review` or `Adjustments requested`.
- MWM-side mirror: the same three states, editable from the admin screen, so
  Michael/LARA can move something manually when a client approves by phone.
- Optional guard rail for later: auto-approve after N days of silence, so a
  quiet client doesn't leave a month hanging forever. **Not in v1** — it should
  be Michael's call, per client.

---

## 6 · Scheduling: client pre-schedules, MWM confirms  🔑 *rewritten in v0.3*

Michael, Aug 9 — after first ruling self-booking out, then landing here:

> *"What if about the scheduling we can have both of the both worlds — they can
> see a whole calendar and they can pick a day and pre-schedule and we need to
> confirm… at least seven days in advance if it's an exterior film shoot; if
> it's in our studio, 48 hours before we'll be fine."*

This is better than either extreme. The client gets the self-service feel of the
studio portal; MWM keeps the veto that on-location shoots require.

### 6.1 The distinction that makes it work

A **pre-schedule is not a booking.** Picking a day holds the slot and files a
request. The shoot is not real until a producer confirms. That single word
carries the whole design — it is why the client can be trusted with a calendar.

```
  [ none ] ── client picks a day ──→ [ pre_scheduled ] ──→ [ confirmed ]
                                            │  ▲              (locked)
              MWM proposes instead ─────────┘  │
                                               └── MWM declines w/ reason,
                                                   proposes an alternative
```

Both directions still exist: MWM can propose (v0.2 flow) **and** the client can
pre-schedule. They converge on the same `confirmed` state.

### 6.2 Notice rules — MICHAEL'S RULE, enforced in the UI

| Shoot type | Minimum notice |
|---|---|
| **MWM Studio** | **48 hours** |
| **On location / exterior** | **7 days** |

Enforcement principles:
- The shoot-type toggle is the FIRST control on the calendar, because it changes
  which days exist. Flip it to on-location and the next five days disappear.
- Days inside the notice window are **unpickable, not warned about**. A rule you
  can click through is a rule you will be asked to break. Nothing to argue with.
- The rule text names the earliest **open** day (clears notice AND we are free) —
  not just the raw cutoff, which may land on a Sunday or a booked day.
- Server re-validates on submit. The client-side block is convenience, not
  security — never trust the browser on a rule that costs a crew day.
- Exceptions are Michael's call only, made in the admin screen. Same posture as
  the studio 24-hour policy: the portal never grants one.

### 6.3 Availability shown to the client
- Read from Google Calendar (already connected — do NOT keep a second copy).
- Show **free / not free** only. Never expose what the other booking is; that is
  another client's business.
- Sundays closed by default; per-client blackout dates supported.
- A pre-scheduled but unconfirmed day shows to that client as *theirs, pending*
  and to everyone else as unavailable — otherwise two clients hold one crew.
- **Hold expiry:** an unconfirmed pre-schedule must not hold a day forever.
  **LOCKED: 48h**, then it releases and the client is told.

### 6.4 What the client submits
Date · time window (Morning 9–12 / Afternoon 1–4 / Full day 9–5) · shoot type ·
**address, required for on-location** · which campaign it belongs to · free-text
notes (who's on camera, gate codes, parking, guests to invite).

### 6.5 Reschedule policy — LOCKED (Aug 9)
The studio's 24-hour cancellation policy does NOT carry over. The roadmap rule
**mirrors the notice rules**: inside 48h (studio) or 7 days (on-location), a
reschedule burns the filming day for that campaign. Michael's exception only —
the portal never grants one, and no agent may promise one.

---

## 7 · Notifications — who hears about a pre-schedule  🔑 *new in v0.4*

Michael: *"when the client pre-schedules, what kind of communication is that
gonna be? I think it's a good idea to send to info@mwmcreations.com."*

### 7.1 What happens today (for contrast)
A studio-portal booking does **not** email anyone. It posts to Slack **#matt**
via `booking_sync_alert()` (`app.py`, `studio_booking_webhook` → `_sb_process`).
That is fine for a studio hour — the room is either free or it isn't, and the
booking is already final. A roadmap pre-schedule is a different animal: **it is
not final, and it has a clock on it.** So it needs email, and email is new work.

### 7.2 The rule that shapes this
A pre-schedule is **not an FYI — it is a task with a deadline.** An on-location
request carries 7 days of runway. If the notification sits unread for three of
them, more than half the lead time Michael just set is gone before anyone looks.
So the notification must (a) reach a box someone is always in, and (b) carry the
action itself, not a link to go find the action.

### 7.3 Channels — on a client pre-schedule

| # | Channel | To | Contents |
|---|---|---|---|
| 1 | **Email** | **info@mwmcreations.com** | The record + the action. Subject carries the decision inputs: `🎬 Pre-scheduled — Z Brothers · Mon Aug 17, full day · ON LOCATION (Winter Garden)`. Body: client, campaign, date, window, shoot type, address, notes, and **Confirm / Decline & propose another** buttons. |
| 2 | **Slack** | `#lara` (delivery owner) + `#matt` if unconfirmed at 24h | Short line, same two buttons. Slack is the nudge; email is the record. |
| 3 | **Email** | the client | *"We've got it — holding Mon Aug 17 for you."* Not a confirmation. Wording must not imply the shoot is booked. |

On **confirm**, two more: the client gets the real confirmation **with the
calendar invite** (reuse `harden_event_body` so the attendee actually lands on
the event — that path has bitten us before), and the portal flips to Confirmed.

On **decline**, the client gets the reason plus a nudge back to the calendar.

### 7.4 Why info@ and not michael@
- It is already the shared operational inbox — everything outbound sends from
  `info@`, never `michael@` (see `app.py:11834`). Consistent surface.
- **LARA owns roadmap delivery.** A shared box means a request can be actioned
  when Michael is travelling, which is most of the time. A personal box makes
  him the single point of failure on a 7-day clock.
- 🔴 Design note: whatever handles `info@` must not treat these as leads. They
  are operational, from an authenticated portal client. Tag or label them so
  the reply automation never touches them.

### 7.5 Confirming from the email — the part that saves Michael's time
The buttons carry a **signed, single-use token** (HMAC over booking id + action
+ expiry), so one tap confirms without logging into anything. Requirements:
- Token expires with the hold (§6.3).
- Replay-safe — a second tap on the same link shows current state, does not
  re-fire.
- Every confirm/decline is written to the audit trail with who and when. An
  email tap is still an actor.
- Decline requires a reason; it goes to the client verbatim.

### 7.6 Escalation
If a pre-schedule is unconfirmed at **24h**, re-ping `#matt`. At **hold expiry**
(§6.3) it releases, the client is told, and the day reopens. Silence must never
be the thing that decides — that is how a client shows up to a shoot nobody
booked.

---

## 8 · Open questions for Michael
1. **Who maintains it?** LARA owns deliverables today. Portal should not create
   a second place to update, or it will rot. Sync or hand over — pick one.
2. **Language.** Z Brothers' roadmap is in Portuguese; the portal chrome is
   English. Per-client language flag?
3. **Do ROADMAP clients also get studio hours?** If yes, one login must show
   both, and hours belong on this portal too.
4. Should the client see the *whole* year up front, or only campaigns already
   agreed? (Prototype shows the whole year — it demonstrates the value of the
   plan they bought.)
5. **Reschedule policy for on-location shoots** — §6.5. Needs a written rule
   before the confirm button goes live.
7. **Hold expiry** — how long does an unconfirmed pre-schedule hold a day before
   it releases? (§6.3, proposed 48h.)
8. **Sundays** — closed by default in the prototype. Correct?
9. **Does LARA get the pre-schedule email too, or only Slack?** (§7.3)
   Working default: Slack only.
10. ~~Who may confirm~~ — **LOCKED (Michael, Aug 9): Michael only.** The token
    is issued to him alone; LARA is notified but has no button. Single-approver
    means the escalation ping at 24h (§7.6) is load-bearing, not optional.
6. **Who gets notified** on approve / request-adjustments — LARA, the editor,
   Michael, or all three? Wrong answer here means either noise or silence.

---

## 9 · The real ROADMAP roster — read from Stripe, Aug 9 2026

Read-only query against live Stripe (`GetSubscriptions` + `GetProducts`). The
plans are real Stripe products: **GOLD PLAN** `prod_OIxgvyHybU4UJG`
("Up to 12 strategic campaigns per year") and **SILVER PLAN**
`prod_OJHRqgj6a2GZzV` ("Up to 6"). Active subscriptions on them:

| Client | Email | Plan | MRR | Note |
|---|---|---|---|---|
| Zerlotini Brothers LLC | thiago@zbrothersconstruction.com | GOLD | $2,397 + $30 | legacy price; the roadmap doc this portal was designed from |
| Luiz Bolfer | drbolfer@gmail.com | GOLD | $2,497 | |
| Antonio de Paula Valentim | valentim1981@hotmail.com | GOLD | $2,497 | 🔴 `pause_collection: void` — billing paused |
| ENZO Auto Services | admin@enzoautoservice.com | SILVER | $1,897 + $30 | 6 campaigns, not 12 |

**So phase 1 is four clients, not one.** Small enough to seed by hand, which is
why the admin screen beats the sheet sync as the next build.

🔴 Two things Michael has to settle before provisioning:
1. **Valentim's billing is paused.** Does a paused contract get portal access?
2. **Smile American** has a full 12-month roadmap in Drive
   (`Smile_American_Roadmap_Detalhado.docx`, Gold, Portuguese) but **no active
   Stripe subscription**. Client, churned, or billed another way?

### 9.1 What this changes about the sheet sync
LARA's deliverables live in **MWM Post-Production Tracker 2026**
(`11il4ab5ycN5uCS25jkaTLesbH_HtgALlc1DRgO9i-7U`). Two problems for a phase-1
sync:
- **It has no campaign/month column.** It is a flat project list across every
  client and every service — there is no "Month 07 — Realtor Partner Series" to
  map onto `roadmap_campaigns`. A sync would have to guess from client + shoot
  date, and guessing wrong shows a client the wrong film.
- **Last modified Jun 24 2026** — six weeks stale as of today. Syncing from it
  would import that staleness and make the portal look broken.

It does carry `Revision Round`, `Final Delivery Link`, `Status` and
`Client Notes`, which map cleanly onto §5 once the campaign dimension exists.

**Conclusion: demote the sheet sync from build step 4 to later.** Build the
admin screen first, enter the four clients' campaigns there, and treat the
tracker as an import assist rather than the source of truth.
