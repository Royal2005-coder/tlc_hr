"""Draft separation fixture only; never changes Employee status or approves a termination."""
import frappe
from frappe.utils import add_days, today


def run(data=None):
    employee = frappe.db.get_value("Employee", {"user_id": "an@demo.example"}, "name")
    if not employee:
        frappe.throw("Seed UAT lifecycle cần nhân viên An.")
    reason = "TLC UAT W4 notice and clearance"
    existing = frappe.db.get_value("Employee Separation", {"employee": employee, "custom_tlc_reason": reason}, "name")
    if existing:
        return existing
    company = frappe.db.get_value("Employee", employee, "company")
    doc = frappe.get_doc({"doctype": "Employee Separation", "employee": employee, "company": company,
        "boarding_begins_on": today(), "custom_tlc_case_type": "Employee resignation",
        "custom_tlc_submitted_on": today(), "custom_tlc_last_day": add_days(today(), 45),
        "custom_tlc_effective_on": add_days(today(), 46), "custom_tlc_reason": reason,
        "custom_tlc_contract_category": "Indefinite", "custom_tlc_evidence": [
            {"item": "DEMO identity handover", "category": "Handover", "required": 1, "status": "Pending"},
            {"item": "DEMO IT account revocation", "category": "Account", "required": 1, "status": "Pending"}]})
    doc.insert(ignore_permissions=True)
    return doc.name
