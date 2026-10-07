"""PATCH #154 gate — an Instant Form lead's WhatsApp handoff is not a second
first touch.

7 Oct 17:40 ET: Meta's thank-you page sent Duncan Wardle's form answers to
WhatsApp as his first message. The WhatsApp "form fill" routing then sent a
second welcome email (17:40:51, after the rail's first touch at 17:40:30)
and told Susan and LARA about a lead the rail had already announced. The
block now skips a record the form rail owns (`meta_lead_ad`). Maya still
answers the WhatsApp message. Prints "N passed, M failed", then runs the
#153 gate (which chains #152 → #151 → #150 → #148 → #143).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
i = SRC.index("# ── Auto-route to Susan + send welcome email when lead has email (form fill) ──")
blk = SRC[i:i + 2600]
check("guard.flag", '_is_form_lead = bool(_ld.get("meta_lead_ad"))' in blk, blk[:900])
check("guard.skip_branch", "if _has_email and _is_form_lead:" in blk and "no second welcome email" in blk)
check("guard.counter", '_TALLY.bump("lead_form.wa_handoff_skipped_welcome"' in blk)
check("guard.welcome_conditioned", "if _has_email and not _is_form_lead:" in blk
      and blk.index("if _has_email and not _is_form_lead:") < blk.index("_send_welcome_email_async(_lead_email, _lead_name"))
check("guard.before_welcome", blk.index("_is_form_lead = bool") < blk.index("_send_welcome_email_async(_lead_email"))
check("guard.new_lead_event_untouched", "_post_new_lead_or_existing_client(" in SRC[i - 700:i], "the pipeline NEW_LEAD event still fires")
check("guard.maya_still_answers", "def process_maya(snap, sndr" in SRC)

print(f"static: {passed} passed, {failed} failed")

r = subprocess.run([sys.executable, os.path.join(HERE, "test_patch153.py")], capture_output=True, text=True)
tail = (r.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r.stdout[-1500:]); print(r.stderr[-800:])
    failed += 1; print("FAIL rail gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("rail: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
