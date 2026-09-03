"""What we have PUBLISHED about texting, as data the code can be tested against.

PATCH #117.

Campaign CM87b39e12 was rejected three times before it was approved, and every
rejection came from the same shape of problem: the words on the website, the
words in the opt-in form, and the words in the message did not say the same
thing. Nothing in this repo could catch that, because the promises lived on
WordPress and the behaviour lived in Python, and neither knew about the other.

So the promises live here now, as data, with the URL they came from and the
date somebody actually read them. `test_sms_promises.py` asserts the code
against this file, which means a future edit to the copy or the caps that
contradicts the published terms **fails the build** instead of failing a
carrier review six weeks later.

⚠️ THIS FILE IS A CLAIM ABOUT THE OUTSIDE WORLD, AND IT GOES STALE.
It is not the source of truth — the website is. `VERIFIED_ON` says when the
pages were last read; if that date is old, re-read them before trusting this.
A promise with a date on it is worth more than a promise without one.
"""

# ── the pages, and when they were last actually read ───────────────────
SOURCES = {
    "terms_s19": "https://mwmcreations.com/terms/",
    "opt_in_form": "https://mwmcreations.com/sms-signup/",
}

VERIFIED_ON = "2026-09-02"
VERIFIED_BY = ("DEV — both pages fetched and read end to end the night of "
               "2 Sep 2026, after the §19 rewrite was published")

# ── what those pages say ───────────────────────────────────────────────
PUBLISHED = {
    # The name a recipient must be able to recognise, in the message itself.
    "business_name": "MWM Creations & Studios",

    # §19 and the form now describe TWO promises, not one. This is the change
    # that unblocks SMS_TERMS_SPLIT_LIVE — the flag was deliberately held at 0
    # until §19 said what the form says. As of VERIFIED_ON, it does.
    "separate_consents": True,

    # "Message frequency varies and is typically no more than 4 messages per
    # month" — stated under MARKETING. Transactional frequency is described as
    # varying with bookings, with no number attached, so no cap may be
    # promised in a transactional message.
    "marketing_monthly_cap": 4,
    "transactional_capped": False,

    # Both pages carry these. All four are carrier requirements, not garnish.
    "opt_out_keyword": "STOP",
    "help_keyword": "HELP",
    "states_rates_may_apply": True,
    "states_not_condition_of_purchase": True,

    # Neither box is pre-ticked, and the form can be submitted with neither.
    "consent_boxes_prechecked": False,

    # We enforce quiet hours in code but do NOT publish them. That is allowed
    # — the federal window applies regardless — and it is recorded here so
    # nobody later "fixes" a mismatch that was never a mismatch.
    "publishes_send_hours": False,
}


def drift(brand, suffix, marketing_copy, transactional_copy,
          marketing_cap, bundled_cap, split_live):
    """Every place the code disagrees with what we published. Empty is good.

    Kept as a function rather than a pile of asserts so the readiness endpoint
    can call it too — a mismatch should be visible in /health, not only in a
    test run nobody watches.
    """
    out = []
    name = PUBLISHED["business_name"]
    if brand != name:
        out.append(f"brand is {brand!r}, the published business name is {name!r}")
    if PUBLISHED["opt_out_keyword"] not in (suffix or ""):
        out.append("outbound copy does not carry the published STOP keyword")
    if PUBLISHED["help_keyword"] not in (suffix or ""):
        out.append("outbound copy does not carry the published HELP keyword")

    cap = PUBLISHED["marketing_monthly_cap"]
    if str(cap) not in (marketing_copy or ""):
        out.append(f"the marketing opt-in confirmation does not state the "
                   f"published cap of {cap} a month")
    if int(marketing_cap) != int(cap):
        out.append(f"marketing cap is {marketing_cap}, published cap is {cap}")
    if int(bundled_cap) != int(cap):
        out.append(f"bundled cap is {bundled_cap}, published cap is {cap}")

    # A transactional message must not promise a frequency, because the pages
    # never promised one for transactional. Saying "no more than 4 a month"
    # about booking reminders would be inventing a limit we cannot keep.
    if not PUBLISHED["transactional_capped"]:
        for token in ("a month", "per month"):
            if token in (transactional_copy or "").lower():
                out.append("the transactional confirmation promises a monthly "
                           "frequency; the published terms do not")
                break

    if PUBLISHED["separate_consents"] and not split_live:
        out.append("NOT A DEFECT, AN ACTION: the published terms now describe "
                   "two separate consents, so SMS_TERMS_SPLIT_LIVE=1 is safe "
                   "to set. Until it is, the machine keeps the stricter "
                   "bundled promise and caps booking reminders too.")
    return out
