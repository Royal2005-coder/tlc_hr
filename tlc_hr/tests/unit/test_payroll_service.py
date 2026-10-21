"""Payroll service boundaries: closed scopes, typed periods and tax/premium separation."""

import unittest
from datetime import date

from pydantic import ValidationError

from tlc_hr.application.payroll import PayrollService
from tlc_hr.contracts.payroll import ComputeOvertime, ComputePayroll
from tlc_hr.domain.overtime import REST_DAY, WORKING_DAY
from tlc_hr.domain.payroll_ports import IPayrollRepository
from tlc_hr.domain.shared import DomainError


class PayrollRepository(IPayrollRepository):
    def __init__(self):
        self.closed = {"TLC": {"Hội sở"}, "Other": {"Nhà máy 1"}}
        self.hours = {WORKING_DAY: 3.0, REST_DAY: 2.0}

    def scope_of(self, department):
        return "Nhà máy 1" if department == "factory" else "Hội sở"

    def locked_scopes(self, company, month):
        return self.closed.get(company, set()) if month == "2026-09" else set()

    def base_salary(self, employee, on):
        return 22_000_000

    def working_days(self, employee, start, end):
        return 22

    def shift_hours(self, employee):
        return 8

    def approved_overtime(self, employee, start, end):
        return self.hours


class TestPayrollService(unittest.TestCase):
    def test_another_company_lock_does_not_close_factory(self):
        service = PayrollService(PayrollRepository())
        with self.assertRaises(DomainError) as failure:
            service.check_can_compute(ComputePayroll(company="TLC", start=date(2026, 9, 1), departments=("office", "factory")))
        self.assertIn("Nhà máy 1", failure.exception.message)

    def test_month_and_scope_locks_are_independent(self):
        service = PayrollService(PayrollRepository())
        readiness = service.check_can_compute(ComputePayroll(company="TLC", start=date(2026, 9, 1), departments=(None, "office")))
        self.assertEqual(readiness.scopes, ("Hội sở",))
        with self.assertRaises(DomainError):
            service.check_can_compute(ComputePayroll(company="TLC", start=date(2026, 10, 1), departments=(None,)))

    def test_empty_employee_scope_cannot_bypass_closing(self):
        with self.assertRaises(ValidationError):
            ComputePayroll(company="TLC", start=date(2026, 9, 1), departments=())

    def test_contract_rejects_reversed_period_without_coercion(self):
        with self.assertRaises(ValidationError):
            ComputeOvertime(employee="E", start=date(2026, 9, 30), end=date(2026, 9, 1))
        with self.assertRaises(ValidationError):
            ComputeOvertime(employee="E", start="2026-09-01", end="2026-09-30")

    def test_approved_overtime_splits_basic_and_premium_amounts(self):
        result = PayrollService(PayrollRepository()).overtime(
            ComputeOvertime(employee="E", start=date(2026, 9, 1), end=date(2026, 9, 30))
        )
        self.assertEqual((result.taxed, result.premium), (625_000, 437_500))

    def test_no_approved_overtime_produces_no_payroll_addition(self):
        repository = PayrollRepository()
        repository.hours = {}
        self.assertIsNone(PayrollService(repository).overtime(
            ComputeOvertime(employee="E", start=date(2026, 9, 1), end=date(2026, 9, 30))))
