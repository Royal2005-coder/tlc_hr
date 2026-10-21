"""Overtime rules and use cases without a site: the Labour Code limits, consent route and slip capping, with in-memory ports."""

import unittest
from datetime import date, time

from pydantic import ValidationError

from tlc_hr.application.overtime import OvertimeService
from tlc_hr.contracts.overtime import AssessOvertime, SlipRow
from tlc_hr.domain import overtime as rules
from tlc_hr.domain.ports import ICalendar, IDirectory, IOvertimeRepository
from tlc_hr.domain.shared import DomainError, NotAllowed

MONDAY, SUNDAY = date(2026, 11, 9), date(2026, 11, 8)


class Repository(IOvertimeRepository):
    def __init__(self, live=(), approved=None):
        self.live, self.approved = list(live), approved or {}

    def live_hours(self, employee, year, exclude):
        return [(d, h) for d, h in self.live if d.year == year]

    def approved_hours(self, employee, start, end):
        return {d: h for d, h in self.approved.items() if start <= d <= end}


class Calendar(ICalendar):
    def weekly_off(self, employee, day):
        return True if day.weekday() == 6 else None


class Directory(IDirectory):
    def __init__(self, line_manager=True, roles=()):
        self.line_manager, self.roles = line_manager, frozenset(roles)

    def proposer(self, user, employee):
        return rules.Proposer(user=user, roles=self.roles, is_line_manager=self.line_manager, is_department_head=False,
                              above_in_reporting_line=False)

    def user_of(self, employee):
        return "worker@x"


def command(day=MONDAY, start=time(17, 30), end=time(20, 30), proposing=True, active=True):
    return AssessOvertime(request=None, employee="E1", ot_date=day, from_time=start, to_time=end, actor="head@x", active=active,
                          proposing=proposing)


class TestRules(unittest.TestCase):
    def test_limits_of_the_labour_code(self):
        self.assertEqual(rules.problems(MONDAY, rules.WORKING_DAY, rules.Totals(3, 12, 80)), [])
        self.assertTrue(rules.problems(MONDAY, rules.WORKING_DAY, rules.Totals(4.5, 12, 80)))  # over half of 8 hours
        self.assertEqual(rules.problems(MONDAY, rules.REST_DAY, rules.Totals(12, 12, 80)), [])
        self.assertTrue(rules.problems(MONDAY, rules.HOLIDAY, rules.Totals(12.5, 13, 80)))
        self.assertTrue(rules.problems(MONDAY, rules.WORKING_DAY, rules.Totals(3, 41, 80)))
        self.assertTrue(rules.problems(MONDAY, rules.WORKING_DAY, rules.Totals(3, 20, 201)))

    def test_hours_over_midnight(self):
        self.assertEqual(rules.Slot(MONDAY, time(22), time(2)).hours(), 4)
        with self.assertRaises(DomainError):
            rules.check_hours(rules.Slot(MONDAY, time(18), time(18)))

    def test_sent_request_is_fixed(self):
        before = {"employee": "E1", "ot_date": "2026-11-09", "from_time": "17:30:00", "to_time": "20:30:00", "reason": "Kiểm kê"}
        rules.check_fixed(before, dict(before), sent=True)
        rules.check_fixed(before, {**before, "to_time": "21:00:00"}, sent=False)  # a draft may change
        with self.assertRaises(DomainError):
            rules.check_fixed(before, {**before, "to_time": "21:00:00"}, sent=True)

    def test_premium_free_of_tax(self):
        self.assertEqual(rules.premium_split({rules.WORKING_DAY: 6, rules.REST_DAY: 4, rules.HOLIDAY: 2}), (12, 6 * 0.5 + 4 * 1 + 2 * 2))


class TestService(unittest.TestCase):
    def test_a_working_day_request(self):
        result = OvertimeService(Repository(), Calendar(), Directory()).assess(command())
        self.assertEqual((result.hours, result.day_type, result.month_hours), (3, rules.WORKING_DAY, 3))

    def test_the_day_cap_counts_every_request_of_the_day(self):
        service = OvertimeService(Repository(live=[(MONDAY, 2)]), Calendar(), Directory())
        with self.assertRaises(DomainError) as caught:
            service.assess(command(start=time(19), end=time(21, 30)))  # 2 + 2.5 h
        self.assertEqual(caught.exception.code, "overtime.over_limit")

    def test_the_month_cap_counts_pending_requests(self):
        month = [(date(2026, 11, d), 4) for d in (2, 3, 4, 5, 6, 10, 11, 12, 13, 16)]  # 40 h
        service = OvertimeService(Repository(live=month), Calendar(), Directory())
        with self.assertRaises(DomainError):
            service.assess(command(day=date(2026, 11, 17), start=time(17), end=time(18)))
        service.assess(command(day=date(2026, 11, 17), start=time(17), end=time(18), active=False))  # a refused one is not counted

    def test_twelve_hours_on_a_sunday(self):
        result = OvertimeService(Repository(), Calendar(), Directory()).assess(command(day=SUNDAY, start=time(7), end=time(19)))
        self.assertEqual((result.day_type, result.hours), (rules.REST_DAY, 12))

    def test_only_the_people_of_the_proposer(self):
        with self.assertRaises(NotAllowed):
            OvertimeService(Repository(), Calendar(), Directory(line_manager=False)).assess(command())
        OvertimeService(Repository(), Calendar(), Directory(line_manager=False, roles=["TLC HR Officer"])).assess(command())
        OvertimeService(Repository(), Calendar(), Directory(line_manager=False)).assess(command(proposing=False))  # consenting

    def test_duplicate_slip_day_cannot_pay_the_same_approval_twice(self):
        service = OvertimeService(Repository(approved={MONDAY: 3}), Calendar(), Directory())
        with self.assertRaises(DomainError) as caught:
            service.cap_slip("E1", MONDAY, MONDAY, [SlipRow(day=MONDAY, hours=3), SlipRow(day=MONDAY, hours=3)])
        self.assertEqual(caught.exception.code, "overtime.duplicate_slip_day")

    def test_slip_rejects_negative_and_non_finite_hours(self):
        for hours in (-1.0, float("inf"), float("nan")):
            with self.subTest(hours=hours), self.assertRaises(ValidationError):
                SlipRow(day=MONDAY, hours=hours)

    def test_slip_pays_approved_hours_only(self):
        service = OvertimeService(Repository(approved={MONDAY: 3}), Calendar(), Directory())
        capped = service.cap_slip("E1", date(2026, 11, 1), date(2026, 11, 30),
                                  [SlipRow(day=MONDAY, hours=4.5), SlipRow(day=date(2026, 11, 10), hours=2)])
        self.assertEqual([(r.day, r.hours) for r in capped.rows], [(MONDAY, 3)])
        self.assertEqual(len(capped.notes), 2)


if __name__ == "__main__":
    unittest.main()
