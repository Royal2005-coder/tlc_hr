"""Monthly attendance closing (TLC Chốt công) on the seeded demo: factory chain and head office chain, open items block the period,
returning needs a reason, a locked month cannot change except through a post-lock adjustment, only the CEO reopens.
Ported from the seed scenarios factory_attendance_period_chain and time_lock_and_adjustment (blueprint UAT-WF-07, UAT-WF-08)."""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from tlc_hr.attendance.period import employees_in
from tlc_hr.setup.period import CARRY_FORWARD_DAYS

WORKER, HEAD, OTHER_HEAD, HR, HR2, CEO = ("f2w01@demo.example", "nm2@demo.example", "hung@demo.example", "lan@demo.example",
                                          "hoa@demo.example", "thanh@demo.example")
MONTH, DAY, LOCKED_DAY = "2026-03", "2026-03-03", "2026-03-04"  # far from the demo data; March 2026 has no public holiday


class TestAttendancePeriod(IntegrationTestCase):
    def setUp(self):
        frappe.flags.tlc_post_lock = False
        self.worker = frappe.db.get_value("Employee", {"user_id": WORKER})
        if not self.worker or not frappe.db.exists("Workflow", "TLC Chốt công"):
            self.skipTest("TLC demo seed not loaded")
        self.company = frappe.db.get_value("Employee", self.worker, "company")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def period(self, scope="Nhà máy 2", month=MONTH):
        frappe.set_user(HR)
        return frappe.get_doc({"doctype": "TLC Attendance Period", "company": self.company, "scope": scope, "period_month": month}).insert()

    def act(self, doc, action, user, reason=None):
        frappe.set_user(user)
        doc = frappe.get_doc(doc.doctype, doc.name)
        if reason:
            doc.db_set("tlc_reject_reason", reason)
        apply_workflow(doc, action)
        doc.reload()
        return doc

    def attendance(self, day, status="Present"):
        frappe.set_user("Administrator")
        return frappe.get_doc({"doctype": "Attendance", "employee": self.worker, "attendance_date": day, "status": status,
                               "company": self.company}).submit()

    def lock(self):
        doc = self.act(self.period(), "Gửi xác nhận", HR)
        doc = self.act(doc, "Xác nhận", HEAD)
        doc = self.act(doc, "Đối soát xong", HR)
        return self.act(doc, "Ký và khoá", CEO)

    def test_summary_per_person(self):
        self.attendance(DAY)
        doc = self.period()
        row = next(r for r in doc.rows if r.employee == self.worker)
        self.assertEqual((doc.employee_count, row.present_days, doc.title),
                         (len(employees_in("Nhà máy 2", self.company, doc.from_date)), 1, "Kỳ công 03/2026 · Nhà máy 2"))
        self.assertEqual((str(doc.from_date), str(doc.to_date), doc.manager_user), ("2026-03-01", "2026-03-31", HEAD))

    def test_factory_chain_locks_the_month(self):
        doc = self.act(self.period(), "Gửi xác nhận", HR)
        self.assertEqual(doc.workflow_state, "Chờ quản lý xác nhận")
        with self.assertRaises(frappe.PermissionError):
            self.act(doc, "Xác nhận", OTHER_HEAD)  # the head of another factory does not even see it
        doc = self.act(doc, "Xác nhận", HEAD)
        doc = self.act(doc, "Đối soát xong", HR)
        doc = self.act(doc, "Ký và khoá", CEO)
        self.assertEqual((doc.workflow_state, doc.docstatus, doc.locked_by), ("Đã khoá", 1, CEO))
        with self.assertRaises(frappe.ValidationError):
            self.attendance(LOCKED_DAY)
        frappe.set_user(WORKER)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Attendance Request", "employee": self.worker, "from_date": LOCKED_DAY, "to_date": LOCKED_DAY,
                            "reason": "On Duty", "tlc_correction_type": "Máy chấm công lỗi", "explanation": "Máy lỗi"}).insert()

    def test_open_request_blocks_the_period(self):
        frappe.set_user(WORKER)
        request = frappe.get_doc({"doctype": "Attendance Request", "employee": self.worker, "from_date": DAY, "to_date": DAY,
                                  "reason": "On Duty", "tlc_correction_type": "Quên chấm ra", "explanation": "Quên chấm ra"}).insert()
        apply_workflow(request, "Gửi duyệt")
        doc = self.period()
        self.assertEqual(doc.open_count, 1)
        self.assertIn(request.name, doc.open_items)
        with self.assertRaises(frappe.ValidationError) as caught:
            self.act(doc, "Gửi xác nhận", HR)
        self.assertIn("chưa xử lý", str(caught.exception))

    def test_head_office_skips_the_factory_head(self):
        doc = self.period(scope="Hội sở")
        self.assertFalse(doc.manager_user)
        with self.assertRaises(frappe.ValidationError):
            self.act(doc, "Gửi xác nhận", HR)
        doc = self.act(doc, "Gửi đối soát", HR)
        self.assertEqual(doc.workflow_state, "Chờ nhân sự đối soát")

    def test_return_needs_a_reason(self):
        doc = self.act(self.period(), "Gửi xác nhận", HR)
        with self.assertRaises(frappe.ValidationError):
            self.act(doc, "Trả lại", HEAD)
        doc = self.act(doc, "Trả lại", HEAD, reason="Thiếu công ca đêm ngày 12")
        self.assertEqual((doc.workflow_state, doc.tlc_rejected_stage), ("Nháp", "Chờ quản lý xác nhận"))

    def test_post_lock_adjustment(self):
        period = self.lock()
        frappe.set_user(WORKER)
        values = {"doctype": "Attendance Request", "employee": self.worker, "from_date": LOCKED_DAY, "to_date": LOCKED_DAY,
                  "reason": "On Duty", "tlc_correction_type": "Điều chỉnh sau chốt", "explanation": "Đi giao hàng, quên báo"}
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(values).insert()  # only HR writes a post-lock adjustment
        frappe.set_user(HR)
        request = frappe.get_doc(values).insert()
        apply_workflow(request, "Gửi duyệt")
        request = self.act(request, "Duyệt", HEAD)
        request = self.act(request, "Duyệt", HR2)
        self.assertEqual((request.workflow_state, request.docstatus), ("Đã duyệt", 1))
        self.assertTrue(frappe.db.exists("Attendance", {"employee": self.worker, "attendance_date": LOCKED_DAY, "docstatus": 1}))
        self.assertTrue(frappe.db.exists("Comment", {"reference_doctype": "TLC Attendance Period", "reference_name": period.name,
                                                     "content": ["like", f"%{request.name}%"]}))
        self.assertFalse(frappe.flags.tlc_post_lock)

    def test_only_the_ceo_reopens_with_a_reason(self):
        doc = self.lock()
        with self.assertRaises(frappe.ValidationError):
            self.act(doc, "Mở lại kỳ", HR)
        with self.assertRaises(frappe.ValidationError):
            self.act(doc, "Mở lại kỳ", CEO)
        doc = self.act(doc, "Mở lại kỳ", CEO, reason="Bổ sung công tác tuần 2")
        self.assertEqual((doc.workflow_state, doc.docstatus), ("Đã mở lại", 2))
        self.attendance(LOCKED_DAY)  # the month is open again

    def test_one_period_per_scope_and_month(self):
        self.period()
        with self.assertRaises(frappe.ValidationError):
            self.period()

    def test_annual_leave_carried_until_30_march(self):
        self.assertEqual(frappe.db.get_value("Leave Type", "Phép năm", "expire_carry_forwarded_leaves_after_days"), CARRY_FORWARD_DAYS)
        self.assertEqual(str(add_days("2027-01-01", CARRY_FORWARD_DAYS - 1)), "2027-03-30")  # HRMS: from_date + days - 1
