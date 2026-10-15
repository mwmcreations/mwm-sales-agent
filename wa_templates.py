"""
wa_templates.py — PATCH #160. The UTILITY WhatsApp templates the booking
rail needs so a confirmation, a same-day reminder and a no-show rebook can
carry the real words (time, date, the studio address, two slots) when the
lead's 24-hour window is closed — Sessa, 6 Oct, got three generic
`mwm_lara_shoot_reminder` templates instead (ERIC, Sat 10 Oct, item 2).

PURE: the definitions, the Graph API bodies, and the parameter builders.
app.py owns the HTTP calls (/admin/wa-templates) and, once Meta approves,
the rail's choice of template per stage.

PATCH #250 (15 Oct) — Meta approved all three, but it RECATEGORIZED
`mwm_visit_rebook` UTILITY -> MARKETING, and MARKETING templates have not
delivered to US (+1) numbers since Meta's pause of 1 Apr 2025 (still in force
Oct 2026, no end date). So: `mwm_visit_reschedule` replaces it, worded as a
continuation of the appointment the lead already had (what the categorizer
looks for); and `usable(rows)` is the rail's test — a name counts only while
Meta lists it APPROVED *and* UTILITY. `stage_template` / `stage_params` /
`reschedule_params` give app.py the per-stage choice it was waiting on.
"""
LANG = "en_US"
STUDIO_ADDRESS = "1500 Park Center Dr, Suite 230, Orlando"

# name -> definition. Names are what the rail will send by; keep them.
TEMPLATES = {
    "mwm_visit_confirm": {
        "stage": "T-24",
        "text": ("Your studio visit with Michael Moraes is {{1}} on {{2}} at " + STUDIO_ADDRESS + ". "
                 "Reply YES to confirm or tell us a better time."),
        "example": ["10:00 AM", "Tuesday, October 13"],
    },
    "mwm_visit_today": {
        "stage": "T-2",
        "text": ("See you at {{1}} today for your visit with Michael Moraes at " + STUDIO_ADDRESS + ". "
                 "Reply here if anything changes."),
        "example": ["10:00 AM"],
    },
    "mwm_visit_rebook": {
        "stage": "no-show",
        "text": ("Hi {{1}}, we missed you at the studio. Michael Moraes has two openings this week: {{2}} or {{3}}. "
                 "Reply with the one you want, or a time that works, and we'll lock it in."),
        "example": ["Sarah", "Tuesday, October 13 at 10:00 AM", "Wednesday, October 14 at 3:00 PM"],
        # #250 — approved 14 Oct as MARKETING (Meta's recategorization), which
        # cannot reach a US number. Kept for the status listing; never sent.
        "retired": "recategorized MARKETING by Meta; MARKETING does not deliver to US numbers",
    },
    "mwm_visit_reschedule": {
        "stage": "no-show",
        "text": ("Hi {{1}}, your studio visit with Michael Moraes on {{2}} was marked as missed. "
                 "To reschedule, reply with one of these times: {{3}} or {{4}}, or another time that works for you."),
        "example": ["Sarah", "Tuesday, October 13 at 10:00 AM", "Thursday, October 15 at 10:00 AM",
                    "Friday, October 16 at 3:00 PM"],
    },
}

# #250 — what the rail sends per stage, once `usable()` says Meta allows it.
STAGE_TEMPLATE = {24: "mwm_visit_confirm", 2: "mwm_visit_today"}
REBOOK_TEMPLATE = "mwm_visit_reschedule"
# The rail's `_sent_via` label for these. Deliberately NOT "WhatsApp (approved
# template)": #157 sends the email *beside* that label because the generic
# template carries neither the YES ask nor the address — these do.
SENT_VIA = "WhatsApp (visit template)"
SECOND_SLOT_FALLBACK = "another day this week"


def graph_body(name):
    """The POST body for /{WABA_ID}/message_templates."""
    t = TEMPLATES[name]
    return {
        "name": name,
        "category": "UTILITY",
        "language": LANG,
        "components": [{"type": "BODY", "text": t["text"], "example": {"body_text": [list(t["example"])]}}],
    }


def _clean(v, limit=60):
    # a template parameter may not hold newlines or runs of spaces/tabs
    return " ".join(str(v or "").split())[:limit] or "-"


def confirm_params(time_str, date_str):
    return [_clean(time_str, 20), _clean(date_str, 40)]


def today_params(time_str):
    return [_clean(time_str, 20)]


def rebook_params(first_name, slot1, slot2):
    return [_clean(first_name, 30), _clean(slot1, 50), _clean(slot2 or "another time this week", 50)]


def reschedule_params(first_name, missed_date, slot1, slot2):
    """#250 — {{1}} name, {{2}} the day they missed, {{3}}/{{4}} two slots."""
    return [_clean(first_name, 30), _clean(missed_date, 40), _clean(slot1, 50),
            _clean(slot2 or SECOND_SLOT_FALLBACK, 50)]


def stage_template(stage_h):
    """#250 — the template for a confirmation stage (hours before), or None
    when the stage has no purpose-built one (48 h, 168 h keep the generic)."""
    try:
        return STAGE_TEMPLATE.get(int(stage_h))
    except (TypeError, ValueError):
        return None


def stage_params(stage_h, time_str, date_str):
    name = stage_template(stage_h)
    if name == "mwm_visit_confirm":
        return confirm_params(time_str, date_str)
    if name == "mwm_visit_today":
        return today_params(time_str)
    return []


def usable(rows):
    """#250 — the names the rail may send right now: ours, not retired, and
    listed by Meta as APPROVED *and* UTILITY (an approval that came back
    MARKETING is not usable — it does not deliver to US numbers)."""
    out = set()
    for r in rows or []:
        n = str((r or {}).get("name") or "")
        if n in TEMPLATES and not TEMPLATES[n].get("retired") \
                and str(r.get("status") or "").upper() == "APPROVED" \
                and str(r.get("category") or "").upper() == "UTILITY":
            out.add(n)
    return out


def status_summary(rows):
    """Meta's listing rows -> {name: {"status", "category", "reason"}} for ours."""
    out = {}
    for r in rows or []:
        n = str(r.get("name") or "")
        if n in TEMPLATES:
            out[n] = {"status": r.get("status"), "category": r.get("category"),
                      "language": r.get("language"), "reason": r.get("rejected_reason") or ""}
    for n in TEMPLATES:
        out.setdefault(n, {"status": "NOT SUBMITTED", "category": "", "language": "", "reason": ""})
    _ok = usable(rows)
    for n in out:
        out[n]["usable"] = n in _ok                      # #250
        if TEMPLATES[n].get("retired"):
            out[n]["retired"] = TEMPLATES[n]["retired"]
    return out
