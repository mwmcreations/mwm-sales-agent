"""PATCH #270 gate — MWM Desk, slice 1 (see). The read model places every kind
of record on the board from the facts the hooks write, the inbox orders by
activity, search finds by name/phone/email, the lead card carries the dated
events and the conversation, the door admits only our domain, and the app
mounts it without touching anything else. Then the #269 gate (→ 267 chain)."""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import desk                       # noqa: E402
import meta_capi as capi          # noqa: E402
import victory_auth as va         # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


NOW = datetime(2026, 11, 7, 23, 30)
H = lambda h: (NOW - timedelta(hours=h)).isoformat()   # noqa: E731
D = lambda d: (NOW - timedelta(days=d)).isoformat()    # noqa: E731

# ── fixtures: one record per era / situation ────────────────────────────────
LEADS = {
    # a Meta form lead, qualified at intake, nobody has spoken to yet
    "whatsapp:+14075550101": {"name": "Linda Garcia", "business": "Garcia Bakery", "phone": "+14075550101",
                              "email": "linda@example.com", "source": "Meta Lead Ad", "channel": "Lead Form",
                              "qualified": "yes", "qualified_reason": "owner, $20K-50K", "lead_form_at": H(2),
                              "last_message_time": H(2), "sms_consent_form": True, "ad_name": "AD_16 film once"},
    # first touch went out on WhatsApp (delivered), SMS armed; no reply yet
    "whatsapp:+14075550102": {"name": "Marcus Lee", "business": "Lee Roofing", "phone": "+14075550102",
                              "source": "Meta Lead Ad", "qualified": "studio-hour", "lead_form_at": H(5),
                              "first_touch_wa": {"wamid": "wamid.1", "status": "delivered", "sent_at": H(4)},
                              "first_touch_sms_pending": {"reason": "wa_wait", "not_before": H(3)},
                              "chase": {"kind": "form", "armed_at": H(4), "sent": {}, "stopped": ""}},
    # a WhatsApp conversation: they wrote, Maya answered, they wrote again → awaiting reply
    "whatsapp:+14075550103": {"name": "Ana Souza", "phone": "+14075550103", "source": "WhatsApp",
                              "first_contact_time": D(1), "last_message_time": H(1), "last_inbound_at": H(1)},
    # booked (event_id) with a display
    "whatsapp:+14075550104": {"name": "Pedro Alves", "business": "Alves Dental", "phone": "+14075550104",
                              "source": "Website form", "event_id": "evt_1", "booked_at": D(2),
                              "booked_slot_id": (NOW + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0).isoformat(), "booking_kind": "studio_visit",
                              "chase": {"kind": "form", "armed_at": D(3), "sent": {"d0_sms": D(3), "d1_email": D(2)},
                                        "stopped": "booked"}},
    # visited, outcome recorded
    "whatsapp:+14075550105": {"name": "Carla Mendes", "phone": "+14075550105", "source": "Instagram Dm",
                              "event_id": "evt_2", "booked_at": D(9), "booked_slot_id": D(6), "last_outcome": "follow_up", "last_outcome_at": D(5)},
    # a client (paid)
    "whatsapp:+14075550106": {"name": "Shawnie Whitaker", "business": "Your Local Alarm Dealer", "phone": "+14075550106",
                              "email": "s@example.com", "source": "Referral", "paid_at": D(1), "product": "MWM Partner Plan",
                              "paid_value": 350, "status": "Client — MWM Partner Plan"},
    # a client by status only (old era)
    "whatsapp:+14075550107": {"name": "Luzia Costa", "phone": "+14075550107", "whatsapp_status": "Client — Studio Package",
                              "last_message_time": D(20)},
    # lost: do not contact
    "whatsapp:+14075550108": {"name": "Spam Bot", "phone": "+14075550108", "do_not_contact": True, "last_message_time": D(3)},
    # lost: chase disqualified
    "whatsapp:+14075550109": {"name": "Tiny Shop", "phone": "+14075550109", "source": "Meta Lead Ad", "qualified": "no",
                              "lead_form_at": D(4), "chase": {"kind": "form", "armed_at": D(4), "sent": {}, "stopped": "disqualified"}},
    # paused: nobody has heard from him in 40 days (temperature is only a badge)
    "whatsapp:+14075550110": {"name": "Cold Carl", "phone": "+14075550110", "source": "WhatsApp",
                              "temperature": "Cold", "last_message_time": D(40), "last_inbound_at": D(40)},
    # Maya scored her Cold, but the chase is live and the first touch is out → Contacted, not Paused
    "whatsapp:+14075550112": {"name": "Allison Carmany", "business": "Soulful Evolution", "phone": "+14075550112", "source": "Meta Lead Ad",
                              "qualified": "studio-hour", "temperature": "Cold", "lead_form_at": D(9), "first_touch_sms_at": D(9),
                              "chase": {"kind": "studio_hour", "armed_at": D(9), "sent": {"d0_email": D(9), "d3_sms": D(6), "d7_email": D(2)}, "stopped": ""}},
    # booked two weeks ago, slot passed, nobody recorded what happened
    "whatsapp:+14075550113": {"name": "Vicente Orellana", "phone": "+14075550113", "source": "WhatsApp", "event_id": "evt_3",
                              "booked_at": D(16), "booked_slot_id": D(14), "last_message_time": D(5), "last_inbound_at": D(5)},
    # an Instagram lead with a conversation, no phone
    "instagram:1789": {"name": "", "source": "", "ig_key": "instagram:1789", "last_message_time": H(6)},
    # a record with no dates at all (oldest era) — must still render, as New
    "whatsapp:+14075550111": {"name": "Old Record", "phone": "+14075550111"},
    # booked in September, before slot times were recorded (#262); nothing since → passed, backlog
    "whatsapp:+14075550114": {"name": "Alex Maldonado", "phone": "+14075550114", "source": "WhatsApp", "event_id": "evt_4",
                              "booked_at": D(60), "last_message_time": D(60), "last_inbound_at": D(60)},
    # an old WhatsApp record whose conversation was never kept — a date, no turns → Paused, not New
    "whatsapp:+14075550115": {"name": "Quiet Quinn", "phone": "+14075550115", "source": "WhatsApp", "last_message_time": D(90)},
    # a test lead — never on the board
    "whatsapp:+10000000000": {"name": "<test lead: tool>", "phone": "+10000000000", "test_lead": True, "last_message_time": H(0)},
    # Meta's Lead Ads Testing Tool dummy, caught by its name alone
    "instagram:4593113990973865": {"name": "<test lead: dummy data for full_name>", "source": "Instagram", "last_message_time": H(0)},
    # garbage — skipped
    "junk": "not a record",
}
CONV = {
    "whatsapp:+14075550103": [{"role": "user", "content": "Hi, I saw the ad about the studio"},
                              {"role": "assistant", "content": "Hi Ana, Maya here — two times this week: 1) Tue 10 AM 2) Thu 3 PM"},
                              {"role": "user", "content": "Thursday works"}],
    "whatsapp:+14075550104": [{"role": "user", "content": "Yes"}, {"role": "assistant", "content": "Booked for Tue Nov 10 at 10:00 AM."}],
    "whatsapp:+14075550106": [{"role": "user", "content": "ok"}, {"role": "assistant", "content": "Welcome aboard!"}],
    "whatsapp:+14075550101": [],
}
IG = {"instagram:1789": [{"role": "user", "content": "do you do podcasts?"}, {"role": "assistant", "content": "We do — in our studio in Orlando."}]}

# ── constants agree with the funnel module ───────────────────────────────────
check("const.visit_outcomes", tuple(desk.VISIT_OUTCOMES) == tuple(capi.VISIT_OUTCOMES), str(desk.VISIT_OUTCOMES))
check("const.qualified", tuple(desk.QUALIFIED_VERDICTS) == tuple(capi.QUALIFIED_VERDICTS))
check("const.stages", desk.STAGES == ("New", "Contacted", "Replied", "Booked", "Visited", "Client", "Paused", "Lost"))

# ── stage_of ────────────────────────────────────────────────────────────────
def st(key):
    rec = LEADS[key]
    return desk.stage_of(rec, desk.turns_for(key, rec, CONV, IG), now=NOW)

check("stage.new_form", st("whatsapp:+14075550101") == "New")
check("stage.contacted_first_touch", st("whatsapp:+14075550102") == "Contacted")
check("stage.replied", st("whatsapp:+14075550103") == "Replied")
check("stage.booked", st("whatsapp:+14075550104") == "Booked")
check("stage.visited", st("whatsapp:+14075550105") == "Visited")
check("stage.client_paid", st("whatsapp:+14075550106") == "Client")
check("stage.client_status", st("whatsapp:+14075550107") == "Client")
check("stage.lost_dnc", st("whatsapp:+14075550108") == "Lost")
check("stage.lost_disqualified", st("whatsapp:+14075550109") == "Lost")
check("stage.paused_quiet", st("whatsapp:+14075550110") == "Paused")
check("stage.temperature_is_not_a_stage", st("whatsapp:+14075550112") == "Contacted")
check("stage.passed_booking_stays_booked", st("whatsapp:+14075550113") == "Booked")
check("stage.quiet_threshold", desk.stage_of({"last_inbound_at": D(29)}, now=NOW) == "Replied" and desk.stage_of({"last_inbound_at": D(31)}, now=NOW) == "Paused"
      and desk.stage_of({"first_touch_sms_at": D(31)}, now=NOW) == "Paused")
check("stage.active_chase_never_paused", desk.stage_of({"first_touch_sms_at": D(45), "chase": {"armed_at": D(45), "sent": {"a": D(45)}, "stopped": ""}}, now=NOW) == "Contacted")
check("stage.undated_turns_paused", desk.stage_of({}, [{"role": "lead", "text": "hi", "at": ""}], now=NOW) == "Paused")
check("stage.dated_no_turns_old", st("whatsapp:+14075550115") == "Paused" and desk.stage_of({"last_message_time": D(3)}, now=NOW) == "New")
check("stage.old_slotless_booking", st("whatsapp:+14075550114") == "Booked")
check("test.meta_dummy", desk.is_test(LEADS["instagram:4593113990973865"]) and desk.is_test(LEADS["whatsapp:+10000000000"]) and not desk.is_test(LEADS["whatsapp:+14075550101"]))
check("stage.not_interested_lost", desk.stage_of({"event_id": "e", "last_outcome": "not_interested"}, now=NOW) == "Lost")
check("quiet.days", round(desk.quiet_days({"last_inbound_at": D(3)}, now=NOW)) == 3 and desk.quiet_days({}, now=NOW) is None)
check("stage.ig_replied", st("instagram:1789") == "Replied")
check("stage.no_dates", st("whatsapp:+14075550111") == "New")
check("stage.client_won_outcome", desk.stage_of({"last_outcome": "client_won", "event_id": "e"}, now=NOW) == "Client")
check("stage.visit_beats_booked", desk.stage_of({"last_outcome": "completed", "event_id": "e"}, now=NOW) == "Visited")
check("stage.dnc_flag_from_store", desk.stage_of({"name": "x", "last_message_time": D(1)}, dnc=True, now=NOW) == "Lost")
check("stage.client_beats_dnc", desk.stage_of({"paid_at": D(1), "do_not_contact": True}, now=NOW) == "Client")

# ── turns / activity / names ────────────────────────────────────────────────
t103 = desk.turns_for("whatsapp:+14075550103", LEADS["whatsapp:+14075550103"], CONV, IG)
check("turns.shape", [t["role"] for t in t103] == ["lead", "maya", "lead"] and t103[1]["text"].startswith("Hi Ana") and t103[0]["at"] == "")
check("turns.ig", [t["role"] for t in desk.turns_for("instagram:1789", LEADS["instagram:1789"], CONV, IG)] == ["lead", "maya"])
check("turns.by_phone", desk.turns_for("+1 (407) 555-0104", {"phone": "4075550104"}, CONV, IG)[-1]["role"] == "maya")
check("turns.none", desk.turns_for("whatsapp:+14075550111", LEADS["whatsapp:+14075550111"], CONV, IG) == [])
check("turns.multimodal", desk.turns_for("k", {}, {"k": [{"role": "user", "content": [{"type": "text", "text": "hello"}, {"type": "image"}]}]}, {})[0]["text"] == "hello")
check("activity.latest", desk.last_activity(LEADS["whatsapp:+14075550104"]) == D(2))
check("activity.chase_counts", desk.last_activity({"chase": {"sent": {"a": D(7), "b": D(6)}}}) == D(6))
check("activity.none", desk.last_activity(LEADS["whatsapp:+14075550111"]) == "")
check("name.fallbacks", desk.display_name({"business": "Bakery"}, "whatsapp:+14075550101") == "Bakery"
      and desk.display_name({}, "whatsapp:+14075550101") == "…0101" and desk.display_name({}, "instagram:1") == "Instagram lead"
      and desk.display_name({"name": "unknown", "phone": "4075550102"}, "x") == "…0102")
check("phone_key", desk.phone_key("whatsapp:+14075550101", {}) == "14075550101" and desk.phone_key("x", {"phone": "(407) 555-0102"}) == "14075550102"
      and desk.phone_key("instagram:1", {}) == "")
check("source.fallbacks", desk.source_of({}, "instagram:1") == "Instagram" and desk.source_of({"channel": "sms"}, "k") == "Sms"
      and desk.source_of({"source": "Meta Lead Ad"}, "k") == "Meta Lead Ad")

# ── lead_view ───────────────────────────────────────────────────────────────
v1 = desk.lead_view("whatsapp:+14075550101", LEADS["whatsapp:+14075550101"], [], now=NOW)
check("view.form_lead", v1["stage"] == "New" and v1["qualified"] is True and "qualified" in v1["flags"] and v1["phone"] == "14075550101"
      and v1["email"] == "linda@example.com" and v1["channel"] == "email" and v1["first_seen"] == H(2)
      and v1["form"]["qualified_reason"] == "owner, $20K-50K" and v1["consent"] == {"form": True} and v1["booking"] is None, json.dumps(v1)[:300])
v2 = desk.lead_view("whatsapp:+14075550102", LEADS["whatsapp:+14075550102"], [], now=NOW)
check("view.first_touch", v2["first_touch"]["whatsapp"]["status"] == "delivered" and v2["first_touch"]["sms_pending"]["reason"] == "wa_wait"
      and "first_touch_pending" in v2["flags"] and "chasing" in v2["flags"] and v2["chase"]["sent"] == 0)
v3 = desk.lead_view("whatsapp:+14075550103", LEADS["whatsapp:+14075550103"], t103, now=NOW)
check("view.awaiting", "awaiting_reply" in v3["flags"] and v3["last_turn_role"] == "lead" and v3["snippet"] == "Thursday works" and v3["turns"] == 3)
v3m = desk.lead_view("whatsapp:+14075550103", LEADS["whatsapp:+14075550103"], t103, manual=True, now=NOW)
check("view.manual_quiets_awaiting", "michael" in v3m["flags"] and "awaiting_reply" not in v3m["flags"])
v4 = desk.lead_view("whatsapp:+14075550104", LEADS["whatsapp:+14075550104"], desk.turns_for("whatsapp:+14075550104", LEADS["whatsapp:+14075550104"], CONV, IG), now=NOW)
check("view.booking", v4["booking"]["when"] == "Tue Nov 10 at 10:00 AM" and v4["booking"]["passed"] is False and v4["booking"]["kind"] == "studio_visit"
      and v4["chase"]["stopped"] == "booked" and v4["chase"]["sent"] == 2 and "chasing" not in v4["flags"] and v4["chase"]["last_sent_at"] == D(2)
      and "visit_passed" not in v4["flags"], json.dumps(v4["booking"]))
v13 = desk.lead_view("whatsapp:+14075550113", LEADS["whatsapp:+14075550113"], [], now=NOW)
check("view.passed_booking", v13["booking"]["passed"] is True and "visit_passed" in v13["flags"] and v13["booking"]["when"].startswith("Sat Oct 24"), json.dumps(v13["booking"]))
v14 = desk.lead_view("whatsapp:+14075550114", LEADS["whatsapp:+14075550114"], [], now=NOW)
check("view.slotless_old_booking", v14["booking"]["passed"] is True and v14["booking"]["when"] == "" and v14["booking"]["slot_at"] == ""
      and "outcome_missing" in v14["flags"] and "visit_passed" not in v14["flags"], json.dumps(v14["booking"]) + str(v14["flags"]))
check("view.slotless_recent_booking", "visit_passed" not in desk.lead_view("k", {"event_id": "e", "booked_at": D(3)}, [], now=NOW)["flags"]
      and desk.lead_view("k", {"event_id": "e", "booked_at": D(3)}, [], now=NOW)["booking"]["passed"] is False
      and "visit_passed" in desk.lead_view("k", {"event_id": "e", "booked_at": D(20)}, [], now=NOW)["flags"])
check("view.slot_display", desk.slot_display("2026-11-10T10:00:00-05:00") == "Tue Nov 10 at 10:00 AM" and desk.slot_display("Tue Nov 10 at 10:00 AM") == "Tue Nov 10 at 10:00 AM"
      and desk.slot_display("2026-11-03T15:00:00") == "Tue Nov 3 at 3:00 PM")
check("view.source_labels", desk.source_of({"source": "Instagram Dm"}) == "Instagram DM" and desk.source_of({"source": "Meta Lead Ad"}) == "Meta Lead Ad"
      and desk.source_of({"source": "Direct — booked by Michael"}) == "Direct — booked by Michael")
check("view.temperature_badge", desk.lead_view("whatsapp:+14075550112", LEADS["whatsapp:+14075550112"], [], now=NOW)["temperature"] == "cold"
      and desk.lead_view("whatsapp:+14075550112", LEADS["whatsapp:+14075550112"], [], now=NOW)["stage"] == "Contacted")
v6 = desk.lead_view("whatsapp:+14075550106", LEADS["whatsapp:+14075550106"], [], now=NOW)
check("view.client", v6["stage"] == "Client" and v6["paid"]["product"] == "MWM Partner Plan" and v6["paid"]["value"] == 350 and v6["product"] == "MWM Partner Plan")
check("view.no_dates", desk.lead_view("whatsapp:+14075550111", LEADS["whatsapp:+14075550111"], [], now=NOW)["last_activity"] == "")
check("view.not_a_dict", desk.lead_view("x", "garbage", [], now=NOW)["stage"] == "New")

# ── timeline ────────────────────────────────────────────────────────────────
tl4 = desk.timeline(v4, LEADS["whatsapp:+14075550104"], desk.turns_for("whatsapp:+14075550104", LEADS["whatsapp:+14075550104"], CONV, IG))
kinds = [e["kind"] for e in tl4["events"]]
check("tl.order", kinds[:3] == ["chase", "chase", "booked"] and kinds[-1] == "chase_stop" and tl4["events"][-1]["at"] == "", str(kinds))
check("tl.turns", len(tl4["turns"]) == 2 and tl4["turns"][0]["role"] == "lead")
tl2 = desk.timeline(v2, LEADS["whatsapp:+14075550102"], [])
check("tl.first_touch", [e["kind"] for e in tl2["events"]] == ["captured", "first_touch"] and "delivered" in tl2["events"][1]["text"])
tl6 = desk.timeline(v6, LEADS["whatsapp:+14075550106"], [])
check("tl.paid", tl6["events"][-1]["kind"] == "paid" and "$350" in tl6["events"][-1]["text"])

# ── board / inbox / search / one ────────────────────────────────────────────
b = desk.board(LEADS, CONV, IG, manual_keys=set(), now=NOW)
check("board.total_skips_test_and_junk", b["total"] == 16 and all(c["key"] not in ("whatsapp:+10000000000", "instagram:4593113990973865") for col in b["columns"].values() for c in col))
check("board.counts", b["counts"] == {"New": 2, "Contacted": 2, "Replied": 2, "Booked": 3, "Visited": 1, "Client": 2, "Paused": 2, "Lost": 2}, str(b["counts"]))
check("board.booked_upcoming_first", [c["key"] for c in b["columns"]["Booked"]] == ["whatsapp:+14075550104", "whatsapp:+14075550113", "whatsapp:+14075550114"],
      str([c["key"] for c in b["columns"]["Booked"]]))
check("board.sorted", [c["key"] for c in b["columns"]["New"]] == ["whatsapp:+14075550101", "whatsapp:+14075550111"])
check("board.awaiting", b["awaiting_reply"] == 1 and b["as_of"] == NOW.isoformat())
check("board.card_shape", set(b["columns"]["Booked"][0].keys()) >= {"key", "name", "stage", "flags", "booking", "last_activity", "snippet", "source"}
      and "timeline" not in b["columns"]["Booked"][0] and "form" not in b["columns"]["Booked"][0])
bm = desk.board(LEADS, CONV, IG, manual_keys={"14075550103"}, now=NOW)
check("board.manual_by_digits", bm["awaiting_reply"] == 0 and "michael" in [c for c in bm["columns"]["Replied"] if c["key"].endswith("0103")][0]["flags"])
ib = desk.inbox(LEADS, CONV, IG, now=NOW)
check("inbox.order", ib["rows"][0]["key"] == "whatsapp:+14075550103" and ib["rows"][1]["key"] == "whatsapp:+14075550101"
      and all(r["key"] != "whatsapp:+14075550111" for r in ib["rows"]), str([r["key"] for r in ib["rows"]][:4]))
check("inbox.attention", [r["key"] for r in desk.inbox(LEADS, CONV, IG, only="attention", now=NOW)["rows"]] == ["whatsapp:+14075550103", "whatsapp:+14075550113"])
check("inbox.conversations", {r["key"] for r in desk.inbox(LEADS, CONV, IG, only="conversations", now=NOW)["rows"]}
      == {"whatsapp:+14075550103", "whatsapp:+14075550104", "whatsapp:+14075550106", "instagram:1789"})
check("inbox.attention_counts_passed", "visit_passed" in [r for r in desk.inbox(LEADS, CONV, IG, now=NOW)["rows"] if r["key"].endswith("0113")][0]["flags"])
check("inbox.limit", len(desk.inbox(LEADS, CONV, IG, limit=2, now=NOW)["rows"]) == 2)
check("search.name", [r["key"] for r in desk.search(LEADS, CONV, IG, "souza")["rows"]] == ["whatsapp:+14075550103"])
check("search.phone", [r["key"] for r in desk.search(LEADS, CONV, IG, "(407) 555-0104")["rows"]] == ["whatsapp:+14075550104"])
check("search.email_business", desk.search(LEADS, CONV, IG, "alarm")["rows"][0]["key"] == "whatsapp:+14075550106"
      and desk.search(LEADS, CONV, IG, "linda@")["rows"][0]["key"] == "whatsapp:+14075550101")
check("search.empty", desk.search(LEADS, CONV, IG, "  ")["rows"] == [] and desk.search(LEADS, CONV, IG, "zzz")["rows"] == [])
o = desk.one(LEADS, CONV, IG, "whatsapp:+14075550103", now=NOW)
check("one.full", o["name"] == "Ana Souza" and len(o["timeline"]["turns"]) == 3 and o["timeline"]["events"][0]["kind"] == "captured")
check("one.by_phone", desk.one(LEADS, CONV, IG, "4075550104", now=NOW)["key"] == "whatsapp:+14075550104")
check("one.missing", desk.one(LEADS, CONV, IG, "whatsapp:+19999999999", now=NOW) is None)
s = desk.status(LEADS, CONV, IG)
check("status.line", s["leads"] == 16 and s["counts"]["Client"] == 2 and s["awaiting_reply"] == 1)

# one bad record never blanks the board
class Bad(dict):
    def get(self, k, d=None):
        if k == "name":
            raise RuntimeError("boom")
        return dict.get(self, k, d)
bb = desk.board({"whatsapp:+14075550199": Bad({"phone": "+14075550199"}), **{k: v for k, v in LEADS.items() if k != "junk"}}, CONV, IG, now=NOW)
check("board.bad_record_isolated", bb["total"] == 17 and any("error" in c["flags"] for c in bb["columns"]["New"]))

# ── the door ────────────────────────────────────────────────────────────────
secret = "s3cr3t"
good = va.sign_session("michael@mwmcreations.com", va.ROLE_MWM, "", secret)
other_role = va.sign_session("someone@mwmcreations.com", va.ROLE_PENDING, "", secret) if va.ROLE_PENDING in va.ROLES else ""
off_domain = va.sign_session("x@victoryma.com", va.ROLE_MWM, "", secret)
check("door.mwm_session", desk.session_ok(good, secret) == ("mwm", "michael@mwmcreations.com"))
check("door.pending_refused", not other_role or desk.session_ok(other_role, secret) == (None, ""))
check("door.off_domain_refused", desk.session_ok(off_domain, secret) == (None, ""))
check("door.bad_cookie", desk.session_ok("garbage.sig", secret) == (None, "") and desk.session_ok(good, "") == (None, ""))
check("door.admin_secret", desk.session_ok("", secret, admin_secret_given="k", admin_ok=lambda s: s == "k") == ("admin", "")
      and desk.session_ok("", secret, admin_secret_given="wrong", admin_ok=lambda s: s == "k") == (None, ""))
check("door.expired", desk.session_ok(good, secret, now=time.time() + va.SESSION_TTL_SECONDS + 10) == (None, ""))
check("door.link_domain", desk.may_request_link("Michael@MWMCreations.com") and not desk.may_request_link("x@victoryma.com")
      and not desk.may_request_link("x@gmail.com") and not desk.may_request_link(""))
check("door.html", "MWM Desk" in desk.door_html() and "Victory" not in desk.door_html() and 'action="/desk/login"' in desk.door_html()
      and "on its way" in desk.door_html(sent=True) and "expired" in desk.door_html("That link has expired", error=True))
check("door.link_mail", "/desk/auth?token=abc" in desk.link_email_html("https://x/desk/auth?token=abc") and "15 minutes" in desk.link_email_text("u"))

# ── files + app wiring (static) ─────────────────────────────────────────────
for f in ("desk_static/desk.html", "desk_static/desk.css", "desk_static/desk.js"):
    check("file." + f, os.path.exists(os.path.join(HERE, f)))
html = open(os.path.join(HERE, "desk_static/desk.html"), encoding="utf-8").read()
js = open(os.path.join(HERE, "desk_static/desk.js"), encoding="utf-8").read()
check("page.refs", '/desk/static/desk.css' in html and '/desk/static/desk.js' in html and 'viewport' in html and "MWM Desk" in html)
check("page.no_outside_scripts", "http://" not in html and "https://" not in html.replace("https://wa.me", ""))
check("js.endpoints", all(p in js for p in ("/desk/api/board", "/desk/api/inbox", "/desk/api/search?q=", "/desk/api/lead/")) and "location.reload()" in js)
check("js.writes_only_to_desk_api", all(("/desk/api/lead/" in l or "/meeting-report/submit" in l or "withAuth(path)" in l or "opts.method" in l)
      for l in js.splitlines() if "POST" in l))   # slice 2 writes, only through the Desk API and the report
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.import", "import desk as _desk" in SRC and "_desk.register(app, _admin_secret_ok, lead_data, conversation_history, ig_conversation_history," in SRC)
check("app.deps", "send_email=_vi_send_email, report_error=_report_error, notify=_vi_notify," in SRC and "manual_keys=_desk_manual_keys" in SRC)
check("app.manual_keys", "def _desk_manual_keys():" in SRC and "dict(_manual_mode).items() if _now < float(until or 0)" in SRC)
check("app.nonfatal", 'print(f"[DESK] wiring skipped (non-fatal): {_dkx!r}")' in SRC)
check("app.health", '"desk": (globals().get("_desk").status(lead_data, conversation_history, ig_conversation_history)' in SRC)
check("app.after_vi", SRC.index("import desk as _desk") > SRC.index("_vi_routes.boot()"))
# the Flask registration itself, on a bare app
try:
    from flask import Flask
    _app = Flask("desk_test")
    ok = desk.register(_app, lambda s: s == "k", LEADS, CONV, IG, send_email=None, manual_keys=lambda: {"14075550103"})
    rules = {r.rule for r in _app.url_map.iter_rules()}
    check("flask.routes", ok and {"/desk/", "/desk/login", "/desk/auth", "/desk/logout", "/desk/api/board", "/desk/api/inbox",
                                 "/desk/api/search", "/desk/api/lead/<path:key>", "/desk/static/<path:fname>"} <= rules, str(sorted(rules)))
    c = _app.test_client()
    r = c.get("/desk/api/board")
    check("flask.401_without_auth", r.status_code == 401)
    r = c.get("/desk/api/board?secret=k")
    j = r.get_json()
    check("flask.board_with_secret", r.status_code == 200 and j["ok"] and j["total"] == 16 and j["awaiting_reply"] == 0)
    r = c.get("/desk/api/lead/whatsapp:+14075550103?secret=k")
    check("flask.lead", r.status_code == 200 and r.get_json()["lead"]["name"] == "Ana Souza" and "michael" in r.get_json()["lead"]["flags"])
    r = c.get("/desk/api/lead/nobody?secret=k")
    check("flask.lead_404", r.status_code == 404)
    r = c.get("/desk/api/search?q=souza&secret=k")
    check("flask.search", r.status_code == 200 and r.get_json()["rows"][0]["name"] == "Ana Souza")
    r = c.get("/desk/")
    check("flask.door", r.status_code == 200 and b"Email me the link" in r.data)
    r = c.get("/desk/?secret=k")
    check("flask.page_with_secret", r.status_code == 200 and b"MWM Desk" in r.data and b"desk.js" in r.data)
    r = c.get("/desk")
    check("flask.redirect", r.status_code in (301, 302, 308) and r.headers["Location"].endswith("/desk/"))
    r = c.post("/desk/login", data={"email": "x@gmail.com"})
    check("flask.login_same_answer", r.status_code == 200 and b"on its way" in r.data)
    r = c.get("/desk/static/desk.css")
    check("flask.static", r.status_code == 200 and b"--accent" in r.data)
except ImportError:
    # the Mac gate has no Flask; the pure model and the static wiring are the
    # gate there, and the routes are proven live right after the deploy
    print("note: flask not installed here — route checks skipped (proven live after deploy)")
except Exception as e:
    check("flask.registration", False, repr(e))

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch269.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #269 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("269: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE270 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
