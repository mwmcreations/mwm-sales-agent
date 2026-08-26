#!/usr/bin/env python3
"""
test_patch96_wiring.py — burst.py passing 23 checks proves the rule.
This proves app.py takes a sequence number on every inbound and checks it at
the ONE place a Maya reply leaves the building — and that a failure there still
sends the reply.

Run: python3 test_patch96_wiring.py
"""
import sys

APP = open("app.py").read()
PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


def body(start, end):
    i = APP.index(start)
    return APP[i:APP.index(end, i + len(start))]


handler = body("def _handle_incoming(", "\n@app.route(\"/webhook/instagram\"")

ok("import burst as _burst" in APP, "app.py imports burst")
ok("_burst.note_inbound(sender)" in handler, "every inbound takes a sequence number")
ok("_burst.is_superseded(sender, _burst_seq)" in handler, "and it is checked before sending")

# the claim must happen BEFORE the reply is generated, or it proves nothing
ok(handler.index("_burst.note_inbound(") < handler.index("_burst.is_superseded("),
   "the sequence is claimed before generation, checked after")

# it must guard the real send, not something upstream of it
send_i = handler.index("send_whatsapp_meta(to_wa, body=clean_reply)")
ok(handler.index("_burst.is_superseded(") < send_i,
   "the check sits above the Maya reply send")
ok("was_audio" in handler[handler.index("_burst.is_superseded("):send_i],
   "and above the voice-note branch too, so an audio reply is covered as well")

# ── failing open ────────────────────────────────────────────────────────────
seq_block = handler[handler.index("_burst.note_inbound("):]
seq_block = seq_block[:seq_block.index("\n\n")] if "\n\n" in seq_block else seq_block
ok("try:" in handler[max(0, handler.index("_burst.note_inbound(") - 400):handler.index("_burst.note_inbound(")],
   "sequencing is wrapped — it must never stop a reply")
chk = handler.index("_burst.is_superseded(")
ok("try:" in handler[max(0, chk - 400):chk],
   "the supersede check is wrapped too")
ok("sending anyway" in handler[chk:chk + 900],
   "and its failure path SENDS — silence is the worse failure")

# ── it is observable ────────────────────────────────────────────────────────
ok('_TALLY.bump("burst.reply_superseded"' in handler,
   "a dropped reply is counted, so /health can show it is working")
ok("superseded" in handler and "dropped" in handler, "and logged in plain words")

# ── no sleeping in the webhook ──────────────────────────────────────────────
ok("time.sleep" not in handler,
   "no sleep was introduced — this webhook has no message-id idempotency, "
   "so a slow handler invites Meta retries and duplicate processing")

print("\nPATCH96_WIRING_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  PATCH #96 WIRING: {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
