#!/usr/bin/env python3
"""GATE for PATCH #294 — /admin/reoffer only=<channels>. Prints GATE294 PASS/FAIL."""
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
        print(f"  FAIL {name} {str(detail)[:300]}")


APP = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
rt = APP[APP.index("def admin_reoffer():"):APP.index("@app.route('/admin/maya-offers'")]
check("only.parsed", '_only = {x.strip().lower() for x in str(request.values.get("only") or "").split(",") if x.strip()}' in rt)
check("only.rejects_unknown", '_bad_only = _only - {"whatsapp", "sms", "email"}' in rt and "only takes whatsapp, sms, email" in rt)
check("only.whatsapp_gate", 'if (not _only or "whatsapp" in _only) and (conversation_history.get(key) or key.startswith("whatsapp:")):' in rt)
check("only.sms_gate", 'if _only and "sms" not in _only:   # PATCH #294\n            pass\n        elif phone and not wa_ok:' in rt)
check("only.email_gate", 'if email and (not _only or "email" in _only):' in rt)
check("only.default_is_all", rt.count("not _only or") == 2)
check("only.validated_before_loop", rt.index("_bad_only") < rt.index("for q in qs:"))
check("compiles", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, "app.py")], capture_output=True).returncode == 0)

# the three gates, as logic
def would(only, has_wa, wa_ok, phone, email):
    o = {x for x in only.split(",") if x}
    sent = []
    ok = False
    if (not o or "whatsapp" in o) and has_wa:
        ok = wa_ok
        sent.append("whatsapp" if wa_ok else "whatsapp-skip")
    if phone and not ok and (not o or "sms" in o):
        sent.append("sms")
    if email and (not o or "email" in o):
        sent.append("email")
    return sent


check("logic.all", would("", True, False, True, True) == ["whatsapp-skip", "sms", "email"])
check("logic.sms_only", would("sms", True, False, True, True) == ["sms"])
check("logic.email_only", would("email", True, True, True, True) == ["email"])
check("logic.wa_then_no_sms", would("whatsapp,sms", True, True, True, True) == ["whatsapp"])

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 294) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
mm = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not mm:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(mm.group(1)); failed += int(mm.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(mm.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE294 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
