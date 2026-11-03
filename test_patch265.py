"""PATCH #265 gate — Maya offers from the whole open day, and a 15-minute
video call (Michael, Mon 2 Nov 21:30, via ERIC in #dev: "Maya can and should
always offer visit time based on our calendar. not only Thursdays or Fridays.
and the 15-minute video call is definitely an option.")

1. slots: extended=False is byte-for-byte the old behaviour; extended=True
   adds the rest of the open hours (9, 12, 13, 16) AFTER the house four, in
   the 48 h window chronologically, in the nearest-fallback house-first; a
   closed (all-day busy) day is skipped, not the week.
2. event_rail: KIND_VIDEO_CALL — title, ladder plan, virtual venue, client
   description with the join link, ladder copy that says "video call" and
   carries the link where a visit carries the address, 15-minute booking
   type, no phone number required.
3. app.py wiring: tool enum, 15-minute event, Meet room request on insert
   (and a refusal does not lose the booking), link written back, booking
   reply carries the link, CAPI StudioVisitBooked(content_name=video_call)
   + companion VideoCallBooked, ladder kinds/copy/templates, the prompt
   block only while the switch is on, both switches OFF by default,
   /admin/maya-offers, /health.
Then test_slots, then the #263 gate (→ 262 → …)."""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import slots as sl               # noqa: E402
import event_rail as er          # noqa: E402

try:
    import pytz
    TZ = pytz.timezone("America/New_York")

    def _loc(dt):
        return TZ.localize(dt)
except Exception:
    from datetime import timezone
    TZ = timezone(timedelta(hours=-5))

    def _loc(dt):
        return dt.replace(tzinfo=TZ)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()


def busy(y, m, d, h1, h2):
    return {"start": _loc(datetime(y, m, d, h1, 0)).isoformat(), "end": _loc(datetime(y, m, d, h2, 0)).isoformat()}


def hours(slots):
    return [datetime.fromisoformat(s["id"]).strftime("%a %H:%M") for s in slots]


# ── 1 · slots ───────────────────────────────────────────────────────────────
check("slots.extra_times", sl.EXTRA_SLOT_TIMES == [(9, 0), (12, 0), (13, 0), (16, 0)])
check("slots.house_first", sl.slot_times_for("morning", extended=True) == [(10, 0), (11, 0), (15, 0), (14, 0), (9, 0), (12, 0), (13, 0), (16, 0)]
      and sl.slot_times_for("morning") == [(10, 0), (11, 0), (15, 0), (14, 0)])
check("slots.all_times", sl.all_slot_times() == [(10, 0), (11, 0), (14, 0), (15, 0)]
      and sl.all_slot_times(True) == [(9, 0), (10, 0), (11, 0), (12, 0), (13, 0), (14, 0), (15, 0), (16, 0)])
# Tuesday 3 Nov 2026 11:30. Today the house times are gone (2–4 PM busy kills
# 1 PM and 4 PM through the buffer), tomorrow and Thursday are solid.
now = _loc(datetime(2026, 11, 3, 11, 30))
taken = [busy(2026, 11, 3, 14, 16), busy(2026, 11, 4, 9, 17), busy(2026, 11, 5, 9, 17)]
old_s, old_fb = sl.offer_slots(now, taken, TZ)
new_s, new_fb = sl.offer_slots(now, taken, TZ, extended=True)
check("slots.old_unchanged_without_flag", old_fb is True and hours(old_s) == ["Fri 10:00", "Mon 15:00"], (old_fb, hours(old_s)))
check("slots.extended_fills_today", new_fb is False and hours(new_s) == ["Tue 12:00"], (new_fb, hours(new_s)))
# nothing inside 48 h at all: nearest, house times first, then the rest of the day
blocked = [busy(2026, 11, 3, 9, 17), busy(2026, 11, 4, 9, 17),
           {"start": _loc(datetime(2026, 11, 5, 9, 0)).isoformat(), "end": _loc(datetime(2026, 11, 5, 12, 30)).isoformat()},
           {"start": _loc(datetime(2026, 11, 5, 14, 30)).isoformat(), "end": _loc(datetime(2026, 11, 5, 17, 0)).isoformat()}]
fb_s, fb = sl.offer_slots(now, blocked, TZ, extended=True)
check("slots.fallback_house_first_then_extra", fb is True and hours(fb_s) == ["Thu 13:00", "Fri 15:00"], (fb, hours(fb_s)))
fb_old, _ = sl.offer_slots(now, blocked, TZ)
check("slots.fallback_old_skips_thursday", hours(fb_old) == ["Fri 10:00", "Mon 15:00"], hours(fb_old))
# a closed day (all-day Busy) is skipped, the week is not
closed_wed = sl.busy_row({"start": {"date": "2026-11-04"}, "end": {"date": "2026-11-05"}}, TZ)
cs, cfb = sl.offer_slots(_loc(datetime(2026, 11, 3, 17, 0)), [closed_wed], TZ, extended=True)
check("slots.closed_day_skipped", cfb is False and hours(cs) == ["Thu 09:00", "Thu 10:00", "Thu 11:00"], (cfb, hours(cs)))
check("slots.compute_signature", "extended=False" in open(os.path.join(HERE, "slots.py")).read())

# ── 2 · event_rail ──────────────────────────────────────────────────────────
check("er.kind", er.KIND_VIDEO_CALL == "video_call" and er.VIDEO_CALL_MINUTES == 15)
k, is_client, why = er.classify_event({"summary": "Video Call — Dana Katz"})
check("er.classify_title", k == er.KIND_VIDEO_CALL and is_client is True, (k, why))
check("er.classify_hyphen", er.classify_event({"summary": "Video Call - Dana Katz"})[0] == er.KIND_VIDEO_CALL)
check("er.strategy_unchanged", er.classify_event({"summary": "Strategy Call — X"})[0] == er.KIND_STRATEGY_CALL
      and er.classify_event({"summary": "Studio Visit — X"})[0] == er.KIND_STUDIO_VISIT)
check("er.plan", er.CONFIRMATION_PLAN[er.KIND_VIDEO_CALL] == [("client", 48), ("client", 24), ("client", 2)])
check("er.venue_virtual", er.EVENT_VENUE[er.KIND_VIDEO_CALL] == er.VENUE_VIRTUAL and er.venue_of(er.KIND_VIDEO_CALL) == er.VENUE_VIRTUAL)
d = er.client_description(er.KIND_VIDEO_CALL, virtual_note="https://meet.google.com/abc-defg-hij", callback_number="+14075551234")
check("er.description_link", d.startswith("Video call (15 minutes) with Michael Moraes") and "Join here at the time above: https://meet.google.com/abc-defg-hij" in d
      and "can call you at +14075551234 instead" in d and "1500 Park" not in d, d)
d2 = er.client_description(er.KIND_VIDEO_CALL)
check("er.description_no_link_yet", "The video link arrives with your confirmation." in d2)
check("er.strategy_description_unchanged", er.client_description(er.KIND_STRATEGY_CALL, callback_number="+1").startswith("Strategy call with Michael Moraes"))
wa2, sub2, html2 = er.confirmation_copy(2, "Dana", "Wednesday, November 04", "10:00 AM", "https://meet.google.com/abc", kind=er.KIND_VIDEO_CALL)
check("er.copy_t2_video", wa2 == "Hi Dana! Your video call with Michael Moraes is today at 10:00 AM. Join: https://meet.google.com/abc Reply here if anything changes."
      and "video call" in sub2 and 'href="https://meet.google.com/abc"' in html2 and "Address" not in html2, wa2)
wa24, sub24, _ = er.confirmation_copy(24, "Dana", "Wednesday, November 04", "10:00 AM", "https://meet.google.com/abc", kind=er.KIND_VIDEO_CALL)
check("er.copy_t24_video", wa24.startswith("Hi Dana! Maya from MWM Creations here") and "Reply YES to confirm your video call with Michael tomorrow at 10:00 AM" in wa24
      and "Join: https://meet.google.com/abc" in wa24, wa24)
wa48, _, _ = er.confirmation_copy(48, "Dana", "Thursday, November 05", "10:00 AM", "", kind=er.KIND_VIDEO_CALL)
check("er.copy_t48_video_no_link", "video call with Michael" in wa48 and "Join:" not in wa48, wa48)
wa_v, _, _ = er.confirmation_copy(2, "Dana", "Wednesday, November 04", "10:00 AM", "1500 Park Center Dr")
check("er.copy_visit_unchanged", wa_v == "Hi Dana! See you at 10:00 AM today for your visit with Michael Moraes — 1500 Park Center Dr. Reply here if anything changes.", wa_v)
check("er.booking_type", er.BOOKING_TYPES["video_call"]["kind"] == er.KIND_VIDEO_CALL and er.BOOKING_TYPES["video_call"]["default_minutes"] == 15
      and er.BOOKING_TYPES["video_call"]["title"] == "Video Call - {name}" and er.BOOKING_TYPE_ORDER.index("video_call") == 2)
check("er.no_number_needed", er.booking_needs_number("video_call") is False and er.resolve_callback_number("video_call", identifier="instagram:123")[0] is True
      and er.booking_needs_number("strategy_call") is True)

# ── 3 · app wiring ──────────────────────────────────────────────────────────
check("app.enum_both_tools", SRC.count('"enum": ["studio_visit", "strategy_call", "video_call"]') == 2 and SRC.count('"enum": ["studio_visit", "strategy_call"]') == 0)
check("app.call_kind", 'return appointment_type in ("strategy_call", "video_call")' in SRC)
bk = SRC[SRC.index("def book_appointment(slot_id, lead_name"):SRC.index("def _cleanup_norm(s):") if SRC.index("def _cleanup_norm(s):") > SRC.index("def book_appointment(slot_id, lead_name") else SRC.index("def check_specific_slot(")]
bk = SRC[SRC.index("def book_appointment(slot_id, lead_name"):SRC.index("def check_specific_slot(")]
check("app.fifteen_minutes", "event_rail.VIDEO_CALL_MINUTES" in bk and 'if appointment_type == "video_call" else 60' in bk)
check("app.title_and_kind", 'event_title = f"Video Call — {lead_name}"' in bk and "else event_rail.KIND_VIDEO_CALL if _video" in bk)
check("app.meet_request", '"conferenceSolutionKey": {"type": "hangoutsMeet"}' in bk and '_ins["conferenceDataVersion"] = 1' in bk)
check("app.meet_refusal_keeps_booking", 'if event.get("conferenceData") and "conference" in str(_conf_err).lower():' in bk
      and 'event.pop("conferenceData", None)' in bk)
check("app.meet_link_written_back", 'created.get("hangoutLink")' in bk and '_priv["meet_url"] = _meet_url[:300]' in bk and "_VIDEO_CALL_LINKS[created[\"id\"]]" in bk)
check("app.location_is_link_or_fallback", "(_meet_url or VIDEO_CALL_LOCATION_FALLBACK) if _video" in bk and bk.count("VIDEO_CALL_LOCATION_FALLBACK") >= 2)
check("app.description_link", "virtual_note=(_meet_url or None) if _video else None" in bk)
hd = SRC[SRC.index('    elif tool_name == "book_appointment":'):SRC.index('    elif tool_name == "cancel_appointment":')]
check("app.reply_carries_link", 'if tool_input.get("appointment_type") == "video_call":' in hd and '_out["meet_link"] = _link' in hd
      and "Give the lead this Google Meet link in your reply" in hd)
check("app.capi_stage_keeps_signal", '_capi_stage(_capi_key, lead_data[_capi_key], _capi.STAGE_BOOKED,' in hd and '"content_name": appt_type' in hd)
check("app.capi_companion", '"VideoCallBooked",' in hd and 'event_id=f"{sender}:VideoCallBooked"' in hd and "_capi.is_test_record(_rec)" in hd)
lad = SRC[SRC.index("def _lead_reminder_thread"):SRC.index("def _lead_reminder_thread") + 60000]
check("app.ladder_kinds", "event_rail.KIND_VIDEO_CALL)" in lad and "kind=kind)" in lad)
check("app.ladder_skips_visit_template_for_video", "elif _wt.stage_template(stage_h) and _wa_visit_template_send(" in lad
      and "if kind != event_rail.KIND_VIDEO_CALL else False:" in lad)
check("app.prompt_block_gated", "def _video_call_prompt_block():" in SRC and 'VIDEO_CALL_PROMPT_BLOCK if _maya_offers().get("video_call") else ""' in SRC
      and "_vc_block = _video_call_prompt_block()" in SRC)
check("app.prompt_wording", "VIDEO CALL OPTION (ON" in SRC and "15-MINUTE VIDEO CALL with Michael (Google Meet)" in SRC
      and 'appointment_type="video_call" — no phone number is needed' in SRC and "The studio visit stays the first offer" in SRC)
check("app.switches_default_off", 'os.getenv("MAYA_VIDEO_CALL", "off")' in SRC and 'os.getenv("MAYA_EXTENDED_HOURS", "off")' in SRC)
check("app.slots_flag", 'extended=bool(_maya_offers().get("extended_hours")),' in SRC)
check("app.route_and_health", "@app.route('/admin/maya-offers'" in SRC and '"maya_offers": _maya_offers(),' in SRC
      and '_pgs.save_state("maya_offers", cur)' in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
for gate, tag in (("test_slots.py", "slots"), ("test_patch263.py", "263")):
    r_ = subprocess.run([sys.executable, os.path.join(HERE, gate)], capture_output=True, text=True)
    out = r_.stdout.strip().splitlines()
    if gate == "test_slots.py":
        m = re.search(r"SLOTS \(Patch #94\): (\d+) passed, (\d+) failed", r_.stdout)
    else:
        tail = [l for l in out if l.startswith("TOTAL ")]
        m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
    if not m:
        print(r_.stdout[-1200:]); print(r_.stderr[-600:])
        failed += 1; print(f"FAIL {gate} did not report")
    else:
        passed += int(m.group(1)); failed += int(m.group(2))
        print(f"{tag}: {m.group(1)} passed, {m.group(2)} failed")
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE265 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
