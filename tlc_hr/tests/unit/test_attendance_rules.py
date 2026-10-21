"""Attendance rules and use cases without a site: check-in, corrections, the lock and the monthly period, with an in-memory port."""

import unittest
from datetime import date, datetime

from pydantic import ValidationError

from tlc_hr.application.attendance import AttendanceService
from tlc_hr.contracts.attendance import Correction, PeriodKey
from tlc_hr.domain import approval
from tlc_hr.domain import attendance as rules
from tlc_hr.domain.attendance_ports import IAttendanceRepository
from tlc_hr.domain.shared import DomainError, NotAllowed

FACTORIES = ("Nhà máy 1", "Nhà máy 2", "Nhà máy 3")
TODAY = date(2026, 10, 21)


class Repository(IAttendanceRepository):
    def __init__(self, locked=None, open_items=(), tracking=True, located=True):
        self.locked, self._open, self.tracking, self._located = locked, list(open_items), tracking, located

    def factories(self):
        return FACTORIES

    def tracking_on(self):
        return self.tracking

    def located(self, employee, shift, at):
        return self._located

    def locked_period(self, employee, start, end):
        return ("TLC-KC-1", "Kỳ công 09/2026 · Nhà máy 1") if self.locked and start <= self.locked[1] and end >= self.locked[0] else None

    def shift_of(self, employee, day):
        return "TLC Ca đêm"

    def people(self, company, scope, start):
        return [rules.Person("E1", "Trần Văn Bình", "Nhà máy 1 - TLC"), rules.Person("E2", "Bùi Văn Phúc", "Nhà máy 1 - TLC")]

    def head_user(self, company, scope):
        return "hung@x" if scope in FACTORIES else None

    def marks(self, employees, start, end):
        return [rules.Mark("E1", "Present", True, False), rules.Mark("E1", "Absent", False, False), rules.Mark("E2", "Half Day", False, True)]

    def approved_overtime(self, employees, start, end):
        return [("E1", 3.0), ("E1", 2.5)]

    def approved_corrections(self, employees, start, end):
        return ["E2"]

    def open_items(self, employees, start, end):
        return self._open

    def other_period(self, key, name):
        return None


def correction(kind, to_date=date(2026, 10, 20), roles=("Employee",), is_new=True, explanation="Quên", shift=None, authorized=False):
    return Correction(employee="E1", from_date=to_date, to_date=to_date, kind=kind, shift=shift, explanation=explanation, is_new=is_new,
                      roles=frozenset(roles), today=TODAY, post_lock_creation_authorized=authorized)


class TestCheckin(unittest.TestCase):
    def test_outside_any_shift_or_site(self):
        with self.assertRaises(DomainError):
            AttendanceService(Repository()).check_in("E1", None, datetime(2026, 10, 21, 12))
        with self.assertRaises(DomainError):
            AttendanceService(Repository(located=False)).check_in("E1", "TLC Ca đêm", datetime(2026, 10, 21, 22))
        AttendanceService(Repository()).check_in("E1", "TLC Ca đêm", datetime(2026, 10, 21, 22))
        AttendanceService(Repository(tracking=False)).check_in("E1", None, datetime(2026, 10, 21, 12))


class TestCorrections(unittest.TestCase):
    def test_forgetting_is_declared_after_the_day(self):
        with self.assertRaises(DomainError):
            AttendanceService(Repository()).correct(correction("Quên chấm ra", to_date=date(2026, 10, 22)))
        self.assertEqual(AttendanceService(Repository()).correct(correction("Quên chấm ra")), "TLC Ca đêm")  # the shift of the day

    def test_post_lock_adjustment_is_written_by_hr_for_a_locked_day(self):
        locked = Repository(locked=(date(2026, 9, 1), date(2026, 9, 30)))
        with self.assertRaises(NotAllowed):
            AttendanceService(locked).correct(correction("Điều chỉnh sau chốt", to_date=date(2026, 9, 18)))
        with self.assertRaises(DomainError):
            AttendanceService(Repository()).correct(correction("Điều chỉnh sau chốt", to_date=date(2026, 9, 18), roles=("TLC HR Officer",)))
        with self.assertRaises(DomainError):
            AttendanceService(locked).correct(correction("Điều chỉnh sau chốt", to_date=date(2026, 9, 18), roles=("TLC HR Officer",),
                                                         explanation=" "))
        AttendanceService(locked).correct(correction("Điều chỉnh sau chốt", to_date=date(2026, 9, 18), roles=("TLC HR Officer",)))
        AttendanceService(locked).correct(correction("Điều chỉnh sau chốt", to_date=date(2026, 9, 18), is_new=False))  # the manager decides
        AttendanceService(locked).correct(correction("Điều chỉnh sau chốt", to_date=date(2026, 9, 18), authorized=True))
        with self.assertRaises(DomainError):
            AttendanceService(Repository()).correct(correction("Điều chỉnh sau chốt", authorized=True))


class TestLock(unittest.TestCase):
    def test_a_locked_day_refuses_changes_but_the_adjustment(self):
        service = AttendanceService(Repository(locked=(date(2026, 9, 1), date(2026, 9, 30))))
        with self.assertRaises(DomainError) as caught:
            service.check_unlocked("E1", date(2026, 9, 4), date(2026, 9, 4))
        self.assertEqual(caught.exception.code, "lock.locked")
        service.check_unlocked("E1", date(2026, 9, 4), date(2026, 9, 4), post_lock_adjustment=True)
        service.check_unlocked("E1", date(2026, 10, 4), date(2026, 10, 4))


class TestCalendarContracts(unittest.TestCase):
    def test_carried_leave_uses_march_30_including_leap_year(self):
        for year in (2027, 2028, 2100):
            self.assertEqual(rules.carry_forward_expiry(date(year, 1, 1), date(year, 12, 31)), date(year, 3, 30))
        self.assertEqual(rules.carry_forward_expiry(date(2028, 1, 1), date(2028, 2, 20)), date(2028, 2, 20))
        with self.assertRaises(DomainError):
            rules.carry_forward_expiry(date(2028, 4, 1), date(2028, 12, 31))

    def test_invalid_period_month_is_a_contract_error(self):
        for month in ("2026-13", "2026-9", "0000-01", "x"):
            with self.subTest(month=month), self.assertRaises(ValidationError):
                PeriodKey(company="TLC", scope="Hội sở", month=month)

    def test_correction_dates_must_be_ordered(self):
        with self.assertRaises(ValidationError):
            Correction(employee="E1", from_date=date(2026, 10, 20), to_date=date(2026, 10, 19), kind=None, shift=None,
                       explanation=None, is_new=True, roles=frozenset(), today=TODAY)


class TestPeriod(unittest.TestCase):
    def test_summary_per_person(self):
        summary = AttendanceService(Repository()).summarize(PeriodKey(company="TLC Demo", scope="Nhà máy 1", month="2026-09"))
        e1 = next(r for r in summary.rows if r.employee == "E1")
        self.assertEqual((e1.present_days, e1.absent_days, e1.late_count, e1.ot_hours), (1, 1, 1, 5.5))
        self.assertEqual((summary.title, str(summary.to_date), summary.manager_user), ("Kỳ công 09/2026 · Nhà máy 1", "2026-09-30", "hung@x"))
        self.assertEqual((summary.totals["half_days"], next(r for r in summary.rows if r.employee == "E2").corrections), (1, 1))

    def test_moving_on_needs_nothing_open_and_returning_needs_a_reason(self):
        with self.assertRaises(DomainError):
            rules.check_move(rules.DRAFT, rules.TO_HEAD, ["HR-ARQ-1 · Bình · Giải trình chưa duyệt xong"], None)
        self.assertIsNone(rules.check_move(rules.DRAFT, rules.TO_HEAD, [], None))
        with self.assertRaises(DomainError):
            rules.check_move(rules.TO_HEAD, rules.DRAFT, [], "")
        self.assertEqual(rules.check_move(rules.TO_HEAD, rules.DRAFT, [], "Thiếu ca đêm"), rules.TO_HEAD)
        with self.assertRaises(DomainError):
            rules.check_reopen(None)

    def test_scope_of_a_department(self):
        self.assertEqual(rules.scope_of_department("Nhà máy 2 - TLC", FACTORIES), "Nhà máy 2")
        self.assertEqual(rules.scope_of_department("Kinh doanh - TLC", FACTORIES), rules.HEAD_OFFICE)


class TestApproval(unittest.TestCase):
    def test_reject_needs_a_reason_and_records_the_stage(self):
        change = approval.StateChange(before="Chờ quản lý duyệt", after="Từ chối", reason="", actor="hung@x", subject="binh@x")
        with self.assertRaises(DomainError):
            approval.rejected_stage(change)
        self.assertEqual(approval.rejected_stage(approval.StateChange("Chờ quản lý duyệt", "Từ chối", "Trùng ca", "hung@x", "binh@x")),
                         "Chờ quản lý duyệt")

    def test_nobody_decides_about_themself(self):
        with self.assertRaises(NotAllowed):
            approval.check_not_self(approval.StateChange("Chờ nhân sự duyệt", "Đã duyệt", None, "hoa@x", "hoa@x"))
        approval.check_not_self(approval.StateChange("Nháp", "Chờ quản lý duyệt", None, "hoa@x", "hoa@x"))  # sending is not deciding


if __name__ == "__main__":
    unittest.main()
