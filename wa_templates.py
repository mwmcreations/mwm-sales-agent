"""
wa_templates.py — PATCH #160. The UTILITY WhatsApp templates the booking
rail needs so a confirmation, a same-day reminder and a no-show rebook can
carry the real words (time, date, the studio address, two slots) when the
lead's 24-hour window is closed — Sessa, 6 Oct, got three generic
`mwm_lara_shoot_reminder` templates instead (ERIC, Sat 10 Oct, item 2).

PURE: the definitions, the Graph API bodies, and the parameter builders.
app.py owns the HTTP calls (/admin/wa-templates) and, once Meta approves,
the rail's choice of template per stage.
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
    },
}


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
    return out
