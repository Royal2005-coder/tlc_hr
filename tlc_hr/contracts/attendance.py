"""Contracts of the attendance use cases."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Correction(Contract):
    """An attendance correction (HRMS Attendance Request) being saved."""

    employee: str
    from_date: date
    to_date: date
    kind: str | None
    shift: str | None
    explanation: str | None
    is_new: bool
    roles: frozenset[str]
    today: date
    post_lock_creation_authorized: bool = False

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.to_date < self.from_date:
            raise ValueError("correction to_date must not precede from_date")
        return self


class PeriodKey(Contract):
    company: str
    scope: str
    month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")

    @model_validator(mode="after")
    def valid_calendar_month(self):
        date(int(self.month[:4]), int(self.month[5:]), 1)
        return self


class PeriodRow(Contract):
    employee: str
    employee_name: str
    department: str | None
    present_days: float
    half_days: float
    absent_days: float
    leave_days: float
    late_count: int
    early_exit_count: int
    ot_hours: float
    corrections: int


class PeriodSummary(Contract):
    from_date: date
    to_date: date
    title: str
    manager_user: str | None
    rows: list[PeriodRow]
    totals: dict[str, float]
    open_items: list[str]
