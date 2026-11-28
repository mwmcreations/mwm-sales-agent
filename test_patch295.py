#!/usr/bin/env python3
"""GATE for PATCH #295 — the morning brief (text + Desk page), decisions filed by
agents, the meeting briefing for hand-made events, the quiet-lead header.
Prints GATE295 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:400]}")


import morning_brief as mb  # noqa: E402

ET = timezone(timedelta(hours=-5))
NOW = datetime(2026, 11, 28, 7, 0, tzinfo=ET)          # Sat Nov 28, 7:00 ET

# ── titles, clock ─────────────────────────────────────────────────────
check("title.clean_emoji", mb.clean_title("🎬 Studio: Camila Silveira") == "Studio: Camila Silveira")
check("title.clean_empty", mb.clean_title("") == "(no title)")
check("title.name_ruben", mb.title_name("🏢 Studio Visit: Ruben Von Schmeling (Victory)") == "Ruben Von Schmeling (Victory)")
check("title.name_dash", mb.title_name("Strategy Call - Ana Lima") == "Ana Lima")
check("title.name_none", mb.title_name("Team lunch") == "")
check("clock.am", mb.clock(datetime(2026, 11, 28, 9, 5, tzinfo=ET)) == "9:05 AM")
check("clock.noon", mb.clock(datetime(2026, 11, 28, 12, 0, tzinfo=ET)) == "12:00 PM")
check("clock.midnight", mb.clock(datetime(2026, 11, 28, 0, 30, tzinfo=ET)) == "12:30 AM")
check("day_line", mb.day_line(NOW) == "Sat Nov 28", mb.day_line(NOW))

# ── due ───────────────────────────────────────────────────────────────
check("due.on_at_7", mb.due(NOW, "2026-11-27", True))
check("due.off_switch", not mb.due(NOW, "2026-11-27", False))
check("due.already_today", not mb.due(NOW, "2026-11-28", True))
check("due.before_7", not mb.due(NOW.replace(hour=6, minute=59), "", True))
check("due.catch_up_959", mb.due(NOW.replace(hour=9, minute=59), "", True))
check("due.not_after_10", not mb.due(NOW.replace(hour=10), "", True))
check("due.weekend_too", NOW.weekday() == 5 and mb.due(NOW, "", True))

# ── leads ─────────────────────────────────────────────────────────────
L = [
    {"name": "Ana", "first_seen": NOW - timedelta(hours=3), "answered": True, "booked_at": NOW - timedelta(hours=2),
     "booked_when": "Tue Dec 1, 10:00 AM", "source": "Meta form"},
    {"name": "Bo", "first_seen": NOW - timedelta(hours=10), "answered": False, "booked_at": None, "source": "Instagram"},
    {"name": "Old", "first_seen": NOW - timedelta(hours=30), "answered": False, "booked_at": None},
    {"name": "OldBooked", "first_seen": NOW - timedelta(days=9), "answered": True, "booked_at": NOW - timedelta(hours=1)},
    {"name": "T", "first_seen": NOW - timedelta(hours=1), "answered": False, "test": True},
    {"name": "NoDate", "first_seen": None, "answered": False, "booked_at": None},
    "junk",
]
S = mb.lead_stats(L, NOW)
check("leads.new", [l["name"] for l in S["new"]] == ["Ana", "Bo"], S["new"])
check("leads.answered", S["answered"] == 1)
check("leads.unanswered_named", [l["name"] for l in S["unanswered"]] == ["Bo"])
check("leads.booked", [l["name"] for l in S["booked"]] == ["Ana", "OldBooked"])
check("leads.line", mb.last24_line(S) == "2 new leads, 1 answered, 2 booked", mb.last24_line(S))
E0 = mb.lead_stats([], NOW)
check("leads.empty_line", mb.last24_line(E0) == "No new leads, no new bookings")
check("leads.one", mb.last24_line(mb.lead_stats([L[1]], NOW)) == "1 new lead, 0 answered")

# ── events ────────────────────────────────────────────────────────────
EV = [
    {"summary": "🎬 Studio: Camila Silveira", "start": NOW.replace(hour=11), "personal": False},
    {"summary": "🥋 TER/QUI — Victory", "start": NOW.replace(hour=17), "personal": True},
    {"summary": "🎬 Studio: Shawnie Whitaker (vision walkthrough)", "start": NOW.replace(hour=10), "personal": False},
    {"summary": "All day thing", "start": None, "personal": False},
    {"summary": "Tomorrow", "start": NOW + timedelta(days=1), "personal": False},
]
T = mb.today_events(EV, NOW)
check("events.order_and_filter", [e["title"] for e in T] == ["Studio: Shawnie Whitaker (vision walkthrough)", "Studio: Camila Silveira"], T)

# ── decisions ─────────────────────────────────────────────────────────
D = [{"id": 8, "owners": ["DEV"], "text": "Deploy the Maya briefing fix?", "status": "open"},
     {"id": 7, "owners": ["ERIC"], "text": "Use the 280 Expo contacts as a custom audience in the December form-leads campaign, with Portuguese creative?", "status": "open"},
     {"id": 5, "owners": ["ROB"], "text": "old", "status": "yes"},
     {"id": 9, "owners": [], "text": "parked one", "status": "later"}]
OD = mb.open_decisions(D)
check("dec.open_sorted", [d["id"] for d in OD] == [7, 8, 9])
dl = mb.decision_line(OD[0])
check("dec.line_short", dl.startswith("D7 ERIC: Use the 280 Expo contacts") and dl.endswith("...") and len(dl) <= 9 + mb.DECISION_SMS_CHARS + 3, dl)
check("dec.line_team", mb.decision_line(OD[2]) == "D9 TEAM: parked one")

# ── the text ──────────────────────────────────────────────────────────
LINK = "https://mwm-sales-agent-production.up.railway.app/desk/brief"
txt = mb.sms(NOW, S, T, D, LINK)
check("sms.head", txt.startswith("MWM, Sat Nov 28\n\nLAST 24H\n2 new leads, 1 answered, 2 booked"), txt[:120])
check("sms.unanswered", "NOT ANSWERED: Bo" in txt)
check("sms.booked", "Booked: Ana, Tue Dec 1, 10:00 AM" in txt)
check("sms.today", "TODAY\n10:00 AM Studio: Shawnie Whitaker (vision walkthrough)\n11:00 AM Studio: Camila Silveira" in txt, txt)
check("sms.needs", "NEEDS YOU (3)\nD7 ERIC:" in txt and "D8 DEV: Deploy the Maya briefing fix?" in txt and "Reply like: D7 yes" in txt, txt)
check("sms.link", txt.endswith("Full page: " + LINK))
check("sms.fits", len(txt) <= mb.SMS_MAX, len(txt))
check("sms.no_personal", "Victory" not in txt and "Tomorrow" not in txt)
check("sms.no_emdash", "—" not in txt and "–" not in txt)
empty = mb.sms(NOW, E0, [], [], LINK)
check("sms.empty_day", empty == "MWM, Sat Nov 28\n\nLAST 24H\nNo new leads, no new bookings\n\nTODAY\nNothing on the studio calendar\n\n"
      "NEEDS YOU (0)\nNothing waiting on you\n\nFull page: " + LINK, empty)
big_ev = [{"at": NOW.replace(hour=8 + i % 10), "title": "Studio session with a very long client name number %d" % i} for i in range(14)]
big_dec = [{"id": 20 + i, "owners": ["ERIC", "EDDIE"], "text": "A long question that keeps going and going about a campaign " * 3, "status": "open"} for i in range(9)]
big_leads = mb.lead_stats([{"name": "Unanswered Lead Number %d" % i, "first_seen": NOW - timedelta(hours=2), "answered": False} for i in range(8)], NOW)
big = mb.sms(NOW, big_leads, big_ev, big_dec, LINK)
check("sms.big_fits", len(big) <= mb.SMS_MAX, len(big))
check("sms.big_keeps_count", "NEEDS YOU (9)" in big and "NOT ANSWERED:" in big, big)
check("sms.big_whole_lines", not big.endswith(" ") and all(len(l) < 120 for l in big.split("\n")))
err = mb.sms(NOW, E0, [], [], LINK, errors=["leads", "calendar", "decisions"])
check("sms.errors_said", "Leads could not be read" in err and "Calendar could not be read" in err and "Decisions could not be read" in err
      and "Nothing on the studio calendar" not in err and "No new leads" not in err and "Nothing waiting on you" not in err, err)

# ── the page ──────────────────────────────────────────────────────────
pg = mb.page(NOW, S, T, D + [{"id": 10, "owners": ["LARA"], "text": "<script>x</script> & ok?", "status": "open"}], sent_day="2026-11-27", live=True)
check("page.sections", all(k in pg for k in ("Needs you", "Last 24 hours", "Today", "<table>")))
check("page.escaped", "<script>x</script>" not in pg and "&lt;script&gt;" in pg)
check("page.unanswered_flag", "NOT answered" in pg and ">Bo<" in pg)
check("page.status_on", "The 7:00 AM text is ON." in pg and "Last sent: 2026-11-27." in pg)
check("page.status_off", "The 7:00 AM text is OFF" in mb.page(NOW, E0, [], []))
check("page.empty_words", "Nothing is waiting on you." in mb.page(NOW, E0, [], []) and "Nothing on the studio calendar today." in mb.page(NOW, E0, [], []))
check("page.errors", "The calendar could not be read just now." in mb.page(NOW, E0, [], [], errors=["calendar"]))
check("page.mobile", 'name="viewport"' in pg and "overflow-x:auto" in pg)

# ── the meeting briefing ──────────────────────────────────────────────
RUBEN_DESC = ("Ruben (Victory Creative &amp; Marketing) visiting the studio.<br>Open with Ruben: Gala regional versions, "
              "Black Belt Boot Camp nationwide promo, FAQ Q&A, Convention 2027 script, Dec 19 coordination. " + "more words " * 60)
rb = mb.meeting_briefing(70, "10:00 AM", summary="🏢 Studio Visit: Ruben Von Schmeling (Victory)", description=RUBEN_DESC)
check("brief.ruben_name", rb.split("\n")[2] == "Ruben Von Schmeling (Victory)", rb[:120])
check("brief.no_guesses", "Unknown" not in rb and "Not specified" not in rb and "Source:" not in rb and "WhatsApp" not in rb)
check("brief.notes", "Notes: Ruben (Victory Creative" in rb and "Gala regional versions" in rb and "<br>" not in rb)
check("brief.notes_capped", len(rb.split("Notes: ")[1].split("\n")[0]) <= 303, len(rb))
check("brief.head", rb.startswith("MEETING BRIEFING - 70 min\n\n") and rb.endswith("Good luck!") and "10:00 AM ET" in rb)
ld = mb.meeting_briefing(60, "02:00 PM", lead_name="Ana Lima", lead_biz="Lima Realty", lead_email="ana@x.com",
                         lead_phone="+14075550100", booked_via="Instagram", conv_summary="  Lead: hi\n  Maya: hello",
                         summary="Studio Visit - Ana Lima", description="Client-facing copy")
check("brief.lead_full", all(k in ld for k in ("Ana Lima", "Lima Realty", "ana@x.com", "+14075550100", "Source: Instagram", "Recent conversation:")))
check("brief.lead_no_notes", "Notes:" not in ld)
check("brief.no_email_placeholder", "not provided" not in mb.meeting_briefing(60, "2 PM", lead_name="A", lead_email="Not provided"))
check("brief.untitled", mb.meeting_briefing(60, "2 PM", summary="").split("\n")[2] == "(no title)")

# ── source: the wiring ────────────────────────────────────────────────
APP = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
OA = open(os.path.join(HERE, "operator_alert.py"), encoding="utf-8").read()
check("src.import", "import morning_brief as _mb" in APP)
check("src.switch_dark", 'SWITCHES["morning_brief_live"] = "MORNING_BRIEF_LIVE"' in APP)
check("src.kind", '"brief":    {"eric": False}' in OA)
check("src.tick_hooked", "            _quiet_tick()" in APP and "            _morning_brief_tick()       # PATCH #295" in APP)
tick = APP[APP.index("def _morning_brief_tick("):APP.index("def _morning_brief_file_decision(")]
check("src.tick_gated", '_mb.due(now, _morning_brief_sent_day(), _switch_on("morning_brief_live"))' in tick)
check("src.marks_before_send", tick.index("_pgs.save_state(_MB_SENT_KEY, day)") < tick.index("_operator_alert.alert(_mb.KIND"))
check("src.tick_never_raises", tick.count("except Exception") >= 2)
blk = APP[APP.index("# ── PATCH #295 — THE MORNING BRIEF"):APP.index("@app.route('/admin/reoffer', methods=['POST'])")]
check("src.link_is_the_desk_host", 'os.getenv("RAILWAY_PUBLIC_DOMAIN")' not in blk and 'os.getenv("MORNING_BRIEF_HOST") or "mwm-sales-agent-production.up.railway.app"' in blk)
check("src.routes", all(r in blk for r in ("'/admin/decision-file'", "'/admin/morning-brief'", "'/desk/brief'")))
check("src.admin_auth", blk.count('_admin_secret_ok(request.values.get("secret", ""))') == 2)
check("src.desk_auth", "if not _desk_auth_ok():\n        return \"\", 302, {\"Location\": \"/desk/\"}" in blk)
check("src.preview_sends_only_on_post", 'request.method == "POST" and' in blk)
check("src.no_model_call", "anthropic" not in blk and "_at_model" not in blk)
check("src.file_brief_flag", 'row["brief"] = True' in blk and 'row["next_text"] = None' in blk and "if urgent:" in blk)
check("src.owner_checked", "if owner not in _at.AGENTS:" in blk)
check("src.no_retext", 'if d.get("brief"):\n            continue' in APP)
check("src.needs_number", "if not _MB_NUMBERED.search(str(text or \"\")):\n            open_dec = [d for d in open_dec if not d.get(\"brief\")]" in APP)
m = re.search(r'_MB_NUMBERED = re\.compile\(r"(.+?)", re\.I\)', APP)
check("src.numbered_re_found", bool(m))
if m:
    NUM = re.compile(m.group(1), re.I)
    for s_, want in (("D7 yes", True), ("d 7 no", True), ("decision 7 later", True), ("yes 7", True), ("7 yes", True),
                     ("yes", False), ("ok do it", False), ("call me at 4075550100", False), ("no", False),
                     ("book Camila tuesday 11", False)):
        check(f"num.{s_}", bool(NUM.search(s_)) == want, s_)
check("src.quiet_header", "MWM quiet leads (days since you last spoke): " in APP and "MWM quiet leads, 10+ days since you last spoke" not in APP)
bf = APP[APP.index("def _pre_meeting_briefer():"):APP.index("threading.Thread(target=_pre_meeting_briefer")]
check("src.briefer_uses_module", "_mb.meeting_briefing(" in bf and "summary=summary, description=description" in bf)
check("src.briefer_no_guess", "'Unknown'" not in bf and "'Not specified'" not in bf and "or 'WhatsApp'" not in bf)
db = APP[APP.index("def _daily_briefing_thread():"):APP.index("# ─── S6.7b: WhatsApp delivery-status callbacks")]
check("src.ana_email_retired_with_switch", 'if _sw and _sw("morning_brief_live"):' in db and db.count("_build_and_send()") == 2
      and db.index('_sw("morning_brief_live")') < db.rindex("_build_and_send()"))
check("page.first_col_nowrap", "td:first-child{white-space:nowrap}" in pg)
check("compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "app.py"),
                                  os.path.join(HERE, "operator_alert.py"), os.path.join(HERE, "morning_brief.py")],
                                 capture_output=True).returncode == 0)

# ── the glue, lifted out of app.py and run against stubs ──────────────
try:
    import time as _time
    import pytz
    import desk as _dk
    import agent_talk as _atm
    _lift = True
except Exception as _imp:          # the pure checks above still gate the patch
    _lift = False
    print(f"  (glue not lifted here: {_imp!r})")
if _lift:
    src = blk[:blk.index("@app.route('/admin/decision-file'")]
    TZ = pytz.timezone("America/New_York")
    N7 = TZ.localize(datetime(2026, 11, 28, 7, 5))

    class PG:
        def __init__(self):
            self.store = {}

        def load_state(self, k, d=None):
            return self.store.get(k, d)

        def save_state(self, k, v):
            self.store[k] = v
            return True

    class Alert:
        def __init__(self):
            self.sent = []

        def alert(self, kind, text, eric_text=None):
            self.sent.append((kind, text))
            return {"sms": "sent"}

    class Tally:
        def bump(self, *a, **k):
            pass

    CAL = {"fail": False, "items": [
        {"summary": "🎬 Studio: Camila Silveira", "start": {"dateTime": "2026-11-28T11:00:00-05:00"}},
        {"summary": "🥋 TER/QUI — Victory · Ter: Julie + Michael Jr.", "start": {"dateTime": "2026-11-28T17:30:00-05:00"}},
        {"summary": "🚫 Dança FECHADA", "start": {"date": "2026-11-28"}},
        {"summary": "🎬 Studio: Cancelled Person", "status": "cancelled", "start": {"dateTime": "2026-11-28T09:00:00-05:00"}},
    ]}

    class _Req:
        def __init__(self, kw):
            self.kw = kw

        def execute(self, num_retries=0):
            if CAL["fail"]:
                raise RuntimeError("calendar down")
            return {"items": CAL["items"]}

    class _Ev:
        def list(self, **kw):
            CAL["asked"] = kw
            return _Req(kw)

    class CalSvc:
        def events(self):
            return _Ev()

    DEC, posts, errs, SW = {}, [], [], {"on": False}
    pg, al = PG(), Alert()
    leads = {
        "whatsapp:+14075550101": {"name": "Ana Booked", "created_at": (N7 - timedelta(hours=3)).isoformat(),
                                  "first_touch_sms_at": (N7 - timedelta(hours=3)).isoformat(), "event_id": "ev1",
                                  "booked_at": (N7 - timedelta(hours=2)).isoformat(), "booked_display": "Tue Dec 1, 10:00 AM"},
        "whatsapp:+14075550102": {"name": "Bo Quiet", "created_at": (N7 - timedelta(hours=9)).isoformat()},
        "whatsapp:+14075550103": {"name": "Old One", "created_at": (N7 - timedelta(days=6)).isoformat()},
        "whatsapp:+14075550104": {"name": "Tester", "created_at": (N7 - timedelta(hours=1)).isoformat(), "test_lead": True},
        "broken": "not a dict",
    }
    ns = dict(os=os, re=re, time=_time, pytz=pytz, datetime=datetime, timedelta=timedelta, TIMEZONE="America/New_York",
              CALENDAR_ID="mwm-cal", lead_data=leads, conversation_history={}, ig_conversation_history={}, _desk=_dk, _mb=mb,
              _pgs=pg, _operator_alert=al, _TALLY=Tally(), _report_error=lambda *a, **k: errs.append(a),
              get_calendar_service=lambda: CalSvc(), _switch_on=lambda n: SW["on"] and n == "morning_brief_live",
              _agent_talk_open_decisions=lambda: [d for d in DEC.values() if isinstance(d, dict) and d.get("status") in ("open", "later")],
              _at=_atm, _AT_DECISIONS="agent_decisions", _at_load=lambda k, d=None: DEC.get(k, d),
              _at_save=lambda k, v: (DEC.__setitem__(k, v) or True), _at_post=lambda *a, **k: posts.append(a),
              SLACK_DEV_CHANNEL="CDEV")
    exec(compile(src, "app_block_295", "exec"), ns)

    b = ns["_morning_brief_build"](N7)
    check("glue.new", [l["name"] for l in b["stats"]["new"]] == ["Ana Booked", "Bo Quiet"], b["stats"]["new"])
    check("glue.unanswered", [l["name"] for l in b["stats"]["unanswered"]] == ["Bo Quiet"])
    check("glue.booked", [(l["name"], l["booked_when"]) for l in b["stats"]["booked"]] == [("Ana Booked", "Tue Dec 1, 10:00 AM")])
    check("glue.events_family_hidden", [e["title"] for e in b["events"]] == ["Studio: Camila Silveira"], b["events"])
    check("glue.calendar_window", CAL["asked"]["calendarId"] == "mwm-cal" and CAL["asked"]["timeMin"].startswith("2026-11-28T00:00:00")
          and CAL["asked"]["timeMax"].startswith("2026-11-29T00:00:00") and CAL["asked"]["singleEvents"] is True)
    check("glue.sms", "NOT ANSWERED: Bo Quiet" in b["sms"] and "11:00 AM Studio: Camila Silveira" in b["sms"]
          and b["sms"].endswith("/desk/brief") and not b["errors"], b["sms"])
    check("glue.link_default", ns["_morning_brief_link"]() == "https://mwm-sales-agent-production.up.railway.app/desk/brief")

    tick = ns["_morning_brief_tick"]
    check("glue.dark_sends_nothing", tick(N7) is None and al.sent == [] and "morning_brief:sent_day" not in pg.store)
    SW["on"] = True
    check("glue.too_early", tick(N7.replace(hour=6, minute=30)) is None and al.sent == [])
    r1 = tick(N7)
    check("glue.sends_once", r1 == {"sms": "sent"} and len(al.sent) == 1 and al.sent[0][0] == "brief"
          and pg.store.get("morning_brief:sent_day") == "2026-11-28", al.sent)
    check("glue.not_twice", tick(N7 + timedelta(minutes=10)) is None and len(al.sent) == 1)
    ns["_MB_LAST"]["sent_day"] = ""                      # a restart: only pg remembers
    check("glue.restart_remembers", tick(N7 + timedelta(minutes=20)) is None and len(al.sent) == 1)
    nxt = N7 + timedelta(days=1)
    CAL["fail"] = True
    r2 = tick(nxt)
    check("glue.next_day_sends", r2 == {"sms": "sent"} and len(al.sent) == 2)
    check("glue.calendar_error_said", "Calendar could not be read" in al.sent[1][1] and "Nothing on the studio calendar" not in al.sent[1][1]
          and any(e[0] == "morning_brief.calendar" for e in errs))
    CAL["fail"] = False

    fd = ns["_morning_brief_file_decision"]
    check("glue.file_unknown_owner", fd("NOBODY", "Should we do the thing?")[0] is None)
    check("glue.file_needs_text", fd("DEV", "ok?")[0] is None and not posts)
    row, why = fd("dev", "Deploy the Maya   briefing fix?")
    check("glue.file_ok", bool(row) and row["id"] == 1 and row["brief"] is True and row["owners"] == ["DEV"] and row["status"] == "open"
          and row["text"] == "Deploy the Maya briefing fix?" and row["texted"] == [] and row["next_text"] is None, row)
    check("glue.file_quiet", len(al.sent) == 2 and len(posts) == 1 and posts[0][0] == _atm.AGENTS["DEV"]["channel"])
    row2, _ = fd("ERIC", "Use the 280 Expo contacts in ads?", urgent=True)
    check("glue.file_urgent_texts", row2["id"] == 2 and al.sent[-1][0] == "decision" and "MWM decision 2: Use the 280 Expo contacts in ads? Reply YES 2, NO 2 or LATER 2." == al.sent[-1][1])
    b3 = ns["_morning_brief_build"](N7)
    check("glue.decisions_in_brief", "NEEDS YOU (2)\nD1 DEV: Deploy the Maya briefing fix?\nD2 ERIC: Use the 280 Expo contacts in ads?\nReply like: D1 yes" in b3["sms"], b3["sms"])
    dcs, ans = _atm.owner_reply("D1 yes", [d for k, d in DEC.items() if k.startswith("agent_decision:")])
    check("glue.answer_by_number", dcs is not None and dcs["id"] == 1 and ans == "yes", (dcs, ans))
    dw, aw = _atm.owner_reply("D2 only the 2026 ones", [d for k, d in DEC.items() if k.startswith("agent_decision:")])
    check("glue.answer_in_words", dw is not None and dw["id"] == 2 and aw == "note", (dw, aw))
    dl2, al2 = _atm.owner_reply("later 1", [d for k, d in DEC.items() if k.startswith("agent_decision:")])
    check("glue.answer_later", dl2 is not None and dl2["id"] == 1 and al2 == "later", (dl2, al2))

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 295) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
mm = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not mm:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(mm.group(1)); failed += int(mm.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(mm.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE295 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
