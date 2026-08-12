# A2P 10DLC — why campaign CM87b39e12 failed four times

**Aug 12 2026 · DEV**

Four rejections. Every fix before today edited the **words** on the consent
checkbox. Nobody checked what the checkbox **did**.

---

## Finding 1 — the consent was never stored

`/book-studio/` collected a mobile number (`#bs-phone`, `name="phone_number"`)
and a consent tick (`#bs-sms-consent-box`, `name="sms_consent"`).

The widget's `reserve()` posted exactly seven fields to `mwm_studio_hold_slot`:

```
date · start_time · hours · editing · name · email · notes
```

Neither the phone nor the consent was among them. `mwm-studio-booking.php`
reads those same seven and contains **zero** references to a phone number or a
consent flag anywhere in the file.

The number was typed and thrown away. The box was ticked and thrown away.

Meanwhile `/sms-opt-in/` told the reviewer: *"Consent is recorded against the
phone number with a timestamp at the moment of submission."* That had never
been true for a single web-form opt-in.

🔑 **A consent checkbox that is not stored is not consent. It is a picture of
consent.**

## Finding 2 — one page made consent a condition of purchase

`/studio-hour/` (page 1193, the AD_09 paid-traffic landing page):

```js
<button id="sh-buy" disabled>Book My Studio Hour — $349</button>
<p id="sh-hint">Tick the box above to continue.</p>
box.addEventListener('change', function(){ btn.disabled = !box.checked; });
btn.addEventListener('click',  function(){ if(!box.checked) return; ... });
```

You could not buy without ticking the SMS consent box — while the label on that
same box read *"Consent is not a condition of purchase."* It said the words and
did the opposite, on the page a reviewer is most likely to be sent to.

The page had **no phone field**, so it took SMS consent for a number it never
collected, and stamped it onto the Stripe session as
`client_reference_id=smsconsent-<timestamp>` — a consent record with nobody in
it, gathered under duress, on every single purchase.

This is the most likely reason the opt-in kept reading as non-compliant after
the wording was corrected.

---

## What shipped

| Surface | Change |
|---|---|
| `/book-studio/` (741) | Two separate checkboxes — transactional, and optional marketing. Both unchecked, neither gates the form. Phone + both answers now submitted. |
| `/studio-hour/` (1193) | Consent checkbox **removed**. Buy button ungated. Stripe consent stamp removed. |
| ledger | New table `{prefix}mwm_sms_consent` — number as typed + E.164, two independent flags, UTC timestamp, name, email, page URL, IP, user agent. Readable at **Tools → SMS consent log**. |
| `/sms-opt-in/` (1159) | Rewritten to describe what the code actually does. |

**The fix on 1193 is removal, not splitting.** An opt-in that cannot be
honoured should not exist. Consent is now collected in exactly one place on the
web, where there is a real phone field and a real record.

## Verified, not assumed

```
table=exists · hook_nopriv=yes@1 · hook_priv=yes
ROW WRITTEN=yes · e164=+14075550134 · transactional=1 · marketing=0
utc=2026-08-12 19:19:01 · url=https://mwmcreations.com/book-studio/
test row deleted, remaining rows=0
no-consent submission wrote=0
```

Buy button on `/studio-hour/` clicked through to Stripe checkout with no
`client_reference_id` — revenue path intact.

## The rule

🔴 **Never edit the label without reading what the field does.** Three weeks and
four rejections went into rewording a control that discarded its own value.
