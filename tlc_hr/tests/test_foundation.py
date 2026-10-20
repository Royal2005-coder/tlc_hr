"""Foundation of payroll, advances and expenses on the seeded TLC demo (accounts, employee payroll fields, 2026 parameters)."""

import frappe
from frappe.tests import IntegrationTestCase

COMPANY = "TLC Demo"


class TestFoundation(IntegrationTestCase):
    def setUp(self):
        if not frappe.db.exists("Company", COMPANY):
            self.skipTest("TLC demo seed not loaded")

    def test_company_accounts_for_payroll_advances_and_claims(self):
        company = frappe.get_doc("Company", COMPANY)
        for field, account_type in (("default_payroll_payable_account", "Payable"), ("default_employee_advance_account", "Receivable"),
                                    ("default_expense_claim_payable_account", "Payable")):
            account = company.get(field)
            self.assertTrue(account, field)
            self.assertEqual(frappe.db.get_value("Account", account, "account_type"), account_type, field)

    def test_payroll_reads_the_tlc_wage_and_dependents(self):
        quang = frappe.db.get_value("Employee", {"user_id": "quang@demo.example"},
                                    ["tlc_monthly_wage", "vn_insurance_salary", "tlc_dependents", "vn_number_of_dependents"], as_dict=True)
        self.assertEqual(quang.vn_insurance_salary, quang.tlc_monthly_wage)
        self.assertEqual((quang.tlc_dependents, quang.vn_number_of_dependents), (2, 2))

    def test_2026_regional_minimum_in_settings(self):
        self.assertEqual(frappe.db.get_single_value("VN Payroll Settings", "min_wage_region_1"), 5_310_000)
