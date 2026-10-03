"""PATCH #150 gate — under budget = the first-hour invitation (Michael, 3 Oct 2026).

"I don't like 'probably not the right fit just yet'. Say the best way from
now is to book your first hour with us. No 30-minute visit for them; one
studio hour so they get to know us." Every door: the form rail's email/text
and Maya's rule on WhatsApp / Instagram / web / SMS. Prints "N passed, M failed".
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import studio_visit as sv   # noqa: E402
import sms_copy as sc       # noqa: E402

SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


COLD = ("not the right fit", "right fit", "established businesses", "subscription",
        "not a fit", "probably not", "just yet")

# the text
for nm, biz in (("Ana", "Lima Dental"), ("Maximiliano Alejandro", "Altamonte Family Hearing Center"),
                ("", ""), ("Daphnee", "bon juice")):
    core = sv.disqualify_text(nm, biz)
    low = core.lower()
    check(f"sms.warm {nm!r}", "book your first studio hour" in core and "mwmcreations.com/book-studio" in core, core)
    check(f"sms.no_cold {nm!r}", not any(c in low for c in COLD), core)
    check(f"sms.no_visit {nm!r}", "visit" not in low, core)
    check(f"sms.fits {nm!r}", sc.segments(sc.compose(core)) <= 2, core)
    check(f"sms.business {nm!r}", (biz in core) if biz else ("sounds great" not in core), core)
check("sms.default_args", "Hi there" in sv.disqualify_text())

# the email
subj, html, text = sv.disqualify_email("Daphnee", "bon juice")
low = text.lower()
check("email.subject", subj == "Daphnee, your first studio hour at MWM Studios", subj)
check("email.warm", "book your first studio hour" in text and "get to know you" in text and "mwmcreations.com/book-studio" in text)
check("email.no_cold", not any(c in low for c in COLD), text)
check("email.no_visit", "visit" not in low)
check("email.credits", sv.CREDITS in text and sv.WE_DO in text)
check("email.maya_number", sv.MAYA_WA in text)
check("email.html", "<p" in html and "Daphnee" in html)
check("email.not_banned", not sv.contains_banned(text))
_, _, t2 = sv.disqualify_email("Ana")
check("email.no_business_ok", "sounds great" not in t2 and "book your first studio hour" in t2)

# Maya's rule (every chat channel)
R = sv.SCRIPT_RULE
i = R.index("UNDER BUDGET")
block = R[i:i + 1200]
check("rule.renamed", "DISQUALIFIED (" not in R)
check("rule.first_hour", "book your first\nstudio hour with us" in block and "mwmcreations.com/book-studio" in block)
spoken = block[block.index('"{Business} sounds great.'):block.index('bring?"') + 7].lower()
check("rule.no_cold_in_spoken_copy", not any(c in spoken for c in COLD), spoken)
check("rule.prohibits_cold", 'never "not the right fit"' in block and '"established businesses"' in block)
check("rule.no_visit", "Do NOT offer the 30-minute visit" in block)
check("rule.no_subscription_mention", "never mention the subscription" in block)
check("rule.price_if_asked", "$249 an hour" in block)
check("rule.not_banned", not sv.contains_banned(R))

# the rail passes name + business, and the text goes through the fit-chain
check("wire.email", '_sv.disqualify_email(name, rec["business"])' in SRC)
check("wire.sms_fit_chain", 'lambda: _sv.disqualify_text(name, rec["business"])' in SRC and "lambda: _sv.disqualify_text()" in SRC)

print(f"static: {passed} passed, {failed} failed")

# the whole rail still passes (#148 gate runs #143's static + behaviour)
r = subprocess.run([sys.executable, os.path.join(HERE, "test_patch148.py")], capture_output=True, text=True)
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
