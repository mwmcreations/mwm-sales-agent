#!/usr/bin/env python3
"""Patch #44 deploy gate — runs every suite and reports ONE verdict.

The autodeploy watcher greps a single test run for a single expected string.
Pointing it at only `test_event_rail.py` would have let #44 through on the
strength of tests that never touch the code #44 changes. This runs all three
and fails the gate if any of them fails.

Prints a final line in the watcher's expected shape: "TOTAL: N passed, M failed".
"""
import subprocess
import sys

SUITES = [
    ("event rail (policy + timing)", "test_event_rail.py"),
    ("do-not-contact guard (#44A)", "test_send_guard.py"),
    ("outcome sequence sender (#44B)", "test_outcome_sender.py"),
]

failures = 0
ran = 0

for label, path in SUITES:
    print(f"\n{'=' * 64}\n  {label}  —  {path}\n{'=' * 64}")
    proc = subprocess.run([sys.executable, path], capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write(proc.stderr)
    ran += 1
    if proc.returncode != 0:
        failures += 1
        print(f"  >>> {path} FAILED (exit {proc.returncode})")

print("\n" + "=" * 64)
print(f"  PATCH #44 GATE: {ran - failures} suite(s) passed, {failures} failed")

# The watcher gates by grepping this whole output for one expected string.
# It must NOT be "0 failed": test_event_rail.py prints "273 passed, 0 failed"
# in its own summary, so that phrase appears even when a LATER suite fails —
# the gate would pass a broken patch. This marker is printed on exactly one
# code path and appears nowhere else in the output.
if failures:
    print("  PATCH44_GATE_RESULT: FAIL")
else:
    print("  PATCH44_GATE_RESULT: PASS")
print("=" * 64)
sys.exit(1 if failures else 0)
