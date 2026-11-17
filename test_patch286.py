#!/usr/bin/env python3
"""GATE for PATCH #286 — the agent bridge goes live where Michael said: an
allowlist of channels for untagged kickoffs in mode on (#susan + #dev first),
set through /admin/agent-talk/mode, shown on /health. Prints GATE286 PASS/FAIL."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agent_talk as at  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


SUSAN = at.AGENTS["SUSAN"]["channel"]
DEV = at.AGENTS["DEV"]["channel"]

# ── 1. the pure helpers ──────────────────────────────────────────────────────
check("ch.none_is_empty", at.channels_from(None) == set())
check("ch.blank_is_empty", at.channels_from("") == set() and at.channels_from("  , ") == set())
check("ch.names_to_ids", at.channels_from("SUSAN, DEV") == {SUSAN, DEV})
check("ch.lowercase_and_hash", at.channels_from("#susan dev") == {SUSAN, DEV})
check("ch.list_input", at.channels_from(["susan", DEV]) == {SUSAN, DEV})
check("ch.plus_separator", at.channels_from("SUSAN + DEV") == {SUSAN, DEV})
check("ch.raw_id_kept", at.channels_from("C0APQ4TDF7W") == {SUSAN})
check("ch.unknown_name_dropped", at.channels_from("SUSAN, NOBODY") == {SUSAN})
check("ch.garbage_dropped", at.channels_from("hello world 123") == set())
check("ch.eddie_has_no_channel", at.channels_from("EDDIE") == set())
check("ch.other_types_empty", at.channels_from(42) == set() and at.channels_from({"a": 1}) == set())
check("ch.names_back", at.channel_names({SUSAN, DEV}) == ["DEV", "SUSAN"])
check("ch.names_unknown_id_kept", at.channel_names({"C0000000000"}) == ["C0000000000"])
check("ch.names_empty", at.channel_names(set()) == [])
check("ch.agents_untouched", at.AGENTS["SUSAN"]["channel"] == "C0APQ4TDF7W" and at.AGENTS["DEV"]["channel"] == "C0AR7NY6SHF")

# ── 2. app.py pins ───────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
blk = SRC[SRC.index("def _at_mode():"):SRC.index("# S7 — STUDIO PACKAGE AUTOMATION WIRING")]
check("app.default_env", 'AGENT_TALK_CHANNELS_DEFAULT = os.getenv("AGENT_TALK_CHANNELS", "").strip()' in blk)
check("app.helper", "def _at_live_channels():" in blk and '_pg.load_state("agent_talk_channels", None)' in blk
      and "return _at.channels_from(v)" in blk)
start = blk[blk.index("def _agent_talk_maybe_start("):blk.index("def _agent_talk_advance(")]
check("app.off_gate_intact", 'if mode == "off":' in start)
check("app.test_gate_intact", 'if mode == "test" and not parsed.get("test") and via != "admin":' in start)
check("app.on_gate", 'if mode == "on" and not parsed.get("test") and via != "admin":   # PATCH #286' in start
      and "_live = _at_live_channels()" in start and "if _live and channel_id not in _live:" in start)
check("app.on_gate_order", start.index('if mode == "test"') < start.index('if mode == "on"') < start.index("cid = _at.conv_id(channel_id, ts)"))
check("app.on_gate_returns_none", "channel not live" in start and start.index("channel not live") < start.index("cid = _at.conv_id(channel_id, ts)"))
check("app.status_shows_channels", '"live_channels": _at.channel_names(_at_live_channels()),' in blk)
route = SRC[SRC.index("def admin_agent_talk_mode():"):SRC.index("# S7 — STUDIO PACKAGE AUTOMATION WIRING")]
check("route.mode_check_intact", 'if mode not in ("off", "test", "on"):' in route and '_at_save("agent_talk_mode", mode)' in route)
check("route.channels_optional", '_ch = payload.get("channels") if "channels" in payload else request.form.get("channels")' in route
      and "if _ch is not None:" in route)
check("route.all_clears", '("all", "*")' in route and '_at_save("agent_talk_channels", sorted(_ids))' in route)
check("route.tells_dev", 'f"🎚 agent-talk mode set to *{mode}{_ch_line}"' in route or 'f"🎚 agent-talk mode set to *{mode}*{_ch_line}"' in route)
check("route.answers_channels", '"live_channels": _at.channel_names(_at_live_channels())' in route)
check("app.no_second_default", SRC.count("AGENT_TALK_CHANNELS_DEFAULT =") == 1)
check("app.helper_once", SRC.count("def _at_live_channels():") == 1)
check("app.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "app.py")], capture_output=True).returncode == 0)
check("at.compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "agent_talk.py")], capture_output=True).returncode == 0)

# ── 3. the gate from #263 still holds its own pins ──────────────────────────
T263 = open(os.path.join(HERE, "test_patch263.py"), encoding="utf-8").read()
check("t263.mode_gate_pin_still_true", 'if mode == "off":' in start and 'if mode == "test" and not parsed.get("test") and via != "admin":' in start)
check("t263.file_untouched_by_286", "#286" not in T263)

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 286) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE286 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
