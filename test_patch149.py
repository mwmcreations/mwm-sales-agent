#!/usr/bin/env python3
"""
test_patch149.py — operator alerts go to Michael by SMS + #eric, never WhatsApp.

Part 1 drives operator_alert.py with fakes: one recipient, plain SMS text,
#eric line carrying the delivery outcome, failures reported, cap, dedupe.
Part 2 reads app.py and proves every Michael alert site moved off WhatsApp.

Run: python3 test_patch149.py
"""
import importlib
import sys

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


# ── Part 1: the module ─────────────────────────────────────────────────────
import operator_alert as oa


def fresh(phone="+1 (813) 503-1224", sms_ok=True, cap=40, pg=None, raise_sms=False):
    importlib.reload(oa)
    calls = {"sms": [], "slack": [], "err": []}

    def sms_post(to, body):
        calls["sms"].append((to, body))
        if raise_sms:
            raise RuntimeError("twilio down")
        return {"ok": True, "sid": "SM123"} if sms_ok else {"ok": False, "reason": "api_21610"}

    store = pg if pg is not None else None
    oa.configure(
        sms_post=sms_post,
        post_slack=lambda ch, t: calls["slack"].append((ch, t)),
        report_error=lambda c, e, d="": calls["err"].append((c, str(e), d)),
        operator_phone=lambda: phone,
        eric_channel="#eric", daily_cap=cap,
        pg_load=(lambda k, d: store.get(k, d)) if store is not None else None,
        pg_save=(lambda k, v: store.__setitem__(k, v)) if store is not None else None,
        today=lambda: "2026-10-02")
    return calls


# normalize
ok(oa.normalize("whatsapp:+1 (813) 503-1224") == "+18135031224", "whatsapp: prefix normalized")
ok(oa.normalize("8135031224") == "+18135031224", "10 digits get +1")
ok(oa.normalize("") == "" and oa.normalize("123") == "", "unusable number -> ''")

# plain
p = oa.plain("🎉 *New Studio Visit Booked!*\n\n\n\n👤 _Name_: `Sessa`")
ok("*" not in p and "_" not in p and "`" not in p, "markup stripped")
ok("🎉" not in p and "👤" not in p, "emoji stripped (keeps SMS in GSM-7)")
ok("\n\n\n" not in p, "blank-line runs collapsed")
ok(len(oa.plain("x" * 2000)) <= oa.SMS_MAX, "SMS capped at SMS_MAX")

# not configured -> does nothing, no crash
importlib.reload(oa)
ok(oa.alert("booking", "x")["sms"] == "not_configured", "unconfigured module sends nothing")

# booking: SMS to Michael + #eric line saying it was sent
c = fresh()
r = oa.alert("booking", "New studio visit booked: Michael Sessa, Tue Oct 6, 3:00 PM ET.",
             eric_text=":calendar: *New studio visit booked* — Michael Sessa")
ok(r == {"sms": "sent", "eric": True}, "booking -> sent + eric")
ok(len(c["sms"]) == 1 and c["sms"][0][0] == "+18135031224", "texted ONLY the operator number")
ok("Michael Sessa" in c["sms"][0][1], "SMS carries the booking")
ok(len(c["slack"]) == 1 and c["slack"][0][0] == "#eric", "same line posted to #eric")
ok("text to Michael: sent" in c["slack"][0][1], "#eric line shows delivery outcome")
ok(c["err"] == [], "no error on success")
ok(oa.status()["sent"] == 1 and oa.status()["eric_posted"] == 1, "status counts")

# there is no way for a caller to choose the recipient
import inspect
ok("to" not in inspect.signature(oa.alert).parameters and "phone" not in inspect.signature(oa.alert).parameters,
   "alert() takes no recipient argument")

# lead / cancel / expo also go to #eric; briefing and test do not
for kind, eric in (("lead", True), ("cancel", True), ("expo", True), ("briefing", False), ("test", False)):
    c = fresh()
    oa.alert(kind, f"{kind} body")
    ok(len(c["sms"]) == 1, f"{kind}: texted")
    ok((len(c["slack"]) == 1) == eric, f"{kind}: #eric {'yes' if eric else 'no'}")

# SMS refused by Twilio -> #eric line says NOT sent, error reported
c = fresh(sms_ok=False)
r = oa.alert("booking", "booked X")
ok(r["sms"] == "api_21610" and r["eric"], "failed SMS still posts #eric")
ok("NOT sent (api_21610)" in c["slack"][0][1], "#eric line names the failure")
ok(len(c["err"]) == 1 and c["err"][0][0].startswith("operator_sms_"), "failure reported to error rail")

# sender raises -> handled
c = fresh(raise_sms=True)
r = oa.alert("lead", "lead Y")
ok(r["sms"].startswith("exception") and r["eric"], "sender exception contained, #eric still posted")

# no operator number -> nothing texted, reported, #eric still told
c = fresh(phone="")
r = oa.alert("booking", "booked Z")
ok(r["sms"] == "no_operator_phone" and c["sms"] == [] and r["eric"], "no MICHAEL_PHONE: refused, #eric told")

# dedupe: same alert twice in 10 min is one text; a failed one may retry
c = fresh()
oa.alert("booking", "same")
r2 = oa.alert("booking", "same")
ok(r2["sms"] == "deduped" and len(c["sms"]) == 1 and len(c["slack"]) == 1, "duplicate suppressed")
c = fresh(sms_ok=False)
oa.alert("booking", "retry me")
oa.alert("booking", "retry me")
ok(len(c["sms"]) == 2, "failed alert is not deduped (retry allowed)")

# daily cap, persisted in pg state
store = {}
c = fresh(cap=2, pg=store)
for i in range(3):
    oa.alert("lead", f"lead {i}")
ok(len(c["sms"]) == 2, "daily cap holds")
ok(store.get(oa.CAP_KEY, {}).get("count") == 2 and store[oa.CAP_KEY]["day"] == "2026-10-02", "cap persisted")
ok("NOT sent (daily_cap)" in c["slack"][-1][1], "capped alert still reaches #eric")
store[oa.CAP_KEY] = {"day": "2026-10-01", "count": 99}
c2_before = len(c["sms"])
oa.alert("lead", "new day")
ok(len(c["sms"]) == c2_before + 1, "cap resets on a new day")

# ── Part 2: app.py wiring ──────────────────────────────────────────────────
APP = open("app.py", encoding="utf-8").read()


def body(start, end):
    i = APP.index(start)
    return APP[i:APP.index(end, i + len(start))]


ok("import operator_alert as _operator_alert" in APP, "app imports operator_alert")
cfg = body("_operator_alert.configure(", "\n)\n")
ok("sms_post=_send_operator_sms" in cfg, "configured with the operator sender")
ok('os.getenv("MICHAEL_PHONE"' in cfg, "recipient is MICHAEL_PHONE")
ok("eric_channel=SLACK_ERIC_CHANNEL" in cfg, "#eric channel wired")

gate = body("def _operator_sms_gates(", "\ndef _send_operator_sms(")
ok('"not_operator"' in gate and 'os.getenv("MICHAEL_PHONE"' in gate, "operator kind passes ONLY MICHAEL_PHONE")
ok("do_not_sms:" in gate, "operator gate honours do_not_sms")
ok("twilio_env_missing" in gate, "operator gate needs Twilio env")
snd = body("def _send_operator_sms(", "\ndef _operator_pg_load(")
ok("_send_sms(to, body, kind=SMS_KIND_OPERATOR)" in snd, "operator sender is the one gated _send_sms")
ss = body("def _send_sms(", "\n# \u2500\u2500 PATCH #111")
ok("if kind == SMS_KIND_OPERATOR:" in ss and "_operator_sms_gates(lead_phone)" in ss, "_send_sms routes operator kind to its gate")
ok("kind != SMS_KIND_OPERATOR" in ss, "operator sends do not touch lead counters")
ok("def _send_sms(lead_phone, body, kind=SMS_KIND_MARKETING)" in APP, "default kind is still marketing")
ok(APP.count("Messages.json") == 1, "still exactly ONE place posts to Twilio (Patch #112 rule)")

expo = body("def notify_michael_expo_interest(", "\ndef extract_expo_interest")
lead = body("def notify_michael_maya_lead(", "\ndef log_lead(")
book = body("def book_appointment(", "\n# ═")
canc = body("Successfully cancelled", "def _parse_datetime_flexible")
canc = body("def cancel_appointment", "def _parse_datetime_flexible")
brief = body("def _pre_meeting_briefer(", "threading.Thread(target=_pre_meeting_briefer")
for name, b, kind in (("expo", expo, "expo"), ("lead", lead, "lead"), ("booking", book, "booking"),
                      ("cancel", canc, "cancel"), ("briefing", brief, "briefing")):
    ok(f'_operator_alert.alert(\n' in b or f'_operator_alert.alert("{kind}"' in b,
       f"{name}: goes through operator_alert")
    ok(f'"{kind}"' in b, f"{name}: kind {kind}")
    ok("send_whatsapp_meta(michael" not in b, f"{name}: no WhatsApp to Michael")
ok("META_ACCESS_TOKEN" not in expo and "META_ACCESS_TOKEN" not in lead,
   "lead alerts no longer depend on the Meta token")
ok("send_whatsapp_meta(michael" not in APP, "no WhatsApp send to michael_* anywhere")
ok("_true_channel" in book[book.index("PATCH #149"):], "booking alert names the channel")

hl = '"operator_alert": _operator_alert.status(),  # PATCH #149'
ok(hl in APP, "/health shows operator_alert")
rt = body('@app.route("/admin/operator-alert-test"', '@app.route("/admin/lead-form-test"')
ok('_admin_secret_ok(request.values.get("secret", ""))' in rt and "403" in rt, "self-test route is secret-gated")
ok('_operator_alert.alert(\n        "test"' in rt, "self-test sends kind=test (no #eric)")

print(f"patch149: {PASS} passed, {FAIL} failed")

# ── Part 3: the neighbours still pass (static rules that guard SMS + rails) ─
import re, subprocess
OTHERS = ["test_patch112_wiring.py", "test_patch148.py", "test_patch147.py",
          "test_patch146.py", "test_patch96_wiring.py"]
bad = []
for t in OTHERS:
    r = subprocess.run([sys.executable, t], capture_output=True, text=True, timeout=300)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    print(f"{t}: exit {r.returncode} | {tail}")
    if r.returncode != 0:
        bad.append(t)
if FAIL == 0 and not bad:
    print("P149 GATE: ALL GREEN")
else:
    print(f"P149 GATE: RED ({FAIL} own failures; failing neighbours: {bad})")
sys.exit(1 if (FAIL or bad) else 0)
