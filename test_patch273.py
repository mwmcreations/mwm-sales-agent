#!/usr/bin/env python3
"""GATE for PATCH #273 — MWM Desk slice 3: visits · clients · stats, and the
Today strip filtered of personal events. Pure checks on desk.py with fixture
records, source pins on app.py and the static files, Flask route checks when
Flask is here, then the #272 gate (→ 271 → …). Prints GATE273 PASS/FAIL."""
import os
import re
import subprocess
import sys
import types
from datetime import datetime, timedelta

import pytz

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


# stubs so desk.py imports without the app's auth modules
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

TZ = pytz.timezone("America/New_York")
NOW = TZ.localize(datetime(2026, 11, 9, 9, 0))
H = lambda h: (NOW + timedelta(hours=h)).isoformat()  # noqa: E731
D = lambda d: (NOW + timedelta(days=d)).isoformat()  # noqa: E731

LEADS = {
    "whatsapp:+14075550101": {"name": "Pedro Alves", "business": "Alves Dental", "phone": "+14075550101", "email": "pedro@alves.com",
                              "source": "Meta Lead Ad", "meta_lead_ad": True, "lead_form_at": D(-3), "event_id": "evt_1", "booked_at": D(-2),
                              "booked_slot_id": D(1), "booked_display": "Tue Nov 10 at 10:00 AM", "first_touch_email_at": D(-3), "first_touch_sms_at": D(-3),
                              "last_message_time": D(-2), "last_inbound_at": D(-2),
                              "chase": {"kind": "form", "armed_at": D(-3), "sent": {"e1": D(-2)}, "stopped": "booked", "stopped_at": D(-2)}},
    "whatsapp:+14075550102": {"name": "Carla Mendes", "phone": "+14075550102", "source": "Instagram", "first_contact_time": D(-20),
                              "event_id": "evt_2", "booked_at": D(-9), "booked_slot_id": D(-5), "last_message_time": D(-9)},
    "whatsapp:+14075550103": {"name": "Ana Souza", "business": "Souza Bakery", "phone": "+14075550103", "source": "WhatsApp", "first_contact_time": D(-8),
                              "event_id": "evt_3", "booked_at": D(-7), "booked_slot_id": D(-4), "last_outcome": "follow_up", "last_outcome_at": D(-4),
                              "last_message_time": D(-4),
                              "chase": {"kind": "post_visit", "armed_at": D(-4), "sent": {"e1": D(-4)}, "stopped": ""}},
    "whatsapp:+14075550104": {"name": "Shawnie Whitaker", "business": "Your Local Alarm Dealer", "phone": "+14075550104", "email": "shawnie@gmail.com",
                              "source": "Referral", "first_contact_time": D(-12), "paid_at": D(-3), "product": "MWM Partner Plan", "paid_value": 350,
                              "studio_package": {"recurring": True, "mrr": 1517, "one_off": 0, "package_name": "MWM Partner Plan"}},
    "whatsapp:+14075550105": {"name": "Marcus Lee", "business": "Lee Roofing", "phone": "+14075550105", "source": "Meta Lead Ad", "meta_lead_ad": True,
                              "lead_form_at": D(-1), "first_touch_wa": {"wamid": "w1", "status": "delivered", "sent_at": H(-23)},
                              "first_touch_email_pending": {"since": H(-23.5), "sh": True, "ai": False},
                              "chase": {"kind": "studio_hour", "armed_at": D(-1), "sent": {}, "stopped": ""}},
    "whatsapp:+14075550106": {"name": "Old Guy", "phone": "+14075550106", "source": "WhatsApp", "first_contact_time": D(-100), "last_message_time": D(-90)},
    "whatsapp:+14075550107": {"name": "Luzia Costa", "phone": "+14075550107", "email": "luzia@hotmail.com", "whatsapp_status": "Client — Studio Package",
                              "first_contact_time": D(-120), "last_message_time": D(-20)},
    "meta_lead_test": {"name": "<test lead: dummy data for full_name>", "test_lead": True, "lead_form_at": D(-1)},
}
CONV = {"whatsapp:+14075550101": [{"role": "assistant", "content": "Hi Pedro, Maya here", "at": D(-3)}, {"role": "user", "content": "Tuesday works", "at": D(-2)}],
        "whatsapp:+14075550103": [{"role": "user", "content": "hi"}]}

# ── 1. the calendar filter ──────────────────────────────────────────────────
MEET = [
    {"name": "Pedro Alves", "business": "Alves Dental", "time": "10:00 AM", "date_label": "", "event_id": "evt_1", "calendar": "mwm", "summary": "Studio Visit — Pedro Alves (Alves Dental)"},
    {"name": "Michael Jr.", "business": "", "time": "3:00 PM", "date_label": "", "event_id": "p1", "calendar": "personal", "summary": "📚 Michael Jr."},
    {"name": "Dentist", "business": "", "time": "8:00 AM", "date_label": "", "event_id": "p2", "calendar": "personal", "summary": "Dentist"},
    {"name": "Carla Mendes", "business": "", "time": "1:00 PM", "date_label": "", "event_id": "p3", "calendar": "personal", "summary": "Coffee with Carla Mendes"},
    {"name": "Guilherme", "business": "", "time": "2:30 PM", "date_label": "", "event_id": "p4", "calendar": "personal", "summary": "Strategy meeting — Guilherme"},
    {"name": "Gym", "business": "", "time": "6:00 AM", "date_label": "", "event_id": "p5", "calendar": "personal", "summary": "Gym"},
    {"name": "Whatever", "business": "", "time": "9:00 AM", "date_label": "", "event_id": "m2", "calendar": "mwm", "summary": "Whatever"},
]
kept, hidden = desk.calendar_filter(MEET, LEADS)
ids = [m["event_id"] for m in kept]
check("cal.mwm_always", "evt_1" in ids and "m2" in ids)
check("cal.personal_hidden", "p1" not in ids and "p2" not in ids and "p5" not in ids and hidden == 3, (ids, hidden))
check("cal.lead_name_kept", "p3" in ids and [m for m in kept if m["event_id"] == "p3"][0]["lead_key"] == "whatsapp:+14075550102")
check("cal.keyword_kept", "p4" in ids)
check("cal.lead_key_on_mwm", [m for m in kept if m["event_id"] == "evt_1"][0]["lead_key"] == "whatsapp:+14075550101")
k2, h2 = desk.calendar_filter(MEET, LEADS, show_all=True)
check("cal.show_all", len(k2) == len(MEET) and h2 == 0)
check("cal.no_calendar_field_kept", desk.calendar_filter([{"name": "X", "summary": "X", "event_id": "z"}], LEADS)[0][0]["event_id"] == "z")
check("cal.single_word_name_never_matches", desk.event_matches_lead("📚 Michael Jr.", desk._lead_names({"k": {"name": "Michael"}})) == "")
check("cal.two_words_match", desk.event_matches_lead("Lunch, Pedro Alves!", desk._lead_names(LEADS)) == "whatsapp:+14075550101")
check("cal.business_match", desk.event_matches_lead("Alves Dental — tour", desk._lead_names(LEADS)) == "whatsapp:+14075550101")
check("cal.test_leads_ignored", desk.event_matches_lead("test lead dummy", desk._lead_names(LEADS)) == "")
check("cal.studio_words", desk.is_studio_event("Podcast recording") and not desk.is_studio_event("Dentist"))

# ── 2. visits ───────────────────────────────────────────────────────────────
v = desk.visits(LEADS, CONV, {}, now=NOW)
up = [c["name"] for c in v["upcoming"]]
check("visits.upcoming", up == ["Pedro Alves"], up)
check("visits.by_day", v["upcoming_by_day"] and v["upcoming_by_day"][0]["day"].startswith("Tue") and v["upcoming_by_day"][0]["cards"][0]["name"] == "Pedro Alves", v["upcoming_by_day"])
check("visits.needs_outcome", [c["name"] for c in v["needs_outcome"]] == ["Carla Mendes"], v["needs_outcome"])
check("visits.recent", [c["name"] for c in v["recent"]] == ["Ana Souza"] and v["recent"][0]["outcome"]["last"] == "follow_up")
check("visits.counts", v["counts"] == {"upcoming": 1, "needs_outcome": 1, "recent": 1}, v["counts"])
check("visits.no_test", all("test" not in c["name"] for c in v["upcoming"] + v["needs_outcome"] + v["recent"]))
v2 = desk.visits(LEADS, CONV, {}, now=NOW + timedelta(days=40))
check("visits.window_moves", v2["counts"]["upcoming"] == 0 and v2["counts"]["recent"] == 0 and v2["counts"]["needs_outcome"] == 2, v2["counts"])

# ── 3. clients ──────────────────────────────────────────────────────────────
ROWS = [
    {"name": "Shawnie Whitaker", "email": "sha…@gmail.com", "package_name": "MWM Partner Plan", "contract_hours": "12.00", "hours_used": "0.00",
     "contract_start_date": "2026-11-06", "contract_end_date": "2027-02-05", "active": True},
    {"name": "Luzia Costa", "email": "Luz…@hotmail.com", "package_name": "4h Podcast - Mensal", "contract_hours": "13.00", "hours_used": "5.00",
     "contract_start_date": "2026-07-01", "contract_end_date": "2027-01-02", "active": True},
    {"name": "Scott Robinson", "email": "hea…@gmail.com", "package_name": "Studio Package", "contract_hours": "12.00", "hours_used": "0.00",
     "contract_start_date": "2026-07-27", "contract_end_date": "2026-11-20", "active": True},
    {"name": "Marcia Cardim", "email": "edi…@icloud.com", "package_name": "Studio 4hr/month + Editing", "contract_hours": "12.00", "hours_used": "7.00",
     "contract_start_date": "2026-07-01", "contract_end_date": "2026-11-01", "active": True},
    {"name": "QA Test — Michael", "email": "mic…@mwmcreations.com", "package_name": "QA Test Package", "contract_hours": "4.00", "hours_used": "0.00",
     "contract_start_date": "2026-07-10", "contract_end_date": "2026-10-10", "active": True},
    {"name": "Iris Flores", "email": "mar…@hisagents.com", "package_name": "Studio Trial — 1 Month", "contract_hours": "4.00", "hours_used": "4.00",
     "contract_start_date": "2026-08-05", "contract_end_date": "2026-09-04", "active": True},
]


def _pkg(name):
    n = str(name or "").lower()
    if n == "studio package":
        return {"recurring": True, "mrr": 1200, "one_off": 0}
    if n.startswith("studio trial"):
        return {"recurring": False, "mrr": 0, "one_off": 1400}
    return None


cl = desk.clients(ROWS, LEADS, now=NOW, package_lookup=_pkg)
names = [c["name"] for c in cl["rows"]]
check("clients.qa_hidden", "QA Test — Michael" not in names)
check("clients.order", names == ["Scott Robinson", "Luzia Costa", "Shawnie Whitaker", "Marcia Cardim", "Iris Flores"], names)   # live soonest-end first, then ended most-recent first
byname = {c["name"]: c for c in cl["rows"]}
check("clients.status", byname["Scott Robinson"]["status"] == "expiring" and byname["Shawnie Whitaker"]["status"] == "active"
      and byname["Marcia Cardim"]["status"] == "ended" and byname["Iris Flores"]["status"] == "ended")
check("clients.days_left", byname["Scott Robinson"]["days_left"] == 11 and byname["Marcia Cardim"]["days_left"] < 0)
check("clients.shawnie_mrr_from_record", byname["Shawnie Whitaker"]["mrr"] == 1517 and byname["Shawnie Whitaker"]["key"] == "whatsapp:+14075550104")
check("clients.lookup_mrr", byname["Scott Robinson"]["mrr"] == 1200 and byname["Iris Flores"]["mrr"] == 0 and byname["Iris Flores"]["one_off"] == 1400)
check("clients.unknown_package_default", byname["Luzia Costa"]["mrr"] == 1200 and byname["Luzia Costa"]["key"] == "whatsapp:+14075550107")
check("clients.mask_match", desk._mask_match("Luz…@hotmail.com", "luzia@hotmail.com") and not desk._mask_match("Luz…@hotmail.com", "luiz@gmail.com"))
check("clients.hours", byname["Luzia Costa"]["left"] == 8.0 and byname["Luzia Costa"]["pct"] == 38 and byname["Marcia Cardim"]["pct"] == 58)
s = cl["summary"]
check("clients.summary", s["active"] == 3 and s["expiring"] == 1 and s["ended"] == 2 and s["mrr"] == 1517 + 1200 + 1200 and s["hours_left"] == 12 + 8 + 12, s)
check("clients.empty_rows", desk.clients([], LEADS, now=NOW)["summary"]["active"] == 0)

# the portal cache
calls = []


def fetch_ok():
    calls.append(1)
    return ROWS


desk._PORTAL_CACHE.update(at=0.0, rows=None, error="")
r1, c1, e1 = desk.portal_rows(fetch_ok, now_s=1000.0)
r2, c2, e2 = desk.portal_rows(fetch_ok, now_s=1100.0)
r3, c3, e3 = desk.portal_rows(fetch_ok, now_s=1000.0 + desk.PORTAL_CACHE_S + 1)
check("cache.hits", len(calls) == 2 and c1 is False and c2 is True and c3 is False and r2 is ROWS)
r4, c4, e4 = desk.portal_rows(lambda: None, now_s=5000.0)
check("cache.unreachable_keeps_last", r4 is ROWS and c4 is True and "unreachable" in e4)
r5, c5, e5 = desk.portal_rows(fetch_ok, force=True, now_s=5001.0)
check("cache.force", len(calls) == 3 and c5 is False)
desk._PORTAL_CACHE.update(at=0.0, rows=None, error="")
r6, c6, e6 = desk.portal_rows(lambda: (_ for _ in ()).throw(RuntimeError("down")), now_s=1.0)
check("cache.error_no_rows", r6 is None and "RuntimeError" in e6)

# ── 4. stats ────────────────────────────────────────────────────────────────
st = desk.stats(LEADS, CONV, {}, days=30, now=NOW, ledger_summary=cl["summary"])
co = st["cohort"]
check("stats.cohort", co["new"] == 5 and co["contacted"] == 3 and co["replied"] == 2, co)        # Pedro, Carla, Ana, Shawnie, Marcus in the window; Carla and Shawnie never touched
check("stats.cohort_booked", co["booked"] == 3 and co["visited"] == 1 and co["won"] == 1, co)
check("stats.rates", co["reply_rate"] == 67 and co["book_rate"] == 60, co)
check("stats.sources", st["by_source"][0]["n"] == 2 and st["by_source"][0]["source"] == "Meta Lead Ad", st["by_source"])
ft = st["first_touch"]
check("stats.first_touch", ft["form_leads"] == 2 and ft["email"] == 1 and ft["sms"] == 1 and ft["whatsapp"] == 1 and ft["waiting"] == 1 and ft["none"] == 0, ft)
check("stats.first_touch_median", ft["median_minutes"] == 60.0, ft)   # Pedro 0 min, Marcus 60 min → upper median
ev = st["events"]
check("stats.events", ev["booked"] == 3 and ev["visits"] == 1 and ev["visits_by_outcome"] == {"follow_up": 1} and ev["won"] == 1, ev)
ch = st["chase"]
check("stats.chase", ch["active"] == 2 and ch["sent"] == 2 and ch["stopped"] == {"booked": 1}, ch)
check("stats.now", st["now"]["leads"] == 7 and st["now"]["stages"]["Client"] == 2 and st["now"]["stages"]["Paused"] >= 1, st["now"])
check("stats.ledger", st["clients"]["mrr"] == cl["summary"]["mrr"])
st7 = desk.stats(LEADS, CONV, {}, days=7, now=NOW)
check("stats.window_7", st7["cohort"]["new"] == 2 and st7["events"]["booked"] == 2, (st7["cohort"], st7["events"]))
check("stats.days_clamped", desk.stats(LEADS, CONV, {}, days=0, now=NOW)["days"] == 1 and desk.stats(LEADS, CONV, {}, days=9999, now=NOW)["days"] == 365)

# the lead card knows the held email
ft1 = desk.first_touch_of(LEADS["whatsapp:+14075550105"])
check("card.email_pending", ft1 and ft1.get("email_pending") and ft1.get("whatsapp"), ft1)
check("card.email_sent", desk.first_touch_of(LEADS["whatsapp:+14075550101"]).get("email", {}).get("at", "").startswith("2026-11-06"))

# ── 5. source pins ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
DSK = open(os.path.join(HERE, "desk.py"), encoding="utf-8").read()
JS = open(os.path.join(HERE, "desk_static", "desk.js"), encoding="utf-8").read()
HTML = open(os.path.join(HERE, "desk_static", "desk.html"), encoding="utf-8").read()
CSS = open(os.path.join(HERE, "desk_static", "desk.css"), encoding="utf-8").read()
check("app.meetings_fields", '"calendar": "mwm" if cal_id == mwm_cal else "personal",' in SRC and '"summary": summary,' in SRC)
check("app.actions_portal", '"portal_clients": lambda: _studio.wp_list_clients(),' in SRC and '"package_by_name": lambda n: _studio.package_by_name(n),' in SRC)
check("app.studio_alias_before", SRC.index("import studio_package as _studio") < SRC.index('"portal_clients": lambda'))
check("desk.routes", all(r in DSK for r in ('"/desk/api/visits"', '"/desk/api/clients"', '"/desk/api/stats"')))
check("desk.proxy_filter", "calendar_filter(body.get(\"meetings\") or []" in DSK and 'request.args.get("all")' in DSK)
check("desk.mount", "slice 3: see + act + measure" in DSK)
check("desk.cache_const", desk.PORTAL_CACHE_S == 300 and desk.EXPIRING_DAYS == 14)
check("js.tabs", all(t in HTML for t in ('data-tab="visits"', 'data-tab="clients"', 'data-tab="stats"')) and len(re.findall(r'class="tab( on)?"', HTML)) == 6)
check("js.loaders", all(f in JS for f in ("async function loadVisits", "async function loadClients", "async function loadStats", "function renderStats")))
check("js.paths_under_desk", all(p in JS for p in ('"/desk/api/visits"', '"/desk/api/clients"', '"/desk/api/stats?days="', '"/desk/api/report/meetings?range=week"')))
check("js.no_outside_calls", "/meeting-report/" not in JS and "/admin/" not in JS)
check("js.chips_split", 'if (ch.dataset.days)' in JS and '$$("#inbox-chips .chip")' in JS)
check("js.hidden_personal", "personal hidden" in JS)
check("js.writes_only_desk_api", all(("/desk/api/" in l or "withAuth(path)" in l or "opts.method" in l) for l in JS.splitlines() if "POST" in l))
check("css.slice3", ".tiles" in CSS and ".hbar" in CSS and ".crow" in CSS and ".tabs.six" in CSS)

# ── 6. the routes, when Flask is here ───────────────────────────────────────
try:
    from flask import Flask, jsonify
    _app = Flask("desk273")
    acts = {"portal_clients": lambda: ROWS, "package_by_name": _pkg, "pipeline_event": lambda *a, **k: None,
            "report_meetings": lambda: jsonify({"ok": True, "meetings": MEET}),
            "report_submit": lambda: jsonify({"ok": True, "message": "filed"})}
    desk.register(_app, lambda s: s == "k", LEADS, CONV, {}, manual_keys=lambda: set(), actions=acts)
    c = _app.test_client()
    for path in ("/desk/api/visits", "/desk/api/clients", "/desk/api/stats"):
        check(f"route.auth {path}", c.get(path).status_code == 401)
    r = c.get("/desk/api/visits?secret=k")
    check("route.visits", r.status_code == 200 and r.get_json()["counts"]["needs_outcome"] >= 1, r.get_data()[:200])
    r = c.get("/desk/api/clients?secret=k")
    j = r.get_json()
    check("route.clients", r.status_code == 200 and j["summary"]["active"] >= 1 and any(x["name"] == "Shawnie Whitaker" for x in j["rows"]), r.get_data()[:200])
    r = c.get("/desk/api/stats?secret=k&days=30")
    j = r.get_json()
    check("route.stats", r.status_code == 200 and j["cohort"]["new"] >= 1 and j["clients"] and j["clients"]["mrr"] > 0, r.get_data()[:200])
    r = c.get("/desk/api/report/meetings?range=today&secret=k")
    j = r.get_json()
    check("route.meetings_filtered", r.status_code == 200 and j["hidden"] == 3 and all(m["event_id"] not in ("p1", "p2", "p5") for m in j["meetings"]), r.get_data()[:300])
    r = c.get("/desk/api/report/meetings?range=today&all=1&secret=k")
    check("route.meetings_all", r.get_json()["hidden"] == 0 and len(r.get_json()["meetings"]) == len(MEET))
    acts["portal_clients"] = lambda: None
    desk._PORTAL_CACHE.update(at=0.0, rows=None, error="")
    r = c.get("/desk/api/clients?secret=k&refresh=1")
    check("route.clients_unreachable", r.status_code == 502 and r.get_json()["ok"] is False)
    r = c.get("/desk/api/stats?secret=k")
    check("route.stats_without_ledger", r.status_code == 200 and r.get_json()["clients"] is None)
    html = c.get("/desk/?secret=k").get_data(as_text=True)
    check("route.page_has_tabs", 'data-tab="stats"' in html)
except ImportError:
    print("note: flask not installed here — route checks skipped (proven live after deploy)")
except Exception as e:
    check("flask.registration", False, repr(e))

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch272.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #272 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("272: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE273 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
