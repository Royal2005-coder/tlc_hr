"""Use cases invoked identically by Raven tools and the authenticated REST adapter."""
from datetime import date

from tlc_hr.contracts.assistant import AssistantQuery, LeaveDraft
from tlc_hr.domain.assistant import IAssistantRepository, authorize
from tlc_hr.domain.shared import DomainError, NotAllowed


class AssistantService:
    def __init__(self, repository: IAssistantRepository):
        self._repository = repository

    def _employee(self, requested, action):
        identity = self._repository.identity()
        try:
            return authorize(identity, requested)
        except NotAllowed:
            self._repository.audit(action, identity.employee, "denied")
            raise

    def query(self, command: AssistantQuery) -> dict:
        employee = self._employee(command.employee, "read_" + command.topic)
        result = self._repository.read_self(command.topic, employee)
        self._repository.audit("read_" + command.topic, employee, "allowed")
        return result

    def draft_leave(self, command: LeaveDraft) -> dict:
        employee = self._employee(command.employee, "draft_leave")
        try:
            start, end = date.fromisoformat(command.from_date), date.fromisoformat(command.to_date)
        except ValueError as exc:
            raise DomainError("AI_DATES", "Ngày nghỉ không hợp lệ.") from exc
        if end < start:
            raise DomainError("AI_DATES", "Ngày kết thúc phải từ ngày bắt đầu trở đi.")
        result = self._repository.create_leave_draft(employee, command)
        self._repository.audit("draft_leave", employee, "allowed")
        return result
