"""Unit tests for pure internal-service business rules."""
import unittest
from datetime import date, timedelta
from tlc_hr.domain.services import (
    require,
    transition,
    working_due,
    working_elapsed,
    intervals_overlap,
    meal_cutoff,
    SERVICE_EDGES,
    LOAN_EDGES,
    MAIL_EDGES,
)
from tlc_hr.domain.shared import DomainError


class TestServiceRules(unittest.TestCase):
    def test_sla_working_days(self):
        start = date(2026, 6, 1)  # Monday
        holidays = {date(2026, 6, 2)}  # Tuesday holiday
        calendar_end = date(2026, 6, 30)

        # 2 working days: skip June 2 -> June 3 (day 1), June 4 (day 2)
        due = working_due(start, 2, holidays, calendar_end)
        self.assertEqual(due, date(2026, 6, 4))

        # Invalid SLA days
        with self.assertRaises(DomainError) as ctx:
            working_due(start, 0, holidays, calendar_end)
        self.assertEqual(ctx.exception.code, "sla_days")

        # Exceeds calendar end
        with self.assertRaises(DomainError) as ctx:
            working_due(start, 50, holidays, calendar_end)
        self.assertEqual(ctx.exception.code, "calendar_missing")

    def test_working_elapsed(self):
        start = date(2026, 6, 1)
        end = date(2026, 6, 5)
        holidays = {date(2026, 6, 3)}
        # Days 2, 4, 5 are working (3 days)
        elapsed = working_elapsed(start, end, holidays)
        self.assertEqual(elapsed, 3)

    def test_intervals_overlap(self):
        t1, t2 = date(2026, 6, 1), date(2026, 6, 5)
        self.assertTrue(intervals_overlap(t1, t2, date(2026, 6, 3), date(2026, 6, 7)))
        self.assertFalse(intervals_overlap(t1, t2, date(2026, 6, 5), date(2026, 6, 8)))  # Adjacent
        self.assertFalse(intervals_overlap(t1, t2, date(2026, 5, 20), date(2026, 6, 1)))  # Adjacent before
        self.assertTrue(intervals_overlap(t1, t2, date(2026, 6, 2), date(2026, 6, 3)))  # Contained

    def test_meal_cutoff(self):
        today = date(2026, 6, 1)
        tomorrow = date(2026, 6, 2)
        # Advance booking allowed for anyone
        meal_cutoff(tomorrow, today, hr=False, reason="")

        # Same-day or past requires HR with a reason
        with self.assertRaises(DomainError) as ctx:
            meal_cutoff(today, today, hr=False, reason="Muộn")
        self.assertEqual(ctx.exception.code, "meal_cutoff")

        with self.assertRaises(DomainError) as ctx:
            meal_cutoff(today, today, hr=True, reason="")
        self.assertEqual(ctx.exception.code, "meal_cutoff")

        # HR with reason succeeds
        meal_cutoff(today, today, hr=True, reason="Đột xuất duyệt thêm suất ăn")

    def test_state_transitions(self):
        # Service transitions
        transition("Requested", "Processing", SERVICE_EDGES)
        transition("Processing", "Waiting Information", SERVICE_EDGES)
        transition("Waiting Information", "Processing", SERVICE_EDGES)
        transition("Processing", "Resolved", SERVICE_EDGES)
        transition("Resolved", "Closed", SERVICE_EDGES)

        with self.assertRaises(DomainError) as ctx:
            transition("Requested", "Closed", SERVICE_EDGES)
        self.assertEqual(ctx.exception.code, "invalid_transition")

        # Loan transitions
        transition("Requested", "Lent", LOAN_EDGES)
        transition("Lent", "Returned", LOAN_EDGES)
        with self.assertRaises(DomainError):
            transition("Returned", "Lent", LOAN_EDGES)

        # Mail transitions
        transition("Need Dispatch", "With Courier", MAIL_EDGES)
        transition("With Courier", "Delivered", MAIL_EDGES)
        with self.assertRaises(DomainError):
            transition("Delivered", "With Courier", MAIL_EDGES)


if __name__ == "__main__":
    unittest.main()
