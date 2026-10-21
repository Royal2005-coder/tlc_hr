"""Overtime use cases: assess a request being saved; cut an HRMS Overtime Slip to the approved hours."""

from datetime import date

from tlc_hr.contracts.overtime import AssessOvertime, CappedSlip, OvertimeAssessment, SlipRow
from tlc_hr.domain import overtime as rules
from tlc_hr.domain.ports import ICalendar, IDirectory, IOvertimeRepository
from tlc_hr.domain.shared import DomainError


class OvertimeService:
    def __init__(self, repository: IOvertimeRepository, calendar: ICalendar, directory: IDirectory):
        self._repository = repository
        self._calendar = calendar
        self._directory = directory

    def assess(self, command: AssessOvertime) -> OvertimeAssessment:
        """Hours, kind of day and totals of the request; raises DomainError / NotAllowed when it breaks a rule."""
        hours = rules.check_hours(rules.Slot(command.ot_date, command.from_time, command.to_time))
        day_type = rules.day_type_of(self._calendar.weekly_off(command.employee, command.ot_date))
        others = self._repository.live_hours(command.employee, command.ot_date.year, command.request)
        totals = rules.Totals(
            day=hours + sum(h for d, h in others if d == command.ot_date),
            month=hours + sum(h for d, h in others if d.month == command.ot_date.month),
            year=hours + sum(h for _d, h in others),
        )
        if command.active:
            rules.check_limits(command.ot_date, day_type, totals)
        if command.proposing:
            rules.check_proposer(self._directory.proposer(command.actor, command.employee))
        return OvertimeAssessment(hours=hours, day_type=day_type, day_hours=totals.day, month_hours=totals.month, year_hours=totals.year)

    def cap_slip(self, employee: str, start: date, end: date, rows: list[SlipRow]) -> CappedSlip:
        """Each day of the slip is cut to the approved hours of that day; days without an approved request are dropped
        (staying late without a request is not overtime). The notes say what was cut."""
        if len({row.day for row in rows}) != len(rows):
            raise DomainError("overtime.duplicate_slip_day", "Một ngày chỉ được có một dòng tăng ca trên phiếu.")
        approved = self._repository.approved_hours(employee, start, end)
        kept, notes = [], []
        for row in rows:
            cap = approved.get(row.day, 0)
            if cap <= 0:
                notes.append(f"{row.day:%d-%m-%Y}: {row.hours:g} giờ ngoài ca không có đơn tăng ca được duyệt, không tính")
                continue
            if row.hours > cap:
                notes.append(f"{row.day:%d-%m-%Y}: {row.hours:g} giờ ngoài ca, chỉ tính {cap:g} giờ đã duyệt")
            kept.append(SlipRow(day=row.day, hours=min(row.hours, cap)))
        return CappedSlip(rows=kept, notes=notes)
