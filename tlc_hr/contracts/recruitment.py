"""Strict commands for recruitment use cases."""

from pydantic import BaseModel, ConfigDict


class CandidateCommand(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    applicant_name: str
    email: str = ""
    phone: str = ""
    identity: str = ""
    date_of_birth: str = ""
    gender: str = ""
    address: str = ""
    education: str = ""
    experience: str = ""
    portfolio: str = ""
    cv: str = ""


class ApplicationCommand(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    application: str


class OfferCommand(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    offer: str
