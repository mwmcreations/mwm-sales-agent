"""PATCH #260 gate — client delivery through /api/send-email (Oct 23 2026:
LARA's EP04 email to Marcia Cardim, ediasm@icloud.com, came back 409
"do-not-contact list"). Michael chose: Marcia STAYS on EMAIL_DNC (no lead mail,
ever) and the endpoint gets `"client_delivery": true`, which lets an address on
TRANSACTIONAL_OK_EMAILS through. The never-contact tier (Yasmin) still refuses.

1. _send_api_refusal: per address — allow skips DNC, block refuses, default =
   the ordinary guard; without the flag nothing changes.
2. _email_send decides the transactional exception PER ADDRESS.
3. The route reads the flag strictly (`is True`), uses the helper for TO+CC
   before sending, and passes transactional=_client_delivery to the sender.
4. The lists themselves are untouched: Marcia on EMAIL_DNC and TRANSACTIONAL_OK,
   Yasmin on NEVER_CONTACT.
Then runs the #259 gate (→ 258 → …)."""
import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
from event_rail import transactional_allowed  # noqa: E402

MARCIA, YASMIN = "ediasm@icloud.com", "yasminfmoraes@icloud.com"
DNC = {MARCIA, YASMIN, "lead-dnc@example.com"}


def fake_suppressed(a):
    e = str(a or "").strip().lower()
    if e in DNC:
        return True, "do-not-contact list"
    if e.endswith("@mwmcreations.com"):
        return True, "internal address"
    return False, ""


tree = ast.parse(SRC)
fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"_send_api_refusal", "_email_send"}}
check("lift.found", set(fns) == {"_send_api_refusal", "_email_send"}, str(set(fns)))

sent = []


def fake_send_gmail(to, subject, html, drive_file_id=None, **kw):
    sent.append((to, kw))
    return {"ok": True, "message_id": "m1"}


G = dict(transactional_allowed=transactional_allowed, email_is_suppressed=fake_suppressed,
         TRANSACTIONAL_OK_EMAILS={MARCIA}, NEVER_CONTACT_EMAILS={YASMIN},
         send_gmail=fake_send_gmail, re=re, print=lambda *a, **k: None,
         _report_error=lambda *a, **k: None)
exec(compile(ast.Module(body=list(fns.values()), type_ignores=[]), "app_260", "exec"), G)
R, S = G["_send_api_refusal"], G["_email_send"]

# ── 1 · the route's guard ─────────────────────────────────────────────────
check("guard.no_flag_marcia_refused", R([MARCIA]) == (MARCIA, "do-not-contact list"))
check("guard.no_flag_ok", R(["ok@gmail.com"]) is None)
check("guard.flag_marcia_allowed", R([MARCIA], True) is None)
check("guard.flag_yasmin_blocked", (R([YASMIN], True) or ("", ""))[0] == YASMIN and "never-contact" in R([YASMIN], True)[1])
check("guard.flag_other_dnc_still_refused", R(["lead-dnc@example.com"], True) == ("lead-dnc@example.com", "do-not-contact list"))
check("guard.flag_internal_still_refused", R(["x@mwmcreations.com"], True) == ("x@mwmcreations.com", "internal address"))
check("guard.flag_mixed_ok", R(["ok@gmail.com", MARCIA], True) is None)
check("guard.flag_cc_yasmin_blocks", (R([MARCIA, YASMIN], True) or ("",))[0] == YASMIN)
check("guard.flag_case_insensitive", R(["EDIASM@icloud.com"], True) is None)

# ── 2 · the sender wrapper ────────────────────────────────────────────────
sent.clear()
r = S(MARCIA, "s", "h", transactional=True)
check("send.marcia_transactional_sent", r.get("ok") and sent and sent[-1][1].get("transactional") is True, str(r))
sent.clear()
r = S(MARCIA, "s", "h")
check("send.marcia_plain_suppressed", r.get("suppressed") and not sent, str(r))
sent.clear()
r = S(MARCIA + ", ok@gmail.com", "s", "h", transactional=True)
check("send.per_address_allow", r.get("ok") and len(sent) == 1, str(r))
sent.clear()
r = S(MARCIA + ", " + YASMIN, "s", "h", transactional=True)
check("send.per_address_block", r.get("suppressed") and r.get("blocked_address") == YASMIN and not sent, str(r))
sent.clear()
r = S("lead-dnc@example.com", "s", "h", transactional=True)
check("send.default_still_guarded", r.get("suppressed") and not sent, str(r))
sent.clear()
r = S("ok@gmail.com", "s", "h")
check("send.ordinary_unchanged", r.get("ok") and "transactional" not in sent[-1][1], str(sent))

# ── 3 · the route wiring ──────────────────────────────────────────────────
rt = SRC[SRC.index("def api_send_email():"):SRC.index("def api_find_thread():")]
check("route.flag_strict", '_client_delivery = data.get("client_delivery") is True' in rt)
check("route.helper_before_send", "_send_api_refusal(to_list + cc_list, _client_delivery)" in rt
      and rt.index("_send_api_refusal(to_list + cc_list") < rt.index("_email_send(to_email"))
check("route.passes_transactional", "transactional=_client_delivery)" in rt)
check("route.409_kept", '"suppressed": True, "to": _addr}), 409' in rt)
check("route.doc", "client_delivery: true for a delivery to a CLIENT" in rt)

# ── 4 · the lists are untouched ───────────────────────────────────────────
dnc_blk = SRC[SRC.index("EMAIL_DNC = {"):SRC.index("def email_is_suppressed")]
check("lists.marcia_still_dnc", '"yasminfmoraes@icloud.com,ediasm@icloud.com"' in dnc_blk)
check("lists.marcia_txok", 'os.getenv("TRANSACTIONAL_OK_EMAILS", "ediasm@icloud.com")' in SRC)
check("lists.yasmin_never", 'os.getenv("NEVER_CONTACT_EMAILS", "yasminfmoraes@icloud.com")' in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch259.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #259 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("259: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE260 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
