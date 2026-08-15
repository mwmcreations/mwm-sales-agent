#!/usr/bin/env python3
"""test_lead_row_wiring.py — Patch #97.

THE DEFECT THIS EXISTS TO PREVENT
=================================
`Maya Leads Report` took its last new-lead row on Aug 3 2026 and none after,
while #pipeline kept posting NEW LEAD every day. The write was being called,
was not throwing, and was not writing.

Patch #72 had already built the instrument to settle that — /health's lead-row
verdict. It could not answer, because two of its four inputs,
`sheets.lead_row_created` and `sheets.lead_row_FAILED`, were READ by the verdict
and INCREMENTED NOWHERE. They were always zero. The diagnostic was blind by
construction and nobody could tell, because a counter that is never bumped and
a thing that never happens look identical from the outside.

That is the sixth "computed and stored, never invoked" defect on this board.
The others were found by a human noticing an outcome was missing, weeks later.

🔑 So this file does not test behaviour. It tests WIRING: every counter the
verdict reads must be bumped somewhere in app.py. A unit test cannot import
app.py — flask and googleapiclient are not installed on the runner — so it reads
app.py as text, which is exactly the right altitude for "is this call site
present at all".

Run: python3 test_lead_row_wiring.py
"""

import io
import os
import re
import sys

from event_rail import lead_row_verdict, LEAD_ROW_GATE_SUSPECT_AT

_passed = _failed = 0
_FAILS = []


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  PASS  " + label)
    else:
        _failed += 1
        _FAILS.append(label)
        print("  FAIL  " + label + "\n          got={!r}\n         want={!r}".format(got, want))


def check_true(label, got):
    check(label, bool(got), True)


def section(title):
    print("\n" + title + "\n" + "-" * len(title))


APP = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"),
              encoding="utf-8").read()


def bumps(counter):
    return len(re.findall(r'_TALLY\.bump\(\s*["\']' + re.escape(counter) + r'["\']', APP))


def reads(counter):
    return len(re.findall(r'_TALLY\.get\(\s*["\']' + re.escape(counter) + r'["\']', APP))


# ══════════════════════════════════════════════════════════════════════
section("1 · every counter the verdict READS must also be BUMPED")

# These four are the verdict's whole input. A counter that is read and never
# written is not a diagnostic, it is a decoration.
for counter in ("sheets.lead_row_created", "sheets.lead_row_FAILED",
                "sheets.lead_row_skipped_duplicate", "sheets.lead_row_gate_not_new"):
    check_true("`{}` is bumped somewhere in app.py".format(counter), bumps(counter) >= 1)

check_true("...and `created` is read by the verdict", reads("sheets.lead_row_created") >= 1)
check_true("...and `FAILED` is read by the verdict", reads("sheets.lead_row_FAILED") >= 1)

# The inverse: nothing may be READ by the verdict that has no writer at all.
_read_counters = set(re.findall(r'_TALLY\.get\(\s*["\'](sheets\.[^"\']+)["\']', APP))
_unwired = sorted(c for c in _read_counters if bumps(c) == 0)
check("no counter is read without a bump site anywhere", _unwired, [])


# ══════════════════════════════════════════════════════════════════════
section("2 · the write path cannot exit silently")

_fn = APP[APP.index("def log_new_contact_to_sheets"):]
_fn = _fn[:_fn.index("\ndef ", 10)]

check_true("the success path bumps `created`",
           re.search(r'_TALLY\.bump\(\s*"sheets\.lead_row_created"', _fn) is not None)
check_true("the exception path bumps `FAILED`",
           re.search(r'_TALLY\.bump\(\s*"sheets\.lead_row_FAILED"', _fn) is not None)
check_true("the duplicate path bumps `skipped_duplicate`",
           re.search(r'_TALLY\.bump\(\s*"sheets\.lead_row_skipped_duplicate"', _fn) is not None)

# The config guard was a bare `return` for the whole life of this function. An
# unset env var and a quiet afternoon produced byte-identical evidence.
_guard = _fn[_fn.index("if not SHEETS_LEADS_ID:"):]
_guard = _guard[:_guard.index("try:")]
check_true("the no-sheet-id guard bumps a counter before returning",
           "_TALLY.bump(" in _guard)
check_true("...and reports it, once, rather than returning silently",
           "_report_error(" in _guard and "_LEAD_ROW_CONFIG_ALERTED" in _guard)
check("...and the bare `return` is gone from that guard",
      re.search(r'if not SHEETS_LEADS_ID:\s*\n\s*return\s*\n', _fn) is not None, False)

_alert_flag = re.findall(r'^_LEAD_ROW_CONFIG_ALERTED\s*=\s*False', APP, re.M)
check("the once-per-process flag is declared exactly once at module level",
      len(_alert_flag), 1)


# ══════════════════════════════════════════════════════════════════════
section("3 · the verdict reads correctly once the counters actually move")

# Before #97 the only reachable answers were these two, whatever was happening.
check("no counters at all -> idle", lead_row_verdict(0, 0, 0, 0)[0], "idle")
check("attempted but nothing created and nothing failed -> dedup_only",
      lead_row_verdict(0, 0, 3, 0)[0], "dedup_only")

# These three were unreachable while `created` and `FAILED` were never bumped.
check("rows written -> ok", lead_row_verdict(5, 0, 0, 0)[0], "ok")
check("every attempt failed -> broken", lead_row_verdict(0, 4, 0, 0)[0], "broken")
check("some failed -> degraded", lead_row_verdict(3, 1, 0, 0)[0], "degraded")
check_true("...and 'broken' names the Sheets call, not the gate",
           "Sheets" in lead_row_verdict(0, 4, 0, 0)[1])

# The gate readings must not be disturbed by #97.
check("high gate count with zero attempts still reads suspect_gate",
      lead_row_verdict(0, 0, 0, LEAD_ROW_GATE_SUSPECT_AT)[0], "suspect_gate")
check("a low gate count stays honest about what it cannot prove",
      lead_row_verdict(0, 0, 0, 1)[0], "all_returning")
check_true("...and says so in words",
           "does NOT prove" in lead_row_verdict(0, 0, 0, 1)[1])

# A failure outranks a gate reading: never blame the gate for a throwing write.
check("a failure outranks any gate reading",
      lead_row_verdict(0, 2, 0, 99)[0], "broken")


print("\nP97_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))
print("\n" + "=" * 60)
print("  TOTAL: {} passed, {} failed".format(_passed, _failed))
if _FAILS:
    for f in _FAILS:
        print("   -", f)
print("=" * 60)
sys.exit(1 if _failed else 0)
