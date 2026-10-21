"""Pure boundary tests; no Frappe import or site."""
import unittest
from datetime import date

from pydantic import ValidationError

from tlc_hr.application.organization import OrganizationService
from tlc_hr.contracts.organization import AssignEmployee, AssessHeadcount, ResolveApprovers
from tlc_hr.domain.organization import Assignment, Period, headcount, mismatch, validate_assignment, validate_reporting, validate_tree
from tlc_hr.domain.shared import DomainError

DAY = date(2026, 1, 1)


class Repository:
    def assignments(self, employee):
        return [Assignment("a", employee, "Sales", "sales", Period(DAY), True)]

    def active_employees(self, position, day):
        return ["alice", "alice", "bob"]

    def approval_users(self, employee, department, day):
        return ["lead-b@example.com", "lead-a@example.com", "lead-a@example.com"]


class OrganizationTests(unittest.TestCase):
    def test_period_end_is_inclusive(self):
        period = Period(DAY, DAY)
        self.assertTrue(period.contains(DAY))
        self.assertTrue(period.overlaps(Period(DAY)))
        self.assertFalse(period.contains(date(2026, 1, 2)))

    def test_invalid_period(self):
        with self.assertRaises(DomainError):
            Period(date(2026, 1, 2), DAY).validate()

    def test_second_primary_rejected_even_in_other_department(self):
        existing = Repository().assignments("alice")
        with self.assertRaises(DomainError):
            validate_assignment(Assignment("b", "alice", "HR", "hr", Period(DAY), True), existing)

    def test_secondary_cross_department_is_allowed(self):
        validate_assignment(Assignment("b", "alice", "HR", "hr", Period(DAY), False), Repository().assignments("alice"))

    def test_duplicate_position_and_primary_on_boundary_rejected(self):
        old = Assignment("a", "alice", "Sales", "sales", Period(DAY, DAY), True)
        with self.assertRaises(DomainError):
            validate_assignment(Assignment("b", "alice", "Sales", "sales", Period(DAY), False), [old])
        validate_assignment(Assignment("b", "alice", "Sales", "sales", Period(date(2026, 1, 2)), True), [old])

    def test_edit_does_not_overlap_itself(self):
        row = Repository().assignments("alice")[0]
        validate_assignment(row, [row])

    def test_headcount_counts_people_not_assignments(self):
        self.assertEqual(headcount(1, ["alice", "alice", "bob"]), (2, 0, 1))
        self.assertEqual(headcount(3, ["alice"]), (1, 2, 0))
        with self.assertRaises(DomainError):
            headcount(-1, [])

    def test_administrative_cycle_is_rejected(self):
        validate_tree({"company": None, "division": "company", "team": "division"})
        with self.assertRaises(DomainError):
            validate_tree({"a": "b", "b": "a"})

    def test_equal_authority_coleaders_not_an_administrative_tree(self):
        validate_reporting([("alice", "lead-a"), ("alice", "lead-b")])
        with self.assertRaises(DomainError):
            validate_reporting([("alice", "lead-a"), ("lead-a", "alice")])
        with self.assertRaises(DomainError):
            validate_reporting([("alice", "alice")])

    def test_warning_respects_secondary_assignment(self):
        self.assertFalse(mismatch("Sales", {"HR"}, "HR"))
        self.assertTrue(mismatch("Sales", {"HR"}, "Warehouse"))
        self.assertFalse(mismatch("Sales", set(), None))

    def test_service_uses_strict_commands_and_returns_both_leaders(self):
        service = OrganizationService(Repository())
        result = service.headcount(AssessHeadcount(position="sales", day=DAY, capacity=1))
        self.assertEqual((result.used, result.vacant, result.excess), (2, 0, 1))
        self.assertEqual(service.approvers(ResolveApprovers(employee="alice", department="Sales", day=DAY)),
                         ("lead-a@example.com", "lead-b@example.com"))
        with self.assertRaises(ValidationError):
            AssessHeadcount(position="sales", day="2026-01-01", capacity=1)
        with self.assertRaises(ValidationError):
            AssessHeadcount(position="sales", day=DAY, capacity="1")
        with self.assertRaises(ValidationError):
            AssignEmployee(name="a", employee="alice", department="Sales", position="sales", start=DAY, unknown=True)
