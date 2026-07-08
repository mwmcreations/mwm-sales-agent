"""Jul 8 2026 matcher-fix regression tests (Robinson incident).

Bug: '/meeting-report' parsed "Studio Visit — Dr. Scott Robinson (...)" with the
LEFT side as the lead name -> matcher searched for a lead called "Studio Visit"
-> match impossible -> follow-up sequence never armed.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from meeting_report_utils import parse_event_summary, extract_emails, booking_status_for

FAIL = 0
def check(label, got, want):
    global FAIL
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}: {label} -> {got!r}")
    if not ok:
        FAIL += 1
        print(f"      expected {want!r}")

# 1. The exact Robinson title (the incident)
check("Robinson incident title",
      parse_event_summary("Studio Visit — Dr. Scott Robinson (There Are No Lines In Heaven)"),
      ("Dr. Scott Robinson", "There Are No Lines In Heaven"))

# 2. Type on the left with plain hyphen
check("hyphen type-first", parse_event_summary("Studio Visit - Jane Doe"), ("Jane Doe", ""))

# 3. Classic "Name - Business" must NOT regress
check("name-first with business", parse_event_summary("Marta Villagra - Coaching Content"),
      ("Marta Villagra", "Coaching Content"))

# 4. Legacy prefix format
check("legacy prefix", parse_event_summary("Meeting with John Smith"), ("John Smith", ""))

# 5. No separator at all
check("no separator", parse_event_summary("Reunião SMILE AMERICAN"), ("Reunião SMILE AMERICAN", ""))

# 6. Parenthesized business without separator
check("parens only", parse_event_summary("Camila Silveira (Camila Beauty)"),
      ("Camila Silveira", "Camila Beauty"))

# 7. Case-insensitive email extraction (the 'Healer2bsure@' vs 'healer2bsure@' miss)
check("email extraction", extract_emails("His e-mail: Healer2bsure@gmail.com — follow up."),
      {"healer2bsure@gmail.com"})

# 8. Multiple + none
check("two emails", extract_emails("a@b.co and C.D+x@E-f.org"), {"a@b.co", "c.d+x@e-f.org"})
check("no emails", extract_emails("no address here"), set())

# 9. Booking status vocabulary (Bug #1 stage-sync)
check("studio visit status", booking_status_for("studio_visit"), "✅ Studio Visit Booked")
check("strategy call status", booking_status_for("strategy_call"), "📞 Strategy Call Booked")

print(f"\n{'ALL TESTS PASS' if FAIL == 0 else str(FAIL) + ' FAILURES'}")
sys.exit(1 if FAIL else 0)
