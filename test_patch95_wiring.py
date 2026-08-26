#!/usr/bin/env python3
"""
test_patch95_wiring.py — shadow.py passing 37 checks proves the rule.
It does not prove app.py runs it, persists it, or fails safely.

Run: python3 test_patch95_wiring.py
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


mirror = body("def _mirror_to_shadow(", "\ndef _mirror_to_lara_shadow_async")

# ── §1 · imported and used where it matters ─────────────────────────────────
ok("import shadow as _shadow" in APP, "app.py imports shadow")
ok("_shadow.should_start_new_thread(" in mirror, "the staleness rule runs in the mirror")
ok("_shadow.header_text(" in mirror, "the header is built by the module")
ok("_shadow.should_rename(" in mirror, "the rename decision is the module's")
ok("chat.update" in mirror, "and it actually calls Slack to rename the card")

# ── §2 · a shadow-log failure must NEVER cost a reply to a lead ─────────────
for _frag, _why in (
    ("_shadow.should_start_new_thread(", "staleness check"),
    ("_shadow.header_text(", "header build"),
    ("chat.update", "rename call"),
):
    i = mirror.index(_frag)
    # walk back to the nearest try/except boundary marker
    ok("try:" in mirror[max(0, i - 700):i],
       "the %s sits inside a try — a log failure cannot break the mirror" % _why)
ok(mirror.count("except Exception") >= 5,
   "every new step has its own guard, not one blanket catch")

# ── §3 · the meta store exists, is written, and SURVIVES A RESTART ──────────
ok("shadow_thread_meta = {}" in APP, "the meta store is declared")
ok("shadow_thread_meta[_meta_key]" in mirror, "it is written on both paths")
ok('_pg.load_state("shadow_thread_meta"' in APP,
   "it is RESTORED at boot — without this every restart makes every thread look stale")
ok('_pg.save_state("shadow_thread_meta"' in APP, "and saved")

# ── §4 · the thread map keeps its old shape ─────────────────────────────────
ok("thread_state[thread_key] = thread_ts" in mirror,
   "thread_state stays {key: ts} — _handle_shadow_relay iterates it and must not break")
ok("for key, ts in maya_shadow_threads.items():" in APP,
   "the relay's iteration is untouched")

# ── §5 · the docstring no longer states the thing that is false ─────────────
ok("in-memory and resets on process restart." not in APP,
   "the stale claim is gone — the map is persisted and has been for a while")
ok("SHADOW_THREAD_MAX_IDLE_DAYS" in APP, "the window is named where a reader will find it")

print("\nPATCH95_WIRING_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  PATCH #95 WIRING: {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
