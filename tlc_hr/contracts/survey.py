from pydantic import BaseModel, ConfigDict


class AnonymousSubmission(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    campaign: str
    answers: dict[str, str]


class SurveyResults(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    campaign: str
    department: str
