"""PATCH #245 gate - re-engagement safety (MAYA, 12 Oct): future bookings are
excluded, impossible addresses are refused, hard bounces suppress the address.
Prints "N passed, M failed", then runs the #244 gate (which chains on)."""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reengage as rg       # noqa: E402
import info_inbox as ii     # noqa: E402
from event_rail import deliverable_email   # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# deliverable_email
check("addr.ez_gmail_refused", deliverable_email("ez@gmail.com")[0] is False)
check("addr.short_googlemail", deliverable_email("abc12@googlemail.com")[0] is False)
check("addr.gmail_ok", deliverable_email("pastiche019@gmail.com")[0] is True)
check("addr.gmail_dots_tag", deliverable_email("j.o.h.n.d.o.e+studio@gmail.com")[0] is True)
check("addr.gmail_bad_char", deliverable_email("john_doe1@gmail.com")[0] is False)
check("addr.gmail_double_dot", deliverable_email("john..doe@gmail.com")[0] is False)
check("addr.other_domain_short_ok", deliverable_email("ez@icloud.com")[0] is True and deliverable_email("a@mwm.co")[0] is True)
check("addr.garbage", deliverable_email("not an email")[0] is False and deliverable_email("")[0] is False)

# bounce parsing
hard = {"from": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "subject": "Delivery Status Notification (Failure)",
        "snippet": "Address not found Your message wasn't delivered to ez@gmail.com because the address couldn't be found, or is unable to receive mail.",
        "failed": "ez@gmail.com"}
check("bounce.hard", ii.parse_bounce(hard) == "ez@gmail.com")
check("bounce.hard_no_header", ii.parse_bounce(dict(hard, failed="")) == "ez@gmail.com")
check("bounce.550", ii.parse_bounce({"from": "postmaster@outlook.com", "subject": "Undeliverable",
                                     "snippet": "550 5.1.1 User unknown <someone@company.com>"}) == "someone@company.com")
soft = {"from": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "subject": "Delivery Status Notification (Delay)",
        "snippet": "Message not delivered There was a temporary problem delivering your message to x@y.com. Gmail will retry for 46 more hours."}
check("bounce.soft_ignored", ii.parse_bounce(soft) is None)
check("bounce.full_ignored", ii.parse_bounce({"from": "mailer-daemon@googlemail.com", "subject": "Failure",
                                              "snippet": "The recipient's mailbox is full and can't accept messages now. x@y.com"}) is None)
check("bounce.person_ignored", ii.parse_bounce(dict(hard, **{"from": "Pastiche <pastiche019@gmail.com>"})) is None)
check("bounce.never_internal", ii.parse_bounce(dict(hard, failed="", snippet="Address not found ... info@mwmcreations.com")) is None)
check("bounce.query", "mailer-daemon" in ii.BOUNCE_QUERY and "newer_than:7d" in ii.BOUNCE_QUERY)

# future bookings
tz = pytz.timezone("America/New_York")
now = tz.localize(datetime(2026, 10, 12, 10, 0))
events = [
    {"summary": "Studio Visit - Pastiche Graham", "start": {"dateTime": "2027-04-02T13:30:00-04:00"},
     "attendees": [{"email": "Pastiche019@gmail.com", "responseStatus": "accepted"}]},
    {"summary": "Studio Visit - Old Person", "start": {"dateTime": "2026-09-01T10:00:00-04:00"},
     "attendees": [{"email": "old@x.com"}]},
    {"summary": "Bolfer shoot", "start": {"date": "2026-11-03"}, "description": "Client: Dr Bolfer\nContact Jane Roe"},
    {"summary": "Cancelled - Sam Lee", "status": "cancelled", "start": {"dateTime": "2026-12-01T10:00:00-05:00"},
     "attendees": [{"email": "sam@lee.com"}]},
    {"summary": "Declined", "start": {"dateTime": "2026-12-02T10:00:00-05:00"},
     "attendees": [{"email": "no@thanks.com", "responseStatus": "declined"}]},
]
idx = rg.future_booking_index(events, now)
check("fb.email", rg.has_future_booking("pastiche019@gmail.com", "", idx))
check("fb.name_title", rg.has_future_booking("", "Pastiche  Graham", idx))
check("fb.name_description", rg.has_future_booking("", "Jane Roe", idx))
check("fb.past_ignored", not rg.has_future_booking("old@x.com", "Old Person", idx))
check("fb.cancelled_ignored", not rg.has_future_booking("sam@lee.com", "Sam Lee", idx))
check("fb.declined_ignored", not rg.has_future_booking("no@thanks.com", "", idx))
check("fb.single_name_no_match", not rg.has_future_booking("", "Pastiche", idx))
check("fb.partial_word_no_match", not rg.has_future_booking("", "Ana Graham", idx))
check("fb.empty_index", not rg.has_future_booking("a@b.com", "A B", None))

# classify: bounced + deliverable
rec = {"name": "Anderson", "email": "ez@gmail.com", "phone": ""}
f = rg.classify("web:1", rec, now, deliverable=deliverable_email)
check("cls.undeliverable", f and f["email"] is False and f["email_addr"] == "")
f = rg.classify("web:2", {"name": "Real Person", "email": "realperson@gmail.com", "email_bounced": {"reason": "hard bounce"}}, now,
                deliverable=deliverable_email)
check("cls.bounced", f and f["email"] is False)
f = rg.classify("web:3", {"name": "Real Person", "email": "realperson@gmail.com"}, now, deliverable=deliverable_email)
check("cls.ok", f and f["email"] is True)

# static wiring
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
rows = SRC[SRC.index("def _reengage_rows(now):"):SRC.index("def _reengage_future_index(")]
check("wire.fail_closed", "_reengage_future_index(now)" in rows and "return []" in rows.split("_reengage_future_index(now)")[1][:600])
check("wire.fb_before_append", rows.index("_rg.has_future_booking(") < rows.index("rows.append(_f)"))
check("wire.deliverable_in_classify", "deliverable=deliverable_email" in rows)
api = SRC[SRC.index("# PATCH #245 — an address that cannot exist"):][:900]
check("wire.api_refuses", "deliverable_email(_folded)" in api and "400" in api)
sw = SRC[SRC.index("def _bounce_sweep_once():"):SRC.index("def _info_watch_thread():")]
check("wire.sweep_seen", "bounce_seen:%s" in sw and "info_inbox.parse_bounce(r)" in sw)
fl = SRC[SRC.index("def _flag_hard_bounce("):SRC.index("def _bounce_sweep_once():")]
check("wire.suppress_key", '"email_suppressed:" + addr' in fl and "email_bounced" in fl and " in str(_rec" not in fl)
th = SRC[SRC.index("def _info_watch_thread():"):][:600]
check("wire.thread_hook", "_bounce_sweep_once()" in th)
check("wire.mailboxes", "info@mwmcreations.com,michael@mwmcreations.com" in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch244.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #244 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("chain: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
