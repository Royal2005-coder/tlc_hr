"""Contracts of the overtime use cases."""

from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class AssessOvertime(Contract):
    """An overtime request being saved: compute it and check it against the law and the TLC route."""

    request: str | None  # None while new
    employee: str
    ot_date: date
    from_time: time
    to_time: time
    actor: str
    active: bool  # not refused or cancelled: counts against the limits
    proposing: bool  # new, or just sent to the worker: the proposer must be entitled


class OvertimeAssessment(Contract):
    hours: float
    day_type: str
    day_hours: float
    month_hours: float
    year_hours: float


class SlipRow(Contract):
    """One day of an HRMS Overtime Slip."""

    day: date
    hours: float = Field(ge=0, allow_inf_nan=False)


class CappedSlip(Contract):
    rows: list[SlipRow]
    notes: list[str]
