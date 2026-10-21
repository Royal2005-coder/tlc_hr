"""Strict boundary contracts; Decimal amounts are normalized only by the Frappe adapter."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class TravelAssessment(Contract):
    name: str | None
    employee: str
    start: date
    end: date
    start_session: Literal["AM", "PM"]
    end_session: Literal["AM", "PM"]
    funded: bool
    budget: Decimal
    requested_advance: Decimal
    active: bool


class FinanceTransition(Contract):
    kind: Literal["travel", "advance", "claim"]
    employee: str
    before: str
    after: str
    actor: str
    reason: str


class SettlementResult(Contract):
    advance: Decimal
    actual: Decimal
    difference: Decimal
    branch: Literal["equal", "refund", "top_up"]


class PayrollRecovery(Contract):
    advance: str
    employee: str
    actor: str
    consent: bool
    evidence: str
    consent_by: str
    due: date | None
    today: date


class AssessSettlement(Contract):
    advance: Decimal
    actual: Decimal
