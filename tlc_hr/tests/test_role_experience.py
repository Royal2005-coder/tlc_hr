"""Read-only integration assertions against the private TLC demo fixtures.

These checks require the normal seeded demo site. They do not create public copies
of personnel data, seed users, or attest any BRD requirement by themselves.
"""

import frappe
from frappe.tests import IntegrationTestCase

from tlc_hr.infrastructure.frappe.role_experience import employee_scope, has_permission, query_conditions


class TestRoleExperienceScope(IntegrationTestCase):
    def setUp(self):
        self.previous_user = frappe.session.user
        self.addCleanup(frappe.set_user, self.previous_user)

    def employee(self, account):
        name = frappe.db.get_value("Employee", {"user_id": account + "@demo.example"})
        self.assertTrue(name, "Seed the normal TLC demo fixtures before this integration suite")
        return name

    def test_each_factory_head_has_own_worker_not_other_factories(self):
        fixtures = (("hung", "binh", "f2w01"), ("nm2", "f2w01", "f3w01"), ("nm3", "f3w01", "binh"))
        for head, own, foreign in fixtures:
            user = head + "@demo.example"
            own_name, foreign_name = self.employee(own), self.employee(foreign)
            scope = employee_scope(user, "Employee")
            self.assertIsNotNone(scope)
            self.assertIn(own_name, scope)
            self.assertNotIn(foreign_name, scope)
            self.assertFalse(has_permission(frappe.get_doc("Employee", foreign_name), user=user, ptype="read"))
            self.assertFalse(has_permission(frappe.get_doc("Employee", foreign_name), user=user, ptype="write"))
            frappe.set_user(user)
            visible = set(frappe.get_list("Employee", pluck="name", limit_page_length=1000))
            self.assertIn(own_name, visible)
            self.assertNotIn(foreign_name, visible)
            self.assertFalse(frappe.has_permission("Employee", "read", foreign_name, user=user))
            frappe.set_user(self.previous_user)

    def test_workers_are_self_only(self):
        for account in ("binh", "f2w01", "f3w01", "an"):
            self.assertEqual(employee_scope(account + "@demo.example", "Employee"), (self.employee(account),))

    def test_hr_and_ceo_are_not_restricted_by_this_adapter(self):
        for account in ("hoa", "lan", "thanh"):
            for doctype in ("Employee", "Attendance", "Shift Assignment"):
                self.assertIsNone(employee_scope(account + "@demo.example", doctype))
                self.assertEqual(query_conditions(account + "@demo.example", doctype), "")

    def test_payroll_scope_does_not_expand_attendance_or_accountant_access(self):
        self.assertIsNone(employee_scope("phuong@demo.example", "Employee"))
        self.assertIsNotNone(employee_scope("phuong@demo.example", "Attendance"))
        self.assertIsNotNone(employee_scope("chi@demo.example", "Employee"))

    def test_unknown_wiring_fails_closed(self):
        self.assertEqual(query_conditions("binh@demo.example", "Salary Slip"), "1=0")
