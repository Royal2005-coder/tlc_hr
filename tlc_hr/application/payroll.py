"""Payroll use cases depend only on typed commands, domain rules and repository ports."""

from tlc_hr.contracts.payroll import ComputeOvertime, ComputePayroll, OvertimePay, PayrollReadiness
from tlc_hr.domain import payroll as rules
from tlc_hr.domain.payroll_ports import IPayrollRepository


class PayrollService:
    def __init__(self, repository: IPayrollRepository):
        self._repository = repository

    def check_can_compute(self, command: ComputePayroll) -> PayrollReadiness:
        month = command.start.strftime("%Y-%m")
        scopes = {self._repository.scope_of(d) for d in command.departments}
        rules.check_periods_locked(month, scopes, self._repository.locked_scopes(command.company, month))
        return PayrollReadiness(month=month, scopes=tuple(sorted(scopes)))

    def overtime(self, command: ComputeOvertime) -> OvertimePay | None:
        by_kind = self._repository.approved_overtime(command.employee, command.start, command.end)
        if not by_kind:
            return None
        taxed, premium = rules.overtime_pay(
            self._repository.base_salary(command.employee, command.end),
            self._repository.working_days(command.employee, command.start, command.end),
            self._repository.shift_hours(command.employee),
            by_kind,
        )
        return OvertimePay(taxed=taxed, premium=premium)
