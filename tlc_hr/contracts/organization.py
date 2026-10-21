"""Strict date-aware organization use-case contracts."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class AssignEmployee(Contract):
    name: str
    employee: str
    department: str
    position: str
    start: date
    end: date | None = None
    primary: bool = False


class AssessHeadcount(Contract):
    position: str
    day: date
    capacity: int = Field(ge=0)


class HeadcountResult(Contract):
    used: int
    vacant: int
    excess: int


class ResolveApprovers(Contract):
    employee: str
    department: str
    day: date
