"""Document events of tlc_hr (registered in hooks.doc_events)."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from tlc_hr.workflow_rules import apply_common

# Corrections about a day already worked; only a business trip may be declared ahead.
PAST_ONLY = ("Quên chấm vào", "Quên chấm ra", "Máy chấm công lỗi")
POST_LOCK = "Điều chỉnh sau chốt"


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
    if not doc.get("shift") and doc.get("employee"):
        # HRMS updates the attendance of the same shift only; the app form does not ask a worker for their shift.
        doc.shift = (frappe.db.get_value("Attendance", {"employee": doc.employee, "attendance_date": doc.from_date, "docstatus": 1}, "shift")
                     or frappe.db.get_value("Employee", doc.employee, "default_shift"))
    if doc.get("tlc_correction_type") in PAST_ONLY and getdate(doc.to_date) > getdate(nowdate()):
        frappe.throw(_("Chỉ giải trình {0} cho ngày đã qua.").format(doc.tlc_correction_type.lower()))
    if doc.get("tlc_correction_type") == POST_LOCK:
        check_post_lock(doc)
    apply_common(doc, approver_field="tlc_approver")


def check_post_lock(doc):
    """A change to a locked month: HR writes it for a day of a locked period, with the reason; it is approved like a correction."""
    from tlc_hr.attendance.lock import locked_period

    if doc.is_new() and not set(frappe.get_roles()).intersection(("TLC HR Lead", "TLC HR Officer", "System Manager")):
        frappe.throw(_("Chỉ nhân sự lập điều chỉnh sau chốt."), frappe.PermissionError)
    if not locked_period(doc.employee, doc.from_date, doc.to_date):
        frappe.throw(_("Ngày này chưa thuộc kỳ công đã khoá: dùng giải trình công thông thường."))
    if not (doc.explanation or "").strip():
        frappe.throw(_("Ghi lý do điều chỉnh sau chốt."))
