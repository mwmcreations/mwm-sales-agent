"""PATCH #271 gate — MWM Desk, slice 2 (act). The actions change the record
the rails already read and leave a line in desk_log; a hand-set stage wins
only where the facts are soft; sends pick the lead's own channel; new
conversation turns carry a clock and the model never sees it; the Desk
session opens the Daily Event Report. Then the #270 gate (→ 269 chain)."""
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

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


NOW = datetime(2026, 11, 8, 1, 0)
H = lambda h: (NOW - timedelta(hours=h)).isoformat()   # noqa: E731
D = lambda d: (NOW - timedelta(days=d)).isoformat()    # noqa: E731

# ── a hand-set stage ────────────────────────────────────────────────────────
rec = {"name": "Ana Souza", "phone": "+14075550103", "last_inbound_at": H(1),
       "chase": {"kind": "form", "armed_at": H(3), "sent": {"d0": H(3)}, "stopped": ""}}
turns = [{"role": "lead", "text": "hi", "at": ""}]
check("stage.before", desk.stage_of(rec, turns, now=NOW) == "Replied")
r = desk.apply_stage(rec, "paused", "michael", NOW, reason="on vacation", turns=turns)
check("stage.paused", r == {"ok": True, "before": "Replied", "after": "Paused"} and rec["desk_stage"]["stage"] == "Paused"
      and rec["desk_stage"]["by"] == "michael" and rec["desk_stage"]["reason"] == "on vacation"
      and rec["chase"]["stopped"] == "manual_paused", str(r) + str(rec.get("desk_stage")))
check("stage.logged", rec["desk_log"][-1]["kind"] == "stage" and "Replied → Paused" in rec["desk_log"][-1]["text"] and rec["desk_log"][-1]["by"] == "michael")
check("stage.view_reads_it", desk.stage_of(rec, turns, now=NOW) == "Paused")
r = desk.apply_stage(rec, "Reopen", "michael", NOW, turns=turns)
check("stage.reopen", r["ok"] and r["after"] == "Replied" and "desk_stage" not in rec and rec["chase"]["stopped"] == "")
r = desk.apply_stage(rec, "Lost", "michael", NOW, turns=turns)
check("stage.lost", r["after"] == "Lost" and rec["chase"]["stopped"] == "manual_lost" and not rec.get("do_not_contact"))
check("stage.no_hand_booking", desk.apply_stage(rec, "Booked", "michael", NOW)["ok"] is False
      and desk.apply_stage(rec, "Client", "michael", NOW)["ok"] is False and desk.apply_stage(rec, "", "michael", NOW)["ok"] is False)
# a booking made AFTER the hand-set Lost un-parks it; one made before does not
later = dict(rec, event_id="evt", booked_at=(NOW + timedelta(hours=2)).isoformat())
check("stage.newer_fact_wins", desk.stage_of(later, turns, now=NOW + timedelta(hours=3)) == "Booked")
earlier = dict(rec, event_id="evt", booked_at=D(2))
check("stage.older_fact_loses", desk.stage_of(earlier, turns, now=NOW) == "Lost")
check("stage.client_fact_old_but_hand_newer", desk.stage_of({"paid_at": D(5), "desk_stage": {"stage": "Lost", "at": H(1)}}, now=NOW) == "Lost"
      and desk.stage_of({"paid_at": H(1), "desk_stage": {"stage": "Lost", "at": D(5)}}, now=NOW) == "Client")
check("stage.override_ignores_bad_value", desk.stage_of({"last_inbound_at": H(1), "desk_stage": {"stage": "Booked", "at": H(0)}}, now=NOW) == "Replied")

# ── notes, chase, dnc ───────────────────────────────────────────────────────
rec2 = {"name": "Pedro", "phone": "+14075550104", "notes": "old free text"}
r = desk.apply_note(rec2, "  Wants the  podcast set  ", "michael", NOW)
check("note.append", r["ok"] and r["notes"] == 2 and rec2["notes"][0] == "old free text" and rec2["notes"][1]["text"] == "Wants the podcast set"
      and rec2["notes"][1]["by"] == "michael" and rec2["desk_log"][-1]["kind"] == "note")
check("note.empty", desk.apply_note(rec2, "   ", "michael", NOW)["ok"] is False)
rec3 = {"name": "Marcus", "phone": "+14075550102", "chase": {"kind": "form", "armed_at": H(4), "sent": {}, "stopped": ""}}
check("chase.pause", desk.apply_chase(rec3, "pause", "michael", NOW) == {"ok": True, "stopped": "manual", "changed": True} and rec3["chase"]["stopped"] == "manual")
check("chase.pause_twice", desk.apply_chase(rec3, "pause", "michael", NOW)["changed"] is False)
check("chase.resume", desk.apply_chase(rec3, "resume", "michael", NOW)["stopped"] == "" and rec3["chase"]["stopped"] == "")
rec3["chase"]["stopped"] = "disqualified"
check("chase.cannot_resume_a_verdict", desk.apply_chase(rec3, "resume", "michael", NOW)["ok"] is False and rec3["chase"]["stopped"] == "disqualified")
check("chase.none", desk.apply_chase({"name": "x"}, "pause", "michael", NOW)["ok"] is False)
check("chase.bad_action", desk.apply_chase(rec3, "dance", "michael", NOW)["ok"] is False)
rec4 = {"name": "Spam", "phone": "+14075550108", "last_inbound_at": H(2), "chase": {"kind": "form", "armed_at": H(4), "sent": {}, "stopped": ""}}
r = desk.apply_dnc(rec4, True, "michael", NOW)
check("dnc.set", r == {"ok": True, "do_not_contact": True} and rec4["do_not_contact"] is True and rec4["dnc_at"] == NOW.isoformat()
      and rec4["chase"]["stopped"] == "dnc" and desk.stage_of(rec4, now=NOW) == "Lost")
r = desk.apply_dnc(rec4, False, "michael", NOW)
check("dnc.lift", rec4["do_not_contact"] is False and "dnc_at" not in rec4 and rec4["desk_log"][-1]["text"].endswith("lifted"))
_capped = {"name": "x"}
for _i in range(70):
    desk.apply_note(_capped, f"n{_i}", "m", NOW)
check("log.capped", len(_capped["desk_log"]) == desk.LOG_MAX and _capped["desk_log"][-1]["text"] == "n69" and len(_capped["notes"]) == 70)

# ── send plan ───────────────────────────────────────────────────────────────
check("send.whatsapp", desk.send_plan("whatsapp:+14075550103", {"phone": "+14075550103"}, "hi there") ==
      {"ok": True, "channel": "whatsapp", "to": "whatsapp:+14075550103", "as": "maya", "text": "hi there"})
check("send.instagram", desk.send_plan("instagram:1789", {}, "hi", "michael") == {"ok": True, "channel": "instagram", "to": "1789", "as": "michael", "text": "hi"})
check("send.sms_lead", desk.send_plan("whatsapp:+14075550109", {"channel": "sms"}, "hi")["channel"] == "sms"
      and desk.send_plan("whatsapp:+14075550109", {"channel": "sms"}, "hi")["to"] == "+14075550109")
check("send.unreachable_wa_falls_to_sms", desk.send_plan("whatsapp:+14075550109", {"wa_unreachable": True}, "hi")["channel"] == "sms")
check("send.phone_from_record", desk.send_plan("email:x@y.z", {"phone": "(407) 555-0110"}, "hi")["to"] == "whatsapp:+14075550110")
check("send.errors", desk.send_plan("email:x@y.z", {}, "hi")["ok"] is False and desk.send_plan("whatsapp:+14075550103", {}, "  ")["ok"] is False
      and desk.send_plan("whatsapp:+14075550103", {}, "x" * 4001)["ok"] is False)
check("send.as_normalised", desk.send_plan("instagram:1", {}, "hi", "MICHAEL")["as"] == "michael" and desk.send_plan("instagram:1", {}, "hi", "robot")["as"] == "maya")

# ── turns with a clock; the model never sees it ────────────────────────────
t = desk.turn("assistant", "hello", by="michael", now=NOW)
check("turn.shape", t == {"role": "assistant", "content": "hello", "at": NOW.isoformat(), "by": "michael"})
check("turn.no_by", "by" not in desk.turn("user", "hi", now=NOW))
check("api_safe", desk.api_safe([t, {"role": "user", "content": [{"type": "text", "text": "x"}], "at": "z"}, "junk"]) ==
      [{"role": "assistant", "content": "hello"}, {"role": "user", "content": [{"type": "text", "text": "x"}]}, "junk"])
tt = desk.turns_for("whatsapp:+14075550103", {}, {"whatsapp:+14075550103": [
    {"role": "user", "content": "hi", "at": H(2)}, {"role": "assistant", "content": "Maya here"},
    {"role": "assistant", "content": "Michael here", "at": H(1), "by": "michael"}]}, {})
check("turns.who", [x["role"] for x in tt] == ["lead", "maya", "michael"] and tt[2]["at"] == H(1) and tt[1]["at"] == "")
check("outbound.counts_michael", desk.has_outbound({}, [{"role": "michael", "text": "x", "at": ""}]))
v = desk.lead_view("whatsapp:+14075550103", {"name": "Ana", "phone": "+14075550103", "desk_log": [{"kind": "note", "text": "n", "by": "michael", "at": H(1)}],
                                            "manual_until": (NOW + timedelta(hours=1)).isoformat()}, tt, now=NOW)
check("view.slice2_fields", v["desk_log"][0]["kind"] == "note" and v["manual_until"] and v["last_turn_role"] == "michael")
tl = desk.timeline(v, {"name": "Ana", "desk_log": v["desk_log"]}, tt)
check("timeline.log_events", any(e["kind"] == "note" and e.get("by") == "michael" for e in tl["events"]))

# ── app wiring (static) ─────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.turn_helper", "def _turn(role, content, by=None):" in SRC and "def _api_safe(messages):" in SRC)
check("app.api_safe_at_call", 'messages=globals().get("_api_safe", lambda _m: _m)(messages)' in SRC)
check("app.final_reply_stamped", 'messages.append((globals().get("_turn") or (lambda r, c, by=None: {"role": r, "content": c}))(' in SRC
      and '"assistant", final_text))   # PATCH #271' in SRC)
stamped = len(re.findall(r'(?:ig_)?conversation_history(?:\[[^\]\n]+\]|\.setdefault\([^)\n]*\))\.append\(_turn\("(?:user|assistant)", ', SRC))
bare = len(re.findall(r'(?:ig_)?conversation_history(?:\[[^\]\n]+\]|\.setdefault\([^)\n]*\))\.append\(\{"role": "(?:user|assistant)"', SRC))
check("app.appends_stamped", stamped >= 8 and bare == 0, f"stamped={stamped} bare={bare}")
check("app.normalize_keeps_clock", 'for _k in ("at", "by"):' in SRC)
check("app.desk_auth_helper", "def _desk_auth_ok():" in SRC and SRC.count("and not _desk_auth_ok():") == 2)
check("app.actions_wired", "def _desk_actions():" in SRC and "actions=_desk_actions())" in SRC
      and '"send_sms": lambda to, body: _send_sms(to, body, kind=SMS_KIND_TRANSACTIONAL)' in SRC
      and '"send_whatsapp": lambda to, body: send_whatsapp_meta(to, body=body)' in SRC
      and '"send_instagram": lambda to, body: send_instagram_dm(to, body=body)' in SRC
      and '_pgd.save_state("manual_mode", _manual_mode)' in SRC and '_pgd.save_state(f"do_not_sms:+{d}", bool(on))' in SRC)
check("app.turn_defined_before_use", SRC.index("def _turn(role, content, by=None):") < SRC.index('.append(_turn("'))
JS = open(os.path.join(HERE, "desk_static/desk.js"), encoding="utf-8").read()
check("js.actions", all(x in JS for x in ('leadPath("note")', 'leadPath("stage")', 'leadPath("chase")', 'leadPath("takeover")', 'leadPath("send")',
                                           '/meeting-report/meetings?range=today', '/meeting-report/submit', 'data-act="report"', "Send as Michael")))
check("js.no_slice1_placeholder", "arrive in slice 2" not in JS)
HTML = open(os.path.join(HERE, "desk_static/desk.html"), encoding="utf-8").read()
check("html.sheet_today", 'id="sheet"' in HTML and 'id="today"' in HTML)

# ── the routes, where Flask is installed ───────────────────────────────────
try:
    from flask import Flask
    LEADS = {"whatsapp:+14075550103": {"name": "Ana Souza", "phone": "+14075550103", "last_inbound_at": H(1),
                                        "chase": {"kind": "form", "armed_at": H(3), "sent": {}, "stopped": ""}},
             "instagram:1789": {"name": "IG Lead", "last_message_time": H(2)},
             "whatsapp:+14075550108": {"name": "Blocked", "phone": "+14075550108", "do_not_contact": True}}
    CONV = {"whatsapp:+14075550103": [{"role": "user", "content": "hi"}]}
    IGC = {"instagram:1789": [{"role": "user", "content": "yo"}]}
    calls = {"wa": [], "ig": [], "sms": [], "pipe": [], "manual": {}, "dnc": []}
    acts = {
        "pipeline_event": lambda et, **kw: calls["pipe"].append((et, kw)),
        "send_whatsapp": lambda to, body: calls["wa"].append((to, body)) or {"messages": [{"id": "wamid.x"}]},
        "send_instagram": lambda to, body: calls["ig"].append((to, body)) or {"message_id": "m1"},
        "send_sms": lambda to, body: calls["sms"].append((to, body)) or {"ok": False, "reason": "outside_window"},
        "manual_set": lambda d, hours: calls["manual"].__setitem__(d, time.time() + hours * 3600) or calls["manual"][d],
        "manual_clear": lambda d: calls["manual"].pop(d, None),
        "dnc_sms": lambda d, on: calls["dnc"].append((d, on)),
        "save": lambda: None,
    }
    _app = Flask("desk_test2")
    desk.register(_app, lambda s: s == "k", LEADS, CONV, IGC, manual_keys=lambda: {d for d, u in calls["manual"].items() if u > time.time()}, actions=acts)
    c = _app.test_client()
    K = "whatsapp:+14075550103"
    r = c.post(f"/desk/api/lead/{K}/note", json={"text": "call back Tuesday"})
    check("route.note_needs_auth", r.status_code == 401)
    r = c.post(f"/desk/api/lead/{K}/note?secret=k", json={"text": "call back Tuesday"})
    check("route.note", r.status_code == 200 and r.get_json()["lead"]["notes"][-1]["text"] == "call back Tuesday" and r.get_json()["lead"]["notes"][-1]["by"] == "agent")
    r = c.post(f"/desk/api/lead/{K}/stage?secret=k", json={"stage": "Paused", "reason": "asked to wait"})
    j = r.get_json()
    check("route.stage", r.status_code == 200 and j["after"] == "Paused" and j["lead"]["stage"] == "Paused" and calls["pipe"][-1][0] == "STAGE_CHANGE"
          and calls["pipe"][-1][1]["old_stage"] == "Replied" and calls["pipe"][-1][1]["new_stage"] == "Paused" and "asked to wait" in calls["pipe"][-1][1]["context"])
    r = c.post(f"/desk/api/lead/{K}/stage?secret=k", json={"stage": "Booked"})
    check("route.stage_refused", r.status_code == 400)
    r = c.post(f"/desk/api/lead/{K}/stage?secret=k", json={"stage": "Reopen"})
    check("route.reopen", r.status_code == 200 and r.get_json()["lead"]["stage"] == "Replied")
    r = c.post(f"/desk/api/lead/{K}/chase?secret=k", json={"action": "pause"})
    check("route.chase", r.status_code == 200 and r.get_json()["lead"]["chase"]["stopped"] == "manual")
    r = c.post(f"/desk/api/lead/{K}/takeover?secret=k", json={"action": "take", "hours": 2})
    j = r.get_json()
    check("route.takeover", r.status_code == 200 and "14075550103" in calls["manual"] and "michael" in j["lead"]["flags"] and j["lead"]["manual_until"])
    r = c.post(f"/desk/api/lead/{K}/send?secret=k", json={"text": "Hi Ana, Michael here", "as": "michael"})
    j = r.get_json()
    check("route.send_whatsapp", r.status_code == 200 and calls["wa"][-1] == ("whatsapp:+14075550103", "Hi Ana, Michael here")
          and CONV[K][-1]["content"] == "Hi Ana, Michael here" and CONV[K][-1]["by"] == "michael" and CONV[K][-1]["at"]
          and j["sent"] == {"channel": "whatsapp", "as": "michael"} and j["lead"]["timeline"]["turns"][-1]["role"] == "michael", str(j)[:300])
    r = c.post(f"/desk/api/lead/{K}/takeover?secret=k", json={"action": "release"})
    check("route.release", r.status_code == 200 and "14075550103" not in calls["manual"] and "michael" not in r.get_json()["lead"]["flags"])
    r = c.post("/desk/api/lead/instagram:1789/send?secret=k", json={"text": "hey", "as": "maya"})
    check("route.send_instagram", r.status_code == 200 and calls["ig"][-1] == ("1789", "hey") and IGC["instagram:1789"][-1]["content"] == "hey"
          and "by" in IGC["instagram:1789"][-1] and IGC["instagram:1789"][-1]["by"] == "maya")
    LEADS[K]["channel"] = "sms"
    r = c.post(f"/desk/api/lead/{K}/send?secret=k", json={"text": "text me", "as": "maya"})
    check("route.send_sms_refusal_surfaces", r.status_code == 400 and r.get_json()["error"] == "outside_window" and calls["sms"][-1] == ("+14075550103", "text me"))
    LEADS[K].pop("channel")
    r = c.post("/desk/api/lead/whatsapp:+14075550108/send?secret=k", json={"text": "hi"})
    check("route.send_dnc_blocked", r.status_code == 400 and "do-not-contact" in r.get_json()["error"] and not any(t == "whatsapp:+14075550108" for t, _ in calls["wa"]))
    r = c.post(f"/desk/api/lead/{K}/dnc?secret=k", json={"on": True})
    check("route.dnc", r.status_code == 200 and r.get_json()["lead"]["stage"] == "Lost" and calls["dnc"][-1] == ("14075550103", True))
    r = c.post(f"/desk/api/lead/{K}/dnc?secret=k", json={"on": False})
    check("route.dnc_lift", r.status_code == 200 and calls["dnc"][-1] == ("14075550103", False))
    r = c.post("/desk/api/lead/nobody/note?secret=k", json={"text": "x"})
    check("route.404", r.status_code == 404)
    r = c.post(f"/desk/api/lead/4075550103/note?secret=k", json={"text": "by phone"})
    check("route.by_phone", r.status_code == 200 and r.get_json()["lead"]["key"] == K)
except ImportError:
    print("note: flask not installed here — route checks skipped (proven live after deploy)")
except Exception as e:
    check("flask.registration", False, repr(e))

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch270.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #270 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("270: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE271 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
