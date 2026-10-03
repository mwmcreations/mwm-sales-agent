"""PATCH #143 — behaviour of the form rail and the chase loop, run against the
real functions lifted out of app.py with every dependency stubbed. No
network, no database, no Flask."""
import ast, os, sys, json
from datetime import datetime, timedelta
import pytz
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import studio_visit as _sv, lead_form as _lf, lead_chase as _chase, sms_copy as _sms_copy
import ai_studio as _ai, icp as _icp, event_rail, meta_capi as _capi

PASS = FAIL = 0
def ok(c, label):
    global PASS, FAIL
    if c: PASS += 1; print("  ok   " + label)
    else: FAIL += 1; print("  FAIL " + label)

SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
want = {"_meta_lead_intake", "_meta_lead_fetch", "_chase_pass", "_chase_aware",
        "_chase_is_client", "_sms_body_that_fits", "_first_touch_sms_body",
        "email_ok", "_chase_mask", "_sms_lead_context",
        "_report_drives_record", "_chase_stop", "_deal_value_from", "_on_payment",
        "_capi_send_async"}
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
ok(len(fns) == len(want), "functions found (%d/%d)" % (len(fns), len(want)))

TZ = pytz.timezone("America/New_York")
TIMEZONE = "America/New_York"

# ── stubs ────────────────────────────────────────────────────────────────
class PG:
    def __init__(self): self.d = {}; self.on = True
    def enabled(self): return self.on
    def load_state(self, k, default=None): return self.d.get(k, default)
    def save_state(self, k, v): self.d[k] = v
pg = PG()
class Tally:
    def __init__(self): self.calls = []
    def bump(self, *a): self.calls.append(a)
calls = {"sms": [], "email": [], "sheet_rows": [], "sheet_updates": [], "slack": [],
         "pipeline": [], "consent": [], "stamp": [], "errors": [], "graph": []}
LEAD_JSON = {}
SMS_RESULT = {"ok": True, "sid": "SM123"}
class Resp:
    def __init__(self, code, body): self.status_code = code; self._b = body
    def json(self): return self._b
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError("HTTP %d" % self.status_code)
class HTTP:
    def get(self, url, params=None, timeout=None):
        calls["graph"].append((url, params))
        return Resp(200, LEAD_JSON)
def _send_sms(phone, body, kind="marketing"):
    calls["sms"].append((phone, body, kind)); return dict(SMS_RESULT)
def _email_send(to, subject, html, via="", lead_key=None, **k):
    sup, why = G["email_is_suppressed"](to)
    if sup:
        return {"ok": False, "suppressed": True, "error": "suppressed: " + why}
    calls["email"].append((to, subject, html, via, lead_key)); return {"ok": True}
lead_data = {}
G = dict(
    lead_data=lead_data, datetime=datetime, timedelta=timedelta, pytz=pytz, TIMEZONE=TIMEZONE,
    os=os, json=json, threading=__import__("threading"), event_rail=event_rail,
    _sv=_sv, _lf=_lf, _chase=_chase, _sms_copy=_sms_copy, _ai=_ai, _icp=_icp,
    http_requests=HTTP(), META_PAGE_ACCESS_TOKEN="tok",
    META_LEAD_FIELDS="id,field_data,custom_disclaimer_responses",
    META_LEAD_FORM_IDS=set(),
    _LEAD_FORM_LAST={"at": None, "leadgen_id": "", "verdict": "", "sms": "", "email": "",
                     "sheet": "", "count": 0, "errors": 0},
    _LEAD_CHASE_LAST={"last_send": ""},
    _TALLY=Tally(),
    _report_error=lambda ctx, exc, detail="": calls["errors"].append((ctx, str(exc), detail)),
    _post_to_slack_async=lambda ch, text, **k: calls["slack"].append((ch, text)),
    SLACK_DEV_CHANNEL="#dev", SLACK_MAYA_CHANNEL="#maya", SLACK_ERIC_CHANNEL="#eric",
    _find_lead_by_phone=lambda p: next(((k, v) for k, v in lead_data.items()
                                        if str(v.get("phone", "")).endswith(str(p)[-10:])), (None, None)),
    _find_lead_by_email=lambda e: next(((k, v) for k, v in lead_data.items()
                                        if v.get("email") == e), (None, None)),
    _is_internal_number=lambda p: str(p).endswith("8135031224"),
    _sms_consent_set=lambda phone, status, source, context="", marketing=None, transactional=None, ts=None:
        calls["consent"].append((phone, status, source, marketing, transactional)),
    log_new_contact_to_sheets=lambda key, _raise=False: calls["sheet_rows"].append(key),
    update_lead_columns=lambda key, upd, _raise=False: calls["sheet_updates"].append((key, upd)),
    _stamp_attribution_async=lambda key: calls["stamp"].append(key),
    _calculate_lead_score=lambda s, m=None: None,
    _post_pipeline_event=lambda *a, **k: calls["pipeline"].append(k),
    get_available_slots=lambda: [{"id": "2026-10-02T10:00:00-04:00", "display": "Friday, October 02 at 10:00 AM EST"},
                                 {"id": "2026-10-05T15:00:00-04:00", "display": "Monday, October 05 at 03:00 PM EST"},
                                 {"id": "2026-10-06T10:00:00-04:00", "display": "x"}],
    _send_sms=_send_sms, _email_send=_email_send,
    email_is_suppressed=lambda e: ((True, "internal address") if e.endswith("@mwmcreations.com") else (False, "")),
    _known_client_lookup=lambda key, cand=None: (False, "no_match", None),
    SMS_KIND_TRANSACTIONAL="transactional", SMS_KIND_MARKETING="marketing",
    _heartbeat=lambda n: None,
    _capi=_capi, re=__import__("re"),
    _sms_consent_get=lambda e164: {"status": "yes", "marketing": True, "transactional": True} if e164 else {},
    _record_win=lambda key, deal_value=0, service="", notes="": calls["wins"].append((key, deal_value, service)),
    OUTCOME_SHEET_STATUS={"client_won": "Client Won", "follow_up": "Visited — Follow-up",
                          "not_interested": "Lost — Not Interested", "no_show": "No-Show — Reschedule"},
)
calls["wins"] = []; calls["capi"] = []
sys.modules["pg_store"] = pg
import sms_consent as _real_sc
sys.modules["sms_consent"] = _real_sc
exec(compile(ast.Module(body=fns, type_ignores=[]), "app_143", "exec"), G)

def reset():
    for v in calls.values(): v.clear()
    lead_data.clear(); pg.d.clear()
    G["_LEAD_FORM_LAST"].update({"count": 0, "errors": 0})

def meta_lead(**over):
    base = {"id": "L1", "created_time": "2026-10-01T13:05:00+0000", "ad_id": "120251304671210738",
            "ad_name": "AD_14 | Education business", "form_id": "1093985030009769",
            "field_data": [
                {"name": "full_name", "values": ["Ana Souza"]},
                {"name": "email", "values": ["ana@smiledental.com"]},
                {"name": "phone_number", "values": ["+14075551234"]},
                {"name": "business_name", "values": ["Smile Dental"]},
                {"name": "website_or_instagram", "values": ["@smiledental"]},
                {"name": "role", "values": ["Owner / Founder / Partner"]},
                {"name": "monthly_revenue", "values": ["$50–150K"]},
                {"name": "what_customers_must_understand", "values": ["that implants are safe"]}],
            "custom_disclaimer_responses": [{"checkbox_key": "optional_1", "is_checked": "1"}]}
    base.update(over)
    return base

# ── 1 · a qualified owner with consent + email ───────────────────────────
print("\n== 1 · qualified owner, consent, email")
reset(); LEAD_JSON.clear(); LEAD_JSON.update(meta_lead())
G["_meta_lead_intake"]({"leadgen_id": "L1", "form_id": "1093985030009769", "ad_id": "120251304671210738"})
ok(calls["graph"] and "custom_disclaimer_responses" in calls["graph"][0][1]["fields"], "Graph fetch asks for the consent box")
rec = lead_data.get("whatsapp:+14075551234")
ok(rec is not None, "record keyed whatsapp:+14075551234")
ok(rec and rec["name"] == "Ana Souza" and rec["business"] == "Smile Dental" and rec["role_raw"].startswith("Owner")
   and rec["revenue_raw"] == "$50–150K" and rec["must_understand"] == "that implants are safe", "record carries every answer")
ok(rec and rec["qualified"] == "yes" and rec["ad_id"] == "120251304671210738" and rec["utm_campaign"] == "AD_14 | Education business"
   and rec["source"] == "Meta Lead Ad" and rec["sms_consent_form"] is True, "qualified, attributed, consent flagged")
ok(calls["consent"] == [("+14075551234", "yes", "lead_form", True, True)], "sms_consent written: yes / lead_form / both boxes")
ok(pg.d.get("sms_optin_confirm_sent:+14075551234") is True, "separate opt-in confirmation suppressed (the first touch carries brand + STOP)")
ok(pg.d.get("meta_lead_seen:L1"), "leadgen_id remembered")
ok(calls["sheet_rows"] == ["whatsapp:+14075551234"], "first-contact row written")
upd = calls["sheet_updates"][0][1] if calls["sheet_updates"] else {}
ok(upd.get("Status") == "Qualified" and upd.get("Name") == "Ana Souza" and upd.get("Business") == "Smile Dental"
   and upd.get("Email") == "ana@smiledental.com" and "sms_consent: yes/lead_form 2026" in upd.get("Notes", "")
   and "must understand: that implants are safe" in upd.get("Notes", ""), "sheet columns + Notes (role, revenue, must-understand, consent, verdict)")
ok(calls["stamp"] == ["whatsapp:+14075551234"], "attribution stamp (U/V) requested")
ok(len(calls["sms"]) == 1 and calls["sms"][0][0] == "+14075551234" and calls["sms"][0][2] == "transactional", "one SMS, transactional")
body = calls["sms"][0][1] if calls["sms"] else ""
ok(body.startswith("MWM Creations & Studios: Hi Ana, Maya from Michael Moraes' team") and body.endswith("Reply STOP to opt out, HELP for help."), "SMS: brand front, STOP back")
ok("30-minute" in body and "in projects with" in body and " we " in body and "Fri Oct 2, 10am or Mon Oct 5, 3pm" in body, "SMS: 30-minute / in projects with / we / two real slots")
ok(_sms_copy.segments(body) <= 2, "SMS fits two segments (%d chars)" % len(body))
ok(len(calls["email"]) == 1 and calls["email"][0][0] == "ana@smiledental.com" and calls["email"][0][3] == "lead_form_first_touch", "one first-touch email")
ok("in projects with" in calls["email"][0][2] and "30-minute" in calls["email"][0][2] and "I also sent you a text" in calls["email"][0][2], "email carries the words and mentions the text")
ch = rec.get("chase") if rec else None
ok(ch and ch["channels"] == ["email", "sms"] and not ch["stopped"] and ch["verdict"] == "yes", "chain armed on both rails")
ok(rec.get("first_touch_sms_at") and rec.get("first_touch_email_at"), "first-touch stamps")
dev = [t for c, t in calls["slack"] if c == "#dev"]
ok(len(dev) == 1 and "qualified: *yes*" in dev[0] and "SMS: sent" in dev[0] and "email: sent" in dev[0] and "sheet: ok" in dev[0], "#dev evidence line")
ok(any(c == "#maya" for c, _ in calls["slack"]) and any(c == "#eric" for c, _ in calls["slack"]), "#maya + #eric told")
ok(calls["pipeline"] and calls["pipeline"][0].get("new_stage") == "New", "pipeline NEW_LEAD")
ok(calls["errors"] == [], "no errors reported")

# duplicate webhook delivery -> nothing twice
G["_meta_lead_intake"]({"leadgen_id": "L1", "form_id": "1093985030009769", "ad_id": "x"})
ok(len(calls["sms"]) == 1 and len(calls["email"]) == 1 and len(calls["graph"]) == 1, "a retried webhook sends nothing twice")

# ── 2 · under $20K -> polite disqualify, no chain ────────────────────────
print("\n== 2 · under $20K")
reset(); LEAD_JSON.clear(); LEAD_JSON.update(meta_lead(id="L2", field_data=[
    {"name": "full_name", "values": ["Bob Low"]}, {"name": "email", "values": ["bob@low.com"]},
    {"name": "phone_number", "values": ["4075550000"]}, {"name": "business_name", "values": ["Bob's Beats"]},
    {"name": "role", "values": ["Freelancer / Creator / Artist"]}, {"name": "monthly_revenue", "values": ["Under $20K"]}]))
G["_meta_lead_intake"]({"leadgen_id": "L2", "form_id": "1093985030009769"})
rec = lead_data.get("whatsapp:+14075550000")
ok(rec and rec["qualified"] == "no" and isinstance(rec.get("disqualified"), dict) and rec["disqualified"]["reason"] == "not_target_market", "disqualified, reversibly")
ok(calls["sms"] == [], "no SMS to a disqualified lead (email exists)")
ok(len(calls["email"]) == 1 and calls["email"][0][3] == "lead_form_disqualify" and "book your first studio hour" in calls["email"][0][2], "the polite disqualify email, ERIC's words")
ok(rec and rec["chase"]["stopped"] == "disqualified", "no chain")
ok(calls["sheet_updates"] and calls["sheet_updates"][0][1]["Status"] == "Disqualified", "sheet says Disqualified")
ok(calls["consent"] and calls["consent"][0][2] == "lead_form", "consent still recorded (they ticked it)")
ok(pg.d.get("sms_optin_confirm_sent:+14075550000") is None, "disqualified lead keeps the normal opt-in confirmation path")

# ── 3 · quiet hours: text waits, email goes, chase loop sends the text later
print("\n== 3 · SMS refused by quiet hours")
reset(); LEAD_JSON.clear(); LEAD_JSON.update(meta_lead(id="L3"))
SMS_RESULT.clear(); SMS_RESULT.update({"ok": False, "reason": "quiet_hours"})
G["_meta_lead_intake"]({"leadgen_id": "L3", "form_id": "1093985030009769"})
rec = lead_data["whatsapp:+14075551234"]
ok(isinstance(rec.get("first_touch_sms_pending"), dict) and rec["first_touch_sms_pending"]["reason"] == "quiet_hours", "text queued")
ok(len(calls["email"]) == 1 and "If you would rather text" in calls["email"][0][2], "email went now (and does not claim a text was sent)")
dev = [t for c, t in calls["slack"] if c == "#dev"]
ok(dev and "SMS: queued (quiet_hours)" in dev[0], "#dev line says queued")
SMS_RESULT.clear(); SMS_RESULT.update({"ok": True, "sid": "SM9"})
counts = G["_chase_pass"](TZ.localize(datetime(2026, 10, 1, 10, 5)))
ok("first_touch_sms_pending" not in rec and rec.get("first_touch_sms_at") and counts["sent"] == 1 and calls["sms"][-1][2] == "transactional", "chase pass sends the waiting text inside the window")
# too late -> dropped, not sent
reset(); LEAD_JSON.clear(); LEAD_JSON.update(meta_lead(id="L3b"))
SMS_RESULT.clear(); SMS_RESULT.update({"ok": False, "reason": "quiet_hours"})
G["_meta_lead_intake"]({"leadgen_id": "L3b", "form_id": "1093985030009769"})
rec = lead_data["whatsapp:+14075551234"]
SMS_RESULT.clear(); SMS_RESULT.update({"ok": True, "sid": "SM9"})
since = datetime.fromisoformat(rec["first_touch_sms_pending"]["since"])
calls["sms"].clear()
G["_chase_pass"](since + timedelta(hours=40))
ok("first_touch_sms_pending" not in rec and rec.get("first_touch_sms_dropped", "").startswith("waited") and not calls["sms"],
   "a text older than 36h is dropped, not sent (pending=%r dropped=%r sms=%d)" % ("first_touch_sms_pending" in rec, rec.get("first_touch_sms_dropped"), len(calls["sms"])))

# ── 4 · no consent -> email only; no email + no consent -> named, not silent
print("\n== 4 · no consent / nothing reachable")
reset(); LEAD_JSON.clear(); LEAD_JSON.update(meta_lead(id="L4", custom_disclaimer_responses=[{"checkbox_key": "optional_1", "is_checked": "0"}]))
G["_meta_lead_intake"]({"leadgen_id": "L4", "form_id": "1093985030009769"})
rec = lead_data["whatsapp:+14075551234"]
ok(calls["sms"] == [] and calls["consent"] == [] and len(calls["email"]) == 1, "no consent: no text, no consent row, email only")
ok(rec["chase"]["channels"] == ["email"], "chain on email only")
reset(); LEAD_JSON.clear(); LEAD_JSON.update(meta_lead(id="L5", field_data=[
    {"name": "full_name", "values": ["No Way"]}, {"name": "business_name", "values": ["X"]},
    {"name": "role", "values": ["Owner"]}, {"name": "monthly_revenue", "values": ["$150K+"]}],
    custom_disclaimer_responses=[]))
G["_meta_lead_intake"]({"leadgen_id": "L5", "form_id": "1093985030009769"})
dev = [t for c, t in calls["slack"] if c == "#dev"]
ok(dev and "SMS: not applicable" in dev[0] and "email: not applicable" in dev[0] and lead_data["meta_lead_L5"]["chase"]["channels"] == [], "unreachable lead: recorded, chain armed on nothing, said out loud")

# ── 5 · Michael's own number (the acceptance test) ──────────────────────
print("\n== 5 · internal number = test lead")
reset(); LEAD_JSON.clear(); LEAD_JSON.update(meta_lead(id="L6", ad_id="120251320140730738", ad_name="AD_19 | Film once | AI | Oct 2026", field_data=[
    {"name": "full_name", "values": ["Michael Moraes"]}, {"name": "email", "values": ["michael@mwmcreations.com"]},
    {"name": "phone_number", "values": ["+18135031224"]}, {"name": "business_name", "values": ["MWM test"]},
    {"name": "role", "values": ["Owner"]}, {"name": "monthly_revenue", "values": ["$50–150K"]},
    {"name": "what_customers_must_understand", "values": ["that this is a test"]}]))
G["_meta_lead_intake"]({"leadgen_id": "L6", "form_id": "1093985030009769", "ad_id": "120251320140730738"})
rec = lead_data.get("meta_lead_L6")
ok(rec is not None and rec["test_lead"] is True and "whatsapp:+18135031224" not in lead_data, "kept off the Command Mode record")
ok(len(calls["sms"]) == 1 and calls["sms"][0][0] == "+18135031224" and "any scene" in calls["sms"][0][1], "SMS still goes to the internal number; AD_19 -> AI opener")
ok(calls["email"] == [] and rec["chase"]["channels"] == ["sms"], "internal email suppressed unless CHASE_TEST_EMAILS names it; chain on SMS only")
ok(rec.get("ai_interest") == "ad_id" and rec["utm_campaign"] == "AD_19 | Film once | AI | Oct 2026", "AI flag from the ad id; label from Meta's ad_name")
dev = [t for c, t in calls["slack"] if c == "#dev"]
ok(dev and "*TEST (internal number)*" in dev[0], "#dev line marks the test")

# ── 6 · the chain over a month ───────────────────────────────────────────
print("\n== 6 · the chase loop")
T0 = TZ.localize(datetime(2026, 10, 1, 9, 30))      # armed Thu 1 Oct 09:30 ET
def armed_lead(leadgen):
    reset(); LEAD_JSON.clear(); LEAD_JSON.update(meta_lead(id=leadgen))
    G["_meta_lead_intake"]({"leadgen_id": leadgen, "form_id": "1093985030009769"})
    r = lead_data["whatsapp:+14075551234"]
    r["chase"]["armed_at"] = T0.isoformat()
    r["last_message_time"] = T0
    for v in calls.values(): v.clear()
    return r
def at(days, hour=11, minute=0):
    return (T0 + timedelta(days=days)).replace(hour=hour, minute=minute)
rec = armed_lead("L7")
c = G["_chase_pass"](at(0, 11, 30))
ok(c["armed"] == 1 and c["active"] == 1 and c["due_now"] == 0 and not calls["email"] and not calls["sms"], "2h: armed, nothing due")
c = G["_chase_pass"](at(1))
ok(len(calls["email"]) == 1 and calls["email"][0][3] == "lead_chase_e1" and "What a 30-minute Studio Strategy Visit looks like" in calls["email"][0][1]
   and "e1" in rec["chase"]["sent"], "day 1: email 1 sent and stamped")
c = G["_chase_pass"](at(1, 11, 10))
ok(len(calls["email"]) == 1, "same day again: nothing doubles")
c = G["_chase_pass"](at(2))
ok(len(calls["sms"]) == 1 and calls["sms"][0][2] == "marketing" and "30-minute" in calls["sms"][0][1] and "s1" in rec["chase"]["sent"], "day 2: text 1 (marketing kind)")
c = G["_chase_pass"](at(5, 23, 30))
ok(len(calls["email"]) == 1 and "e2" not in rec["chase"]["sent"], "day 5 at 23:30: email waits for the window")
c = G["_chase_pass"](at(6, 9, 0))
ok(len(calls["email"]) == 2 and calls["email"][1][3] == "lead_chase_e2" and "How Smile American uses the studio" in calls["email"][1][1], "day 6 morning: email 2 (case study, dental)")
rec["last_message_time"] = at(6, 11, 0)          # the lead replies
c = G["_chase_pass"](at(9))
ok(rec["chase"]["stopped"] == "replied" and len(calls["sms"]) == 1 and c["stopped"].get("replied") == 1, "a reply stops the chain; day-9 text not sent")
rec = armed_lead("L8"); rec["booked"] = True
G["_chase_pass"](at(1))
ok(rec["chase"]["stopped"] == "booked" and not calls["email"], "booked: chain stops before day 1")
rec = armed_lead("L9")
G["_known_client_lookup"] = lambda key, cand=None: (True, "match", {})
G["_chase_pass"](at(1))
ok(rec["chase"]["stopped"] == "client" and not calls["email"], "client: chain stops")
G["_known_client_lookup"] = lambda key, cand=None: (False, "no_match", None)
rec = armed_lead("L10")
for d in (1, 2, 5, 9, 10, 14, 30):
    G["_chase_pass"](at(d, 11, 5))
ok(len(calls["email"]) == 5 and len(calls["sms"]) == 2 and sorted(rec["chase"]["sent"]) == ["e1", "e2", "e3", "e4", "e5", "s1", "s2"], "five emails + two texts over 30 days")
G["_chase_pass"](at(31))
ok(rec["chase"]["stopped"] == "closed", "then closed")
subjects = [e[1] for e in calls["email"]]
ok(any("three videos every Smile Dental needs" in s for s in subjects) and any("still open" in s for s in subjects) and any("door stays open" in s for s in subjects), "the five subjects")
# a step missed by more than 72h is skipped, the chain continues
rec = armed_lead("L11")
G["_chase_pass"](at(8, 11, 0))
ok(sorted(rec["chase"]["skipped"]) == ["e1", "e2", "s1"] and not calls["email"] and not calls["sms"], "after an 8-day outage: e1/s1/e2 skipped with a reason, nothing stale goes out")
G["_chase_pass"](at(10, 11, 0))
ok("s2" in rec["chase"]["sent"] and len(calls["sms"]) == 1 and not calls["email"], "the chain resumes at the next step still on time (s2, one step per pass)")
G["_chase_pass"](at(10, 11, 5))
ok("e3" in rec["chase"]["sent"] and len(calls["email"]) == 1 and "three videos" in calls["email"][0][1], "next pass: e3")

# ── 7 · the daily report drives the record, the chain and the sheet (#145) ──
print("\n== 7 · event report (Patch #145)")
G["_capi_send_async"] = lambda ev: calls["capi"].append(ev)
rec = armed_lead("L12")
plan0 = {"steps": [(48, "WhatsApp", "nudge")], "why": "old", "close_after_days": 14}
plan = G["_report_drives_record"]("follow_up", "whatsapp:+14075551234", rec, "ana@smiledental.com",
                                  "Ana Souza", "", "great visit", "start in October", plan0, False, [])
ok(rec["chase"]["kind"] == "post_visit" and rec["chase"]["channels"] == ["email", "sms"] and rec["chase"]["agreed_next"] == "start in October",
   "follow_up: post-visit chain armed on email + sms, agreed next step kept")
ok(plan["steps"] == [] and "post-visit chain armed" in plan["why"], "the old 48h/day-7 plan is replaced (no double touch)")
ok(calls["sheet_updates"] and calls["sheet_updates"][-1][1]["Status"] == "Visited — Follow-up", "sheet row says Visited — Follow-up")
T1 = datetime.fromisoformat(rec["chase"]["armed_at"]); calls["email"].clear(); calls["sms"].clear()
rec["last_message_time"] = T1 - timedelta(hours=1)      # their last message came before the report
def at_h(h):
    """The first 11:00 local at or after T1 + h hours (inside the send window)."""
    t = (T1 + timedelta(hours=h)).replace(hour=11, minute=0, second=0, microsecond=0)
    return t if t >= T1 + timedelta(hours=h) else t + timedelta(days=1)
G["_chase_pass"](at_h(2))
ok(len(calls["email"]) == 1 and "thank you for coming in" in calls["email"][0][1] and "start in October" in calls["email"][0][2], "+2h: thank-you email with the agreed next step")
G["_chase_pass"](at_h(48))
ok(len(calls["sms"]) == 1 and "Michael here" in calls["sms"][0][1] and calls["sms"][0][2] == "marketing", "day 2: Michael's text (marketing kind)")
G["_chase_pass"](at_h(24 * 6)); G["_chase_pass"](at_h(24 * 14))
ok(len(calls["email"]) == 3 and "first month" in calls["email"][1][1] and "door stays open" in calls["email"][2][1], "day 6 + day 14 emails")
G["_chase_pass"](T1 + timedelta(days=16))
ok(rec["chase"]["stopped"] == "closed", "post-visit chain closes after four steps")
# payment stops a running post-visit chain
rec = armed_lead("L13")
G["_report_drives_record"]("follow_up", "whatsapp:+14075551234", rec, "ana@smiledental.com", "Ana Souza", "", "", "", plan0, False, [])
rec["last_message_time"] = datetime.fromisoformat(rec["chase"]["armed_at"]) - timedelta(hours=1)
G["_on_payment"]({"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs_1", "amount_total": 120000, "currency": "usd",
    "customer_details": {"email": "ana@smiledental.com", "phone": "+14075551234", "name": "Ana Souza"},
    "metadata": {"sku": "studio_subscription"}}}})
ok(rec.get("paid_at") and rec["relationship"] == "new_client" and rec["chase"]["stopped"] == "client", "a Stripe payment marks paid, client, and stops the chain")
ok(calls["sheet_updates"][-1][1]["Status"] == "Paid — Client", "sheet row says Paid — Client")
ok(calls["capi"] and calls["capi"][-1]["event_name"] == "Purchase" and calls["capi"][-1]["custom_data"]["value"] == 1200.0
   and "em" in calls["capi"][-1]["user_data"], "Purchase event built for Meta (hashed email, $1,200)")
# client_won from the report
rec = armed_lead("L14")
G["_report_drives_record"]("client_won", "whatsapp:+14075551234", rec, "ana@smiledental.com", "Ana Souza", "Studio Subscription $1,200/month", "", "", dict(plan0), False, [])
ok(rec["relationship"] == "new_client" and rec["chase"]["stopped"] == "client" and calls["wins"][-1] == ("whatsapp:+14075551234", 1200.0, "Studio Subscription $1,200/month"), "client_won: record Won, chain stopped, _record_win with the deal value")
ok(any(c == "#eric" and "AD → WON" in t for c, t in calls["slack"]), "ERIC hears ad -> won")
ok(calls["sheet_updates"][-1][1]["Status"] == "Client Won" and calls["sheet_updates"][-1][1]["Lead Temperature"] == "Client", "sheet row says Client Won")
rec = armed_lead("L15")
G["_report_drives_record"]("not_interested", "whatsapp:+14075551234", rec, "", "Ana", "", "", "", dict(plan0), False, [])
ok(rec["chase"]["stopped"] == "disqualified", "not_interested stops the form chain")
# CAPI Lead on a qualified form lead
reset(); LEAD_JSON.clear(); LEAD_JSON.update(meta_lead(id="123456789012345"))
G["_meta_lead_intake"]({"leadgen_id": "123456789012345", "form_id": "1093985030009769"})
ok(calls["capi"] and calls["capi"][-1]["event_name"] == "Lead" and calls["capi"][-1]["user_data"].get("lead_id") == 123456789012345
   and calls["capi"][-1]["custom_data"]["qualified"] == "yes", "a qualified form lead becomes a Lead event keyed by leadgen id")
ok(_capi.send([calls["capi"][-1]], post=lambda u, j: (200, {"events_received": 1}), dataset_id="1", token="t")[0]
   and _capi.send([calls["capi"][-1]], dataset_id="", token="")[1] == "unconfigured", "CAPI send: ok when configured, named skip when dark")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
