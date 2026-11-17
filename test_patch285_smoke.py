#!/usr/bin/env python3
"""Lift the #285 block out of app.py and run _quiet_pass against the real desk
module with a fake board: dark (nothing sent, the would-list filled), then live
(one email, one SMS, one escalation, one close), then a reply resets the count.
Lives in the repo as test_patch285_smoke.py and runs from test_patch285 (Patch #285)."""
import os
import sys
import threading
from datetime import datetime, timedelta

import pytz

TREE = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TREE)
import desk  # noqa: E402
import quiet_lead as _ql  # noqa: E402
import studio_visit as _sv  # noqa: E402

SRC = open(os.path.join(TREE, "app.py"), encoding="utf-8").read()
blk = SRC[SRC.index("# PATCH #285 — THE QUIET-LEAD RAIL"):SRC.index("def _lead_chase_loop():")]
blk = blk[:blk.index('@app.route("/admin/quiet-rail"')]          # the route needs Flask; not here

ET = pytz.timezone("US/Eastern")
NOW = ET.localize(datetime(2026, 11, 17, 10, 0, 0))


def d(days):
    return (NOW - timedelta(days=days)).isoformat()


class Tally:
    def __init__(self):
        self.rows = []

    def bump(self, *a):
        self.rows.append(a)


SENT = {"email": [], "sms": [], "slack": [], "alert": [], "errors": []}
SWITCH = {"quiet_rail_live": False}


class OA:
    @staticmethod
    def alert(kind, text):
        SENT["alert"].append((kind, text))
        return {"sms": "sent"}


lead_data = {
    # Replied 6 days ago, has email + consent → touch 1 by SMS
    "whatsapp:+14073614743": {"name": "Vicente Orellana", "business": "Owning Your House", "email": "vic@example.com",
                              "phone": "+14073614743", "last_message_time": d(6),
                              "chase": {"armed_at": d(20), "stopped": "replied", "stopped_at": d(19), "sent": {"e1": d(19)}}},
    # Replied 11 days ago, email only → touch 1 (email) + escalate
    "whatsapp:+13127237582": {"name": "Renay PeGee", "business": "", "email": "renay@example.com", "phone": "+13127237582",
                              "last_message_time": d(11), "last_inbound_at": d(11),
                              "chase": {"armed_at": d(15), "stopped": "replied", "stopped_at": d(14), "sent": {}}},
    # Replied 2 days ago → on the rail, nothing due
    "whatsapp:+14079820323": {"name": "McBride", "business": "Law", "email": "mc@example.com", "phone": "+14079820323",
                              "last_message_time": d(2), "last_inbound_at": d(2), "chase": {"armed_at": d(3), "stopped": "replied", "stopped_at": d(2)}},
    # Client → never
    "whatsapp:+10000000001": {"name": "Paid Person", "email": "p@example.com", "phone": "+10000000001",
                              "last_message_time": d(6), "paid_at": d(5)},
    # Booked ahead → never
    "whatsapp:+10000000002": {"name": "Coming Soon", "email": "c@example.com", "phone": "+10000000002",
                              "last_message_time": d(6), "event_id": "ev1", "booked": True, "booked_at": d(6),
                              "booked_slot_id": (NOW + timedelta(days=2)).isoformat()},
    # Replied 40 days ago → Paused → re-engagement list, not this rail
    "whatsapp:+10000000003": {"name": "Old Quiet", "email": "o@example.com", "phone": "+10000000003",
                              "last_message_time": d(40), "chase": {"armed_at": d(45), "stopped": "replied", "stopped_at": d(44)}},
    # Replied 25 days ago with 4 touches already → close
    "whatsapp:+10000000004": {"name": "Four Touches", "email": "f@example.com", "phone": "+10000000004",
                              "last_message_time": d(25), "last_inbound_at": d(25), "chase": {"armed_at": d(30), "stopped": "replied", "stopped_at": d(29)},
                              "quiet_rail": {"armed_at": d(20), "since": d(25), "escalated_at": d(15), "stopped": "", "stopped_at": "",
                                             "touches": [{"n": i, "at": d(25 - 5 * i), "channel": "email"} for i in (1, 2, 3, 4)]}},
    # Visited, pitched → the studio rail's, not this one
    "whatsapp:+10000000005": {"name": "Pitched Person", "email": "pp@example.com", "phone": "+10000000005",
                              "last_message_time": d(8), "event_id": "ev2", "booked": True, "booked_at": d(9),
                              "last_outcome": "studio_package_pitched", "last_outcome_at": d(7),
                              "studio_pitch": {"done": False}},
    # test record → skipped
    "whatsapp:+10000000006": {"name": "Test Lead", "email": "t@example.com", "phone": "+10000000006",
                              "last_message_time": d(6), "test_lead": True, "last_inbound_at": d(6),
                              "chase": {"armed_at": d(8), "stopped": "replied"}},
}
conversation_history = {"whatsapp:+14073614743": [{"role": "user", "content": "ok", "at": d(6)}]}
ig_conversation_history = {}

G = {
    "os": os, "threading": threading, "pytz": pytz, "datetime": datetime, "timedelta": timedelta,
    "TIMEZONE": "US/Eastern", "lead_data": lead_data, "conversation_history": conversation_history,
    "ig_conversation_history": ig_conversation_history, "_desk": desk, "_desk_manual_keys": lambda: set(),
    "_switch_on": lambda n: SWITCH.get(n, False), "_sms_gates": lambda e, k: ((True, "ok") if e == "+14073614743" else (False, "no_consent")),
    "SMS_KIND_MARKETING": "marketing", "_chase_is_client": lambda k: False,
    "email_is_suppressed": lambda e: (False, ""), "_chase_mask_key": lambda k: str(k)[-4:],
    "_chase_mask": lambda e: e[:2] + "…", "_TALLY": Tally(),
    "_post_to_slack_async": lambda ch, text, **kw: SENT["slack"].append((ch, text)),
    "SLACK_SUSAN_CHANNEL": "susan", "SLACK_MATT_CHANNEL": "matt", "SLACK_DEV_CHANNEL": "dev",
    "_email_send": lambda to, subj, html, **kw: (SENT["email"].append((to, subj)) or {"ok": True, "message_id": "m1"}),
    "email_ok": lambda r: bool(r.get("ok")), "_sv": _sv,
    "_sms_body_that_fits": lambda builders: builders[0](),
    "_send_sms": lambda e164, body, kind=None: (SENT["sms"].append((e164, body)) or {"ok": True, "sid": "s1"}),
    "_operator_alert": OA, "_report_error": lambda *a, **k: SENT["errors"].append(a),
    "print": lambda *a, **k: None, "_ql": _ql,
}
exec(compile(blk, "block285", "exec"), G)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:400]}")


# ── dark pass ──
out = G["_quiet_pass"](NOW)
check("dark.no_sends", not SENT["email"] and not SENT["sms"] and not SENT["alert"], SENT)
check("dark.on_rail_four", out["on_rail"] == 4, out)             # Vicente, Renay, McBride, Four Touches (closed this pass)
would = [w for w in out["would"] if "touch" in w]
check("dark.two_due", out["due"] == 2 and len(would) == 2, out)
byname = {w["name"]: w for w in would}
check("dark.vicente_sms_t1", byname.get("Vicente Orellana", {}).get("channel") == "sms" and byname["Vicente Orellana"]["touch"] == 1
      and byname["Vicente Orellana"]["held"] == "switch off", byname)
check("dark.renay_email_t1_no_consent", byname.get("Renay PeGee", {}).get("channel") == "email" and byname["Renay PeGee"]["sms"] == "no_consent", byname)
check("dark.copy_shown", byname["Vicente Orellana"]["copy"].startswith("Hi Vicente, "), byname["Vicente Orellana"]["copy"])
esc = [w for w in out["would"] if "escalate" in w]
check("dark.escalation_listed_not_sent", len(esc) == 1 and any("Renay" in n for n in esc[0]["escalate"]), esc)
check("dark.close_counted", out["closed"] == 1 and lead_data["whatsapp:+10000000004"]["quiet_rail"]["stopped"] == "quiet 20d", out)
sk = out["skipped"]
off = out["off_rail"]
check("dark.client_off", off.get("Client") == 1, off)
check("dark.booked_off", off.get("Booked") == 1, off)
check("dark.paused_off", off.get("Paused") == 1, off)
check("dark.pitched_skipped", any("studio pitch" in k for k in sk) or any("visit outcome" in k for k in sk), sk)
check("dark.test_skipped", "quiet_rail" not in lead_data["whatsapp:+10000000006"])
check("dark.states_written", isinstance(lead_data["whatsapp:+14073614743"].get("quiet_rail"), dict)
      and lead_data["whatsapp:+14073614743"]["quiet_rail"]["since"] == d(6))
check("dark.no_touch_recorded", lead_data["whatsapp:+14073614743"]["quiet_rail"]["touches"] == [])
check("dark.no_errors", not SENT["errors"], SENT["errors"])

# ── live pass ──
SWITCH["quiet_rail_live"] = True
G["_QUIET_LAST"]["sent_today"] = 0
out2 = G["_quiet_pass"](NOW)
check("live.sent_two", out2["sent"] == 2 and len(SENT["sms"]) == 1 and len(SENT["email"]) == 1, (out2, SENT))
check("live.sms_to_vicente", SENT["sms"][0][0] == "+14073614743" and SENT["sms"][0][1].startswith("Hi Vicente, Michael here"), SENT["sms"])
check("live.email_to_renay", SENT["email"][0][0] == "renay@example.com" and SENT["email"][0][1] == "Still interested, Renay?", SENT["email"])
check("live.touch_recorded", lead_data["whatsapp:+14073614743"]["quiet_rail"]["touches"][0]["channel"] == "sms")
check("live.escalated_once", out2["escalated"] == 1 and len(SENT["alert"]) == 1 and SENT["alert"][0][0] == "quiet"
      and "Renay PeGee (11d)" in SENT["alert"][0][1], SENT["alert"])
check("live.escalation_recorded", lead_data["whatsapp:+13127237582"]["quiet_rail"]["escalated_at"] == NOW.isoformat())
check("live.susan_told", sum(1 for ch, t in SENT["slack"] if ch == "susan" and "quiet rail touch" in t) == 2, SENT["slack"])
check("live.matt_told", any(ch == "matt" for ch, t in SENT["slack"]), SENT["slack"])
check("live.no_errors", not SENT["errors"], SENT["errors"])

# ── same hour again: nothing more ──
out3 = G["_quiet_pass"](NOW + timedelta(minutes=5))
check("live.idempotent_same_hour", out3["sent"] == 0 and out3["escalated"] == 0 and not out3["would"], out3)

# ── Vicente replies → reset ──
lead_data["whatsapp:+14073614743"]["last_message_time"] = (NOW + timedelta(hours=1)).isoformat()
out4 = G["_quiet_pass"](NOW + timedelta(hours=2))
st = lead_data["whatsapp:+14073614743"]["quiet_rail"]
check("reset.after_reply", st["touches"] == [] and st["since"] == (NOW + timedelta(hours=1)).isoformat(), st)

# ── window + cap ──
G["_QUIET_LAST"]["sent_today"] = 0
SENT["sms"].clear(); SENT["email"].clear()
lead_data["whatsapp:+13127237582"]["quiet_rail"] = {"armed_at": d(1), "since": d(16), "touches": [{"n": 1, "at": d(10), "channel": "email"},
                                                    {"n": 2, "at": d(5), "channel": "email"}], "escalated_at": d(5), "stopped": "", "stopped_at": ""}
out5 = G["_quiet_pass"](ET.localize(datetime(2026, 11, 17, 19, 0)))
held = [w for w in out5["would"] if w.get("name") == "Renay PeGee"]
check("window.held_at_19h", held and held[0]["held"] == "outside 8–18 ET" and not SENT["email"], (out5, SENT["email"]))
G["_QUIET_LAST"]["sent_today"] = G["QUIET_RAIL_DAILY_CAP"]
G["_QUIET_LAST"]["day"] = "2026-11-18"
out6 = G["_quiet_pass"](ET.localize(datetime(2026, 11, 18, 10, 0)))
held = [w for w in out6["would"] if w.get("name") == "Renay PeGee"]
check("cap.held", held and held[0]["held"] == "daily cap", out6)

# ── a refused SMS road is remembered ──
G["_QUIET_LAST"]["sent_today"] = 0
G["_send_sms"] = lambda e164, body, kind=None: {"ok": False, "reason": "no_consent_marketing"}
lead_data["whatsapp:+14073614743"]["last_message_time"] = d(6)
lead_data["whatsapp:+14073614743"]["quiet_rail"] = None
del lead_data["whatsapp:+14073614743"]["quiet_rail"]
conversation_history["whatsapp:+14073614743"] = []
out7 = G["_quiet_pass"](ET.localize(datetime(2026, 11, 18, 11, 0)))
st = lead_data["whatsapp:+14073614743"]["quiet_rail"]
check("refused.sms_road_closed", st.get("no_sms") == "no_consent_marketing" and st["touches"] == [], st)
out8 = G["_quiet_pass"](ET.localize(datetime(2026, 11, 18, 12, 0)))
check("refused.next_pass_email", any(e[0] == "vic@example.com" for e in SENT["email"]), SENT["email"])

print(f"smoke: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
