"""Pure domain boundaries; no Frappe/site dependency."""
import unittest
from datetime import date, timedelta
from decimal import Decimal
from tlc_hr.domain.lifecycle import (add_working_days, completion_gate, deduction_count,
    effective_interval, final_balance, notice, probation_days, settlement_due)
from tlc_hr.domain.shared import DomainError


class LifecycleRulesTest(unittest.TestCase):
    def setUp(self):
        self.start = date(2026, 1, 5)
        self.working = lambda day: day.weekday() < 5

    def assertCode(self, code, fn, *args, **kwargs):
        with self.assertRaises(DomainError) as exc:
            fn(*args, **kwargs)
        self.assertEqual(exc.exception.code, code)

    def test_probation_calendar_limits_are_inclusive(self):
        for category, days in (("Enterprise manager", 180), ("College or higher", 60), ("Technical or vocational", 30)):
            with self.subTest(category=category):
                self.assertEqual(probation_days(category, self.start, self.start + timedelta(days=days-1), self.working), days)
                self.assertCode("OB-LIMIT", probation_days, category, self.start, self.start + timedelta(days=days), self.working)

    def test_other_work_counts_only_actual_working_days(self):
        self.assertEqual(probation_days("Other work", self.start, date(2026, 1, 12), self.working), 6)
        self.assertCode("OB-LIMIT", probation_days, "Other work", self.start, date(2026, 1, 13), self.working)

    def test_factory_sunday_is_not_assumed_a_holiday(self):
        self.assertCode("OB-LIMIT", probation_days, "Other work", self.start, self.start+timedelta(days=6), lambda day: True)

    def test_second_probation_for_same_job_rejected(self):
        self.assertCode("OB-ONCE", probation_days, "College or higher", self.start, self.start, self.working, repeated=True)

    def test_unknown_category_never_gets_permissive_default(self):
        self.assertCode("OB-CATEGORY", probation_days, "Manager", self.start, self.start, self.working)

    def test_probation_reversed_interval(self):
        self.assertCode("OB-DATES", probation_days, "College or higher", self.start, self.start-timedelta(days=1), self.working)

    def test_notice_calendar_45_and_30(self):
        for category, days in (("Indefinite", 45), ("Fixed 12-36 months", 30)):
            exact = self.start + timedelta(days=days)
            self.assertTrue(notice(category, self.start, exact, self.working).sufficient)
            result = notice(category, self.start, exact-timedelta(days=1), self.working)
            self.assertFalse(result.sufficient)
            self.assertEqual(result.earliest, exact)

    def test_three_working_days_skips_actual_holiday(self):
        submitted = date(2026, 1, 9)
        working = lambda day: day.weekday() < 5 and day != date(2026, 1, 12)
        result = notice("Fixed under 12 months", submitted, date(2026, 1, 14), working)
        self.assertFalse(result.sufficient)
        self.assertEqual(result.earliest, date(2026, 1, 15))

    def test_exception_requires_both_evidence_and_reviewer(self):
        for evidence, reviewer in (("", "hr"), ("/private/files/legal.pdf", "")):
            self.assertCode("EXIT-LEGAL", notice, "Indefinite", self.start, self.start, self.working,
                            "Statutory employee exception", evidence, reviewer)
        self.assertTrue(notice("Indefinite", self.start, self.start, self.working,
                               "Statutory employee exception", "/private/files/legal.pdf", "hr").sufficient)

    def test_unlisted_exception_not_accepted(self):
        self.assertCode("EXIT-EXCEPTION", notice, "Indefinite", self.start, self.start, self.working, "Emergency", "file", "hr")

    def test_normal_settlement_14_working_days(self):
        self.assertEqual(settlement_due(date(2026, 1, 9), self.working), date(2026, 1, 29))

    def test_extended_settlement_30_calendar_days(self):
        self.assertCode("EXIT-SETTLEMENT-LEGAL", settlement_due, self.start, self.working, True)
        self.assertEqual(settlement_due(self.start, self.working, True, "file", "hr"), date(2026, 2, 4))

    def test_completion_gate_lists_every_blocker(self):
        self.assertIsNone(completion_gate([]))
        self.assertCode("LC-INCOMPLETE", completion_gate, ["Laptop", "ERP account", "Settlement"])

    def test_effective_dates(self):
        effective_interval(self.start, None)
        effective_interval(self.start, self.start)
        self.assertCode("CORE-DATES", effective_interval, self.start, self.start-timedelta(days=1))

    def test_verified_dependents_only_effective_on_tax_day(self):
        rows = [{"status":"Verified", "valid_from":self.start, "valid_to":self.start},
                {"status":"Pending", "valid_from":self.start},
                {"status":"Verified", "valid_from":self.start+timedelta(days=1)},
                {"status":"Verified", "valid_from":self.start-timedelta(days=10), "valid_to":self.start-timedelta(days=1)}]
        self.assertEqual(deduction_count(rows, self.start), 1)

    def test_money_does_not_use_binary_float(self):
        self.assertEqual(final_balance("100.10", "2.20", "3.30", "4.40", "5.50"), Decimal("95.70"))
        self.assertCode("EXIT-AMOUNT", final_balance, 1, 0, 0, -1, 0)

    def test_invalid_calendar_fails_instead_of_hanging(self):
        self.assertCode("LC-CALENDAR", add_working_days, self.start, 1, lambda day: False)
