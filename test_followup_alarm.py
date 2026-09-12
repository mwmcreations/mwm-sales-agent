#!/usr/bin/env python3
"""Tests for followup_alarm.py — Patch #141.

THE TEST THAT WOULD HAVE CAUGHT THIS
The rail was dead for seven days and the alarm was silent, because it measured
"has any email left the building" instead of "has anyone been followed up".
test_general_email_does_not_silence_the_alarm is that week, written down: due
work, transactional mail flowing normally, no follow-ups. The old logic
returned quiet. This one must page.
"""
import unittest
from datetime import datetime, timedelta

import pytz

import followup_alarm as fa

TZ = pytz.timezone("America/New_York")
NOW = TZ.localize(datetime(2026, 9, 12, 9, 0, 0))


def ago(days=0, hours=0):
    return NOW - timedelta(days=days, hours=hours)


class TestTheWeekThatWasMissed(unittest.TestCase):

    def test_general_email_does_not_silence_the_alarm(self):
        """🔴 THE REGRESSION. Sep 5-12: six follow-ups due, nothing followed up
        for 40 days, and booking confirmations going out every day. The old
        alarm read the shared send stamp, saw minutes, and stayed quiet."""
        s = fa.rail_state(NOW, due_count=6, last_followup_at=ago(days=40))
        self.assertTrue(s["alarm"])
        self.assertEqual(s["reason"], "due_work_and_no_followups")
        self.assertAlmostEqual(s["dry_days"], 40.0, places=1)

    def test_it_would_have_fired_on_day_two(self):
        """Not on day seven. The threshold is two days for a reason."""
        self.assertTrue(fa.rail_state(NOW, 5, ago(days=2))["alarm"])
        self.assertFalse(fa.rail_state(NOW, 5, ago(days=1, hours=23))["alarm"])

    def test_a_rail_that_is_moving_stays_quiet(self):
        s = fa.rail_state(NOW, due_count=3, last_followup_at=ago(hours=6))
        self.assertFalse(s["alarm"])
        self.assertEqual(s["reason"], "rail_moving")


class TestQuietIsNotTheSameAsBroken(unittest.TestCase):

    def test_no_work_due_never_pages(self):
        """A quiet rail with nothing owed is not a broken one, and paging here
        is how an alarm gets muted for the week it matters."""
        s = fa.rail_state(NOW, due_count=0, last_followup_at=ago(days=90))
        self.assertFalse(s["alarm"])
        self.assertEqual(s["reason"], "no_work_due")

    def test_never_sent_with_work_due_pages(self):
        s = fa.rail_state(NOW, due_count=4, last_followup_at=None)
        self.assertTrue(s["alarm"])
        self.assertGreaterEqual(s["dry_days"], fa.NEVER)

    def test_an_unreadable_stamp_refuses_to_decide(self):
        """🔑 Not evidence of health, and not evidence of failure. Saying so
        beats guessing in either direction."""
        s = fa.rail_state(NOW, due_count=4, last_followup_at="garbage")
        self.assertFalse(s["alarm"])
        self.assertEqual(s["reason"], "last_send_unreadable")

    def test_every_branch_states_a_reason(self):
        """An alarm that cannot say why is one nobody can act on."""
        cases = [
            (0, ago(days=90)), (3, ago(hours=1)), (3, ago(days=9)),
            (3, None), (3, "garbage"),
        ]
        for due, last in cases:
            self.assertIn("reason", fa.rail_state(NOW, due, last))
            self.assertTrue(fa.rail_state(NOW, due, last)["reason"])


class TestTheMessage(unittest.TestCase):

    def test_no_message_when_there_is_no_alarm(self):
        s = fa.rail_state(NOW, 0, ago(days=90))
        self.assertIsNone(fa.alarm_text(s, 0))

    def test_it_says_what_was_measured(self):
        """Six days were spent checking a send token that was never the
        problem, because the old page did not say what it had measured."""
        s = fa.rail_state(NOW, 6, ago(days=40))
        t = fa.alarm_text(s, 6)
        self.assertIn("followup_sent", t)
        self.assertIn("not from general outbound mail", t)

    def test_it_names_the_worst_lead(self):
        s = fa.rail_state(NOW, 6, ago(days=40))
        t = fa.alarm_text(s, 6, oldest_name="Dondrique Lewis", oldest_days=40.7)
        self.assertIn("Dondrique Lewis", t)
        self.assertIn("40.7", t)

    def test_never_reads_as_never_not_999_days(self):
        s = fa.rail_state(NOW, 4, None)
        self.assertIn("never", fa.alarm_text(s, 4).lower())
        self.assertNotIn("999", fa.alarm_text(s, 4))

    def test_it_counts_the_due_work(self):
        s = fa.rail_state(NOW, 6, ago(days=40))
        self.assertIn("6 follow-up(s) are DUE", fa.alarm_text(s, 6))


class TestDaysBetween(unittest.TestCase):

    def test_missing_either_side_is_none(self):
        self.assertIsNone(fa.days_between(NOW, None))
        self.assertIsNone(fa.days_between(None, NOW))

    def test_a_bad_type_is_none_not_an_exception(self):
        """This runs inside a daemon loop. A raise here kills the digest too."""
        self.assertIsNone(fa.days_between(NOW, "garbage"))

    def test_it_measures_forward(self):
        self.assertAlmostEqual(fa.days_between(NOW, ago(days=3)), 3.0, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
