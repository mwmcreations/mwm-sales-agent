"""PATCH #262 gate — an answer by email is an answer, and a move is a state
(Mon 2 Nov 2026: Shawnie Whitaker answered Friday's "moving our visit" email at
02:34 — "Thursday, November 5 at 2:30 PM works perfectly for me!" — the info@
watcher posted a notice at 02:37 and nothing booked it; Vicente Orellana never
saw his, Saturday's T-48h reminder confirmed Monday, he drove in from Tampa).

1. lead_reply (pure): the lead's words → a chosen offer, a proposal, or an
   intent; our quoted options read back; body/quote handling; the copy.
2. _lead_reply_handle is wired into the info@ watcher BEFORE the generic
   notice; it stops the chase, books a pick through handle_tool_call, confirms
   in the thread, escalates everything else to Michael by text.
3. /admin/visit-reschedule: secret, dry by default, marks the state, pulls or
   flags the old event, sends on every channel, arms the escalation; mode=confirm.
4. The ladder skips a moving event; Maya's prompt carries the pending move;
   the booking tool records booked_slot_id and resolves the move; the form rail
   and the chase remember offered_slots; the escalation pass rides the watcher.
5. operator_alert has the "reply" kind (Michael + #eric). info_inbox.py is
   untouched and still metadata-only.
Then runs the #261 gate (→ 260 → …)."""
import ast
import base64
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lead_reply as lr          # noqa: E402
import operator_alert as oa      # noqa: E402
import sms_copy as sc            # noqa: E402

try:
    import pytz
    TZ = pytz.timezone("America/New_York")
except Exception:                # the gate must still run without pytz
    from datetime import timezone, timedelta
    TZ = timezone(timedelta(hours=-5))

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


def _loc(dt):
    try:
        return TZ.localize(dt)
    except Exception:
        return dt.replace(tzinfo=TZ)


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
ast.parse(SRC)
check("app.imports_lead_reply", "import lead_reply as _lrp" in SRC)

NOW = _loc(datetime(2026, 11, 2, 2, 35))
OFFERS = [{"id": "2026-11-05T14:30:00-05:00", "display": "Thursday, November 05 at 02:30 PM EST"},
          {"id": "2026-11-06T13:00:00-05:00", "display": "Friday, November 06 at 01:00 PM EST"}]


def pick(text, offers=OFFERS, now=NOW):
    m = lr.match_offer(text, offers, now, TZ)
    return (m["slot"] or {}).get("id"), m


# ── 1 · the parser, on the real sentences ───────────────────────────────────
sid, m = pick("Hi Michael, Apologies for the late revert. No worries at all! Things come up, I totally "
              "understand. 😊 Thursday, November 5 at 2:30 PM works perfectly for me! Looking forward to it. 🙌")
check("parse.shawnie_picks_thursday", sid == OFFERS[0]["id"] and m["via"] == "datetime", str(m))
check("parse.shawnie_is_a_choice", lr.intent("Thursday, November 5 at 2:30 PM works perfectly for me!", m) == lr.INTENT_CHOICE)

wed_offers = [{"id": "2026-11-03T10:00:00-05:00", "display": "Tue"}, {"id": "2026-11-04T14:00:00-05:00", "display": "Wed"}]
sid, m = pick("Yes, Wedesday the 4th 2 pm 👍🙏 MICHEAL, LET'S BUILD SOMETHING BIGGER", wed_offers,
              _loc(datetime(2026, 10, 27, 22, 3)))
check("parse.the_4th_2pm_typo_weekday", sid == wed_offers[1]["id"], str(m))

sid, m = pick("Likewise")
check("parse.likewise_is_nothing", sid is None and m["proposed"] is None and not m["ambiguous"])
check("parse.likewise_intent_other", lr.intent("Likewise", m) == lr.INTENT_OTHER)

check("parse.thursday_alone", pick("Thursday works")[0] == OFFERS[0]["id"])
check("parse.time_alone", pick("2:30 works for me")[0] == OFFERS[0]["id"])
check("parse.ordinal_1", pick("1")[0] == OFFERS[0]["id"])
check("parse.ordinal_option_2", pick("Option 2 please")[0] == OFFERS[1]["id"])
check("parse.ordinal_second", pick("the second one")[0] == OFFERS[1]["id"])
check("parse.bare_digit_in_sentence_is_not_an_answer", pick("I will have 2 people with me, is that ok")[0] is None)
check("parse.negation_before", pick("I can't do Thursday")[0] is None)
check("parse.negation_after_clause_scoped", pick("Thursday doesn't work, Friday is fine")[0] == OFFERS[1]["id"])
check("parse.not_thursday_period_friday", pick("Not Thursday. Friday.")[0] == OFFERS[1]["id"])
check("parse.no_comma_thursday_please", pick("No, Thursday please")[0] == OFFERS[0]["id"])
check("parse.friday_1pm_datetime", pick("Friday at 1 pm it is")[1]["via"] == "datetime")
check("parse.numeric_date", pick("11/6 at 1pm")[0] == OFFERS[1]["id"])
sid, m = pick("Can we do the 6th at 3?")
check("parse.proposal_when_unoffered", sid is None and m["proposed"] is not None
      and m["proposed"].isoformat().startswith("2026-11-06T15:00"), str(m["proposed"]))
check("parse.proposal_is_a_choice", lr.intent("Can we do the 6th at 3?", m) == lr.INTENT_CHOICE)
sid, m = pick("I can do Thursday at 2:30 or Friday at 1, either works")
check("parse.both_is_ambiguous", sid is None and m["ambiguous"])
check("parse.weekday_abbrev", pick("Tue Nov 3 at 10 AM please")[1]["proposed"] is not None)
check("parse.business_hours_guess", lr._hm("2", "30", None) == (14, 30) and lr._hm("10", None, None) == (10, 0)
      and lr._hm("12", None, None) == (12, 0) and lr._hm("9", None, "am") == (9, 0) and lr._hm("12", "15", "pm") == (12, 15))
check("parse.weekday_passed_rolls_a_week",
      lr.parse_datetimes("Monday at 1", _loc(datetime(2026, 11, 2, 14, 0)), TZ)[0]["date"].isoformat() == "2026-11-09")

check("intent.decline", lr.intent("Not interested anymore, please cancel") == lr.INTENT_DECLINE)
check("intent.later", lr.intent("Let's circle back next month") == lr.INTENT_LATER)
check("intent.question", lr.intent("What's the address?") == lr.INTENT_QUESTION)
check("intent.ack", lr.intent("Thanks!") == lr.INTENT_ACK)
check("intent.other", lr.intent("We have been very busy with the move") == lr.INTENT_OTHER)

QUOTED = ("On Fri, Oct 30, 2026 at 8:54 AM <info@mwmcreations.com> wrote:\n> Hi Shawnie,\n"
          "> Would one of these work for you?\n> - Thursday, November 5 at 2:30 PM\n> - Friday, November 6 at 1:00 PM\n")
offers = lr.offers_from_text(QUOTED, _loc(datetime(2026, 10, 30, 8, 54)), TZ)
check("offers.read_from_our_quoted_email", [o["id"][:16] for o in offers] == ["2026-11-05T14:30", "2026-11-06T13:00"], str(offers))
check("offers.quote_header_is_not_an_option", all("10-30" not in o["id"] for o in offers))

BODY = ("Hi Michael,\n\nThursday, November 5 at 2:30 PM works perfectly for me! Looking forward to it.\n\n"
        "Best,\nShawn\n\nOn Fri, Oct 30, 2026 at 8:54 AM <info@mwmcreations.com> wrote:\n> Hi Shawnie,\n> Something came up")
own = lr.strip_quoted(BODY)
check("quote.stripped", own.endswith("Shawn") and "Something came up" not in own and ">" not in own, repr(own))
check("quote.pt_br_header", "antes" not in lr.strip_quoted("Pode ser quinta.\n\nEm seg., 2 de nov. de 2026 às 08:00, Maya escreveu:\n> antes"))
check("quote.outlook_header", "old" not in lr.strip_quoted("Thursday is fine\n\n-----Original Message-----\nFrom: x\nold"))


def b64(s):
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")


msg = {"payload": {"mimeType": "multipart/alternative", "parts": [
    {"mimeType": "text/plain", "body": {"data": b64("plain part here")}},
    {"mimeType": "text/html", "body": {"data": b64("<p>html <b>part</b></p>")}}]}}
check("body.prefers_plain", lr.body_text(msg) == "plain part here")
msg_html = {"payload": {"mimeType": "text/html", "body": {"data": b64("<div>Hi<br>Thursday&nbsp;works<ul><li>a</li></ul></div>")}}}
bt = lr.body_text(msg_html)
check("body.html_fallback_flattened", "Thursday works" in bt and "<" not in bt and "• a" in bt, repr(bt))
check("body.empty_is_empty_string", lr.body_text({}) == "" and lr.body_text(None) == "")

txt = lr.reschedule_text("Vicente Orellana", "Monday, November 2 at 10:00 AM ET", OFFERS)
check("copy.reschedule_text_has_both_and_reply_1_or_2",
      "Thursday, November 5 at 2:30 PM" in txt and "Friday, November 6 at 1:00 PM" in txt and "Reply 1 or 2" in txt)
check("copy.reschedule_text_fits_two_segments", sc.compose_reply(sc.ascii_fold(txt)).endswith("suits you."), txt)
subj, html, text = lr.reschedule_email("Vicente Orellana", "Monday, November 2 at 10:00 AM ET", OFFERS, "1500 Park Center Dr")
check("copy.reschedule_email", subj.startswith("Moving your studio visit") and "<li>Thursday, November 5 at 2:30 PM</li>" in html
      and "2. Friday, November 6 at 1:00 PM" in text and "1500 Park Center Dr" in html)
subj, html, text = lr.confirmation_email("Shawnie Whitaker", "Thursday, November 5 at 2:30 PM ET", "1500 Park Center Dr")
check("copy.confirmation_email", "Thursday, November 5 at 2:30 PM ET" in subj and "booked for" in html and "Maya" in text)
esc = lr.escalation_sms("Shawnie Whitaker", "+13216890012", "Thanks, I'll get back to you", "reply")
check("copy.escalation_has_number_and_words", "+13216890012" in esc and "get back to you" in esc and "not a date pick" in esc)
check("copy.escalation_kinds", "backing out" in lr.escalation_sms("A", "", "", "declined")
      and "has not answered" in lr.escalation_sms("A", "", "", "silent") and "taken" in lr.escalation_sms("A", "", "", "taken"))
check("constants.moving", lr.MOVING_PROP == "mwm_moving" and lr.MOVING_PREFIX.startswith("⏳"))

# ── 2 · the watcher acts ────────────────────────────────────────────────────
w = SRC.index("def _info_watch_once():")
watch = SRC[w:SRC.index("def _flag_hard_bounce", w)]
check("watch.calls_handler_before_notice", "_handled = _lead_reply_handle(svc, r)" in watch
      and watch.index("_lead_reply_handle(svc, r)") < watch.index('"📥 *New mail in info@ — nobody has replied yet*\\n"'))
check("watch.generic_notice_kept_for_strangers", "if _handled:" in watch and "else:" in watch
      and "_info_mark_seen(r[\"id\"], r)" in watch)

h = SRC.index("def _lead_reply_handle(svc, row, now=None):")
handler = SRC[h:SRC.index("def _find_visit_event_for", h)]
check("handler.only_known_leads", "_find_lead_by_email(addr)" in handler and "return None" in handler
      and "info_inbox.is_internal(addr)" in handler)
check("handler.reads_body_once_in_app_not_watcher", 'format="full"' in handler)
check("handler.stops_chase", 'rec["last_message_time"] = now' in handler)
check("handler.offers_priority", "_lrp.offers_from_text(quoted, now, tz)" in handler
      and "_reschedule_pending_for(key)" in handler and 'rec.get("offered_slots")' in handler)
check("handler.books_through_the_tool_path", 'handle_tool_call("book_appointment", tool_input, sender=key)' in handler
      and '"lead_role": _gate_role_for(rec)' in handler)
check("handler.proposal_is_checked_first", "check_specific_slot(slot_iso)" in handler and '"taken"' in handler)
check("handler.idempotent_on_same_slot", 'rec.get("booked_slot_id") or "")[:16] == slot_iso[:16]' in handler)
check("handler.confirms_in_thread", "_lrp.confirmation_email(name, when_disp, STUDIO_ADDRESS" in handler
      and 'thread = {"mailbox": "info", "thread_id": tid}' in handler and "thread=thread" in handler)
check("handler.escalates_everything_else", '_operator_alert.alert("reply", _lrp.escalation_sms(name, phone, own, kind)' in handler)
check("handler.decline_goes_to_pipeline", 'new_stage="Backing out"' in handler)
check("handler.mirrors_to_shadow", '"inbound", f"[EMAIL] {own[:600]}"' in handler)

# ── 3 · the reschedule route ────────────────────────────────────────────────
r = SRC.index('@app.route("/admin/visit-reschedule", methods=["POST"])')
route = SRC[r:SRC.index("def _reschedule_escalation_pass", r)]
check("route.secret", '_admin_secret_ok(request.values.get("secret", ""))' in route)
check("route.dry_by_default", 'apply = str(request.values.get("apply") or "") in ("1", "true", "yes")' in route
      and '"dry": not apply' in route and "if not apply:\n        return jsonify(plan)" in route)
check("route.one_lead_only", "leads matched — narrow q" in route and "a #256 pair is one lead" in route)
check("route.state_before_sends", route.index('rec["reschedule"] = {"pending": True') < route.index("_lrp.reschedule_text(name, old_display, slots)"))
check("route.old_event_pulled_or_flagged", 'sendUpdates="all"' in route and "_lrp.MOVING_PROP: \"1\"" in route
      and "_lrp.MOVING_PREFIX" in route and "keep_event" in route)
check("route.every_channel", "wa_send_eligibility(key, is_template=False)" in route
      and "_send_sms(phone, _sms_copy.compose_reply(_sms_copy.ascii_fold(text)), kind=SMS_KIND_TRANSACTIONAL)" in route
      and '_email_send(email, subj, html, via="visit_reschedule", lead_key=key, transactional=True)' in route)
check("route.arms_escalation", '"escalate_at": (now + timedelta(hours=RESCHEDULE_ESCALATE_H)).isoformat()' in route)
check("route.twin_carries_state", 'tw["reschedule"] = dict(rec["reschedule"])' in route)
check("route.tells_the_room", 'new_stage="Rescheduling"' in route and "*Visit rescheduling*" in route)
check("route.confirm_mode", 'if mode == "confirm":' in route and 'how="confirmed_by_hand"' in route
      and 'rec["booked_slot_id"] = ns.isoformat()' in route)
check("route.past_slot_refused", "slot in the past" in route)

e = SRC.index("def _reschedule_escalation_pass(now=None):")
esc_src = SRC[e:SRC.index("# ── PATCH #245", e)]
check("escalation.texts_michael_daily_capped", '_operator_alert.alert("reply", _lrp.escalation_sms(name, phone, f"offered {opts}", "silent")' in esc_src
      and "RESCHEDULE_ESCALATE_MAX" in esc_src and 'rs["escalate_at"] = (now + timedelta(hours=24)).isoformat()' in esc_src)
check("escalation.rides_the_watcher", "_reschedule_escalation_pass()          # PATCH #262" in SRC[SRC.index("def _info_watch_thread():"):SRC.index("def _info_watch_thread():") + 1200])

# ── 4 · the guards and the memory ───────────────────────────────────────────
lad = SRC[SRC.index("def _lead_reminder_thread():"):SRC.index("def _lead_reminder_thread():") + 9000]
check("ladder.skips_moving_event", "if _event_is_moving(event):" in lad
      and lad.index("if _event_is_moving(event):") < lad.index("_rsvp_tier = due_rsvp_tier(hours_until)")
      and lad.index("if _event_is_moving(event):") > lad.index("if not is_client:"))
mv = SRC[SRC.index("def _event_is_moving(event):"):SRC.index("def _lead_display_when", SRC.index("def _event_is_moving(event):"))]
check("moving.three_signals", "_lrp.MOVING_PROP" in mv and "_lrp.MOVING_PREFIX" in mv and 'str(rs.get("old_event_id") or "") == eid' in mv)

gcr = SRC[SRC.index("def get_claude_reply("):SRC.index("def get_claude_reply(") + 6000]
check("maya.prompt_block_on_every_channel", "_rs_block = _reschedule_prompt_block(sender)" in gcr and "if sender and not is_owner:" in gcr)
pb = SRC[SRC.index("def _reschedule_prompt_block(sender):"):SRC.index("def _event_is_moving", SRC.index("def _reschedule_prompt_block(sender):"))]
check("maya.prompt_block_says_book_the_pick", "VISIT BEING RESCHEDULED (HARD RULE)" in pb and "call book_appointment" in pb
      and "do not re-qualify" in pb and "Do not send the booking link" in pb)

tool = SRC[SRC.index('    elif tool_name == "book_appointment":'):SRC.index('    elif tool_name == "cancel_appointment":')]
check("tool.records_slot_and_resolves_move", 'lead_data[sender]["booked_slot_id"] = str(tool_input.get("slot_id") or "")' in tool
      and '_reschedule_resolve(sender, event_id, tool_input.get("slot_id"))' in tool)
form = SRC[SRC.index("slots = (get_available_slots() or [])[:2]"):SRC.index("slots = (get_available_slots() or [])[:2]") + 600]
check("form.remembers_offered_slots", 'lr["offered_slots"] = [{"id": str(s.get("id") or ""), "display": str(s.get("display") or "")}' in form)
check("chase.remembers_offered_slots", 'rec["offered_slots"] = [{"id": str(s.get("id") or ""), "display": str(s.get("display") or "")}' in SRC)
check("rail.insertions_are_self_contained", "_offered_slots_record" not in SRC)
check("roles.form_owner_maps_to_gate", '"owner_founder"' in SRC[SRC.index("def _gate_role_for(rec):"):SRC.index("def _gate_role_for(rec):") + 1200])

# ── 5 · operator_alert + info_inbox contract ────────────────────────────────
check("oa.reply_kind", oa.KINDS.get("reply") == {"eric": True})
check("oa.hold_unchanged", oa.KINDS.get("hold") == {"eric": False})
II = open(os.path.join(HERE, "info_inbox.py"), encoding="utf-8").read()
check("info_inbox.still_metadata_only", 'format="full"' not in II and 'format="metadata"' in II)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch261.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #261 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("261: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE262 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
