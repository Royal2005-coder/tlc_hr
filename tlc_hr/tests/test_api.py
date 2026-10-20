"""API of the /tlc home on the seeded TLC demo: ask for leave, decide, and the rules the API must not bypass."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from tlc_hr.api import decide, submit_leave
from tlc_hr.setup.install import APPROVED, REJECTED, TO_HR, TO_MANAGER

WORKER, FACTORY_HEAD, OTHER_FACTORY_HEAD, HR_LEAD = "binh@demo.example", "hung@demo.example", "nm2@demo.example", "hoa@demo.example"


def working_day(offset):
    day = add_days(getdate(nowdate()), offset)
    while day.weekday() >= 5:
        day = add_days(day, 1)
    return str(day)


class TestTlcApi(IntegrationTestCase):
    def setUp(self):
        if not frappe.db.exists("User", WORKER):
            self.skipTest("TLC demo seed not loaded (bench execute tlc_hr.seed.run)")
        self.day = working_day(36 + frappe.db.count("Leave Application") % 4)  # inside the 2026 allocation

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def ask(self):
        frappe.set_user(WORKER)
        return submit_leave("Phép năm", self.day, self.day, "Việc gia đình")

    def test_worker_request_goes_to_the_factory_head(self):
        result = self.ask()
        self.assertEqual((result["workflow_state"], result["leave_approver"]), (TO_MANAGER, FACTORY_HEAD))
        self.assertEqual(result["total_leave_days"], 1)

    def test_factory_head_then_hr_lead_approve(self):
        name = self.ask()["name"]
        frappe.set_user(FACTORY_HEAD)
        self.assertEqual(decide(name, "approve")["workflow_state"], TO_HR)
        frappe.set_user(HR_LEAD)
        self.assertEqual(decide(name, "approve")["workflow_state"], APPROVED)

    def test_head_of_another_factory_cannot_decide(self):
        name = self.ask()["name"]
        frappe.set_user(OTHER_FACTORY_HEAD)
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            decide(name, "approve")

    def test_reject_needs_a_reason_and_keeps_it(self):
        name = self.ask()["name"]
        frappe.set_user(FACTORY_HEAD)
        with self.assertRaises(frappe.ValidationError):
            decide(name, "reject", "  ")
        self.assertEqual(decide(name, "reject", "Trùng ca kiểm kê")["workflow_state"], REJECTED)
        self.assertEqual(frappe.db.get_value("Leave Application", name, "tlc_reject_reason"), "Trùng ca kiểm kê")

    def test_request_needs_a_reason_and_valid_dates(self):
        frappe.set_user(WORKER)
        with self.assertRaises(frappe.ValidationError):
            submit_leave("Phép năm", self.day, self.day, "")
        with self.assertRaises(frappe.ValidationError):
            submit_leave("Phép năm", self.day, str(add_days(getdate(self.day), -1)), "x")
