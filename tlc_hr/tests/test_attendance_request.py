"""Attendance corrections (TLC Điều chỉnh công) on the seeded demo: line manager then HR, scope, reason to reject."""

import datetime as dt

import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase

WORKER, HEAD, OTHER_HEAD, HR = "binh@demo.example", "hung@demo.example", "nm2@demo.example", "lan@demo.example"


def working_day(offset):
    day = dt.date.today() + dt.timedelta(days=offset)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return str(day)


class TestAttendanceCorrection(IntegrationTestCase):
    def setUp(self):
        self.employee = frappe.db.get_value("Employee", {"user_id": WORKER})
        if not self.employee or not frappe.db.exists("Workflow", "TLC Điều chỉnh công"):
            self.skipTest("TLC demo seed not loaded")
        self.day = working_day(38 + frappe.db.count("Attendance Request") % 5)  # mid December, no public holiday

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def request(self, correction="Đi công tác / làm việc ngoài"):
        frappe.set_user(WORKER)
        doc = frappe.get_doc({"doctype": "Attendance Request", "employee": self.employee, "from_date": self.day, "to_date": self.day,
                              "reason": "On Duty", "tlc_correction_type": correction, "explanation": "Giao hàng ở kho đối tác"}).insert()
        apply_workflow(doc, "Gửi duyệt")
        doc.reload()
        return doc

    def test_line_manager_then_hr_marks_present(self):
        doc = self.request()
        self.assertEqual((doc.workflow_state, doc.tlc_approver), ("Chờ quản lý duyệt", HEAD))
        frappe.set_user(HEAD)
        apply_workflow(doc, "Duyệt")
        frappe.set_user(HR)
        doc.reload()
        apply_workflow(doc, "Duyệt")
        doc.reload()
        self.assertEqual((doc.workflow_state, doc.docstatus), ("Đã duyệt", 1))
        status = frappe.db.get_value("Attendance", {"employee": self.employee, "attendance_date": self.day, "docstatus": 1}, "status")
        self.assertEqual(status, "Present")

    def test_head_of_another_factory_cannot_decide(self):
        doc = self.request()
        frappe.set_user(OTHER_HEAD)
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            apply_workflow(doc, "Duyệt")

    def test_rejection_needs_a_reason_and_creates_no_attendance(self):
        doc = self.request()
        frappe.set_user(HEAD)
        with self.assertRaises(frappe.ValidationError):
            apply_workflow(doc, "Từ chối")
        doc.reload()
        doc.tlc_reject_reason = "Không có lệnh điều động"
        doc.save()
        apply_workflow(doc, "Từ chối")
        doc.reload()
        self.assertEqual((doc.workflow_state, doc.docstatus, doc.tlc_rejected_stage), ("Từ chối", 0, "Chờ quản lý duyệt"))

    def test_forgot_to_check_in_cannot_be_in_the_future(self):
        frappe.set_user(WORKER)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Attendance Request", "employee": self.employee, "from_date": self.day, "to_date": self.day,
                            "reason": "On Duty", "tlc_correction_type": "Quên chấm vào"}).insert()
