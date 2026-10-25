"""PATCH #261 gate — manual mode is for Michael, and nothing a lead says is dropped
(Sun 25 Oct 2026, Shawnie Whitaker +1 321…0012: the "Maya 24h followup" task
posted its follow-up in her #maya-shadow thread at 18:04; the relay took it for
Michael, muted Maya 60 min; her 18:24 "I'd love to come visit… 11 AM?" was
dropped in silence; nobody was told; the mute ended and nothing caught up).

1. _relay_is_agent_authored / _relay_clean_text — the "Sent using Claude" tail
   marks an agent post; Michael's own text has none.
2. The relay (WhatsApp branch): agent-authored → no manual mode, label
   FOLLOW-UP; Michael → manual mode for MANUAL_MODE_TTL_S, label MICHAEL.
3. process_maya: a muted inbound is HELD (one waiter per lead, ⏸ note + text),
   and after the mute ends Maya answers iff the lead's turn is still last;
   a held reply skips the burst-supersede drop.
4. /admin/maya-catchup route exists, dry by default, apply=1 sends.
5. operator_alert has the "hold" kind (Michael only).
Then runs the #260 gate (→ 259 → …)."""
import ast
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import operator_alert as oa  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
want = {"_relay_is_agent_authored", "_relay_clean_text", "_manual_mode_until", "_manual_hold_begin",
        "_fmt_local_hm", "_manual_hold_notify", "_manual_hold_wait", "_manual_hold_end"}
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
check("lift.found", len(fns) == len(want), f"{len(fns)}/{len(want)}")
# module-level assignments the helpers need
assigns = [n for n in tree.body if isinstance(n, ast.Assign) and any(
    isinstance(t, ast.Name) and t.id in {"_AGENT_ATTRIBUTION_RE"} for t in n.targets)]
check("lift.regex", len(assigns) == 1)

tally, slack_posts, alerts = [], [], []


class Tally:
    def bump(self, *a): tally.append(a)


class Resp:
    def json(self): return {"ok": True}


class Http:
    def post(self, url, json=None, headers=None, timeout=None):
        slack_posts.append(json); return Resp()


class OA:
    def alert(self, kind, text, eric_text=None): alerts.append((kind, text)); return {"sms": "sent"}


import pytz, datetime as _dt  # noqa: E402
G = dict(re=re, time=time, os=os, pytz=pytz, datetime=_dt.datetime, TIMEZONE="America/New_York",
         _TALLY=Tally(), http_requests=Http(), SLACK_BOT_TOKEN="x", SLACK_MAYA_SHADOW_CHANNEL="C0ARME48ZPF",
         maya_shadow_threads={"13216890012": "1792000000.1"}, lead_data={}, conversation_history={},
         _operator_alert=OA(), _manual_mode={}, _manual_hold={}, MANUAL_MODE_TTL_S=3600, MANUAL_HOLD_MAX_S=10800,
         print=lambda *a, **k: None)
exec(compile(ast.Module(body=assigns + fns, type_ignores=[]), "app_261", "exec"), G)

# ── 1 · attribution ─────────────────────────────────────────────────────────
agent = "Hey Shawnie, just circling back! Which one would suit you better? *Sent using* Claude"
check("attr.agent", G["_relay_is_agent_authored"](agent) is True)
check("attr.agent_cowork", G["_relay_is_agent_authored"]("Olá! Sent using Cowork") is True)
check("attr.michael", G["_relay_is_agent_authored"]("Hey Shawnie, it's Michael — 11 works, see you Tuesday!") is False)
check("attr.clean", G["_relay_clean_text"](agent) == "Hey Shawnie, just circling back! Which one would suit you better?")
check("attr.clean_plain", G["_relay_clean_text"]("  hi there  ") == "hi there")
check("attr.empty", G["_relay_is_agent_authored"]("") is False and G["_relay_clean_text"](None) == "")

# ── 2 · the relay source ────────────────────────────────────────────────────
i = SRC.index("def _handle_shadow_relay(")
relay = SRC[i:SRC.index("def _build_maya_sender_identity(")]
check("relay.detects", "_agent_authored = _relay_is_agent_authored(text)" in relay and "text = _relay_clean_text(text)" in relay)
check("relay.no_mute_for_agent", "if _agent_authored:" in relay and 'relay.agent_followup' in relay)
check("relay.mute_for_michael", "_manual_mode[_digits] = time.time() + MANUAL_MODE_TTL_S" in relay)
check("relay.old_hardcode_gone", "time.time() + 3600" not in relay)
check("relay.labels", 'FOLLOW-UP (via Maya' in relay and 'MICHAEL (via Maya' in relay)
check("relay.detect_before_lookup", relay.index("_agent_authored = _relay_is_agent_authored") < relay.index("Reverse lookup"))

# ── 3 · the hold ────────────────────────────────────────────────────────────
G["_manual_mode"]["13216890012"] = time.time() + 2
hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hi!"},
        {"role": "user", "content": "No, I would love to come visit the studio, what's the address and you're saying 11 AM?"}]
G["conversation_history"]["whatsapp:+13216890012"] = hist
ok1 = G["_manual_hold_begin"]("13216890012", "whatsapp:+13216890012", {"name": "Shawnie Whitaker"}, hist[-1]["content"])
ok2 = G["_manual_hold_begin"]("13216890012", "whatsapp:+13216890012", {"name": "Shawnie Whitaker"}, "second message")
check("hold.one_waiter", ok1 is True and ok2 is False)
check("hold.note_posted", len(slack_posts) == 1 and slack_posts[0]["thread_ts"] == "1792000000.1"
      and "Maya is holding" in slack_posts[0]["text"] and "Michael replied in this thread" in slack_posts[0]["text"])
check("hold.text_sent", len(alerts) == 1 and alerts[0][0] == "hold" and "Shawnie Whitaker" in alerts[0][1]
      and "11 AM" in alerts[0][1] and "#maya-shadow" in alerts[0][1])
check("hold.tally", any(a[0] == "maya.manual_hold" for a in tally))
t0 = time.time(); G["_manual_hold_wait"]("13216890012"); waited = time.time() - t0
check("hold.waits_until_mute_ends", 1.5 <= waited <= 20, f"{waited:.1f}s")
check("hold.end_unanswered", G["_manual_hold_end"]("13216890012", "whatsapp:+13216890012") is True
      and "13216890012" not in G["_manual_hold"])
# a human answered during the hold → Maya stays quiet
G["_manual_hold"]["13216890012"] = {"since": 0, "until": 0}
hist.append({"role": "assistant", "content": "Michael: see you at 11!"})
check("hold.end_answered", G["_manual_hold_end"]("13216890012", "whatsapp:+13216890012") is False)
check("hold.bounded", "MANUAL_HOLD_MAX_S" in SRC[SRC.index("def _manual_hold_wait"):SRC.index("def _manual_hold_end")])
check("hold.fmt", re.match(r"\d{1,2}:\d{2} [AP]M", G["_fmt_local_hm"](time.time())) is not None)

# process_maya wiring
j = SRC.index("def process_maya(snap, sndr, ctx=")
pm = SRC[j:j + 2600]
check("pm.hold_not_drop", "_manual_hold_begin(_digits, sndr, identity" in pm and "_manual_hold_wait(_digits)" in pm
      and "_manual_hold_end(_digits, sndr)" in pm and "snap = list(conversation_history.get(sndr) or snap)" in pm
      and "_held = True" in pm)
check("pm.old_drop_gone", "Auto-reply suppressed" not in pm)
k = SRC.index("if not _held and _burst.is_superseded(sender, _burst_seq):")
check("pm.held_skips_supersede", j < k)
check("pm.catchup_mode_cleared_on_human", "a human answered, Maya stays quiet" in pm)

# ── 4 · the admin route ─────────────────────────────────────────────────────
r = SRC.index('@app.route("/admin/maya-catchup", methods=["POST"])')
route = SRC[r:r + 3200]
check("route.secret", "_admin_secret_ok(request.values.get(\"secret\"" in route)
check("route.dry_default", 'request.values.get("apply", "0") != "1"' in route and '"dry": True' in route)
check("route.only_when_pending", 'if last.get("role") != "user":' in route)
check("route.sends_and_mirrors", "send_whatsapp_meta(sender, body=clean_reply)" in route
      and '_mirror_to_maya_shadow_async(_build_maya_sender_identity(sender), "outbound", clean_reply)' in route
      and "_loop_note_reply(sender, clean_reply)" in route)
check("route.clears_mute", "_manual_mode.pop(phone, None)" in route and "_manual_hold.pop(phone, None)" in route)

# ── 5 · operator_alert kind ─────────────────────────────────────────────────
check("oa.hold_kind", oa.KINDS.get("hold") == {"eric": False})
check("oa.unchanged_others", oa.KINDS["booking"]["eric"] is True and oa.KINDS["reminder"]["eric"] is False)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch260.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #260 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("260: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE261 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
