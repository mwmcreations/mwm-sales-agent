"""PATCH #266 gate — the re-offer (new times + the video call) to leads who
never picked a time (ERIC's assignment, Mon 2 Nov: "run it on the current
unbooked pool"). Pure copy in lead_reply; POST /admin/reoffer (dry by
default, Michael's OK first); the numbered times remembered on the record so
"1"/"2" books that slot; Maya's prompt carries them for 7 days.
Then the #265 gate (→ test_slots → 263 → …)."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lead_reply as lr          # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
SL = [{"id": "2026-11-04T10:00:00-05:00", "display": "Wednesday, November 04 at 10:00 AM EST"},
      {"id": "2026-11-04T15:00:00-05:00", "display": "Wednesday, November 04 at 03:00 PM EST"}]

t = lr.reoffer_text("Dana Katz", SL, video=True)
check("copy.sms_video", t == ("Hi Dana, it's Maya from Michael Moraes' team at MWM Creations. Michael opened more times for your "
                              "studio visit: 1) Wed Nov 4, 10:00 AM 2) Wed Nov 4, 3:00 PM. If coming in is a stretch, he also does a "
                              "quick 15-min video call (Google Meet). Reply 1 or 2, or VIDEO, and I'll set it up."), t)
check("copy.sms_two_segments", len(t) <= 306 and t.isascii())
t0 = lr.reoffer_text("Dana Katz", SL)
check("copy.sms_no_video", "video" not in t0 and t0.endswith("Reply 1 or 2, or send a time that suits you.") and len(t0) <= 306, t0)
check("copy.sms_one_slot", "Reply YES, or VIDEO" in lr.reoffer_text("Dana", SL[:1], video=True))
check("copy.sms_no_slot", "send me a day and time" in lr.reoffer_text("Dana", [], video=False))
subj, html, txt = lr.reoffer_email("Dana Katz", SL, "1500 Park Center Dr", video=True)
check("copy.email_video", subj == "New times for your studio visit (or a 15-minute video call)" and "<ol><li>Wednesday, November 4 at 10:00 AM</li>" in html
      and "reply VIDEO" in txt and "Studio: 1500 Park Center Dr" in txt and "info@mwmcreations.com" in txt, (subj, txt[:120]))
subj0, html0, txt0 = lr.reoffer_email("Dana Katz", SL)
check("copy.email_no_video", subj0 == "New times for your studio visit" and "VIDEO" not in txt0 and "Studio:" not in txt0)
check("copy.email_no_links", "http" not in html and "href" not in html)

# ── app wiring ──────────────────────────────────────────────────────────────
check("app.route", "@app.route('/admin/reoffer', methods=['POST'])" in SRC)
rt = SRC[SRC.index("def admin_reoffer():"):SRC.index("@app.route('/admin/maya-offers'")]
check("app.secret_and_dry", "_admin_secret_ok(request.values.get(\"secret\", \"\"))" in rt and 'apply = str(request.values.get("apply") or "") in ("1", "true", "yes")' in rt
      and '"dry": not apply' in rt and "if not apply:\n            results.append(row)\n            continue" in rt)
check("app.several_leads", 'split(";")' in rt)
check("app.slots_from_calendar", "get_available_slots() or []" in rt and "[:2]" in rt)
check("app.video_from_switch", 'video = bool(offers.get("video_call"))' in rt and "_lrp.reoffer_text(name, slots, video=video)" in rt
      and "_lrp.reoffer_email(name, slots, STUDIO_ADDRESS, video=video)" in rt)
check("app.skips_booked_and_clients", '"skipped": "already booked"' in rt and '"skipped": "client, not a lead"' in rt)
check("app.channels_wa_then_sms_plus_email", "wa_send_eligibility(key, is_template=False)" in rt and "if phone and not wa_ok:" in rt
      and "kind=SMS_KIND_MARKETING" in rt and '_email_send(email, subj, html, via="reoffer", lead_key=key)' in rt)
check("app.remembers_offer", 'rec["offered_slots"] = slots' in rt and 'rec["reoffer_at"] = now.isoformat()' in rt and 'tw["offered_slots"] = slots' in rt)
check("app.tells_the_room", '_post_pipeline_event("REOFFER"' in rt and "Re-offer sent* (Michael's OK)" in rt and '"[RE-OFFER] {text}"' in rt)
check("app.prompt_block", "def _reoffer_prompt_block(sender):" in SRC and "_ro_block = _reoffer_prompt_block(sender)" in SRC
      and "TIMES YOU ALREADY OFFERED (HARD RULE)" in SRC and "REOFFER_PROMPT_DAYS = 7" in SRC
      and 'A reply of VIDEO means the 15-minute video call' in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch265.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not m:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print("FAIL #265 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("265: " + tail[-1])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE266 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
