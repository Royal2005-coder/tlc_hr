"""Strict public contracts shared by Raven custom tools and authenticated REST."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssistantQuery(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    topic: Literal["profile", "attendance", "leave", "payslip"]
    employee: str | None = None


class LeaveDraft(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    leave_type: str = Field(min_length=1, max_length=140)
    from_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    to_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)
    employee: str | None = None
