#!/usr/bin/env python3
"""test_greeting_name.py — Patch #98. ERIC's `"Hi ,"`.

ERIC, Aug 8 2026: *"Every conversation, both campaigns, opens on the vague
account-level greeting with the broken `Hi ,`"* — mapped as systemic across 8+
templates. It then sat for a week, because MATT assigned it to ERIC and the fix
lives in the send code, which is DEV's. It fell exactly where he warned it
would fall.

Part of why nobody found it: **the string is not in the repo.** The Meta
template body holds `Hi {{1}},` and we supply {{1}}. The template was fine. We
were handing it a character you cannot see.

Reproduced Aug 15 against the guard every send site was using:

    (name or "there").split()[0]

    name = "   "      -> IndexError. Not a bad greeting — a DEAD SEND.
                         `or` only catches falsy, and "   " is truthy.
    name = "‎"   -> returns "‎". `.strip()` removes whitespace and a
                         left-to-right mark is not whitespace. Meta renders it
                         as nothing: "Hi ,".

Instagram display names are full of these — direction marks, zero-width
joiners between emoji, non-breaking spaces. IG is the #1 lead source.

Run: python3 test_greeting_name.py
"""

import io
import os
import re
import sys

from event_rail import greeting_name, GREETING_FALLBACK

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


HERE = os.path.dirname(os.path.abspath(__file__))


def src(name):
    return io.open(os.path.join(HERE, name), encoding="utf-8").read()


# ══════════════════════════════════════════════════════════════════════
section("1 · the two defects that produced ERIC's report")

# The old guard, kept here as the thing we are testing AGAINST.
def old_guard(name):
    return (name or "there").split()[0]

_crashed = False
try:
    old_guard("   ")
except IndexError:
    _crashed = True
check("the old guard CRASHED on a whitespace-only name", _crashed, True)
check("greeting_name does not", greeting_name("   "), "there")

check("the old guard passed an invisible character straight through",
      old_guard("‎"), "‎")
check("greeting_name refuses to greet with something unreadable",
      greeting_name("‎"), "there")


# ══════════════════════════════════════════════════════════════════════
section("2 · every shape of nothing resolves to a word a human can read")

for label, value in (
    ("None", None),
    ("empty string", ""),
    ("spaces", "   "),
    ("tab and newline", "\t\n"),
    ("zero-width space", "​"),
    ("zero-width joiner", "‍"),
    ("left-to-right mark", "‎"),
    ("right-to-left mark", "‏"),
    ("byte order mark", "﻿"),
    ("word joiner", "⁠"),
    ("non-breaking space", " "),
    ("narrow no-break space", " "),
    ("a mark wrapped in spaces", "  ‎  "),
    ("several marks together", "​‎﻿"),
    ("a lone open bracket", "("),
    ("an integer 0", 0),
):
    check("{} -> the fallback".format(label), greeting_name(value), "there")

check("the fallback is overridable", greeting_name(None, "Unknown"), "Unknown")
check("...and the default is the exported constant", GREETING_FALLBACK, "there")


# ══════════════════════════════════════════════════════════════════════
section("3 · real names still come through untouched")

check("a plain first name", greeting_name("Sarah"), "Sarah")
check("first name of a full name", greeting_name("Jonathan Pineda"), "Jonathan")
check("leading/trailing space is trimmed", greeting_name("  Michael  "), "Michael")
check("accents survive", greeting_name("Juliane Almeida"), "Juliane")
check("non-latin survives", greeting_name("Луиз Болфер"), "Луиз")

# Patch #42: a record can hold two people.
check("the parenthetical is never greeted",
      greeting_name("Krista Neeley (with Michael Neeley)"), "Krista")
check("...even with no space before the bracket",
      greeting_name("Krista(with Michael)"), "Krista")

# Instagram display names — the #1 lead source, and the messiest input we take.
check("an emoji-suffixed IG name keeps the name", greeting_name("Tina ❤️"), "Tina")
check("a name glued to marks still resolves",
      greeting_name("‎Dylan‏ Zollinger"), "Dylan")
check("an all-emoji display name is not greeted with an emoji... it IS the name",
      greeting_name("5ive⚡"), "5ive⚡")
check("a company-style name", greeting_name("Express Auto Detailing Inc"), "Express")


# ══════════════════════════════════════════════════════════════════════
section("4 · it never raises, whatever it is handed")

for weird in (None, "", "   ", 0, 12345, [], {}, (), object(), True, 3.14,
              "​" * 50, "(" * 20, "a" * 5000):
    try:
        out = greeting_name(weird)
        ok = isinstance(out, str) and out.strip() != ""
    except Exception as exc:
        ok = "RAISED {}".format(type(exc).__name__)
    check("{} -> a non-empty string".format(type(weird).__name__ + repr(weird)[:18]), ok, True)


# ══════════════════════════════════════════════════════════════════════
section("5 · wiring — no send path may keep its own copy of the guard")

_RAW = re.compile(r'\(\s*\w[\w\.\[\]\'\"]*\s+or\s+"(?:there|Unknown)"\s*\)\.split\(\)\[0\]')
for mod in ("app.py", "maya_actions.py", "outcome_sender.py"):
    body = src(mod)
    # strip docstrings/comments cheaply: the pattern is only a finding in code
    hits = [ln for ln in body.splitlines()
            if _RAW.search(ln) and not ln.strip().startswith("#")]
    check("{} no longer builds a greeting name by hand".format(mod), hits, [])

check_true("maya_actions imports the shared helper",
           "greeting_name" in src("maya_actions.py"))
check_true("outcome_sender delegates to it rather than keeping a second copy",
           "return greeting_name(name)" in src("outcome_sender.py"))
check_true("app.py routes its greeting sites through it",
           src("app.py").count("event_rail.greeting_name(") >= 10)


print("\nP98_GATE_RESULT: " + ("PASS" if _failed == 0 else "FAIL"))
print("\n" + "=" * 60)
print("  TOTAL: {} passed, {} failed".format(_passed, _failed))
if _FAILS:
    for f in _FAILS:
        print("   -", f)
print("=" * 60)
sys.exit(1 if _failed else 0)
