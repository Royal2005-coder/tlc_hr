"""Document events of tlc_hr (registered in hooks.doc_events)."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from tlc_hr.workflow_rules import apply_common

# Corrections about a day already worked; only a business trip may be declared ahead.
PAST_ONLY = ("Quên chấm vào", "Quên chấm ra", "Máy chấm công lỗi")


def employee_validate(doc, method=None):
    """Payroll reads the Vietnamese fields of erpnextvn: keep them in step with the TLC fields (one value, two names)."""
    if doc.get("tlc_monthly_wage") and not doc.get("vn_insurance_salary"):
        doc.vn_insurance_salary = doc.tlc_monthly_wage
    doc.vn_number_of_dependents = doc.get("tlc_dependents") or 0


def leave_application_validate(doc, method=None):
    """Approver from the employee when the request comes from the API; shared rules of TLC workflows."""
    if not doc.get("leave_approver"):
        # HRMS fills it in its forms; requests created through the API need it too.
        doc.leave_approver = frappe.db.get_value("Employee", doc.employee, "leave_approver")
    apply_common(doc)


def attendance_request_validate(doc, method=None):
    """Corrections: the line manager decides first; forgetting to check in is declared after the day, never ahead."""
    if doc.get("tlc_correction_type") and doc.reason != "Work From Home":
        doc.reason = "On Duty"
    if doc.get("tlc_correction_type") in PAST_ONLY and getdate(doc.to_date) > getdate(nowdate()):
        frappe.throw(_("Chỉ giải trình {0} cho ngày đã qua.").format(doc.tlc_correction_type.lower()))
    apply_common(doc, approver_field="tlc_approver")
