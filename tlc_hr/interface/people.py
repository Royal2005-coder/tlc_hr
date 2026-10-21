"""Adapters of leave requests and employee records (doc_events)."""

import frappe

from frappe.utils import getdate

from tlc_hr.domain.attendance import carry_forward_expiry
from tlc_hr.interface.approval import apply_common
from tlc_hr.interface.errors import domain_errors


def employee_validate(doc, method=None):
    """Payroll reads the Vietnamese fields of erpnextvn: keep them in step with the TLC fields (one value, two names)."""
    if doc.get("tlc_monthly_wage") and not doc.get("vn_insurance_salary"):
        doc.vn_insurance_salary = doc.tlc_monthly_wage
    doc.vn_number_of_dependents = doc.get("tlc_dependents") or 0


def carried_leave_validate(doc, method=None):
    """HRMS has a fixed day-count setting; use a calendar expiry for TLC annual carried balances."""
    if (doc.leave_type != "Phép năm" or doc.transaction_type != "Leave Allocation"
            or not doc.is_carry_forward or doc.is_expired):
        return
    start, end = frappe.db.get_value("Leave Allocation", doc.transaction_name, ["from_date", "to_date"])
    with domain_errors():
        doc.to_date = carry_forward_expiry(getdate(start), getdate(end))


def leave_application_validate(doc, method=None):
    """Approver from the employee when the request comes from the API; shared rules of TLC workflows."""
    if not doc.get("leave_approver"):
        doc.leave_approver = frappe.db.get_value("Employee", doc.employee, "leave_approver")
    apply_common(doc)
