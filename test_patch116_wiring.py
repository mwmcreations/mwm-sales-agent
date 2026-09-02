#!/usr/bin/env python3
"""
test_patch116_wiring.py — PATCH #116, the wiring half.

loop_guard.py can be perfect and Maya can still send seventy messages to
another company's robot, because the logic is only worth anything if it is
called BEFORE the reply is generated, on BOTH rails, and if a human can get
the conversation back afterwards.

This reads app.py and proves six things:

  1. the guard is consulted before the model call, on WhatsApp AND Instagram;
  2. a stop actually returns — it does not merely log and carry on;
  3. every reply we send is recorded, or the "we are sending filler" rule is
     blind;
  4. a human answering in #maya-shadow releases the guard, on both channels;
  5. the guard FAILS OPEN — a bug in it must not silence the sales line;
  6. the pause is persisted, because a pause that dies with the process is a
     pause-shaped gap in which the loop starts again.

Run: python3 test_patch116_wiring.py
"""
import io
import re

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


SRC = io.open("app.py", encoding="utf-8").read()


def idx(needle, whence=0):
    return SRC.find(needle, whence)


# ── 1 · the module is imported at all ─────────────────────────────────
ok("import loop_guard as _loopguard" in SRC, "app.py imports loop_guard")

# ── 2 · consulted BEFORE the model call, on both rails ────────────────
wa_guard = idx('_loop_allows_reply(sender, incoming_msg, "· WhatsApp")')
wa_thread = idx("threading.Thread(target=process_maya, args=(history_snapshot")
ok(wa_guard != -1, "WhatsApp rail consults the guard")
ok(wa_thread != -1, "WhatsApp rail still launches Maya")
ok(-1 < wa_guard < wa_thread,
   "WhatsApp: the guard runs BEFORE the model call, not after")

ig_guard = idx('_loop_allows_reply(sender, incoming_msg, "· Instagram DM")')
ig_thread = idx("target=process_maya_ig,")
ok(ig_guard != -1, "Instagram rail consults the guard")
ok(-1 < ig_guard < ig_thread,
   "Instagram: the guard runs BEFORE the model call — this is the rail the "
   "Top Florida Homes loop ran on")

# ── 3 · a stop returns; it does not log and continue ──────────────────
for label, start, stop in (("WhatsApp", wa_guard, wa_thread),
                           ("Instagram", ig_guard, ig_thread)):
    between = SRC[start:stop]
    ok("if not _lg_ok:" in between, f"{label}: the verdict is actually tested")
    ok(re.search(r"\n\s+return\b", between) is not None,
       f"{label}: a stop RETURNS instead of falling through to the model")

# ── 4 · Michael is never locked out of his own line ───────────────────
_before_wa = SRC[max(0, wa_guard - 400):wa_guard]
ok("if not is_michael:" in _before_wa,
   "WhatsApp: Michael is exempt from the guard")
ok(_before_wa.count("if ") == 1,
   "...and that exemption is the only condition wrapping the call")

# ── 5 · we record what we send ────────────────────────────────────────
ok(SRC.count("_loop_note_reply(sndr, clean_reply)") == 2,
   "both rails record the reply they sent (the filler rule depends on it)")
ok(idx("_loop_note_reply(sndr, clean_reply)", idx('Maya reply sent to {to_wa}')) > 0,
   "WhatsApp records AFTER a successful send, not before")
ok(idx("_loop_note_reply(sndr, clean_reply)", idx("Maya IG DM reply sent to")) > 0,
   "Instagram records AFTER a successful send, not before")

# ── 6 · a human takes it back ─────────────────────────────────────────
ok('_loop_release(f"instagram:{_igsid}"' in SRC,
   "answering in #maya-shadow releases an Instagram conversation")
ok('_loop_release(wa_sender' in SRC,
   "answering in #maya-shadow releases a WhatsApp conversation")

# ── 7 · fails OPEN ────────────────────────────────────────────────────
fn_start = idx("def _loop_allows_reply(")
fn_end = idx("def _loop_note_reply(")
body = SRC[fn_start:fn_end]
ok(fn_start != -1 and fn_end > fn_start, "_loop_allows_reply exists")
tail = body[body.rfind("except Exception"):]
ok("return True" in tail,
   "a crash inside the guard lets the conversation through — it FAILS OPEN")
ok("_report_error" in tail, "...and is reported, not swallowed")
ok(body.count("_post_to_slack_async") == 1,
   "a stop tells #maya exactly once")
ok("if not already:" in body,
   "...only when it TRIPS, so a held conversation does not spam the channel")

# ── 8 · the pause outlives the process ────────────────────────────────
save = SRC[idx("def _loop_state_save("):idx("_LOOP_REASON_TEXT")]
ok("save_state(_loop_key(sender)" in save, "the pause is persisted")
ok('"paused_at": state.get("paused_at")' in save, "...including when it started")
load = SRC[idx("def _loop_state_get("):idx("def _loop_state_save(")]
ok("load_state(_loop_key(sender)" in load, "...and read back after a restart")
ok('"turns"' not in save,
   "the turn-by-turn evidence is NOT persisted — it is about the last few "
   "minutes and means nothing after a restart")

# ── 9 · the switch, and the numbers, are configurable without a deploy ─
for env in ("LOOP_GUARD", "LOOP_GUARD_BOT_MAX_OUT", "LOOP_GUARD_MAX_OUT",
            "LOOP_GUARD_FAST_S", "LOOP_GUARD_PAUSE_TTL_S"):
    ok(env in SRC, f"{env} is settable from the environment")

print("\n" + "=" * 60)
print(f"  TOTAL: {PASS} passed, {FAIL} failed")
print("=" * 60)
raise SystemExit(1 if FAIL else 0)
