"""Vietnamese payroll of TLC on the site: payslips computed by HRMS with the structure of customizing/payroll.yaml (the golden
cases of tests/unit/test_payroll.py, end to end), and the chain of workflow TLC Bảng lương: compute only after the attendance lock,
CEO signs, the accountant confirms the bank payment (blueprint UAT-PAY-01, UAT-PAY-03), overtime paid as taxed part + free premium."""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from tlc_hr.infrastructure.customizing.loader import load_bundle

PAYROLL, CEO, ACCOUNTANT, HR, HR2, HEAD = ("phuong@demo.example", "thanh@demo.example", "chi@demo.example", "lan@demo.example",
                                           "hoa@demo.example", "hung@demo.example")
STRUCTURE = load_bundle().payroll.structure.name
# August: the UAT computes and pays September, so the chain is tested on a month no other run has paid
MONTH, MONTH_START, MONTH_END = "2026-08", "2026-08-01", "2026-08-31"


def employee_of(user):
    return frappe.db.get_value("Employee", {"user_id": user})


def amount(slip, abbr):
    return sum(flt(r.amount) for r in slip.earnings + slip.deductions if r.abbr == abbr)


class TestPayrollVN(IntegrationTestCase):
    def setUp(self):
        if not frappe.db.exists("Salary Structure", STRUCTURE) or not employee_of(PAYROLL):
            self.skipTest("TLC demo seed not loaded")
        self.company = frappe.db.get_value("Employee", employee_of(CEO), "company")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def assign(self, employee):
        if not frappe.db.exists("Salary Structure Assignment", {"employee": employee, "docstatus": 1}):
            frappe.get_doc({"doctype": "Salary Structure Assignment", "employee": employee, "salary_structure": STRUCTURE,
                            "company": self.company, "from_date": "2026-01-01",
                            "base": frappe.db.get_value("Employee", employee, "tlc_monthly_wage")}).insert().submit()

    def slip(self, user, start="2026-08-01", end="2026-08-31"):
        frappe.set_user("Administrator")
        employee = employee_of(user)
        self.assign(employee)
        return frappe.get_doc({"doctype": "Salary Slip", "employee": employee, "start_date": start, "end_date": end, "posting_date": end,
                               "salary_structure": STRUCTURE, "payroll_frequency": "Monthly"}).insert()

    def test_golden_payslips_on_the_site(self):
        an = self.slip("an@demo.example")
        self.assertEqual((amount(an, "TNCN"), flt(an.net_pay)), (209_500, 19_480_500))
        self.assertEqual((flt(an.vn_pit_amount), flt(an.vn_insurance_employee)), (209_500, 2_310_000))  # erpnextvn agrees
        employer = {r.abbr: flt(r.amount) for r in an.employer_contributions}
        self.assertEqual(employer, {"BHXH_DN_TLC": 3_850_000, "BHYT_DN_TLC": 660_000, "BHTN_DN_TLC": 220_000, "KPCD_DN_TLC": 440_000})
        self.register_dependents("quang@demo.example", 2)  # only dependents HR verified reduce PIT
        self.assertEqual(amount(self.slip("quang@demo.example"), "TNCN"), 1_377_300)
        thanh = self.slip(CEO)
        self.assertEqual((amount(thanh, "BHXH_NLD"), amount(thanh, "BHTN_NLD")), (4_048_000, 1_062_000))

    def register_dependents(self, user, count):
        """Verified dependents (TLC Employee Dependent) as HR leaves them after checking the evidence."""
        for i in range(count):
            frappe.get_doc({"doctype": "TLC Employee Dependent", "employee": employee_of(user), "dependent_name": f"Người phụ thuộc {i + 1}",
                            "date_of_birth": "2015-01-01", "relationship": "Child", "identity_number": f"07921500000{i}",
                            "valid_from": "2026-01-01", "status": "Verified", "evidence": "/files/demo-evidence.pdf",
                            "docstatus": 1, "workflow_state": "Đã duyệt"}).db_insert()

    # ------------------------------------------------------------------ payroll chain

    def lock(self, scope, steps):
        """Lock the test month for a scope (an existing locked period is reused)."""
        if frappe.db.exists("TLC Attendance Period", {"company": self.company, "scope": scope, "period_month": MONTH, "docstatus": 1}):
            return
        frappe.set_user(HR)
        period = frappe.get_doc({"doctype": "TLC Attendance Period", "company": self.company, "scope": scope, "period_month": MONTH}).insert()
        for action, user in steps:
            frappe.set_user(user)
            apply_workflow(frappe.get_doc(period.doctype, period.name), action)

    def payroll(self, department, start=MONTH_START, end=MONTH_END):
        frappe.set_user(PAYROLL)
        abbr = frappe.db.get_value("Company", self.company, "abbr")
        doc = frappe.get_doc({"doctype": "Payroll Entry", "company": self.company, "posting_date": end, "payroll_frequency": "Monthly",
                              "start_date": start, "end_date": end, "currency": "VND", "exchange_rate": 1,
                              "department": f"{department} - {abbr}",
                              "payroll_payable_account": frappe.db.get_value("Company", self.company, "default_payroll_payable_account"),
                              "payment_account": frappe.db.get_value("Account", {"company": self.company, "account_number": "1121"}),
                              "cost_center": frappe.db.get_value("Company", self.company, "cost_center")}).insert()
        doc.fill_employee_details()
        frappe.set_user("Administrator")
        for row in doc.employees:
            self.assign(row.employee)
        frappe.set_user(PAYROLL)
        doc.save()
        return doc

    def act(self, doc, action, user):
        frappe.set_user(user)
        doc = frappe.get_doc(doc.doctype, doc.name)
        apply_workflow(doc, action)
        doc.reload()
        return doc

    def test_no_payroll_before_the_attendance_lock(self):
        doc = self.payroll("Ban điều hành", "2026-10-01", "2026-10-31")  # October is not closed
        with self.assertRaises(frappe.ValidationError) as caught:
            self.act(doc, "Tính lương", PAYROLL)
        self.assertIn("Hội sở", str(caught.exception))

    def test_compute_sign_and_pay(self):
        self.lock("Hội sở", [("Gửi đối soát", HR), ("Đối soát xong", HR2), ("Ký và khoá", CEO)])
        doc = self.act(self.payroll("Ban điều hành"), "Tính lương", PAYROLL)
        self.assertEqual((doc.workflow_state, doc.docstatus), ("Đã tính lương", 1))
        self.assertEqual(set(frappe.get_all("Salary Slip", filters={"payroll_entry": doc.name}, pluck="docstatus")), {0})
        doc = self.act(doc, "Gửi ký", PAYROLL)
        with self.assertRaises(frappe.ValidationError):
            self.act(doc, "Trả lại", CEO)  # returning needs a reason
        doc = self.act(doc, "Ký duyệt", CEO)
        self.assertEqual(set(frappe.get_all("Salary Slip", filters={"payroll_entry": doc.name}, pluck="docstatus")), {1})
        with self.assertRaises(frappe.ValidationError):
            self.act(doc, "Xác nhận đã chi", ACCOUNTANT)  # no bank reference yet
        frappe.db.set_value("Payroll Entry", doc.name, {"tlc_bank_reference": "VCB-UNC-0926-001", "tlc_paid_on": "2026-10-05"})
        doc = self.act(doc, "Xác nhận đã chi", ACCOUNTANT)
        self.assertEqual(doc.workflow_state, "Đã chi")
        self.assertTrue(frappe.db.exists("Journal Entry", {"voucher_type": "Bank Entry", "cheque_no": "VCB-UNC-0926-001", "docstatus": 1}))

    def test_overtime_paid_as_taxed_part_and_free_premium(self):
        worker = employee_of("binh@demo.example")
        frappe.get_doc({"doctype": "TLC Overtime Request", "employee": worker, "employee_user": "binh@demo.example",
                        "department": frappe.db.get_value("Employee", worker, "department"), "ot_date": "2026-08-12", "from_time": "17:30:00",
                        "to_time": "20:30:00", "hours": 3, "day_type": "Ngày thường", "reason": "Kiểm kê cuối tháng", "docstatus": 1,
                        "workflow_state": "Đã duyệt"}).db_insert()  # approved before the month closes
        rows = [frappe._dict(employee=worker)]
        self.lock("Nhà máy 1", [("Gửi xác nhận", HR), ("Xác nhận", HEAD), ("Đối soát xong", HR2), ("Ký và khoá", CEO)])
        doc = self.act(self.payroll("Nhà máy 1"), "Tính lương", PAYROLL)
        employee = rows[0].employee
        paid = {r.salary_component: flt(r.amount) for r in frappe.get_all(
            "Additional Salary", filters={"employee": employee, "ref_docname": doc.name, "docstatus": 1}, fields=["salary_component", "amount"])}
        self.assertTrue(paid.get("Tiền tăng ca") and paid.get("Phụ trội tăng ca"))
        slip = frappe.get_doc("Salary Slip", {"payroll_entry": doc.name, "employee": employee})
        self.assertEqual((amount(slip, "OT"), amount(slip, "OTP")), (paid["Tiền tăng ca"], paid["Phụ trội tăng ca"]))
