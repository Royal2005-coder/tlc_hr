"""Assignment, staffing and equal-authority reporting use cases."""
from tlc_hr.contracts.organization import AssignEmployee, AssessHeadcount, HeadcountResult, ResolveApprovers
from tlc_hr.domain.organization import Assignment, OrganizationRepository, Period, headcount, validate_assignment


class OrganizationService:
    def __init__(self, repository: OrganizationRepository):
        self.repository = repository

    def assess_assignment(self, command: AssignEmployee):
        assignment = Assignment(command.name, command.employee, command.department, command.position,
                                Period(command.start, command.end), command.primary)
        validate_assignment(assignment, self.repository.assignments(command.employee))
        return assignment

    def headcount(self, command: AssessHeadcount) -> HeadcountResult:
        used, vacant, excess = headcount(command.capacity, self.repository.active_employees(command.position, command.day))
        return HeadcountResult(used=used, vacant=vacant, excess=excess)

    def approvers(self, command: ResolveApprovers) -> tuple[str, ...]:
        return tuple(sorted(set(self.repository.approval_users(command.employee, command.department, command.day))))
