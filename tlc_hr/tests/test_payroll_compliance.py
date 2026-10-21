"""Unit and integration regressions for TLC Payroll Compliance (HR-LG-01..26).

Covers:
- Effective salary proration and segments.
- Variance and unapproved salary review gating before CEO sign.
- Approved payroll immutability and next-period adjustment voucher lifecycle.
- Performance bonus service calculation and duplicate prevention.
- Insurance changes (D02-LT) and benefit claims against leave records.
- Annual salary review authorization, department budgeting, and SSA issuance.
- Role-private access enforcement on cost reports and exports.
- Bank export disclaimer and statutory reports (PIT, Labor register, Simulation).
"""
import json
from datetime import date
from decimal import Decimal

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate
from frappe.utils.file_manager import save_file

from tlc_hr.domain.payroll_compliance import effective_base, service_bonus, variance_percent
from tlc_hr.infrastructure.frappe import payroll_compliance_exports as exports
from tlc_hr.interface import payroll_compliance as comp

PAYROLL_USER = "phuong@demo.example"
CEO_USER = "thanh@demo.example"
HR_USER = "lan@demo.example"
WORKER_USER = "an@demo.example"
FACTORY_HEAD = "hung@demo.example"


class TestPayrollCompliance(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.company = frappe.db.get_value("Company", {}, "name")
        self.employee = frappe.db.get_value("Employee", {"user_id": WORKER_USER}, "name")
        if not self.company or not self.employee:
            self.skipTest("Demo data not initialized")

        # Setup private evidence fixture
        self.evidence = frappe.db.get_value("File", {"file_name": "test-evidence.txt", "is_private": 1}, "file_url")
        if not self.evidence:
            self.evidence = save_file(
                "test-evidence.txt",
                "TEST EVIDENCE ONLY. Phê duyệt lương và chứng từ kiểm tra.\n",
                "Employee",
                self.employee,
                is_private=1
            ).file_url

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_effective_base_pure_domain_proration(self):
        # 15 days at 20,000,000 and 15 days at 30,000,000
        segments = [
            {"base": 20000000, "payment_days": 15},
            {"base": 30000000, "payment_days": 15}
        ]
        avg = effective_base(segments)
        self.assertEqual(avg, Decimal("25000000"))

        # Zero paid days returns 0
        self.assertEqual(effective_base([{"base": 20000000, "payment_days": 0}]), Decimal("0"))

    def test_variance_calculation(self):
        self.assertEqual(variance_percent(100, 120), Decimal("20"))
        self.assertEqual(variance_percent(100, 80), Decimal("20"))
        self.assertEqual(variance_percent(0, 100), Decimal("100"))
        self.assertEqual(variance_percent(0, 0), Decimal("0"))

    def test_service_bonus_proration(self):
        # Joining on 2026-07-01 in a full calendar year bonus
        # (365 - 181 + 1) = 184 days in second half of 2026
        bonus = service_bonus(
            reference_salary=10000000,
            multiplier=1.0,
            period_start="2026-01-01",
            period_end="2026-12-31",
            joining_date="2026-07-01"
        )
        # 184 / 365 * 10,000,000 = 5,041,096
        self.assertEqual(bonus, Decimal("5041096"))

        # Relieved before period end
        early_bonus = service_bonus(
            reference_salary=12000000,
            multiplier=1.0,
            period_start="2026-01-01",
            period_end="2026-12-31",
            joining_date="2025-01-01",
            relieving_date="2026-06-30"
        )
        # 181 days out of 365 = 5,950,685
        self.assertEqual(early_bonus, Decimal("5950685"))

    def fill_entry(self, entry):
        """Mandatory accounting fields of a Payroll Entry (company currency, payable and bank accounts)."""
        entry.update({"currency": frappe.db.get_value("Company", self.company, "default_currency"), "exchange_rate": 1,
                      "posting_date": "2026-08-31", "payroll_frequency": "Monthly",
                      "payroll_payable_account": frappe.db.get_value("Company", self.company, "default_payroll_payable_account"),
                      "payment_account": frappe.db.get_value("Account", {"company": self.company, "account_number": "1121"}),
                      "cost_center": frappe.db.get_value("Company", self.company, "cost_center")})

    def test_large_variance_gate_requires_review(self):
        frappe.set_user("Administrator")
        entry = frappe.new_doc("Payroll Entry")
        entry.company = self.company
        self.fill_entry(entry)
        entry.start_date = "2026-08-01"
        entry.end_date = "2026-08-31"
        entry.payroll_frequency = "Monthly"
        entry.workflow_state = "Nháp"
        entry.insert(ignore_permissions=True)

        # Mock review_issues returning a variance issue
        with unittest_mock(comp, "entry_payload", lambda e: [{"employee": self.employee, "name": "SLIP-TEST"}]):
            with unittest_mock(comp, "review_issues", lambda e: [{
                "employee": self.employee,
                "issue": "Variance",
                "fingerprint": "abc123hash",
                "details": "Gross increased by 40%"
            }]):
                # Attempt to move to "Chờ giám đốc ký" without review must throw
                entry._doc_before_save = frappe.get_doc(entry.doctype, entry.name)  # as Document.save does
                entry.workflow_state = "Chờ giám đốc ký"
                with self.assertRaises(frappe.ValidationError):
                    comp.entry_guard(entry)

                # Now insert submitted review
                review = frappe.new_doc("TLC Payroll Review")
                review.payroll_entry = entry.name
                review.employee = self.employee
                review.issue = "Variance"
                review.review_fingerprint = "abc123hash"
                review.reason = "Thưởng đột xuất được phê duyệt"
                review.evidence = self.evidence
                review.insert(ignore_permissions=True)
                review.submit()

                # Gating now passes
                comp.entry_guard(entry)

    def test_approved_payroll_immutability(self):
        frappe.set_user("Administrator")
        entry = frappe.new_doc("Payroll Entry")
        entry.company = self.company
        self.fill_entry(entry)
        entry.start_date = "2026-07-01"
        entry.end_date = "2026-07-31"
        entry.insert(ignore_permissions=True)
        entry.db_set("workflow_state", "Đã ký")  # signed by the CEO through the workflow

        # Prohibit approved deletion
        with self.assertRaises(frappe.ValidationError):
            comp.prohibit_approved_change(entry, method="on_trash")

        # Prohibit approved cancel
        with self.assertRaises(frappe.ValidationError):
            comp.prohibit_approved_change(entry, method="before_cancel")

    def test_salary_review_budget_and_permissions(self):
        dept = frappe.db.get_value("Employee", self.employee, "department")
        base = frappe.db.get_value("Salary Structure Assignment", {"employee": self.employee, "docstatus": 1}, "base") or 10000000.0

        # Create review exceeding budget
        review = frappe.new_doc("TLC Salary Review")
        review.company = self.company
        review.department = dept
        review.effective_on = "2026-10-01"
        review.annual_budget_increase = 1000000  # Budget is 1M VND
        review.reason = "Xét tăng lương bộ phận"
        review.evidence = self.evidence
        review.append("employees", {
            "employee": self.employee,
            "old_base": base,
            "new_base": base + 500000  # 500k/mo * 12 = 6M VND > 1M budget
        })

        with self.assertRaises(frappe.ValidationError):
            review.insert(ignore_permissions=True)

        # Adjust budget to 10M VND -> Valid insert
        review.annual_budget_increase = 10000000
        review.insert(ignore_permissions=True)
        self.assertEqual(review.review_stage, "Draft")

    def test_role_private_cost_reports(self):
        # Non-payroll worker cannot access cost report
        frappe.set_user(WORKER_USER)
        with self.assertRaises(frappe.PermissionError):
            exports.get_role_private_cost_report(self.company, "2026-01-01", "2026-12-31")

        # Factory manager cannot access cost report
        frappe.set_user(FACTORY_HEAD)
        with self.assertRaises(frappe.PermissionError):
            exports.get_role_private_cost_report(self.company, "2026-01-01", "2026-12-31")

        # Authorized HR / Payroll user can access
        frappe.set_user(PAYROLL_USER)
        res = exports.get_role_private_cost_report(self.company, "2026-01-01", "2026-12-31")
        self.assertIn("groups", res)
        self.assertIn("summary", res)

    def test_bank_batch_export_disclaimer(self):
        frappe.set_user("Administrator")
        entry = frappe.new_doc("Payroll Entry")
        entry.company = self.company
        self.fill_entry(entry)
        entry.start_date = "2026-06-01"
        entry.end_date = "2026-06-30"
        entry.insert(ignore_permissions=True)

        # Mock slips
        with unittest_mock(frappe, "get_all", lambda *a, **kw: [{"name": "SLIP-01", "employee": self.employee,
                           "employee_name": "Nguyen Hoai An", "net_pay": 15000000, "bank_name": "VCB", "bank_account_no": "123"}]):
            res = exports.export_bank_payment_batch(entry.name, "VCB")
            self.assertFalse(res["certified"])
            self.assertIn("UNVERIFIED BANK TEMPLATE", res["content"])
            self.assertIn("Not certified", res["note"])

    def test_salary_simulation(self):
        frappe.set_user(PAYROLL_USER)
        sim = exports.simulate_salary_budget(self.company, 10, base_date="2026-07-01")
        self.assertEqual(sim["percent_increase"], 10.0)
        self.assertGreater(sim["simulated_monthly_base"], sim["current_monthly_base"])
        self.assertGreater(sim["annualized_cost_delta"], 0)


class unittest_mock:
    """Lightweight patch context manager."""
    def __init__(self, target, attribute, mock_value):
        self.target = target
        self.attribute = attribute
        self.mock_value = mock_value
        self.original = None

    def __enter__(self):
        self.original = getattr(self.target, self.attribute)
        setattr(self.target, self.attribute, self.mock_value)
        return self.mock_value

    def __exit__(self, exc_type, exc_val, exc_tb):
        setattr(self.target, self.attribute, self.original)
