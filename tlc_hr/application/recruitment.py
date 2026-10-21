"""Recruitment orchestration; adapters own transaction and native document writes."""

from tlc_hr.contracts.recruitment import ApplicationCommand, CandidateCommand, OfferCommand
from tlc_hr.domain.recruitment import RecruitmentRepository, identifiers, require_final_round


class RecruitmentService:
    def __init__(self, repository: RecruitmentRepository):
        self.repository = repository

    def candidate(self, command: CandidateCommand) -> str:
        return self.repository.resolve_candidate(
            identifiers(command.email, command.phone, command.identity), command.model_dump()
        )

    def check_offer(self, command: ApplicationCommand) -> None:
        require_final_round(self.repository.has_final_round(command.application))

    def approve_requisition(self, requisition: str) -> list[str]:
        return self.repository.open_vacancies(requisition)

    def accept_offer(self, command: OfferCommand) -> str:
        return self.repository.accept_offer(command.offer)
