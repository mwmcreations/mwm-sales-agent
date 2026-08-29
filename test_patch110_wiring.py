#!/usr/bin/env python3
"""
test_patch110_wiring.py — PATCH #110, the wiring half.

known_client.py can be flawless and change nothing. House rule since #49: a
module is not a feature until something calls it. This reads app.py and proves
the guard sits on all three paths that hurt — the two places a NEW LEAD is
announced, and the place a quiet lead is handed to the re-engagement machine.

Run: python3 test_patch110_wiring.py
"""
import io
import re
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

# ── §1 · IT IS IMPORTED AND HAS AN EVENT TO POST ───────────────────────────
ok("import known_client as _kc" in SRC, "known_client is imported")
ok('"EXISTING_CLIENT"' in SRC, "EXISTING_CLIENT is a real pipeline event type")
ok('"EXISTING_CLIENT": "' in SRC.split("_PIPELINE_EVENT_TYPES = {")[1].split("}")[0],
   "and it is registered in _PIPELINE_EVENT_TYPES, so it renders an emoji")

# ── §2 · NO NEW_LEAD IS POSTED WITHOUT THE CHECK ───────────────────────────
ok("def _known_client_lookup(" in SRC, "_known_client_lookup() exists")
ok("def _post_new_lead_or_existing_client(" in SRC,
   "_post_new_lead_or_existing_client() exists")

raw = [l for l in SRC.splitlines() if '"NEW_LEAD",' in l]
ok(len(raw) >= 1, "NEW_LEAD is still posted somewhere (found %d)" % len(raw))

# Every inbound-message path must route through the guard, not post directly.
calls = SRC.count("_post_new_lead_or_existing_client(")
ok(calls >= 3, "the guard is defined and called from both legs (%d refs)" % calls)
ok("Instagram DM" in SRC.split("_post_new_lead_or_existing_client(")[2],
   "the Instagram leg goes through the guard")
ok('"WhatsApp"' in SRC.split("_post_new_lead_or_existing_client(")[3],
   "the WhatsApp leg goes through the guard")

fn = SRC.split("def _post_new_lead_or_existing_client")[1].split("\ndef ")[0]
ok('_post_pipeline_event("NEW_LEAD"' in fn,
   "on no match it still posts a normal NEW_LEAD")
ok('"EXISTING_CLIENT"' in fn, "on a match it posts EXISTING_CLIENT instead")
ok("return False" in fn and "return True" in fn, "it reports which happened")
ok("no prospecting, no re-engagement" in fn,
   "the card tells a human what NOT to do with it")

# ── §3 · FAIL OPEN, NEVER SILENT ───────────────────────────────────────────
lk = SRC.split("def _known_client_lookup")[1].split("\ndef ")[0]
ok("except Exception" in lk and 'return False, "lookup_failed", None' in lk,
   "a lookup error degrades to 'new lead', never to silence")
ok('k != sender' in lk,
   "a record never matches itself — otherwise every client is their own duplicate")
ok('"already_marked"' in lk,
   "a record already marked client is left alone rather than re-announced")

# ── §4 · THE EXPENSIVE PATH: RE-ENGAGEMENT ─────────────────────────────────
ok("add_to_reengagement_queue(" in SRC, "the enqueue call still exists")
before = SRC.split("add_to_reengagement_queue(\n")[0]
ok("_known_client_lookup(phone)" in before,
   "the client check runs BEFORE the enqueue, not after")
ok("reengagement.client_not_enqueued" in SRC,
   "skips are counted so /health can show them")
ok('"skipped:client"' in SRC,
   "the record says WHY it was skipped rather than claiming it was enqueued")
ok("$1,200" in SRC, "the comment records what this cost, so nobody removes it")

print("\nPATCH110_WIRING_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  KNOWN CLIENT WIRING (Patch #110): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
