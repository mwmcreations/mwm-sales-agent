"""
lead_form.py — PATCH #143. What a Meta Instant Form submission means.

THE FORM (ERIC, 26 Sep 2026; form 1093985030009769 "Studio Strategy Visit -
apply | Sep 2026"): full_name · email · phone_number · business_name ·
website_or_instagram · role (Owner/Founder/Partner · Marketing lead ·
Employee · Freelancer/Creator/Artist) · monthly_revenue (Under $20K ·
$20-50K · $50-150K · $150K+) · what_customers_must_understand (free text) ·
an OPTIONAL SMS-consent checkbox (custom disclaimer; Meta returns it in
`custom_disclaimer_responses`, not in field_data).

QUALIFIED (ERIC): role Owner/Founder/Partner AND revenue >= $50K; $20-50K
only if owner AND the industry fits. "Fits" is a judgement, so that case is
returned as REVIEW: Maya still opens, still offers the visit, and a human
can read the answers. Revenue under $20K or a creator role is NO — the polite
disqualify, no chase chain.

Meta's question keys are what the form builder generated from the question
text, so matching is tolerant: a key is normalised and matched by what it
contains. A key we cannot place is kept verbatim in `extra` and never
dropped — the sheet's Notes column carries it.

PURE: no network, no clock, no Flask.
"""

import re

Q_YES = "yes"        # qualified — opener + visit + chase chain
Q_REVIEW = "review"  # opener + visit + chain, flagged for a human read
Q_NO = "no"          # polite disqualify, no chain

ROLE_OWNER = "owner"
ROLE_MARKETING = "marketing_lead"
ROLE_EMPLOYEE = "employee"
ROLE_CREATOR = "creator"
ROLE_UNKNOWN = ""

# Revenue band -> lower bound in $K/month. Unknown -> None.
BAND_UNDER_20 = 0
BAND_20_50 = 20
BAND_50_150 = 50
BAND_150_PLUS = 150

# Ad id -> label, for the sheet's "Ad Campaign" column and the AI branch.
# ERIC posted these on 30 Sep. The env var META_AD_LABELS ("id:label,id:label")
# extends or overrides without a deploy.
KNOWN_ADS = {
    "120251271360280738": "S1 | Owners static",
    "120251304671210738": "AD_14 | Education business",
    "120251304671220738": "AD_15 | The room or the brain",
    "120251304671230738": "AD_17 | Client proof",
    "120251320140730738": "AD_19 | Film once | AI",
}
AI_AD_IDS_DEFAULT = ("120251320140730738",)   # AD_19 — the AI opener

_ROLE_HINTS = (
    (("owner", "founder", "partner", "ceo", "president", "proprietor",
      "director"), ROLE_OWNER),
    (("marketing",), ROLE_MARKETING),
    (("freelanc", "creator", "artist", "influenc", "musician", "student",
      "hobby"), ROLE_CREATOR),
    (("employee", "staff", "team member", "manager"), ROLE_EMPLOYEE),
)


def norm_key(key):
    s = str(key or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def parse_field_data(field_data):
    """[{name, values}] -> {normalised_key: first value (str)}."""
    out = {}
    for f in field_data or []:
        if not isinstance(f, dict):
            continue
        k = norm_key(f.get("name"))
        if not k:
            continue
        vals = f.get("values") or []
        v = vals[0] if vals else ""
        out[k] = str(v if v is not None else "").strip()
    return out


def consent_checked(custom_disclaimer_responses, fields=None):
    """True when the SMS consent box was ticked.

    Meta: custom_disclaimer_responses = [{checkbox_key, is_checked: "1"}].
    is_checked arrives as a STRING. A form may also carry the box as a plain
    field named *consent*/*sms*; both are honoured, neither is assumed."""
    for r in custom_disclaimer_responses or []:
        if not isinstance(r, dict):
            continue
        if _truthy(r.get("is_checked")):
            return True
    for k, v in (fields or {}).items():
        if ("consent" in k or "sms" in k or "text_message" in k) and _truthy(v):
            return True
    return False


def _truthy(v):
    if isinstance(v, bool):
        return v
    return str(v if v is not None else "").strip().lower() in (
        "1", "true", "yes", "y", "on", "checked")


def _pick(fields, *needles, exclude=()):
    """First value whose key contains any needle (and none of exclude)."""
    for k, v in fields.items():
        if any(n in k for n in needles) and not any(x in k for x in exclude):
            if v:
                return v, k
    return "", None


def extract(fields):
    """The form answers we care about, by meaning rather than by key."""
    fields = dict(fields or {})
    used = set()

    def take(*needles, exclude=()):
        v, k = _pick(fields, *needles, exclude=exclude)
        if k:
            used.add(k)
        return v

    name = (fields.get("full_name") or "").strip()
    if name:
        used.add("full_name")
    if not name:
        fn, ln = fields.get("first_name", ""), fields.get("last_name", "")
        name = (fn + " " + ln).strip()
        used.update(k for k in ("first_name", "last_name") if k in fields)
    email = take("email").lower()
    phone = take("phone", "mobile", "cell", "whatsapp")
    business = take("business_name", "company", "business", exclude=("website",))
    website = take("website", "instagram", "site", "url")
    role = take("role", "position", "title")
    revenue = take("revenue", "sales", "turnover")
    must = take("understand", "customers_must", "before_they_buy", "explain")
    extra = {k: v for k, v in fields.items() if k not in used and v}
    return {
        "name": name, "email": email, "phone": phone, "business": business,
        "website": website, "role_raw": role, "revenue_raw": revenue,
        "must_understand": must, "extra": extra,
    }


def role_kind(raw):
    s = str(raw or "").lower()
    for words, kind in _ROLE_HINTS:
        if any(w in s for w in words):
            return kind
    return ROLE_UNKNOWN


def revenue_band(raw):
    """-> lower bound in $K/month (0, 20, 50, 150) or None when unreadable."""
    s = str(raw or "").lower().replace(",", "")
    if not s:
        return None
    if "under" in s or "below" in s or "less" in s or "<" in s:
        return BAND_UNDER_20
    if "k" in s:
        nums = [int(n) for n in re.findall(r"(\d+)", s)]
    else:
        nums = [int(n) // 1000 for n in re.findall(r"\$?\s*(\d{4,7})", s)]
    if not nums:
        return None
    lo = min(nums)
    if lo >= 150:
        return BAND_150_PLUS
    if lo >= 50:
        return BAND_50_150
    if lo >= 20:
        return BAND_20_50
    return BAND_UNDER_20


def qualify(role_raw, revenue_raw):
    """-> (verdict, reason). ERIC's rule, with the judgement call named."""
    role = role_kind(role_raw)
    band = revenue_band(revenue_raw)
    if role == ROLE_CREATOR:
        return Q_NO, "role: creator/freelancer/artist/student"
    if band is not None and band < BAND_20_50:
        return Q_NO, "revenue under $20K/month"
    if role == ROLE_OWNER and band is not None and band >= BAND_50_150:
        return Q_YES, f"owner + ${band}K+/month"
    if role == ROLE_OWNER and band == BAND_20_50:
        return Q_REVIEW, "owner + $20-50K/month (industry fit is a human call)"
    if role == ROLE_OWNER and band is None:
        return Q_REVIEW, "owner, revenue not given"
    if band is not None and band >= BAND_50_150:
        return Q_REVIEW, f"{role or 'role unknown'} at a ${band}K+/month business"
    return Q_REVIEW, f"{role or 'role unknown'}, band {band}"


def ad_label(ad_id, ad_name="", env_map=""):
    """The sheet's 'Ad Campaign' cell: Meta's ad_name when it sends one, else
    ERIC's label, else the raw id."""
    aid = str(ad_id or "").strip()
    labels = dict(KNOWN_ADS)
    for pair in str(env_map or "").split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            if k.strip():
                labels[k.strip()] = v.strip()
    if ad_name and str(ad_name).strip():
        return str(ad_name).strip()
    return labels.get(aid, aid)


def is_ai_ad(ad_id, ad_name="", ai_ids=None):
    aid = str(ad_id or "").strip()
    ids = set(ai_ids if ai_ids is not None else AI_AD_IDS_DEFAULT)
    if aid and aid in ids:
        return True
    low = str(ad_name or "").lower()
    return bool(low) and any(w in low for w in ("ad_19", "film once", "ai |",
                                               "| ai", "anywhere"))


def temperature(verdict):
    return {Q_YES: "Hot", Q_REVIEW: "Warm", Q_NO: "Cold"}.get(verdict, "")


def status_label(verdict):
    return {Q_YES: "Qualified", Q_REVIEW: "Qualified (review)",
            Q_NO: "Disqualified"}.get(verdict, "New Lead")


def notes_line(rec, consent, consent_ts_iso, verdict, reason):
    """The Notes cell — every form answer the sheet has no column for, in one
    readable line, so the row answers ERIC's questions without a lookup."""
    parts = []
    if rec.get("role_raw"):
        parts.append("role: " + rec["role_raw"])
    if rec.get("revenue_raw"):
        parts.append("revenue: " + rec["revenue_raw"])
    if rec.get("website"):
        parts.append("site/IG: " + rec["website"])
    if rec.get("must_understand"):
        parts.append("must understand: " + rec["must_understand"][:300])
    parts.append("sms_consent: " + ("yes/lead_form " + str(consent_ts_iso or "")
                                    if consent else "no"))
    parts.append(f"qualified: {verdict} ({reason})")
    for k, v in sorted((rec.get("extra") or {}).items()):
        parts.append(f"{k}: {str(v)[:120]}")
    return " · ".join(parts)


def sheet_updates(rec, consent, consent_ts_iso, verdict, reason):
    """Column header -> value for update_lead_columns."""
    out = {
        "Status": status_label(verdict),
        "Service Interest": "Studio Strategy Visit (ad form)",
        "Lead Temperature": temperature(verdict),
        "Notes": notes_line(rec, consent, consent_ts_iso, verdict, reason),
    }
    if rec.get("name"):
        out["Name"] = rec["name"]
    if rec.get("business"):
        out["Business"] = rec["business"]
    if rec.get("email"):
        out["Email"] = rec["email"]
    return out


def first_touch_plan(verdict, consent, dialable, has_email):
    """Which channels carry the first touch, in order. Returns a list of
    ('sms'|'email', why) — never WhatsApp: a form lead has not written to us,
    so a free-form WhatsApp send is refused by Meta, and the thank-you
    screen's WhatsApp button already lets the lead open that door."""
    plan = []
    if consent and dialable:
        plan.append(("sms", "consent + US mobile"))
    if has_email:
        # Michael (30 Sep): "US leads text AND email". The email carries the
        # full explanation; the text is the fast ping. When there is no
        # consented mobile the email is the whole first touch.
        plan.append(("email", "alongside the text" if plan
                     else "no SMS consent or no mobile"))
    if not plan:
        plan.append(("none", "no consented mobile and no email"))
    return plan
