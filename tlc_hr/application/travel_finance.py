"""Travel/finance use cases depend on the repository port, never on Frappe."""
from tlc_hr.contracts.travel_finance import SettlementResult
from tlc_hr.domain import travel_finance as rules
from tlc_hr.domain.shared import DomainError
from tlc_hr.domain.travel_finance_ports import ITravelFinanceRepository


class TravelFinanceService:
    def __init__(self, repository: ITravelFinanceRepository):
        self.repository = repository

    def assess_travel(self, command):
        window = rules.Window(command.start, command.end, command.start_session, command.end_session)
        window.slots()
        if not command.budget.is_finite() or not command.requested_advance.is_finite():
            raise DomainError("travel.amount", "Dự toán và tạm ứng phải là số tiền hữu hạn.")
        if min(command.budget, command.requested_advance) < 0:
            raise DomainError("travel.amount", "Dự toán và tạm ứng không được âm.")
        if command.funded and (command.budget <= 0 or command.requested_advance > command.budget):
            raise DomainError("travel.budget", "Công tác có phí phải có dự toán; tạm ứng từ 0 đến tổng dự toán.")
        if not command.funded and (command.budget or command.requested_advance):
            raise DomainError("travel.no_cost", "Công tác không phí không được có dự toán hoặc tạm ứng.")
        if command.active:
            self.repository.lock_employee(command.employee)
            conflicts = self.repository.conflicts(command.employee, window, command.name)
            if conflicts:
                raise DomainError("travel.overlap", "Trùng lịch nghỉ phép, tăng ca hoặc công tác: " + ", ".join(conflicts))
        return window

    def transition(self, command):
        rules.check_transition(command.kind, command.before, command.after,
                               self.repository.actor(command.actor, command.employee),
                               self.repository.route(command.employee), command.reason)

    def settle(self, command):
        result = rules.settlement(command.advance, command.actual)
        return SettlementResult(advance=result.advance, actual=result.actual, difference=result.difference, branch=result.branch)

    def authorize_recovery(self, command):
        route = self.repository.route(command.employee)
        rules.require_payroll_consent(allowed=self.repository.payroll_policy(command.employee), consent=command.consent,
                                      evidence=command.evidence, consent_by=command.consent_by, subject=route.subject,
                                      due=command.due, today=command.today)
        rules.authorize(self.repository.actor(command.actor, command.employee), route, rules.ACCOUNTANT)
