"""PATCH #143 — the form-lead rail: Meta Instant Form -> lead row -> SMS consent
-> qualified flag -> first touch (SMS + email) -> chase chain; Maya answers
SMS; one script on every door (ERIC 26/28 Sep, Michael 30 Sep: "automated all
the way to the end"). Gate test — pure modules plus app.py wiring by source."""
import os, sys
from datetime import datetime, timedelta
import pytz
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import studio_visit as sv
import lead_form as lf
import lead_chase as lc
import sms_copy as sc
import ai_studio as ai

PASS = FAIL = 0
def ok(c, label):
    global PASS, FAIL
    if c: PASS += 1; print("  ok   " + label)
    else: FAIL += 1; print("  FAIL " + label)

TZ = pytz.timezone("America/New_York")
NOW = TZ.localize(datetime(2026, 10, 1, 9, 30))

# ── studio_visit: the script and the words Michael corrected ─────────────
print("\n== studio_visit: the script")
R = " ".join(sv.SCRIPT_RULE.split())
ok("Two quick questions" in R and "what do your customers need to understand before they buy" in R, "ERIC's opener is in the rule")
ok("30-minute Studio Strategy Visit" in R and "we map the videos" in R, "30-minute + 'we' in the qualified line")
ok("in projects with Disney, Universal, Amazon and TV Globo for over 20 years" in R, "credits say 'in projects with'")
ok("we plan it, write it, shoot it and cut it" in R, "'we' do the work")
ok("$1,200 a month: four studio hours" in R and "up to 8 short videos an hour" in R, "price line is Michael's numbers")
ok("Do NOT volunteer the minimum term" in R and "never deny it" in R, "minimum term: not volunteered, never denied")
ok("mwmcreations.com/book-studio has the calendar" in R, "polite disqualify in the rule")
ok("No Calendly" in R and "book_appointment" in R, "no Calendly; books on MWM CREATIONS")
ok("Film once" in R and "rooftop, restaurant, stage, city at night" in R, "AI ad branch in the rule")
ok(sv.contains_banned(R) is None, "rule carries none of the banned wordings (%r)" % sv.contains_banned(R))
ok(sv.contains_banned("Michael does a 45-minute visit") == "45-minute", "guard catches 45-minute")
ok(sv.contains_banned("he directed for Disney") == "directed for", "guard catches 'directed for'")
ok(sv.first_name("Ana Maria Souza") == "Ana" and sv.first_name("ana@x.com") == "Ana" and sv.first_name("") == "there", "first_name")

print("\n== studio_visit: outgoing copy")
slots = [{"id": "2026-10-01T10:00:00-04:00", "display": "Thursday, October 01 at 10:00 AM EST"},
         {"id": "2026-10-02T15:00:00-04:00", "display": "Friday, October 02 at 03:00 PM EST"}]
ok(sv.short_slot(slots[0]) == "Thu Oct 1, 10am" and sv.short_slot("Friday, October 02 at 03:30 PM EST") == "Fri Oct 2, 3:30pm", "slots shortened for SMS")
for ai_flag in (False, True):
    core = sv.form_first_touch_sms("Ana Souza", "Smile Dental", ai=ai_flag, slots=slots)
    full = sc.compose(core)
    ok(sc.segments(full) <= 2, "first-touch SMS fits two segments (ai=%s, %d chars)" % (ai_flag, len(full)))
    ok("30-minute" in core and "in projects with" in core and " we " in core, "first-touch SMS says 30-minute / in projects with / we (ai=%s)" % ai_flag)
    ok("Thu Oct 1, 10am or Fri Oct 2, 3pm" in core, "first-touch SMS offers two real slots (ai=%s)" % ai_flag)
    longname = sv.form_first_touch_sms("Maximiliano", "Smile Dental", ai=ai_flag, slots=slots)
    ok(len(longname) + 63 <= 330, "a long first name stays near the ceiling (ai=%s, %d)" % (ai_flag, len(longname) + 63))
    ok(full.startswith(sc.PREFIX) and full.endswith(sc.SUFFIX), "brand on the front, STOP on the back (ai=%s)" % ai_flag)
    ok(sv.contains_banned(core) is None, "no banned wording in the SMS (ai=%s)" % ai_flag)
core0 = sv.form_first_touch_sms("Ana", "", slots=None)
ok("Which day" in core0 and sc.segments(sc.compose(core0)) <= 2, "no slots -> asks for a day, still fits")
subj, html, text = sv.form_first_touch_email("Ana Souza", "Smile Dental", "that implants are safe", ai=False, slots=slots, sms_sent=True)
ok("Studio Strategy Visit" in subj and "30-minute" in text and "in projects with" in text and "we map" in text, "first-touch email carries the corrected words")
ok("that implants are safe" in text and "Smile Dental" in text, "email quotes the form answers")
ok("I also sent you a text" in text, "email mentions the text when one went")
ok("<p " in html and "&" not in text.replace("MWM Creations & Studios", ""), "html built, text plain")
ok(sv.disqualify_text() == ("Thanks for reaching out. We work with established businesses on a monthly "
                            "subscription, so we're probably not the right fit. If you ever need studio "
                            "hours on their own, mwmcreations.com/book-studio has the calendar."), "disqualify text is ERIC's, word for word")
ok(sc.segments(sc.compose(sv.disqualify_text())) <= 2, "disqualify fits as an SMS")
for step in range(1, 6):
    s, h, t = sv.chase_email(step, "Ana", "Smile Dental", "implants are safe")
    ok(bool(s) and "Michael Moraes" in t and sv.CTA_EMAIL in t, "chase email %d: subject, Michael's voice, one CTA" % step)
    ok("only $1,200" not in t and "just $1,200" not in t and sv.contains_banned(t) is None, "chase email %d: $1,200 flat, no banned words" % step)
s2, _, t2 = sv.chase_email(2, "Ana", "Smile Dental", "")
ok("Smile American" in s2, "case study picks the dental client for a dental business")
s2m, _, _ = sv.chase_email(2, "Ana", "Victory Jiu-Jitsu Academy", "")
ok("Victory Martial Arts" in s2m, "case study picks Victory for a martial-arts business")
s3, _, t3 = sv.chase_email(3, "Ana", "Smile Dental", "")
ok("three videos every Smile Dental needs" in s3 and "1. The problem video" in t3, "day-10 email names the three videos")
s4, _, t4 = sv.chase_email(4, "Ana", "", "")
ok("$1,200 a month: four studio hours" in t4 and "30-minute" in t4, "day-14 recap carries the price line")
s5, _, t5 = sv.chase_email(5, "Ana", "", "")
ok("last email" in t5 and "door stays open" in t5.lower(), "day-30 closes the door politely")
for st in (1, 2):
    c = sv.chase_sms(st, "Ana", slots)
    ok(sc.segments(sc.compose(c)) <= 2 and "30-minute" in c, "chase SMS %d fits and says 30-minute" % st)
ok(sv.opener("Ana").startswith("Hi Ana, Maya here from Michael Moraes' team") and "Two quick questions" in sv.opener("Ana"), "chat opener = ERIC's copy")
ok("any scene" in sv.opener("Ana", ai=True) and "Two quick questions" in sv.opener("Ana", ai=True), "AI opener keeps the two questions")

# ── lead_form: the form, parsed and judged ───────────────────────────────
print("\n== lead_form")
FD = [{"name": "full_name", "values": ["Ana Souza"]},
      {"name": "email", "values": ["ANA@Example.com"]},
      {"name": "phone_number", "values": ["+14075551234"]},
      {"name": "business_name", "values": ["Smile Dental"]},
      {"name": "website_or_instagram", "values": ["@smiledental"]},
      {"name": "role", "values": ["Owner / Founder / Partner"]},
      {"name": "monthly_revenue", "values": ["$50–150K"]},
      {"name": "what_customers_must_understand", "values": ["that implants are safe"]}]
f = lf.parse_field_data(FD)
r = lf.extract(f)
ok(r["name"] == "Ana Souza" and r["email"] == "ana@example.com" and r["phone"] == "+14075551234", "name/email/phone")
ok(r["business"] == "Smile Dental" and r["website"] == "@smiledental", "business + website")
ok(r["role_raw"].startswith("Owner") and r["revenue_raw"] == "$50–150K" and r["must_understand"] == "that implants are safe", "role / revenue / must-understand")
ok(r["extra"] == {}, "nothing unplaced")
f2 = lf.parse_field_data([{"name": "What's your business name?", "values": ["Enzo Auto"]},
                          {"name": "Your role in the business", "values": ["Marketing lead"]},
                          {"name": "Monthly revenue", "values": ["Under $20K"]},
                          {"name": "What must customers understand before they buy?", "values": ["x"]},
                          {"name": "custom_question_1", "values": ["blue"]}])
r2 = lf.extract(f2)
ok(r2["business"] == "Enzo Auto" and r2["role_raw"] == "Marketing lead" and r2["revenue_raw"] == "Under $20K" and r2["must_understand"] == "x", "tolerant key matching (question-text keys)")
ok(r2["extra"] == {"custom_question_1": "blue"}, "unknown answers kept, never dropped")
ok(lf.consent_checked([{"checkbox_key": "optional_1", "is_checked": "1"}]) is True, "consent: is_checked '1' (a STRING) = ticked")
ok(lf.consent_checked([{"checkbox_key": "optional_1", "is_checked": "0"}]) is False, "consent: '0' = not ticked")
ok(lf.consent_checked([]) is False and lf.consent_checked(None, {"sms_consent": "true"}) is True, "consent: empty = no; a plain consent field counts")
ok(lf.qualify("Owner / Founder / Partner", "$50–150K") == (lf.Q_YES, "owner + $50K+/month"), "owner + $50-150K = yes")
ok(lf.qualify("Owner", "$150K+")[0] == lf.Q_YES, "owner + $150K+ = yes")
ok(lf.qualify("Owner", "$20–50K")[0] == lf.Q_REVIEW, "owner + $20-50K = review (industry is a human call)")
ok(lf.qualify("Owner", "Under $20K")[0] == lf.Q_NO, "under $20K = no")
ok(lf.qualify("Freelancer / Creator / Artist", "$150K+")[0] == lf.Q_NO, "creator = no, whatever the revenue")
ok(lf.qualify("Marketing lead", "$150K+")[0] == lf.Q_REVIEW, "marketing lead at a big business = review")
ok(lf.qualify("Employee", "$20–50K")[0] == lf.Q_REVIEW, "employee at $20-50K = review (not a disqualify)")
ok(lf.qualify("", "")[0] == lf.Q_REVIEW, "nothing answered = review, never auto-no")
ok(lf.revenue_band("$50,000 - $150,000") == 50 and lf.revenue_band("150k+") == 150 and lf.revenue_band("less than 20k") == 0 and lf.revenue_band("$20–50K") == 20 and lf.revenue_band("$50–150K") == 50, "revenue band parsing")
ok(lf.ad_label("120251320140730738") == "AD_19 | Film once | AI" and lf.ad_label("120251320140730738", "AD_19 | Film once | AI | Oct 2026") == "AD_19 | Film once | AI | Oct 2026", "ad label: Meta's ad_name wins, else ERIC's label")
ok(lf.ad_label("999", "", "999:AD_20 | Wall") == "AD_20 | Wall" and lf.ad_label("111") == "111", "ad label: env map, else the raw id")
ok(lf.is_ai_ad("120251320140730738") and not lf.is_ai_ad("120251304671210738") and lf.is_ai_ad("x", "AD_19 | Film once"), "AI ad detection by id and by name")
ok(set(ai.ai_ad_ids()) >= {"120251320140730738"}, "ai_studio knows AD_19 without a Railway variable")
u = lf.sheet_updates(r, True, "2026-10-01T09:30:00-04:00", lf.Q_YES, "owner + $50K+/month")
ok(u["Status"] == "Qualified" and u["Lead Temperature"] == "Hot" and u["Name"] == "Ana Souza" and u["Business"] == "Smile Dental" and u["Email"] == "ana@example.com", "sheet columns")
ok("role: Owner" in u["Notes"] and "revenue: $50–150K" in u["Notes"] and "must understand: that implants are safe" in u["Notes"] and "sms_consent: yes/lead_form 2026-10-01T09:30:00-04:00" in u["Notes"] and "qualified: yes" in u["Notes"], "Notes carries every form answer + consent + verdict")
ok(lf.sheet_updates(r2, False, "", lf.Q_NO, "revenue under $20K/month")["Status"] == "Disqualified", "disqualified status")
ok(lf.first_touch_plan(lf.Q_YES, True, True, True) == [("sms", "consent + US mobile"), ("email", "alongside the text")], "plan: SMS + email")
ok(lf.first_touch_plan(lf.Q_YES, False, True, True)[0][0] == "email" and len(lf.first_touch_plan(lf.Q_YES, False, True, True)) == 1, "plan: no consent -> email only")
ok(lf.first_touch_plan(lf.Q_YES, True, True, False) == [("sms", "consent + US mobile")], "plan: no email -> SMS only")
ok(lf.first_touch_plan(lf.Q_YES, False, False, False)[0][0] == "none", "plan: nothing reachable is named, not silent")

# ── lead_chase: the chain ────────────────────────────────────────────────
print("\n== lead_chase")
st = lc.arm(NOW, channels=("email", "sms"), verdict="yes")
ok(st["armed_at"] == NOW.isoformat() and st["channels"] == ["email", "sms"] and not st["stopped"], "arm()")
ok(lc.next_step(st, NOW) is None and lc.next_step(st, NOW + timedelta(hours=23)) is None, "nothing due before 24h")
ok(lc.next_step(st, NOW + timedelta(hours=24)) == ("e1", "email", 1), "e1 due at 24h")
st["sent"]["e1"] = (NOW + timedelta(hours=24)).isoformat()
ok(lc.next_step(st, NOW + timedelta(hours=30)) is None and lc.next_step(st, NOW + timedelta(hours=48)) == ("s1", "sms", 1), "s1 (text) due at 48h, not before")
st_e = lc.arm(NOW, channels=("email",))
st_e["sent"]["e1"] = "x"
ok(lc.next_step(st_e, NOW + timedelta(hours=48)) is None, "no SMS consent -> no text steps")
ok(lc.next_step(st_e, NOW + timedelta(days=5)) == ("e2", "email", 2), "e2 at day 5")
late = lc.arm(NOW, channels=("email",))
r_late = lc.next_step(late, NOW + timedelta(days=6))
ok(r_late == ("skip", "e1", "missed by 120h"), "a step 5 days late is skipped with a reason, not sent (%r)" % (r_late,))
late["skipped"]["e1"] = "missed"
ok(lc.next_step(late, NOW + timedelta(days=6)) == ("e2", "email", 2), "walk continues after a skip")
ok(lc.stop_reason(st, {"booked": True}, NOW) == lc.STOP_BOOKED, "stop: booked")
ok(lc.stop_reason(st, {"relationship": "client"}, NOW) == lc.STOP_CLIENT and lc.stop_reason(st, {}, NOW, is_client=True) == lc.STOP_CLIENT, "stop: client")
ok(lc.stop_reason(st, {"disqualified": {"reason": "x"}}, NOW) == lc.STOP_DISQUALIFIED, "stop: disqualified")
ok(lc.stop_reason(st, {}, NOW, last_inbound=NOW + timedelta(hours=5)) == lc.STOP_REPLIED, "stop: the lead replied after arming")
ok(lc.stop_reason(st, {}, NOW, last_inbound=NOW) == "", "the arming-time stamp itself is not a reply")
ok(lc.stop_reason(st, {}, NOW) == "", "nothing stops a fresh chain")
ok(lc.stop_reason({}, {}, NOW) == lc.STOP_CLOSED, "no state = closed")
full = lc.arm(NOW, channels=("email", "sms"))
for k, _, _, _ in lc.STEPS:
    full["sent"][k] = "x"
ok(lc.is_finished(full) and "finished" in lc.summary(full, NOW), "finished after seven steps")
ok("next e1 (email) in 24h" in lc.summary(lc.arm(NOW, channels=("email", "sms")), NOW), "summary names the next step")
ok(lc.FIRST_TOUCH_SMS_MAX_WAIT_H == 36 and lc.MAX_LATE_H == 72, "constants")

# ── sms_copy: conversational replies ─────────────────────────────────────
print("\n== sms_copy.compose_reply")
rep = sc.compose_reply("Great — Thursday at 10:00 AM works. I've booked it; you'll get a confirmation. See you at the studio!")
ok(not rep.startswith(sc.PREFIX) and not rep.endswith(sc.SUFFIX) and "—" not in rep, "no prefix/suffix, ASCII folded")
longtxt = ("This is a long sentence that goes on. " * 12)
rep2 = sc.compose_reply(longtxt)
ok(len(rep2) <= 306 and rep2.endswith("."), "long reply cut at a sentence end inside two segments (%d chars)" % len(rep2))
try:
    sc.compose_reply("   "); ok(False, "empty reply refused")
except ValueError:
    ok(True, "empty reply refused")

# ── app.py wiring, by source ─────────────────────────────────────────────
print("\n== app.py wiring")
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
ok("import studio_visit as _sv" in SRC and "import lead_form as _lf" in SRC and "import lead_chase as _chase" in SRC, "modules imported")
ok('""" + _sv.SCRIPT_RULE + """' in SRC, "SCRIPT_RULE is in MAYA_SHARED_KNOWLEDGE (WhatsApp + web + IG prompts)")
ok(SRC.count("MAYA_SHARED_KNOWLEDGE + ") == 2, "shared knowledge still feeds both base prompts")
ok("def _meta_lead_intake(value, lead_meta=None)" in SRC and "threading.Thread(target=_meta_lead_intake" in SRC, "webhook ACKs fast, lead handled in a thread")
ok('@app.route("/admin/meta-leads-subscribe"' in SRC and "subscribed_apps" in SRC and 'fields.add("leadgen")' in SRC, "#144: page->app leadgen subscription can be inspected and repaired from the machine")
ok('@app.route("/admin/lead-form-test"' in SRC and 'kwargs={"lead_meta": lead_meta}' in SRC, "#144: synthetic form lead through the real rail")
ok("custom_disclaimer_responses" in SRC and "fields\": META_LEAD_FIELDS" in SRC, "Graph fetch asks for the consent checkbox + ad_name")
ok('meta_lead_seen:' in SRC, "leadgen_id de-duplicated (Meta retries, the test tool resends)")
ok('_sms_consent_set(e164, "yes", "lead_form"' in SRC and 'marketing=True, transactional=True' in SRC, "form consent -> sms_consent:{phone}, source lead_form")
ok('_lf.sheet_updates(rec, consent, consent_ts, verdict, reason)' in SRC and "log_new_contact_to_sheets(sender_key)" in SRC, "sheet: first-contact row then every answer")
ok("_first_touch_sms_body(name, rec[\"business\"], ai, slots)" in SRC and "def _sms_body_that_fits(" in SRC and "kind=SMS_KIND_TRANSACTIONAL" in SRC, "first-touch SMS through _send_sms (every gate applies); copy shortened until it fits")
ok('"first_touch_sms_pending"' in SRC and "FIRST_TOUCH_SMS_MAX_WAIT_H" in SRC, "a text refused by quiet hours waits for the window, then is dropped")
ok("_sv.form_first_touch_email(" in SRC and 'via="lead_form_first_touch"' in SRC, "first-touch email through _email_send (suppression applies)")
ok("_sv.disqualify_email(name)" in SRC and "_icp.mark_disqualified(lr, _icp.REASON_NOT_TARGET_MARKET" in SRC, "disqualified: polite email, reversible mark, no chain")
ok('lr["chase"] = _chase.arm(now, channels=chans, verdict=verdict)' in SRC, "chain armed on every qualified/review lead")
ok("def _lead_chase_loop()" in SRC and 'name="lead_chase"' in SRC and "_heartbeat(\"lead_chase\")" in SRC, "chase loop thread with heartbeat")
ok("stamp BEFORE send" in SRC and "_sv.chase_email(copy_step" in SRC and "_sv.chase_sms(copy_step" in SRC, "chain sends the five emails + two texts")
ok("event_rail.within_send_window(now)" in SRC, "chase emails respect the 8-20 ET window")
ok('"lead_form": dict(_LEAD_FORM_LAST)' in SRC and '"lead_chase": dict(_LEAD_CHASE_LAST)' in SRC, "/health shows the rail")
ok('@app.route("/admin/chase"' in SRC and "_admin_secret_ok(request.values.get(\"secret\"" in SRC, "/admin/chase behind the admin secret")
ok("def _handle_incoming_sms(frm, body)" in SRC and 'channel="sms"' in SRC and "_sms_copy.compose_reply(clean)" in SRC, "Maya answers inbound SMS")
ok('if kw in ("YES", "Y", "YES PLEASE", "SIM", "SI"):' in SRC and '_sms_consent_set(frm, "yes", "maya"' in SRC, "a YES by text is recorded as consent (B3) and still answered")
ok('why="the client replied to a text; nothing answers SMS automatically"' not in SRC, "the old 'nothing answers SMS' assignment is gone")
ok('--- CHANNEL: SMS (TEXT MESSAGE) ---' in SRC, "SMS channel layer in get_claude_reply")
ok("def _ig_is_scene_dm(" in SRC and "_ig_scene_handoff" in SRC and "SCENE keyword" in SRC, "IG: SCENE DMs go to Michael, Maya quiet")
ok('body="Thanks for sharing! How can I help you today?' not in SRC, "IG: the canned 'Thanks for sharing' is gone")
ok("_sv.opener((rec or {}).get(\"name\", \"\"), ai=_ai_on)" in SRC and '"ig.no_text_opener"' in SRC, "IG: no-text first message gets the opener (AI variant on an ad referral)")
ok("CHASE_TEST_EMAILS" in SRC and "if e in CHASE_TEST_EMAILS:" in SRC, "CHASE_TEST_EMAILS lets a named internal address receive the test (never overrides DNC)")
ok("AI_AD_IDS_DEFAULT" in open(os.path.join(HERE, "ai_studio.py"), encoding="utf-8").read(), "AD_19 default in ai_studio")

# ── the behaviour suite runs as part of this gate ────────────────────────
print("\n== behaviour suite (test_patch143_behaviour.py)")
import subprocess, re as _re
_b = subprocess.run([sys.executable, os.path.join(HERE, "test_patch143_behaviour.py")],
                    capture_output=True, text=True)
_m = _re.search(r"(\d+) passed, (\d+) failed", _b.stdout or "")
if _m:
    PASS += int(_m.group(1)); FAIL += int(_m.group(2))
    print("  behaviour: %s passed, %s failed" % (_m.group(1), _m.group(2)))
    if int(_m.group(2)):
        print("\n".join(l for l in _b.stdout.splitlines() if "FAIL" in l))
else:
    FAIL += 1
    print("  FAIL behaviour suite did not report (rc=%s)\n%s" % (_b.returncode, (_b.stderr or "")[-1500:]))

print("\nTOTAL %d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
