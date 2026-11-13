#!/usr/bin/env python3
"""GATE for PATCH #280 — the post-pitch sequence sends only the package it was
written for, in office hours, and can be held. Prints GATE280 PASS/FAIL."""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("TIMEZONE", "US/Eastern")
import studio_package as sp  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


ET = pytz.timezone("US/Eastern")
sent, slack = [], []
LD = {}
sp._deps.update({
    "lead_data": LD,
    "send_email": lambda to, subject, html: (sent.append((to, subject)) or True),
    "post_slack": lambda ch, msg: slack.append((ch, msg)),
    "matt_channel": "#matt", "dev_channel": "#dev", "lara_channel": "#lara",
    "pipeline_event": lambda *a, **k: None,
    "report_error": lambda *a, **k: None,
})
# office hours by default: a Wednesday at 10:00 ET
sp._now_et = lambda: ET.localize(datetime(2026, 11, 18, 10, 0))

# ── 1. package kinds ────────────────────────────────────────────────────────
check("kind.ai_pro", sp.pitch_package_kind("AI Pro plan") == "ai_pro")
check("kind.ai_growth", sp.pitch_package_kind("ai growth") == "ai_growth")
check("kind.ai_starter", sp.pitch_package_kind("AI Starter") == "ai_starter")
check("kind.studio", sp.pitch_package_kind("Studio Package $1,200/month") == "studio_3mo")
check("kind.studio_words", sp.pitch_package_kind("3-month studio package") == "studio_3mo")
check("kind.trial", sp.pitch_package_kind("Studio Trial (1 month)") == "studio_trial_1mo")
check("kind.empty", sp.pitch_package_kind("") == "" and sp.pitch_package_kind(None) == "")
check("kind.other", sp.pitch_package_kind("Full Immersion video") == "other")
check("hours.weekday_10", sp.pitch_seq_in_hours(ET.localize(datetime(2026, 11, 18, 10, 0))))
check("hours.weekday_1759", sp.pitch_seq_in_hours(ET.localize(datetime(2026, 11, 18, 17, 59))))
check("hours.weekday_18", not sp.pitch_seq_in_hours(ET.localize(datetime(2026, 11, 18, 18, 0))))
check("hours.midnight", not sp.pitch_seq_in_hours(ET.localize(datetime(2026, 11, 13, 0, 6))))
check("hours.saturday", not sp.pitch_seq_in_hours(ET.localize(datetime(2026, 11, 14, 11, 0))))
check("hours.sunday", not sp.pitch_seq_in_hours(ET.localize(datetime(2026, 11, 15, 11, 0))))

# ── 2. the sequence ─────────────────────────────────────────────────────────
ago = lambda **k: (datetime.utcnow() - timedelta(**k)).isoformat()  # noqa: E731

# legacy record (armed before #280, no kind) -> halted, nothing sent, Michael told
LD["whatsapp:+10000000001"] = {"name": "Ayodele Pompey", "email": "ayo@x.com",
                               "studio_pitch": {"date": ago(hours=2), "next_stage": 0, "done": False}}
# AI Pro pitched -> halted
LD["whatsapp:+10000000002"] = {"name": "Ai Pro Lead", "email": "pro@x.com"}
sp.start_pitch_sequence("whatsapp:+10000000002", LD["whatsapp:+10000000002"], service="AI Pro plan")
LD["whatsapp:+10000000002"]["studio_pitch"]["date"] = ago(hours=2)
# 3-month package pitched 2h ago -> recap sent
LD["whatsapp:+10000000003"] = {"name": "Studio Lead", "email": "studio@x.com"}
sp.start_pitch_sequence("whatsapp:+10000000003", LD["whatsapp:+10000000003"], service="Studio Package $1,200/month")
LD["whatsapp:+10000000003"]["studio_pitch"]["date"] = ago(hours=2)
# 3-month package but held until tomorrow -> not sent
LD["whatsapp:+10000000004"] = {"name": "Held Lead", "email": "held@x.com"}
sp.start_pitch_sequence("whatsapp:+10000000004", LD["whatsapp:+10000000004"], service="Studio Package")
LD["whatsapp:+10000000004"]["studio_pitch"]["date"] = ago(hours=2)
LD["whatsapp:+10000000004"]["studio_pitch"]["hold_until"] = (datetime.utcnow() + timedelta(days=1)).isoformat()
# 3-month package, hold expired -> sent
LD["whatsapp:+10000000005"] = {"name": "Hold Over", "email": "over@x.com"}
sp.start_pitch_sequence("whatsapp:+10000000005", LD["whatsapp:+10000000005"], service="Studio Package")
LD["whatsapp:+10000000005"]["studio_pitch"]["date"] = ago(days=3)
LD["whatsapp:+10000000005"]["studio_pitch"]["hold_until"] = ago(hours=1)
# already bought -> done, nothing sent
LD["whatsapp:+10000000006"] = {"name": "Bought", "email": "b@x.com", "product": sp.PACKAGE_NAME}
sp.start_pitch_sequence("whatsapp:+10000000006", LD["whatsapp:+10000000006"], service="Studio Package")
LD["whatsapp:+10000000006"]["studio_pitch"]["date"] = ago(hours=2)

n = sp._sequence_pass()
check("seq.sent_count", n == 2, n)
check("seq.recipients", sorted(t for t, _ in sent) == ["over@x.com", "studio@x.com"], sent)
check("seq.recap_subject", any(s.startswith("Great meeting you") for _, s in sent), sent)
ayo = LD["whatsapp:+10000000001"]["studio_pitch"]
check("seq.legacy_halted", ayo.get("done") is True and isinstance(ayo.get("halted"), dict) and ayo["halted"]["kind"] == "unknown", ayo)
pro = LD["whatsapp:+10000000002"]["studio_pitch"]
check("seq.ai_pro_halted", pro.get("done") is True and pro["halted"]["kind"] == "ai_pro" and pro["package"] == "AI Pro plan", pro)
check("seq.halt_told_michael", sum(1 for ch, m in slack if ch == "#matt" and "HALTED" in m) == 2, slack)
check("seq.halt_message_names_plan", any("AI Pro plan" in m for _, m in slack) and any("no package recorded" in m for _, m in slack), slack)
check("seq.held_not_sent", LD["whatsapp:+10000000004"]["studio_pitch"]["next_stage"] == 0)
check("seq.studio_advanced", LD["whatsapp:+10000000003"]["studio_pitch"]["next_stage"] == 1)
check("seq.bought_done", LD["whatsapp:+10000000006"]["studio_pitch"]["done"] is True)

# outside office hours: nothing goes, nothing advances, nothing halted twice
sent.clear(); slack.clear()
LD["whatsapp:+10000000007"] = {"name": "Night Lead", "email": "night@x.com"}
sp.start_pitch_sequence("whatsapp:+10000000007", LD["whatsapp:+10000000007"], service="Studio Package")
LD["whatsapp:+10000000007"]["studio_pitch"]["date"] = ago(hours=2)
sp._now_et = lambda: ET.localize(datetime(2026, 11, 13, 0, 6))   # Fri 00:06
check("seq.midnight_waits", sp._sequence_pass() == 0 and not sent and LD["whatsapp:+10000000007"]["studio_pitch"]["next_stage"] == 0)
sp._now_et = lambda: ET.localize(datetime(2026, 11, 14, 23, 10))  # Sat 23:10
check("seq.saturday_waits", sp._sequence_pass() == 0 and not sent)
sp._now_et = lambda: ET.localize(datetime(2026, 11, 16, 9, 5))    # Mon 09:05
check("seq.monday_sends", sp._sequence_pass() == 2 and sorted(t for t, _ in sent) == ["night@x.com", "over@x.com"], sent)   # night: recap · over: value (day 2, was held)
check("seq.no_double_halt", not slack, slack)

# ── 3. app.py pins ──────────────────────────────────────────────────────────
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.report_passes_service", "_studio.start_pitch_sequence(_p39_key, _p39_rec, service=service)   # PATCH #280" in SRC)
check("app.old_call_gone", "_studio.start_pitch_sequence(_p39_key, _p39_rec)\n" not in SRC)
i = SRC.index('@app.route("/admin/pitch-seq", methods=["GET", "POST"])')
seg = SRC[i:i + 4000]
check("app.route_secret", '_admin_secret_ok(request.values.get("secret", ""))' in seg)
check("app.route_actions", '("status", "stop", "hold", "resume")' in seg and '"hold needs until=YYYY-MM-DD"' in seg)
check("app.route_hold_9am_et", 'hour=9, minute=0' in seg and '.astimezone(pytz.UTC).replace(tzinfo=None).isoformat()' in seg)
check("app.route_cap", 'len(_hits) > 3' in seg and 'lead_data[_k] = _nr' in seg)
check("app.route_tells_dev", 'via /admin/pitch-seq (Patch #280)' in seg)
SPS = open(os.path.join(HERE, "studio_package.py"), encoding="utf-8").read()
check("sp.copy_untouched", 'return ("Great meeting you at MWM Studios' in SPS and 'return ("Shall we reserve your studio dates?"' in SPS)
check("sp.guard_before_send", SPS.index("if _kind not in PITCH_SEQ_KINDS_WITH_COPY:") < SPS.index('subject, html = _seq_email(stage_name, first)'))

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 280) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(m.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE280 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
