#!/usr/bin/env python3
"""
test_patch111_wiring.py — PATCH #111, the wiring half.

The roster can be perfect and Maya can still pitch a studio visit to a paying
client, because the roster is only useful if it reaches the prompt. This reads
app.py and proves the client-mode branch sits on BOTH inbound legs, before the
message is handed to Maya — not after.

Run: python3 test_patch111_wiring.py
"""
import io
import sys

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


SRC = io.open("app.py", encoding="utf-8").read()

# ── §1 · THE ROSTER IS LOADED AND KEPT FRESH ───────────────────────────────
ok("import client_roster as _roster_mod" in SRC, "client_roster is imported")
ok("_CLIENT_ROSTER = _roster_mod.Roster(" in SRC, "a single shared roster exists")
ok("def _client_roster_poller(" in SRC, "a poller refreshes it")
ok("threading.Thread(target=_client_roster_poller, daemon=True).start()" in SRC,
   "and the poller is actually started")
ok('_heartbeat("client_roster_poller")' in SRC, "it heartbeats so the watchdog sees it")
ok("_studio.wp_list_clients" in SRC.split("def _client_roster_refresh")[1][:600],
   "it refreshes from the portal's own client list")

poll = SRC.split("def _client_roster_poller")[1].split("\nthreading.Thread")[0]
ok("_fails == 3" in poll,
   "three consecutive failures report once — not every cycle, not never")

# ── §2 · THE ROSTER IS CONSULTED FIRST, AND FAILS SOFT ─────────────────────
lk = SRC.split("def _known_client_lookup")[1].split("\ndef ")[0]
ok("_CLIENT_ROSTER.find(" in lk, "the lookup consults the roster")
ok(lk.index("_CLIENT_ROSTER.find(") < lk.index("others = [v for k, v in lead_data"),
   "and consults it BEFORE falling back to lead_data — the portal is authoritative")
ok('"roster/"' in lk, "a roster match is labelled as such, so the source is visible")
ok("except Exception" in lk.split("_CLIENT_ROSTER.find(")[1][:400],
   "a roster failure falls back to lead_data instead of breaking the message")

# ── §3 · MAYA IS ACTUALLY TOLD ─────────────────────────────────────────────
ok("EXISTING_CLIENT_BLOCK" in SRC, "the client-mode instruction block exists")
blk = SRC.split('EXISTING_CLIENT_BLOCK = """')[1].split('"""')[0]
ok("DO NOT SELL" in blk, "it says plainly not to sell")
ok("STUDIO VISIT" in blk and "WRONG" in blk,
   "it explicitly overrides the studio-visit instruction Maya carries by default")
ok("BOOKING HOURS" in blk,
   "and names the RIGHT action — booking hours they already own")
ok("NEVER SAY" in blk, "it gives concrete phrases never to use")
ok("{hours_line}" in blk and "{expired_line}" in blk,
   "it carries their real balance and contract state")

ok("def _existing_client_context(" in SRC, "a renderer builds it from the roster row")
rend = SRC.split("def _existing_client_context")[1].split("\ndef ")[0]
ok('return ""' in rend.split("if not rec")[1][:80],
   "no record means no block — a lead is never told it is a client")
ok("RENEWAL" in rend, "an expired contract becomes a renewal conversation, not a cold pitch")
ok("except Exception" in rend, "a render failure degrades to no block, never to a crash")

# Both legs, and before the hand-off to Maya.
ok(SRC.count("CLIENT MODE for") == 2, "the branch is on both inbound legs")
wa = SRC.split("threading.Thread(target=process_maya,")[0]
ok(wa.count("_existing_client_context(") >= 2,
   "the WhatsApp leg applies it before process_maya is dispatched")
ig = SRC.split("target=process_maya_ig,")[0]
ok(ig.count("_existing_client_context(") >= 3,
   "and the Instagram leg applies it before process_maya_ig")
ok('_TALLY.bump("maya.client_mode"' in SRC, "client-mode turns are counted")

# ── §4 · IT IS VISIBLE FROM OUTSIDE ────────────────────────────────────────
ok('"client_roster": _CLIENT_ROSTER.summary(),' in SRC,
   "/health reports the roster, so 'it is working' is checkable without guessing")

print("\nPATCH111_WIRING_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  CLIENT MODE WIRING (Patch #111): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
