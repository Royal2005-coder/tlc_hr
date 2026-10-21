"""Typed boundary between native payroll documents and the TLC payroll use cases."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ComputePayroll(Contract):
    company: str = Field(min_length=1)
    start: date
    departments: tuple[str | None, ...] = Field(min_length=1)


class PayrollReadiness(Contract):
    month: str
    scopes: tuple[str, ...]


class ComputeOvertime(Contract):
    employee: str = Field(min_length=1)
    start: date
    end: date

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end < self.start:
            raise ValueError("overtime period end must not precede start")
        return self


class OvertimePay(Contract):
    taxed: int
    premium: int
