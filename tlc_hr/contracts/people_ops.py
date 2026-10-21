"""Strict commands at the people-operations boundary."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ReceiptCommand(Command):
    actor: str
    expected_actor: str
    evidence: str = Field(min_length=1)
    submitted: bool


class LicenseCommand(Command):
    seats: int = Field(gt=0)
    used: int = Field(ge=0)
    expires_on: date
    today: date


class BenefitCommand(Command):
    event: Literal["Marriage", "Birth", "Hospitalization", "Bereavement"]
    event_date: date
    effective_from: date
    effective_to: date
    amount: float = Field(ge=0)


class TransitionCommand(Command):
    previous: str
    target: str
    actor_kind: str
    evidence: str = ""
