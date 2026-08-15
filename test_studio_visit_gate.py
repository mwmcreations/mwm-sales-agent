#!/usr/bin/env python3
"""test_studio_visit_gate.py — Patch #101. The label is not the fact.

Aug 15 2026, on Michael's calendar: "Studio Visit — James Perry (1wayy5 (music
artist))", 3pm Monday, booked by Maya off an Instagram ad. Michael: *"this lead
is not a studio visit candidate."*

Patch #74 was written for exactly this lead, ten days earlier, after a hobbyist
musician took a 10 AM tour. It still let this one through, because both of its
tests are answered by the model that wants to make the booking: it checks `role`
against an allow-list and `business` for non-emptiness, and Maya supplies both.
She wrote the business as "1wayy5 (music artist)" and filed the role under
`professional_personal_brand` — defined in the code as an EARNING practice,
lawyer/doctor/coach/consultant/realtor. To a language model a music artist IS a
personal brand. The gate was auditing its own witness.

⚠️ The risk in fixing this is over-blocking. A tattoo artist, a makeup artist
and a visual artist run earning practices and are real clients — and PODCASTERS
ARE THE CORE PRODUCT. Half of this file exists to keep those booking.

Run: python3 test_studio_visit_gate.py
"""

import sys

from event_rail import (studio_visit_verdict, looks_like_music_artist,
                        STUDIO_ROLES_ALLOWED, STUDIO_ROLES_BLOCKED,
                        STUDIO_FLOOR_USD, CAMPAIGN_FLOOR_USD, applicable_floor)

_passed = _failed = 0
_FAILS = []


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  PASS  " + label)
    else:
        _failed += 1
        _FAILS.append(label)
        print("  FAIL  " + label + "\n          got={!r}\n         want={!r}".format(got, want))


def allows(role=None, business=None, **kw):
    return studio_visit_verdict(role=role, business=business, **kw)[0]


def section(title):
    print("\n" + title + "\n" + "-" * len(title))


# ══════════════════════════════════════════════════════════════════════
section("1 · the two incidents this gate exists for")

# The one that got through on Aug 15 — the exact strings off the calendar event.
check("James Perry is refused the studio",
      allows(role="professional_personal_brand", business="1wayy5 (music artist)"), False)
check("...and the refusal names the booking page, so Maya has somewhere to send him",
      "studio-hour" in studio_visit_verdict(
          role="professional_personal_brand", business="1wayy5 (music artist)")[1], True)
check("...and tells her not to present slots",
      "do not present time slots" in studio_visit_verdict(
          role="professional_personal_brand", business="1wayy5 (music artist)")[1].lower(), True)

# The one #74 was written for, whose shape #74 documented and still allowed.
check("Joseph Hernandez is refused too",
      allows(role="professional_personal_brand", business="Cositø (proyecto musical)"), False)

# The label alone must no longer be enough in either direction.
check("a music artist labelled owner_founder is still refused",
      allows(role="owner_founder", business="independent recording artist"), False)
check("...and labelled marketing_lead",
      allows(role="marketing_lead", business="rapper / hip hop"), False)
check("the tell in the ROLE field alone is enough",
      allows(role="music artist", business="Perry Media LLC"), False)


# ══════════════════════════════════════════════════════════════════════
section("2 · 🔴 the clients Michael actually has must still book")

for who, role, biz in (
    ("Z Brothers Construction", "owner_founder", "Zerlotini Brothers LLC (construction)"),
    ("Smile American Dental", "professional_personal_brand", "Smile American Dental"),
    ("Vida Fit (gym)", "owner_founder", "Vida Fit — gym in Orlando"),
    ("Starrz Talk (podcast)", "owner_founder", "Starrz Talk — podcast/radio show"),
    ("a realtor", "professional_personal_brand", "Keller Williams Orlando"),
    ("VS International Properties", "owner_founder", "VS International Properties"),
    ("MyParkTickets", "owner_founder", "MyParkTickets — ticket reseller"),
    ("a tattoo artist", "owner_founder", "Ink Theory Tattoo Studio"),
    ("a makeup artist", "professional_personal_brand", "makeup artist — bridal"),
    ("a visual artist with a gallery", "owner_founder", "visual artist, gallery owner"),
    ("a coach", "professional_personal_brand", "executive coaching practice"),
    ("a marketing lead", "marketing_lead", "A Society Marketing"),
):
    check("{} still books".format(who), allows(role=role, business=biz), True)

# The single most expensive false positive available. Podcasts are the product.
check("'podcast' is never a music marker", looks_like_music_artist("podcast host"), False)
check("...nor 'video podcast production'", looks_like_music_artist("video podcast production"), False)
check("...nor a podcast studio", looks_like_music_artist("podcast studio owner"), False)


# ══════════════════════════════════════════════════════════════════════
section("3 · what counts as the tell")

for t in ("music artist", "musician", "recording artist", "rapper", "singer",
          "songwriter", "vocalist", "beatmaker", "music producer",
          "proyecto musical", "artista musical", "indie artist", "my music",
          "hip hop", "hip-hop", "mixtape", "DJ", "the band", "music career"):
    check("'{}' reads as a music artist".format(t), looks_like_music_artist(t), True)

for t in ("artist", "creator", "Artist", "  creator  "):
    check("a field that is exactly '{}' is not enough to book".format(t.strip()),
          looks_like_music_artist(t), True)

for t in ("", None, "construction", "dental practice", "real estate",
          "marketing agency", "gym owner", "restaurant", "law firm",
          "photographer", "content creator for my clinic"):
    check("{!r} is not a music artist".format(t), looks_like_music_artist(t), False)


# ══════════════════════════════════════════════════════════════════════
section("4 · #74 and S84 still behave exactly as before")

check("an unknown role still fails closed", allows(role=None, business="Acme Ltd"), False)
check("an empty business still blocks", allows(role="owner_founder", business=""), False)
check("a blocked role still blocks",
      allows(role="freelancer_hobbyist_student", business="Acme Ltd"), False)
check("a stated budget under the rate card blocks",
      allows(role="owner_founder", business="Acme Ltd", stated_budget=100), False)
check("a lead already declined on price stays blocked",
      allows(role="owner_founder", business="Acme Ltd", budget_declined=True), False)
check("silence on budget still passes — vague is not below floor",
      allows(role="owner_founder", business="Acme Ltd", stated_budget=None), True)
check("$300 clears the rate card", allows(role="owner_founder", business="Acme Ltd",
                                          stated_budget=300, floor=STUDIO_FLOOR_USD), True)
check("...but not the campaign floor", allows(role="owner_founder", business="Acme Ltd",
                                              stated_budget=300, floor=CAMPAIGN_FLOOR_USD), False)
check("a campaign-sourced lead is held to $349",
      applicable_floor(ad_id="120250280385450738"), CAMPAIGN_FLOOR_USD)
check("an organic lead is held to the rate card", applicable_floor(), STUDIO_FLOOR_USD)

check("the new role labels are on the blocked list",
      {"artist", "creator", "music_artist", "artist_musician_creator"} <= STUDIO_ROLES_BLOCKED, True)
check("the allowed list is unchanged", STUDIO_ROLES_ALLOWED, {
    "owner_founder", "executive_decision_maker", "marketing_lead",
    "professional_personal_brand"})

# A refusal is a different door, never a rejection of the person.
_why = studio_visit_verdict(role="owner_founder", business="rapper")[1]
check("the refusal offers a route rather than closing one",
      ("booking page" in _why or "studio-hour" in _why) and "call" in _why, True)


print("\nP101_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))
print("\n" + "=" * 60)
print("  TOTAL: {} passed, {} failed".format(_passed, _failed))
if _FAILS:
    for f in _FAILS:
        print("   -", f)
print("=" * 60)
sys.exit(1 if _failed else 0)
