"""Leave workflow TLC Nghỉ phép on the seeded TLC demo: run inside a site with `bench --site <site> run-tests --app tlc_hr`."""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from tlc_hr.setup.install import APPROVED, REJECTED, TO_HR, TO_MANAGER

WORKER, MANAGER, OTHER_MANAGER, HR_LEAD = "binh@demo.example", "hung@demo.example", "quang@demo.example", "hoa@demo.example"
DIRECTOR = "thanh@demo.example"


def next_working_day(offset):
    day = add_days(getdate(nowdate()), offset)
    while day.weekday() >= 5:
        day = add_days(day, 1)
    return day


class TestLeaveWorkflow(IntegrationTestCase):
    def setUp(self):
        if not frappe.db.exists("User", WORKER):
            self.skipTest("TLC demo seed not loaded (bench execute tlc_hr.seed.run)")
        self.offset = 30 + frappe.db.count("Leave Application")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def new_request(self, user=WORKER):
        frappe.set_user(user)
        employee = frappe.db.get_value("Employee", {"user_id": user})
        day = next_working_day(self.offset)
        doc = frappe.get_doc({"doctype": "Leave Application", "employee": employee, "leave_type": "Phép năm",
                              "from_date": day, "to_date": day, "description": "test"})
        doc.insert()
        apply_workflow(doc, "Gửi duyệt")
        doc.reload()
        return doc

    def test_manager_then_hr_lead_approves(self):
        doc = self.new_request()
        self.assertEqual(doc.workflow_state, TO_MANAGER)
        self.assertEqual(doc.leave_approver, MANAGER)

        frappe.set_user(MANAGER)
        apply_workflow(doc, "Duyệt")
        doc.reload()
        self.assertEqual(doc.workflow_state, TO_HR)
        self.assertEqual(doc.docstatus, 0)

        frappe.set_user(HR_LEAD)
        apply_workflow(doc, "Duyệt")
        doc.reload()
        self.assertEqual(doc.workflow_state, APPROVED)
        self.assertEqual((doc.docstatus, doc.status), (1, "Approved"))

    def test_only_the_named_leave_approver_can_decide(self):
        doc = self.new_request()
        frappe.set_user(OTHER_MANAGER)
        # Another manager may not even read the request; if a role ever lets them read it, the workflow condition still refuses.
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            apply_workflow(doc, "Duyệt")

    def test_hr_lead_cannot_approve_their_own_request(self):
        doc = self.new_request(user=HR_LEAD)  # the HR lead asks for leave; the director approves at the manager level
        frappe.set_user(DIRECTOR)
        apply_workflow(doc, "Duyệt")
        doc.reload()
        self.assertEqual(doc.workflow_state, TO_HR)
        frappe.set_user(HR_LEAD)
        with self.assertRaises(frappe.ValidationError):
            apply_workflow(doc, "Duyệt")

    def test_rejection_needs_a_reason(self):
        doc = self.new_request()
        frappe.set_user(MANAGER)
        with self.assertRaises(frappe.ValidationError):
            apply_workflow(doc, "Từ chối")
        doc.reload()
        doc.tlc_reject_reason = "Trùng lịch kiểm kê kho"
        doc.save()
        apply_workflow(doc, "Từ chối")
        doc.reload()
        self.assertEqual((doc.workflow_state, doc.status), (REJECTED, "Rejected"))
