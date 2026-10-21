"""PATCH #256 gate — one lead, two numbers (Vicente Orellana, 21 Oct 07:58:
Instant Form …2350, thank-you-page WhatsApp handoff from …4743 → two
records; the form chain could not see a WhatsApp reply or booking, and the
WhatsApp side raised a second card, Susan/LARA lines and a lead alert).

1. lead_form.handoff_fields reads the handoff; tidy_name re-cases a name
   typed in one case ('VICENTE ORELLANA' -> 'Vicente Orellana'); first_name
   does the same for the texts and emails.
2. The link helpers, lifted out of app.py: a handoff finds its form record
   by email or by the form phone in the message; linking marks both; the
   chase reads inbound and booked across the pair, and the handoff message
   itself is not a reply.
3. _chase_pass (lifted with the #143 stubs) stops the form chain when the
   lead books or writes from the WhatsApp number — and does NOT stop on
   the handoff alone.
4. Wiring: the WhatsApp handler links before the pipeline event, skips the
   second card / welcome / Susan / LARA / lead alert for a linked record,
   the booking tool marks the form record and sends the stage under it,
   the repair route links pre-patch pairs.
Then runs the #255 gate (→ 254 → 253 → …)."""
import ast
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lead_form as lf            # noqa: E402
import lead_chase as _chase       # noqa: E402
import studio_visit as sv         # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


TZ = pytz.timezone("America/New_York")
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()

# ── 1 · pure ────────────────────────────────────────────────────────────────
check("tidy.caps", lf.tidy_name("VICENTE ORELLANA") == "Vicente Orellana")
check("tidy.lower", lf.tidy_name("vicente orellana") == "Vicente Orellana")
check("tidy.mixed_untouched", lf.tidy_name("McDonald Smith") == "McDonald Smith" and lf.tidy_name("DeShawn Lee") == "DeShawn Lee")
check("tidy.particles", lf.tidy_name("JOÃO DA SILVA") == "João da Silva" and lf.tidy_name("VAN DER BERG") == "Van der Berg")
check("tidy.punct", lf.tidy_name("O'BRIEN JEAN-LUC") == "O'Brien Jean-Luc" and lf.tidy_name("J.R. SMITH") == "J.R. Smith")
check("tidy.empty_and_space", lf.tidy_name("") == "" and lf.tidy_name("  ANA  ") == "Ana")
check("extract.tidies", lf.extract({"full_name": "VICENTE ORELLANA", "email": "A@B.com"})["name"] == "Vicente Orellana")
check("first_name.caps", sv.first_name("VICENTE ORELLANA") == "Vicente" and sv.first_name("McDonald") == "McDonald"
      and sv.first_name("AL") == "Al" and sv.first_name("A") == "A" and sv.first_name("") == "there")

HANDOFF = ("Hello! I filled out your form and would like to know more about your business.\n\n"
           "What do customers need to understand before they buy from you?: Our unique process\n"
           "Your website or Instagram?: www.owningyourhouse.com\n"
           "What is your role in the business?: Owner / Founder / Partner\n"
           "Phone number: +14077772350\nCompany name: Owning Your House\n"
           "Email: Vicente7Orellana@Gmail.com\nFull name: VICENTE ORELLANA\n"
           "What is your business's monthly revenue?: $50K to $150K")
h = lf.handoff_fields(HANDOFF)
check("handoff.vicente", h == {"is_handoff": True, "email": "vicente7orellana@gmail.com",
                               "phone": "14077772350", "name": "Vicente Orellana"})
check("handoff.plain_message_not", lf.handoff_fields("hi, my email is bob@x.com can we talk")["is_handoff"] is False)
check("handoff.two_labels", lf.handoff_fields("Email: a@b.co\nFull name: Bob Lee")["is_handoff"] is True)
check("handoff.phone_paren", lf.handoff_fields("Phone number: (407) 555-1212\nEmail: x@y.org.")
      == {"is_handoff": True, "email": "x@y.org", "phone": "14075551212", "name": ""})
check("handoff.empty", lf.handoff_fields("")["is_handoff"] is False and lf.handoff_fields(None)["email"] == "")

# ── 2 · the link helpers, lifted ────────────────────────────────────────────
tree = ast.parse(SRC)
want = {"_find_form_twin", "_link_form_handoff", "_find_wa_twin", "_chase_twin",
        "_chase_inbound", "_chase_booked", "_chase_aware"}
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
check("lift.found", len(fns) == len(want), f"{len(fns)}/{len(want)}")
lead_data = {}
G = dict(lead_data=lead_data, re=re, datetime=datetime, timedelta=timedelta, pytz=pytz,
         TIMEZONE="America/New_York", _chase=_chase)
exec(compile(ast.Module(body=fns, type_ignores=[]), "app_256", "exec"), G)

T0 = TZ.localize(datetime(2026, 10, 21, 7, 58, 21))      # form
T1 = TZ.localize(datetime(2026, 10, 21, 7, 58, 28))      # handoff
FORM = "whatsapp:+14077772350"
WA = "whatsapp:+14073614743"
lead_data[FORM] = {"name": "Vicente Orellana", "email": "vicente7orellana@gmail.com", "phone": "+14077772350",
                   "business": "Owning Your House", "meta_lead_ad": True, "leadgen_id": "1639562691152723",
                   "last_message_time": T0, "chase": _chase.arm(T0, channels=("email", "sms"))}
lead_data[WA] = {"source": "WhatsApp", "first_contact_time": T1, "last_message_time": T1,
                 "email": "Vicente7Orellana@Gmail.com", "name": "VICENTE ORELLANA"}
lead_data["whatsapp:+10000000001"] = {"email": "other@x.com", "meta_lead_ad": True, "phone": "+10000000001"}
lead_data["junk"] = "x"

check("twin.by_email", G["_find_form_twin"](WA, "VICENTE7ORELLANA@gmail.com", "")[0] == FORM)
check("twin.by_form_phone", G["_find_form_twin"](WA, "", "4077772350")[0] == FORM)
check("twin.not_self", G["_find_form_twin"](FORM, "vicente7orellana@gmail.com", "")[0] is None)
check("twin.only_form_leads", G["_find_form_twin"]("whatsapp:+1999", "nobody@x.com", "")[0] is None)
check("twin.reverse", G["_find_wa_twin"](FORM, "vicente7orellana@gmail.com")[0] == WA
      and G["_find_wa_twin"](FORM, "")[0] is None)

wa, fr = G["_link_form_handoff"](WA, FORM, T1)
check("link.both_sides", wa["linked_form_key"] == FORM and fr["linked_wa_key"] == WA
      and wa["form_handoff_at"] == T1.isoformat() and fr["linked_at"] == T1.isoformat())
check("link.borrows_not_form", wa["business"] == "Owning Your House" and wa["name"] == "VICENTE ORELLANA"
      and not wa.get("meta_lead_ad") and not wa.get("leadgen_id") and wa["_email_notified"] is True)
check("twin.read", G["_chase_twin"](lead_data[FORM]) is lead_data[WA] and G["_chase_twin"](lead_data[WA]) is None
      and G["_chase_twin"]({"linked_wa_key": "nope"}) is None)
check("inbound.handoff_is_not_reply", G["_chase_inbound"](lead_data[FORM]) == T0)
lead_data[WA]["last_message_time"] = T1 + timedelta(minutes=5)
check("inbound.later_wa_message_is", G["_chase_inbound"](lead_data[FORM]) == T1 + timedelta(minutes=5))
lead_data[FORM]["last_message_time"] = T1 + timedelta(hours=2)
check("inbound.own_wins_when_later", G["_chase_inbound"](lead_data[FORM]) == T1 + timedelta(hours=2))
check("booked.neither", G["_chase_booked"](lead_data[FORM]) is False)
lead_data[WA]["booked"] = True
check("booked.via_twin", G["_chase_booked"](lead_data[FORM]) is True and G["_chase_booked"]({}) is False)

# ── 3 · the chase pass stops on the twin ────────────────────────────────────
import sms_copy as _sms_copy      # noqa: E402
import event_rail                 # noqa: E402
import sms_consent as _sc         # noqa: E402
pfn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("_chase_pass", "_chase_mask", "email_ok")]
check("lift.pass", len(pfn) == 3)
sms_calls, email_calls, tally = [], [], []


class Tally:
    def bump(self, *a): tally.append(a)


BL = {}
BG = dict(G, lead_data=BL, _sc=_sc, _sv=sv, _sms_copy=_sms_copy, event_rail=event_rail,
          SMS_KIND_MARKETING="marketing", SMS_KIND_TRANSACTIONAL="transactional",
          _LEAD_CHASE_LAST={"last_send": ""}, _TALLY=Tally(),
          _chase_is_client=lambda k: False, email_is_suppressed=lambda e: (False, ""),
          get_available_slots=lambda: [], _sms_body_that_fits=lambda fns: fns[0](),
          _send_sms=lambda phone, body, kind="marketing": (sms_calls.append((phone, body)) or {"ok": True}),
          _email_send=lambda to, subject, html, via="", lead_key=None, **k: (email_calls.append((to, subject, via)) or {"ok": True}))
exec(compile(ast.Module(body=fns + pfn, type_ignores=[]), "app_256_pass", "exec"), BG)
BL[FORM] = {"name": "Vicente Orellana", "email": "vicente7orellana@gmail.com", "phone": "+14077772350",
            "business": "Owning Your House", "meta_lead_ad": True, "last_message_time": T0,
            "chase": _chase.arm(T0, channels=("email",))}
BL[WA] = {"source": "WhatsApp", "first_contact_time": T1, "last_message_time": T1,
          "email": "vicente7orellana@gmail.com", "linked_form_key": FORM, "form_handoff_at": T1.isoformat()}
BL[FORM]["linked_wa_key"] = WA
c = BG["_chase_pass"](T0 + timedelta(hours=1))
check("pass.handoff_alone_keeps_chain", c["active"] == 1 and not BL[FORM]["chase"].get("stopped"), str(c))
BL[WA]["last_message_time"] = T1 + timedelta(hours=3)
c = BG["_chase_pass"](T0 + timedelta(hours=4))
check("pass.wa_reply_stops_chain", BL[FORM]["chase"].get("stopped") == _chase.STOP_REPLIED, str(BL[FORM]["chase"]))
BL[FORM]["chase"] = _chase.arm(T0, channels=("email",))
BL[WA]["last_message_time"] = T1
BL[WA]["booked"] = True
c = BG["_chase_pass"](T0 + timedelta(hours=4))
check("pass.wa_booking_stops_chain", BL[FORM]["chase"].get("stopped") == _chase.STOP_BOOKED, str(BL[FORM]["chase"]))
# the late first-touch text is dropped when the lead already booked on the other number
BL[FORM]["chase"] = _chase.arm(T0, channels=("email", "sms"))
BL[FORM]["first_touch_sms_pending"] = {"since": T0.isoformat(), "core": "x", "reason": "quiet_hours"}
sms_calls.clear()
c = BG["_chase_pass"](T0 + timedelta(hours=1))
check("pass.pending_sms_dropped_when_twin_booked", "first_touch_sms_pending" not in BL[FORM]
      and BL[FORM].get("first_touch_sms_dropped") and not sms_calls, str(BL[FORM].get("first_touch_sms_dropped")))
# ...and goes out when the twin is merely linked (the handoff is not a reply)
BL[WA]["booked"] = False
BL[FORM]["chase"] = _chase.arm(T0, channels=("email", "sms"))
BL[FORM].pop("first_touch_sms_dropped", None)
BL[FORM]["first_touch_sms_pending"] = {"since": T0.isoformat(), "core": "Hi Vicente, Maya from Michael Moraes' team. Which works?", "reason": "quiet_hours"}
sms_calls.clear()
c = BG["_chase_pass"](TZ.localize(datetime(2026, 10, 21, 8, 4)))
check("pass.pending_sms_sent_when_only_linked", len(sms_calls) == 1 and sms_calls[0][0] == "+14077772350"
      and BL[FORM].get("first_touch_sms_at") and "first_touch_sms_pending" not in BL[FORM], str(sms_calls))

# ── 4 · wiring ──────────────────────────────────────────────────────────────
i_link = SRC.index("_handoff_form_key, _ = _find_form_twin(")
i_card = SRC.index("if _handoff_form_key:\n                    _TALLY.bump(\"lead_form.wa_handoff_linked\"")
check("wire.link_before_card", i_link < i_card < SRC.index("_post_new_lead_or_existing_client(\n                        sender, \"WhatsApp\""))
check("wire.link_guarded", "_ho = _lf.handoff_fields(incoming_msg)\n                if _ho[\"is_handoff\"]:" in SRC
      and "_report_error(\"lead_form.wa_handoff_link\", _lnk_err, sender)" in SRC)
check("wire.154_guard_sees_link", "_is_form_lead = bool(_ld.get(\"meta_lead_ad\") or _ld.get(\"linked_form_key\"))" in SRC)
check("wire.early_name_tidied", "_early_name = _lf.tidy_name(_name_match.group(1).strip())" in SRC)
check("wire.lead_alert_skipped", "_lk = (lead_data.get(sender) or {}).get(\"linked_form_key\") if sender else None\n        if _lk:" in SRC
      and SRC.index("def notify_michael_maya_lead(") < SRC.index("_TALLY.bump(\"lead_form.wa_handoff_skipped_lead_alert\"") < SRC.index("def log_lead("))
check("wire.booking_marks_form", "_fk = lead_data[sender].get(\"linked_form_key\")\n                    if _fk and isinstance(lead_data.get(_fk), dict):" in SRC
      and "\"event_id\": event_id, \"booked_via_linked\": sender})" in SRC
      and "_capi_stage(_capi_key, lead_data[_capi_key], _capi.STAGE_BOOKED," in SRC)
check("wire.chase_pass", SRC.count("inbound = _chase_inbound(rec)") == 2
      and "rec_v = dict(rec, booked=True) if _chase_booked(rec) else rec\n        reason = _chase.stop_reason(state, rec_v, now, last_inbound=inbound," in SRC
      and "or _chase_booked(rec) or isinstance(rec.get(\"disqualified\"), dict):" in SRC)
check("wire.repair_links", "_wk, _wr = _find_wa_twin(_k, _r.get(\"email\"))" in SRC
      and "\"link_candidates\": sum(1 for r in _rows if r.get(\"link_candidate\"))" in SRC
      and "_row[\"booked_either\"] = _chase_booked(_r)" in SRC)
check("wire.143_behaviour_lifts", all(n in open(os.path.join(HERE, "test_patch143_behaviour.py"), encoding="utf-8").read()
                                      for n in ("\"_chase_twin\"", "\"_chase_inbound\"", "\"_chase_booked\"")))

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch255.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #255 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("255: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE256 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
