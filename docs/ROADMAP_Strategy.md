# MWM ROADMAP™ — PROGRAM STRATEGY v1.0

**Authored Aug 11 2026, from a working session between Michael and DEV.**
This is the **business model**: what a client buys, what it costs MWM, and what
rules govern the exchange. `ROADMAP_Portal_Spec.md` is the **build spec** — how the
portal implements this. When the two disagree, **this document wins** and the spec
gets corrected.

> Michael, at the close of that session: *"what we have done in this session it's
> very very important… it's gonna change the way we work with our clients from now
> on and vice versa."*

Everything here is either Michael's ruling, or a proposal he accepted in that
session. Where a number is an estimate rather than a measurement, it says so.

---

## 1 · The thing being sold

**The unit of work is a CAMPAIGN, and a campaign is a MONTH.** One theme, one
production day, many deliverables.

The word is load-bearing and was chosen deliberately:

> *"Some clients will get confused and think that one film shoot is like one video…
> 'oh, just one video a month, it's not enough.' And this is not true."*

🔴 **NEVER publish an hours figure against a campaign.** "Up to 6 hours" invites a
client to feel short-changed when a shoot wraps in three, and re-anchors them on
duration instead of outcome — the exact disease the word "campaign" exists to cure.
A campaign is **a full production day**, with no published hour count.

🔴 **NEVER publish a fixed deliverable count either.** Michael: *"some campaigns are
gonna produce more deliverables than others, so I don't like to tell them there is
one hero and eight social cuts and two teasers. I don't want to lock those numbers."*
Deliverables follow from what the campaign was. **The cap is on the input, not the
output** — see §3.

---

## 2 · The three dials

Everything in this program is governed by three finite resources. They exist
because they are **the three things that actually cost MWM money**, and they are
priced independently.

| Dial | What it measures | The real cost behind it |
|---|---|---|
| **Film days** | Times MWM mobilises a crew | A full production day, whether you roll 2 hours or 6 |
| **Edit days** | Post-production capacity consumed | Editor time — the true bottleneck |
| **Throughput** | How many campaigns are in post at once | Fixed at ONE. See §5 |

🔑 **The scarce resource in production is the number of times MWM MOBILISES, not
hours rolled.** A "two-hour shoot" is a five-hour crew day — studio, load, drive,
shoot, drive, unload — costing ~70% of a full day. Any rule that prices a short
shoot as a *fraction* of a campaign loses money on every one.
**You cannot make short dedicated shoots cheap. You can only make them fewer.**

---

## 3 · Edit days — the post budget

**Michael's estimates, from experience, not measurement.** They are the basis of
every number in this document and should be revisited once real data exists.

| Campaign type | Edit days |
|---|---|
| Institutional video | 3 |
| Full day on location (e.g. ENZO) | 4 |
| Before / after video | 2 |
| Testimonial video | 1 |
| Podcast episode *(incl. shorts — AI assists cuts + captions)* | 1 |
| Social media videos shot in studio | 1 |

🔑 **Campaign types differ by 4× in post cost.** This is why an edit budget is
mandatory: given a free hand, a client will naturally choose the impressive ones —
every month becomes institutional or on-location, MWM absorbs 3–4 edit days a month
on a plan priced for one or two, and the flexibility we are selling becomes the
thing that breaks the margin.

**Each plan therefore carries an annual edit-day budget.** The client composes their
mix inside it. Wanting institutional every month (36) on a Gold budget (30) means
trading two months down to testimonials or podcasts — **which is exactly the
creative trade-off the portal exists to enable.**

🔴 **EDIT DAYS ARE INTERNAL. THE CLIENT NEVER SEES THE NUMBER.** It is MWM's cost
structure. Publishing it invites a negotiation about whether an institutional
*really* takes three days. The client sees a **fullness meter** — *"this campaign is
80% planned"* — never units, never days. Same reasoning as §5's hidden queue.

---

## 4 · The plans

| Plan | Price/mo | Campaigns | Film days | Edit days *(proposed)* | Captures *(proposed)* | Studio hrs |
|---|---|---|---|---|---|---|
| Silver | $1,997 | 6 | 6 | 15 | 2 | 6 |
| **Gold** | $2,497 | 12 | 12 | 30 | 4 | 12 |
| Platinum | $4,397 | 24 | 24 | 60 | 8 | 24 |
| Enterprise | $6,997 | "unlimited" — governed by §5, not by a count | | | negotiated | |

⚠️ Edit-day and capture figures are **proposals awaiting Michael's ruling.** Derived
from ~2.5 edit days average per campaign. Capture allowance is deliberately
conservative and DEV believes it is too low — see §6.

🔑 **The flex bucket should be the client's choice at signup.** Z Brothers hold 12
studio hours and have used **zero**, while the thing they ask for repeatedly —
filming houses on location — is not in their plan at all. **Their flex allowance is
denominated in the wrong currency for their business.** A builder does not need a
studio; an author or a coach needs nothing else. Proposal, accepted in principle:
at signup the client picks studio hours, Captures, or a split, at equal value.
*Open: does this apply mid-contract or only at renewal?*

---

## 5 · Throughput — the serial pipeline

> Michael: *"We only start editing another campaign once the first one is already
> delivered… it's unlimited, yes, but we only start editing one video after the
> other one is fully approved and delivered."*

**Work-in-progress limit = 1, and it applies to EVERY tier, not only Enterprise**
(Michael, explicitly). This is the honest cap behind the word "unlimited": the
ceiling is not a number of campaigns, it is that **the pipeline is serial.**

### 5.1 · What this unlocks

A client's own delay becomes visibly theirs. The portal can say, without anyone
sounding like they are nagging:

> *Realtor Series is waiting on your approval — 6 days. Nothing else in your
> roadmap starts editing until it is signed off.*

That is not a reminder. It is a consequence, and it is true. It converts MWM's worst
operational problem — chasing clients, which *"pushes back film shoots a lot
throughout the year and kinda unmotivates clients"* — into something the client
resolves in their own interest.

### 5.2 · 🔴 The queue is INVISIBLE to clients

**Michael's ruling:** a client sees **only their own queue**, and must never learn
they are behind another client. *"We are not giving away our bottleneck to them."*

**Therefore the portal MUST NOT COMPUTE DELIVERY DATES.** MWM's editor is shared
across all clients; a client can be first in their own queue and still wait. If two
portals both calculate "editing starts the 26th", one of them is lying and MWM has
to explain it.

**Instead, show state — and let a date appear only when it is real:**

`Approved` → `In your queue` → `Editing now` → `Delivered`

A client in the queue sees position **within their own roadmap** and no promise. A
delivery date appears when editing actually starts, and it is a date a human
committed to, not one a formula guessed.

---

## 6 · Captures — flexibility priced in scheduling latitude

The recurring real case: a house completes and must be filmed before handover, or a
build needs before/during/after coverage. Two hours on location, one operator with
a gimbal. Too small for a campaign, too expensive to give away.

**What the client pays with is not money. It is control of the date.**

| | How it schedules | Allowance |
|---|---|---|
| **Series** | Property + cadence, absorbed into an existing route | **Does NOT draw down** |
| **Standard** | Client names the property, **MWM picks the day within 10 working days**, batched | Draws 1 |
| **Priority** | Client names the day, or needs it inside 5 days | **PAID at rate card**, never drawn |

This works because **a finished house has a window** — it is staged and empty for a
week or more before handover. The need is "before it is gone", not "on Tuesday".

🔴 **If a builder's handover window is shorter than 10 working days, this model
needs re-cutting.** Still unconfirmed.

⚠️ **The allowance is probably too small.** One operator with a gimbal covers 3–4
properties in a batched day, so a builder-shaped client could carry 8–12 a year
without touching margin. **Blocked on: what a Capture actually costs in crew.**

**A Capture is raw material, not an errand.** Every capture is tagged to a campaign
month and feeds that month's deliverables — acquisition spread across the month
instead of crammed into one production day.

---

## 7 · Conversion — one valve, one direction

**One unused campaign day → 6 studio hours OR 2 Captures.** Never the reverse.

- **One-way only.** A campaign carries crew, direction, editing and strategy. If
  hours could buy campaigns, a full production day has been sold at room rate.
- **Max 2 conversions per contract year.** Past that the plan has become a studio
  rental and the client belongs on a different product.
- **Never inside a shoot's notice window** (7 days location / 48h studio). That is a
  cancellation wearing a costume.
- **Renewal window:** in the final 60 days, open the valve on everything unused. It
  turns *"we paid for 12 and used 9"* from a renewal argument into a favour.
  🔴 **Z Brothers renew 14 Nov with 11 of 12 studio hours unused.**

### 7.1 · 🔴 What happens to unused campaigns at the end of a year

**Michael's ruling, Aug 11.** There are two paths and they are deliberately unequal,
because the inequality is the point.

| | What happens to the unused balance |
|---|---|
| **They renew** | **It carries over** into the new contract year. |
| **They do not renew** | **30 days' grace** to use what is left. Then it is gone. |

> *"That way we don't have to stay a full 30 days of the grace period where they have
> no contract — they are just trying to use the remaining of what they have and they
> are not even paying for that extra month. So it makes more sense that right away
> after the contract is done he starts a new contract paying for that following
> month, and we just carry over."*

🔑 **Carryover is not generosity, it is the renewal incentive.** A grace period is a
month where MWM is producing and nobody is paying. Carryover converts that month into
a paid one and makes renewing the obviously better option. **DEV proposed the
opposite — no carry, on pipeline grounds — and was overruled correctly: that answer
protected production and ignored the revenue shape entirely.**

⚠️ **The one thing to watch.** Carryover compounds if a client under-uses two years
running. One year in hand is absorbable; a client arriving at year three with nine
banked campaigns is owed twenty-one in twelve months, which cannot be built. **No cap
is set today** — flag it before the second renewal that carries a balance.

### 7.2 · 🔴 A banked campaign is the campaign, not the date

Nothing expires inside a contract year, and unfilmed campaigns bank. But the promise
has an edge, and the edge is §5: **the pipeline is serial.**

> *"They are yours and they don't expire. They are scheduled one at a time, in order."*

🔑 **Banking does not add work — it CONCENTRATES it.** Twelve campaigns still cost
twelve campaigns; what changes is that some of them slide into a shorter window that
already holds the others. **A lumpy year is precisely what a serial pipeline cannot
absorb.** So when a client is behind, the urgency is real and it is **not expiry, it
is throughput** — nothing they are owed disappears, but MWM's ability to deliver it
all in the time remaining does.

**Banked campaigns sit in the normal status ladder as `planned`, never as a credit
note** — visibly in the year, in order, behind whatever is ahead of them.

**A campaign is spent on the shoot day** (Michael), and also by a no-show or a move
inside the notice window — the crew day was committed either way.

---

## 8 · The client as producer

> Michael: *"they are gonna act as producers for us as well, so it's gonna be easier
> for us to have them putting information in rather than us having to go after all
> of those information, which sometimes pushes back film shoots a lot throughout the
> year and kinda unmotivates clients."*

**This is the operational core of the whole portal.** Chasing information is what
delays shoots; the portal makes the client supply it, structured, in their own
interest.

Every shoot carries **four confirmations**, and none is optional:

1. **Date** — confirmed, inside the notice rules.
2. **Location** — confirmed; a full street address is mandatory for on-location.
3. **Script** — *"the script has to be confirmed and approved by the client."*
   A script is an **asset**, so it runs the same approval machine as a film and
   every transition is logged — "who approved the script and when" is answerable.
4. **People** — everyone on camera, each with a role and their own confirmation.
   A podcast month reads *guest*; an institutional month reads
   *testimonial · your client*. **Unfilled slots are shown, not hidden**
   — *"third client not yet chosen — we need a name from you"* — because a gap the
   portal states out loud is a gap that gets filled before the shoot day.

---

## 9 · The roadmap is MWM's, the plan inside it is the client's

Michael, agreeing with DEV's pushback against total freedom:

> *"We cannot just let the client choose whatever. We need to give them this
> roadmap — that's the entire name of this program. We build the roadmap for them…
> and then inside what we've laid out they can choose the film shoots."*

**MWM authors the annual arc.** Institutional first, then differentiators, real
stories, a podcast month, and so on. That sequence is the expertise being sold and
is why the program works.

**Inside it the client controls:** when each shoot happens, where, who is in it,
what the script says, and how that month's capacity is spent across deliverables.

**Changes to the arc itself are PROPOSED, not made** — swap two months, change a
theme — and MWM confirms. This reuses the propose/confirm machinery already specced
for scheduling, so it costs nothing new to build and keeps MWM in the room.

---

## 10 · The AI script tool

Michael's idea, and the strongest one in the session — for a reason worth stating
precisely.

> *"The scripts are gonna have to be enough to fulfil that time and not over, so
> that intelligence can be all connected."*

🔑 **A script has a runtime, and runtime converts to shoot time.** Spoken word count
÷ speaking pace gives minutes; multiplied by coverage and setups it gives hours on
the floor. So the portal can tell a client **while they are still writing**:

> *This runs about 3:20. With two setups and B-roll, roughly two hours of your day —
> you have four left.*

That turns an abstract allowance into something felt during the creative act, and it
kills a familiar failure: a client arriving with four hours of material for a day
that also needs interviews and B-roll. **The script stops being a document and
becomes the planning instrument.** The same engine runs the other way — a finished
script implies how many short cuts it can yield, which feeds the post capacity meter.

### 10.1 · 🔴 What the AI must never do

**It drafts. It never approves and never schedules.** Left alone it will cheerfully
promise a six-part series that does not fit the day, and the people who eat that are
the crew.

### 10.2 · 🔴 The strategic risk — read this before building it

**If a client can generate their own scripts, what are they paying $2,497/mo for?**

Built carelessly, this tool argues against MWM's own invoice. A client writing their
own scripts starts wondering why they need a strategist — and strategy is precisely
what separates ROADMAP from hiring a freelancer with a camera.

**Position it deliberately: the client brings intent, the tool shapes it, MWM
directs it.** The script area is where a client dumps ideas, references, what
happened this month, which house completed. It comes back structured — and then it
enters **the approval flow, going to Michael before it reaches a shoot.** The client
feels prepared and heard. MWM stays the author of the strategy.

---

## 11 · Capacity, and the hiring case

**Michael is currently the only editor** — a position he intends to leave: *"I'm
ready to bring one or two new editors… we're gonna fix that."* He edits **3–4 days
a week**, which is ~170 edit days a year.

Current committed load: four ROADMAP clients (Zerlotini, Bolfer, Valentim on Gold;
ENZO on Silver) = 42 campaigns ≈ **95–110 edit days a year** at a ~2.5-day average.
That fits — but it consumes most of his editing year before Smile American, the
studio-portal clients, Victory, or the ads.

🔑 **The real cost is not capacity, it is what those days displace.** Three to four
days a week editing means three to four days a week not selling, not directing, not
building. This document exists because he was not editing today.

**The hiring case:** one editor at five days a week ≈ **220 edit days/year**. That
covers the entire current ROADMAP book and leaves room for **four or five more Gold
clients** — roughly $10–12k/mo of revenue MWM currently cannot accept.

**The production board (§12) makes this verifiable rather than a hunch:** committed
edit days climb toward a visible ceiling, and the hire happens *before* clients are
late, with a date and a number attached.

---

## 12 · 🔑 Build the production board FIRST

While MWM has one editor, **the highest-value screen in this system is Michael's,
not the client's**: one board showing every campaign across every client, in order,
with its edit-day cost and its state.

It answers what to pick up next. It shows in August that October is oversold. It
turns *"I'll bring editors depending on workload"* into a dated decision.

**The client portal is a filtered, sanitised read of that same board** — their own
queue only, no edit days, no other clients. Build the board and the client view is
mostly presentation.

---

## 13 · Open questions

| # | Question | Blocks |
|---|---|---|
| 1 | **What does a Capture cost in crew?** One operator + gimbal vs two-person setup | Capture allowance (§4, §6) |
| 2 | Is **10 working days** genuinely acceptable to a builder's handover window? | The entire batching model (§6) |
| 3 | Where is the line for a **crewed short shoot** needing direction — Capture, campaign day, or paid add-on? | §6 |
| 4 | Does the **flex-bucket choice** apply mid-contract or only at renewal? | §4 |
| ~~8~~ | ~~What happens to unused campaigns at the end of a year?~~ **ANSWERED Aug 11 — §7.1: carry over on renewal, 30 days' grace if not.** | — |
| 5 | Are the **proposed edit-day budgets** (30/15/60) right? | §4 |
| 6 | Do the **edit-day estimates hold by scope** — is an institutional always 3, or 3 small / 5 large? | §3 — if it varies, the client's meter must be an estimate that moves |
| 7 | How is **Enterprise** actually sold, given "unlimited" is governed by §5? | §4 |

---

## 14 · Build order

1. ~~Schema~~ — **DONE**, live as WP snippet 21, v1.1.0.
2. **Production board (§12)** — Michael's queue. Highest value while he is the only editor.
3. Client login + read-only roadmap render.
4. Producer intake — the four confirmations (§8).
5. Booking: campaign days, captures, studio hours, with notice rules enforced server-side.
6. Delivery approval workflow (already specced §5 of the build spec).
7. Capacity meters + conversion valve.
8. AI script tool (§10) — **last**, because §10.2 must be settled before it ships.
