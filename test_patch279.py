#!/usr/bin/env python3
"""GATE for PATCH #279 — personal events off the Desk on any calendar. Chains to the newest earlier gate present. Prints GATE279 PASS/FAIL."""
import os
import re
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


for modname, attrs in (("victory_auth", {"ROLE_MWM": "mwm", "HOME_DOMAIN": "mwmcreations.com", "LINK_MAX_PER_IP": 15,
                                          "LINK_MAX_PER_EMAIL": 5, "SESSION_TTL_SECONDS": 14 * 86400,
                                          "verify_session": lambda v, s, now=None: None,
                                          "normalize_email": lambda e: str(e or "").strip().lower(),
                                          "domain_of": lambda e: e.split("@")[-1],
                                          "RateLimiter": type("RL", (), {"allow": lambda self, *a: True}),
                                          "new_token": lambda: ("t", "h")}),
                       ("victory_store", {"session_secret": lambda create=True: "", "create_link": lambda *a: True})):
    if modname not in sys.modules:
        m = types.ModuleType(modname)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[modname] = m
import desk  # noqa: E402

LEADS = {
    "instagram:1096": {"name": "Grandmaster Von Schmeling", "business": "Victory Martial Arts"},
    "whatsapp:+13218886544": {"name": "Visit Orlando", "business": "Visit Orlando"},
    "whatsapp:+14075550101": {"name": "Pedro Alves", "business": "Alves Dental"},
    "whatsapp:+14075550102": {"name": "Julie Martins", "business": "Martins Bakery"},
}
# the four events Michael saw on 9 Nov, as the API returned them
MEET = [
    {"time": "9:15 AM", "name": "Grandmaster Von Schmeling · Victory HQ", "business": "", "calendar": "mwm", "event_id": "e1",
     "summary": "Meeting with Grandmaster Von Schmeling · Victory HQ"},
    {"time": "4:00 PM", "name": "🤸 SEG/QUI", "business": "Julie · Ginástica (16h00–18h00)", "calendar": "mwm", "event_id": "e2",
     "summary": "🤸 SEG/QUI — Julie · Ginástica (16h00–18h00)"},
    {"time": "6:30 PM", "name": "📚 SEG", "business": "Julie · Tutoring com Giuliana Almeida em casa · 18h30–19h30", "calendar": "mwm", "event_id": "e3",
     "summary": "📚 SEG — Julie · Tutoring com Giuliana Almeida em casa · 18h30–19h30"},
    {"time": "11:00 AM", "name": "MWM Creations & Studios x Visit Orlando", "business": "", "calendar": "personal", "event_id": "e4",
     "summary": "MWM Creations & Studios x Visit Orlando "},
]
kept, hidden = desk.calendar_filter(MEET, LEADS)
ids = [m["event_id"] for m in kept]
check("today.michaels_screen", ids == ["e1", "e4"] and hidden == 2, (ids, hidden))
check("today.gymnastics_hidden", "e2" not in ids)
check("today.tutoring_hidden", "e3" not in ids)
check("today.lead_on_mwm_kept", "e1" in ids and [m for m in kept if m["event_id"] == "e1"][0]["lead_key"] == "instagram:1096")
check("today.business_on_personal_kept", "e4" in ids)
check("today.personal_flag", all(m.get("personal") is False for m in kept))
k2, h2 = desk.calendar_filter(MEET, LEADS, show_all=True)
check("today.show_all_marks", len(k2) == 4 and h2 == 0 and [m["personal"] for m in k2] == [False, True, True, False])

# the words and the pattern
check("pw.gymnastics", desk.is_personal_event("🤸 SEG/QUI — Julie · Ginástica (16h00–18h00)"))
check("pw.tutoring_beats_session", desk.is_personal_event("Tutoring session — Julie") and desk.is_studio_event("Tutoring session — Julie"))
check("pw.weekday_codes", desk.is_personal_event("SEG — swim") and desk.is_personal_event("📚 TER/QUI — piano") and not desk.is_personal_event("Segundo Studio Visit"))
check("pw.not_business", not desk.is_personal_event("Studio Visit — Pedro Alves (Alves Dental)") and not desk.is_personal_event("Podcast recording — PRESENCE ep 12"))
check("pw.dentist_is_personal_but_dental_lead_wins",
      desk.is_personal_event("Dentist 8am") and desk.calendar_filter([{"summary": "Alves Dental — Pedro Alves", "event_id": "x", "calendar": "mwm"}], LEADS)[0])
check("pw.lead_named_julie_wins", desk.calendar_filter([{"summary": "Julie Martins — studio tour", "event_id": "y", "calendar": "mwm"}], LEADS)[0][0]["lead_key"] == "whatsapp:+14075550102")
# a plain title with no studio word is hidden on any calendar; a studio word shows it
check("rule.plain_hidden_mwm", desk.calendar_filter([{"summary": "Lunch", "event_id": "a", "calendar": "mwm"}], LEADS)[1] == 1)
check("rule.studio_shown_mwm", desk.calendar_filter([{"summary": "Studio Strategy Visit — new lead", "event_id": "b", "calendar": "mwm"}], LEADS)[1] == 0)
check("rule.studio_shown_personal", desk.calendar_filter([{"summary": "Client call — Appenin", "event_id": "c", "calendar": "personal"}], LEADS)[1] == 0)
check("rule.personal_word_hides_despite_studio_word", desk.calendar_filter([{"summary": "Family meeting at church", "event_id": "d", "calendar": "mwm"}], LEADS)[1] == 1)

# static
JS = open(os.path.join(HERE, "desk_static", "desk.js"), encoding="utf-8").read()
CSS = open(os.path.join(HERE, "desk_static", "desk.css"), encoding="utf-8").read()
DS = open(os.path.join(HERE, "desk.py"), encoding="utf-8").read()
check("js.toggle", JS.count("cal-toggle") >= 4 and 'state.calAll = !state.calAll' in JS and '(state.calAll ? "&all=1" : "")' in JS)
check("js.personal_class", 'm.personal ? "personal" : ""' in JS)
check("css.personal", ".today-ev.personal, .cal-ev.personal" in CSS)
check("desk.no_calendar_branch", 'personal = _lower(m.get("calendar")) == "personal"' not in DS)
check("desk.flag", 'm["personal"] = bool((is_personal_event(title) and not (lk and _studio)) or (not lk and not _studio))' in DS)   # #291

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 279) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE279 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
