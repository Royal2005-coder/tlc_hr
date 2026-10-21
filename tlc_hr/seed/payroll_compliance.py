"""Dedicated demo fixtures for Payroll Compliance Desk UAT.

Never invoked automatically by imports or migrations.
Creates demo evidence files, salary review proposals, adjustment vouchers,
performance bonuses, and statutory insurance filings.
"""
from datetime import date

import frappe
from frappe.utils import add_days, getdate, today
from frappe.utils.file_manager import save_file


def _insert(doctype, filters, values, submit=False):
    existing = frappe.db.get_value(doctype, filters, "name")
    if existing:
        return existing
    doc = frappe.get_doc({"doctype": doctype, **values})
    doc.insert(ignore_permissions=True)
    if submit:
        doc.submit()
    return doc.name


def run(data=None):
    """Seed demo fixtures for payroll compliance UAT."""
    company = frappe.db.get_value("Company", {}, "name")
    if not company:
        return {}

    # Ensure company has variance threshold
    frappe.db.set_value("Company", company, "tlc_payroll_variance_percent", 20)

    # Get sample employees from main seed
    an_emp = frappe.db.get_value("Employee", {"user_id": "an@demo.example"}, "name")
    quang_emp = frappe.db.get_value("Employee", {"user_id": "quang@demo.example"}, "name")
    if not an_emp:
        an_emp = frappe.db.get_value("Employee", {}, "name")
    if not quang_emp:
        quang_emp = an_emp

    # Private evidence file
    evidence_url = frappe.db.get_value("File", {"file_name": "tlc-payroll-demo-evidence.txt", "is_private": 1}, "file_url")
    if not evidence_url and an_emp:
        evidence_url = save_file(
            "tlc-payroll-demo-evidence.txt",
            "TLC DEMO ONLY. Chứng từ mẫu cho UAT kiểm tra biến động, quyết định lương, thưởng và bảo hiểm.\n",
            "Employee",
            an_emp,
            is_private=1
        ).file_url

    results = {"evidence": evidence_url}

    # 1. Demo Salary Review (Annual review batch)
    dept = frappe.db.get_value("Employee", an_emp, "department")
    base_an = frappe.db.get_value(
        "Salary Structure Assignment",
        {"employee": an_emp, "docstatus": 1},
        "base",
        order_by="from_date desc"
    ) or 15000000.0

    review_name = _insert(
        "TLC Salary Review",
        {"reason": "TLC UAT Annual Salary Review 2026"},
        {
            "company": company,
            "department": dept,
            "effective_on": "2026-07-01",
            "annual_budget_increase": 50000000,
            "review_stage": "Draft",
            "reason": "TLC UAT Annual Salary Review 2026",
            "evidence": evidence_url,
            "employees": [
                {
                    "employee": an_emp,
                    "old_base": base_an,
                    "new_base": base_an + 2000000.0
                }
            ]
        }
    )
    results["salary_review"] = review_name

    # 2. Demo Payroll Bonus (Monthly / Yearly bonus)
    bonus_name = _insert(
        "TLC Payroll Bonus",
        {"reason": "TLC UAT Monthly Performance Bonus"},
        {
            "employee": an_emp,
            "frequency": "Monthly",
            "period_start": "2026-06-01",
            "period_end": "2026-06-30",
            "payroll_date": "2026-07-05",
            "multiplier": 0.5,
            "reason": "TLC UAT Monthly Performance Bonus",
            "evidence": evidence_url
        }
    )
    results["bonus"] = bonus_name

    # 3. Demo Insurance Change (D02-LT labor change)
    ins_change = _insert(
        "TLC Insurance Change",
        {"filing_reference": "BHXH-UAT-D02-202607-01"},
        {
            "employee": an_emp,
            "insurance_number": "7912345678",
            "change_type": "Base Change",
            "effective_on": "2026-07-01",
            "contribution_base": 18000000,
            "status": "Prepared",
            "filing_reference": "BHXH-UAT-D02-202607-01",
            "reason": "TLC UAT Điều chỉnh mức đóng BHXH định kỳ",
            "evidence": evidence_url
        }
    )
    results["insurance_change"] = ins_change

    # 4. Demo Insurance Benefit (Sickness / Maternity)
    leave_app = frappe.db.get_value("Leave Application", {"employee": an_emp, "docstatus": 1}, "name")
    if leave_app:
        l_doc = frappe.get_doc("Leave Application", leave_app)
        ins_benefit = _insert(
            "TLC Insurance Benefit",
            {"leave_application": leave_app},
            {
                "employee": an_emp,
                "leave_application": leave_app,
                "benefit_type": "Sickness",
                "actual_from": l_doc.from_date,
                "actual_to": l_doc.to_date,
                "status": "Prepared",
                "evidence": evidence_url
            }
        )
        results["insurance_benefit"] = ins_benefit

    # 5. Demo Payroll Adjustment (next-period correction against submitted slip)
    past_slip = frappe.db.get_value("Salary Slip", {"employee": an_emp, "docstatus": 1}, "name")
    if past_slip:
        s_doc = frappe.get_doc("Salary Slip", past_slip)
        comp = frappe.db.get_value("Salary Component", {"salary_component_abbr": "PCTN"}, "name")
        if comp:
            adj_name = _insert(
                "TLC Payroll Adjustment",
                {"original_slip": past_slip, "reason": "TLC UAT Truy lĩnh phụ cấp trách nhiệm"},
                {
                    "original_slip": past_slip,
                    "employee": an_emp,
                    "salary_component": comp,
                    "direction": "Increase",
                    "amount": 1000000,
                    "payroll_date": add_days(s_doc.end_date, 30),
                    "reason": "TLC UAT Truy lĩnh phụ cấp trách nhiệm",
                    "evidence": evidence_url
                }
            )
            results["adjustment"] = adj_name

    return results
