"""Lifecycle use cases depend on a small calendar/evidence port, not Frappe."""
from typing import Protocol
from tlc_hr.contracts.lifecycle import ProbationCommand, SeparationCommand
from tlc_hr.domain.lifecycle import completion_gate, notice, probation_days


class LifecycleRepository(Protocol):
    def is_working(self, employee, day) -> bool: ...
    def probation_exists(self, employee, job, excluding) -> bool: ...
    def completion_blockers(self, doctype, name, employee) -> list[str]: ...


class LifecycleService:
    def __init__(self, repository: LifecycleRepository):
        self.repository = repository

    def validate_probation(self, command: ProbationCommand, excluding=""):
        return probation_days(command.category, command.start, command.end,
                              lambda day: self.repository.is_working(command.employee, day),
                              self.repository.probation_exists(command.employee, command.job, excluding))

    def check_notice(self, command: SeparationCommand):
        return notice(command.category, command.submitted, command.last_day,
                      lambda day: self.repository.is_working(command.employee, day),
                      command.exception, command.legal_evidence, command.legal_reviewer)

    def complete(self, doctype, name, employee):
        completion_gate(self.repository.completion_blockers(doctype, name, employee))
