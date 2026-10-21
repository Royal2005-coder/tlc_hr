"""Strict commands shared by the native Desk adapters."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict


class LifecycleCommand(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class EmployeeChange(LifecycleCommand):
    employee: str
    field: Literal["bank_ac_no", "bank_name", "pan_number", "custom_tax_code", "custom_social_insurance_number", "passport_number", "cell_number", "personal_email", "current_address", "permanent_address"]
    value: str
    effective_on: date
    reason: str
    evidence: str


class ProbationCommand(LifecycleCommand):
    employee: str
    job: str
    category: Literal["Enterprise manager", "College or higher", "Technical or vocational", "Other work"]
    start: date
    end: date


class SeparationCommand(LifecycleCommand):
    employee: str
    category: Literal["Indefinite", "Fixed 12-36 months", "Fixed under 12 months"]
    submitted: date
    last_day: date
    exception: str = ""
    legal_evidence: str = ""
    legal_reviewer: str = ""
