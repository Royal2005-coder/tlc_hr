"""TLC People portal on the seeded demo: request preview, withdraw, the timeline of a rejected request, scope of shared widgets."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from tlc_hr.api import decide, preview_leave, submit_leave, withdraw
from tlc_hr.portal import data
from tlc_hr.portal.common import flags, me
from tlc_hr.setup.install import TO_HR, TO_MANAGER

WORKER, FACTORY_HEAD, OFFICE = "binh@demo.example", "hung@demo.example", "an@demo.example"


def working_day(offset):
    day = add_days(getdate(nowdate()), offset)
    while day.weekday() >= 5:
        day = add_days(day, 1)
    return str(day)


class TestPortal(IntegrationTestCase):
    def setUp(self):
        if not frappe.db.exists("User", WORKER):
            self.skipTest("TLC demo seed not loaded (bench execute tlc_hr.seed.run)")
        self.day = working_day(26 + frappe.db.count("Leave Application") % 6)  # inside the 2026 allocation, away from the UAT days

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_preview_counts_working_days_and_pending_requests(self):
        frappe.set_user(WORKER)
        before = preview_leave("Phép năm", self.day, self.day)
        self.assertEqual(before["days"], 1)
        submit_leave("Phép năm", self.day, self.day, "x")
        later = working_day(34)
        after = preview_leave("Phép năm", later, later, half_day=1)
        self.assertEqual(after["days"], 0.5)
        self.assertEqual(after["balance"], before["balance"] - 1)  # the pending request is already counted

    def test_withdraw_a_pending_request_only_by_its_owner(self):
        frappe.set_user(WORKER)
        name = submit_leave("Phép năm", self.day, self.day, "x")["name"]
        frappe.set_user(OFFICE)
        with self.assertRaises(frappe.PermissionError):
            withdraw(name)
        frappe.set_user(WORKER)
        withdraw(name)
        self.assertFalse(frappe.db.exists("Leave Application", name))

    def test_no_withdraw_after_the_manager_decided(self):
        frappe.set_user(WORKER)
        name = submit_leave("Phép năm", self.day, self.day, "x")["name"]
        frappe.set_user(FACTORY_HEAD)
        decide(name, "approve")
        frappe.set_user(WORKER)
        with self.assertRaises(frappe.PermissionError):
            withdraw(name)

    def test_timeline_marks_the_level_that_rejected(self):
        frappe.set_user(WORKER)
        name = submit_leave("Phép năm", self.day, self.day, "x")["name"]
        frappe.set_user(FACTORY_HEAD)
        decide(name, "reject", "Trùng ca")
        self.assertEqual(frappe.db.get_value("Leave Application", name, "tlc_rejected_stage"), TO_MANAGER)
        steps = data.timeline("Từ chối", TO_MANAGER)
        self.assertEqual([s["status"] for s in steps], ["done", "failed", "todo", "failed"])
        self.assertEqual([s["status"] for s in data.timeline("Từ chối", TO_HR)], ["done", "done", "failed", "failed"])

    def test_scope_of_shared_widgets(self):
        frappe.set_user(WORKER)
        worker = me()
        self.assertEqual(set(data.scope_names(worker, flags(set(frappe.get_roles())))),
                         set(frappe.get_all("Employee", filters={"department": worker.department, "status": "Active"}, pluck="name")))
        frappe.set_user(FACTORY_HEAD)
        head = me()
        scope = data.scope_names(head, flags(set(frappe.get_roles())))
        self.assertEqual(len(scope), 15)  # the 14 people of factory 1 and the head
        frappe.set_user("hoa@demo.example")
        self.assertIsNone(data.scope_names(me(), flags(set(frappe.get_roles()))))  # HR: the whole company
