"""Attendance use cases: check-in, correction, the lock of a closed month and the monthly period."""

from datetime import datetime

from tlc_hr.contracts.attendance import Correction, PeriodKey, PeriodRow, PeriodSummary
from tlc_hr.domain import attendance as rules
from tlc_hr.domain.attendance_ports import IAttendanceRepository


class AttendanceService:
    def __init__(self, repository: IAttendanceRepository):
        self._repository = repository

    def check_in(self, employee: str, shift: str | None, at: datetime) -> None:
        tracking = self._repository.tracking_on()
        located = bool(shift) and tracking and self._repository.located(employee, shift, at)
        rules.check_checkin(tracking, shift, located)

    def correct(self, correction: Correction) -> str | None:
        """Check a correction; returns the shift it must carry (HRMS updates the attendance of the same shift only)."""
        locked = correction.kind == rules.POST_LOCK and bool(
            self._repository.locked_period(correction.employee, correction.from_date, correction.to_date))
        rules.check_correction(correction.kind, correction.to_date, correction.today, correction.is_new, correction.roles, locked,
                               correction.explanation, correction.post_lock_creation_authorized)
        return correction.shift or self._repository.shift_of(correction.employee, correction.from_date)

    def check_unlocked(self, employee: str, start, end, post_lock_adjustment: bool = False) -> None:
        period = self._repository.locked_period(employee, start, end)
        rules.check_lock(period[1] if period else None, post_lock_adjustment)

    def scope(self, department: str | None) -> str:
        return rules.scope_of_department(department, self._repository.factories())

    def summarize(self, key: PeriodKey) -> PeriodSummary:
        start, end, month = rules.period_dates(key.month)
        people = self._repository.people(key.company, key.scope, start)
        names = [p.employee for p in people]
        rows = rules.summarize(people, self._repository.marks(names, start, end), self._repository.approved_overtime(names, start, end),
                               self._repository.approved_corrections(names, start, end))
        totals = {field: float(sum(r[field] for r in rows)) for field in rules.TOTALS}
        return PeriodSummary(from_date=start, to_date=end, title=f"Kỳ công {month} · {key.scope}",
                             manager_user=self._repository.head_user(key.company, key.scope), rows=[PeriodRow(**r) for r in rows],
                             totals=totals, open_items=self._repository.open_items(names, start, end))

    def open_items(self, key: PeriodKey) -> list[str]:
        start, end, _month = rules.period_dates(key.month)
        names = [p.employee for p in self._repository.people(key.company, key.scope, start)]
        return self._repository.open_items(names, start, end)

    def check_unique(self, key: PeriodKey, name: str | None) -> None:
        rules.check_unique(self._repository.other_period(key, name))
