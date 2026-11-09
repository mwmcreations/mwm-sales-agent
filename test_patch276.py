#!/usr/bin/env python3
"""GATE for PATCH #276 — what Vicente's report exposed: the post-visit chain no
longer stops on the visit's own booking; a report lands on both twin records;
the Desk counts a twinned visit once. Prints GATE276 PASS/FAIL."""
import os
import re
import subprocess
import sys
import types
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lead_chase as lc  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


TZ = pytz.timezone("America/New_York")
T0 = TZ.localize(datetime(2026, 11, 8, 22, 56))

# ── 1. the post-visit chain and the booking ─────────────────────────────────
pv = lc.arm(T0, channels=[lc.EMAIL, lc.SMS], verdict="post_visit", kind=lc.KIND_POST_VISIT)
vicente = {"booked": True, "booked_at": "2026-10-23T11:44:09.272638-04:00", "event_id": "rdo4e8", "last_outcome": "follow_up"}
check("pv.visit_booking_does_not_stop", lc.stop_reason(pv, vicente, T0 + timedelta(minutes=5)) == "", lc.stop_reason(pv, vicente, T0 + timedelta(minutes=5)))
check("pv.e1_due", lc.next_step(pv, T0 + timedelta(hours=2, minutes=1)) == ("e1", "email", 1))
rebooked = dict(vicente, booked_at=(T0 + timedelta(days=1)).isoformat())
check("pv.new_booking_stops", lc.stop_reason(pv, rebooked, T0 + timedelta(days=1, hours=1)) == lc.STOP_BOOKED)
naive_rebooked = dict(vicente, booked_at=(T0 + timedelta(days=1)).replace(tzinfo=None).isoformat())
check("pv.naive_new_booking_stops", lc.stop_reason(pv, naive_rebooked, T0 + timedelta(days=1, hours=1)) == lc.STOP_BOOKED)
check("pv.booked_no_date_continues", lc.stop_reason(pv, {"booked": True}, T0 + timedelta(hours=1)) == "")
check("pv.reply_still_stops", lc.stop_reason(pv, vicente, T0 + timedelta(hours=3), last_inbound=T0 + timedelta(hours=3)) == lc.STOP_REPLIED)
check("pv.client_still_stops", lc.stop_reason(pv, dict(vicente, paid_at="x"), T0 + timedelta(hours=1)) == lc.STOP_CLIENT)
check("pv.disq_still_stops", lc.stop_reason(pv, dict(vicente, disqualified={"why": "x"}), T0 + timedelta(hours=1)) == lc.STOP_DISQUALIFIED)
for kind in (lc.KIND_FORM, lc.KIND_STUDIO_HOUR, lc.KIND_IG):
    st = lc.arm(T0, channels=[lc.EMAIL], verdict="x", kind=kind)
    check(f"other.{kind}.booked_stops", lc.stop_reason(st, vicente, T0 + timedelta(hours=1)) == lc.STOP_BOOKED)
    check(f"other.{kind}.booked_nodate_stops", lc.stop_reason(st, {"booked": True}, T0 + timedelta(hours=1)) == lc.STOP_BOOKED)

# ── 2. the Desk counts a twinned visit once ─────────────────────────────────
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

NOW = TZ.localize(datetime(2026, 11, 9, 9, 0))
D = lambda d: (NOW + timedelta(days=d)).isoformat()  # noqa: E731
FORM = "whatsapp:+14077772350"
WA = "whatsapp:+14073614743"
LEADS = {
    FORM: {"name": "VICENTE ORELLANA", "phone": "+14077772350", "email": "v@x.com", "source": "Meta Lead Ad", "meta_lead_ad": True,
           "lead_form_at": D(-19), "event_id": "evt_v", "booked_at": D(-17), "linked_wa_key": WA,
           "last_outcome": "follow_up", "last_outcome_at": D(-0.4), "last_message_time": D(-0.4)},
    WA: {"name": "Vicente Orellana", "phone": "+14073614743", "email": "v@x.com", "source": "WhatsApp", "first_contact_time": D(-19),
         "event_id": "evt_v", "booked_at": D(-17), "linked_form_key": FORM, "last_message_time": D(-7)},
    "whatsapp:+14075550199": {"name": "Pastiche Graham", "phone": "+14075550199", "source": "Instagram", "first_contact_time": D(-50),
                              "event_id": "evt_p", "booked_at": D(-43), "last_message_time": D(-43)},
}
CONV = {WA: [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hi Vicente"}]}
v = desk.visits(LEADS, CONV, {}, now=NOW)
check("desk.recent_once", [c["name"] for c in v["recent"]] == ["VICENTE ORELLANA"], v["recent"])
check("desk.needs_without_twin", [c["name"] for c in v["needs_outcome"]] == ["Pastiche Graham"], [c["name"] for c in v["needs_outcome"]])
check("desk.losers", desk.twin_losers(desk._views(LEADS, CONV, {}, now=NOW)) == {WA})
# no outcome anywhere: the record with the conversation represents the visit
L2 = {k: dict(r) for k, r in LEADS.items()}
L2[FORM].pop("last_outcome"); L2[FORM].pop("last_outcome_at")
v2 = desk.visits(L2, CONV, {}, now=NOW)
check("desk.needs_once_conversation_wins", sorted(c["key"] for c in v2["needs_outcome"]) == sorted([WA, "whatsapp:+14075550199"]), [c["key"] for c in v2["needs_outcome"]])
# after #276's mirror both twins carry the outcome: still one card, the form one (first with outcome) or either — exactly one
L3 = {k: dict(r) for k, r in LEADS.items()}
L3[WA]["last_outcome"] = "follow_up"; L3[WA]["last_outcome_at"] = L3[FORM]["last_outcome_at"]; L3[WA]["outcome_via_twin"] = FORM
v3 = desk.visits(L3, CONV, {}, now=NOW)
check("desk.mirrored_once", len(v3["recent"]) == 1 and not v3["needs_outcome"] or [c["name"] for c in v3["needs_outcome"]] == ["Pastiche Graham"], (v3["recent"], v3["needs_outcome"]))
check("desk.mirrored_recent_one", len(v3["recent"]) == 1, v3["recent"])
st = desk.stats(L3, CONV, {}, days=30, now=NOW)
check("desk.stats_visit_once", st["events"]["visits"] == 1 and st["events"]["booked"] == 1, st["events"])   # Vicente once; Pastiche out of window
st2 = desk.stats(L3, CONV, {}, days=30, now=NOW - timedelta(days=16))
check("desk.stats_booking_once", st2["events"]["booked"] == 2, st2["events"])   # Vicente once + Pastiche, not 3
check("desk.no_event_untouched", desk.twin_losers([{"key": "a", "booking": None}, {"key": "b", "booking": {}}]) == set())

# ── 3. app.py pins ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
i = SRC.index("# PATCH #276 — the same visit lives on both numbers")
check("app.mirror_after_outcome", SRC.rfind('rec["last_outcome_at"] = now.isoformat()', 0, i) > 0 and i < SRC.index("# PATCH #251 — the visit happened"))
seg = SRC[i:i + 900]
check("app.mirror_both_links", 'for _tk in (rec.get("linked_wa_key"), rec.get("linked_form_key")):' in seg
      and '_tw["last_outcome"] = outcome' in seg and '_tw["outcome_via_twin"] = key' in seg and "lead_data[_tk] = _tw" in seg)
check("app.mirror_not_self", "_tk != key" in seg)
check("app.mirror_guarded", "except Exception as _twx:" in seg and '_report_error("p276.twin_outcome", _twx, key)' in seg)
check("app.chain_arms_once", SRC.count('st = _chase.arm(now, channels=chans, verdict="post_visit", kind=_chase.KIND_POST_VISIT)') == 1)
check("app.chase_pass_booked_line_intact", "rec_v = dict(rec, booked=True) if _chase_booked(rec) else rec" in SRC)
LCS = open(os.path.join(HERE, "lead_chase.py"), encoding="utf-8").read()
check("lc.rule_present", 'if state.get("kind") != KIND_POST_VISIT:\n            return STOP_BOOKED' in LCS and "_bat > _arm + timedelta(minutes=1)" in LCS)
DS = open(os.path.join(HERE, "desk.py"), encoding="utf-8").read()
check("desk.helper_used_twice", DS.count("_losers = twin_losers(views)") == 2 and "def twin_losers(views):" in DS)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch275.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #275 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("275: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE276 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
