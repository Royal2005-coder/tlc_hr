"""Locked attendance periods (doc_events of six doctypes): once the CEO signs a TLC Attendance Period, nobody changes the time
data of its people and days directly. The one way in is a post-lock adjustment ("Điều chỉnh sau chốt"): an Attendance Request
created by HR, approved like any correction, logged on the period and paid with the next payroll.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from tlc_hr.attendance.period import scope_of_employee

POST_LOCK = "Điều chỉnh sau chốt"
# doctype -> (start field, end field) of the days a document touches
GUARDED = {"Attendance": ("attendance_date", "attendance_date"), "Employee Checkin": ("time", "time"),
           "Leave Application": ("from_date", "to_date"), "Attendance Request": ("from_date", "to_date"),
           "TLC Overtime Request": ("ot_date", "ot_date"), "Shift Assignment": ("start_date", "start_date")}


def locked_period(employee, start, end=None):
    company = frappe.db.get_value("Employee", employee, "company")
    return frappe.db.get_value("TLC Attendance Period", {"docstatus": 1, "company": company, "scope": scope_of_employee(employee),
                                                         "from_date": ["<=", getdate(end or start)], "to_date": [">=", getdate(start)]},
                               ["name", "title"], as_dict=True)


def days_of(doc):
    start_field, end_field = GUARDED[doc.doctype]
    start = doc.get(start_field)
    return (getdate(start), getdate(doc.get(end_field) or start)) if start else (None, None)


def guard(doc, method=None):
    if frappe.flags.tlc_post_lock or frappe.flags.in_install or frappe.flags.in_migrate or not doc.get("employee"):
        return
    if doc.doctype == "Attendance Request" and doc.get("tlc_correction_type") == POST_LOCK:
        return  # the sanctioned way to change a locked day
    versions = [doc]
    before = doc.get_doc_before_save() if method == "validate" else None
    if before and before.get("employee"):
        versions.append(before)  # moving a document out of a locked day is a change of that day too
    for version in versions:
        start, end = days_of(version)
        period = start and locked_period(version.employee, start, end)
        if period:
            frappe.throw(_("{0} đã khoá: không sửa dữ liệu công của kỳ này. HR lập \"Điều chỉnh sau chốt\" (giải trình công) để thay đổi.")
                         .format(period.title), title=_("Kỳ công đã khoá"))


def allow_post_lock(doc, method=None):
    """Attendance Request before_submit: HRMS writes Attendance on submit; let an approved post-lock adjustment through."""
    if doc.get("tlc_correction_type") == POST_LOCK:
        frappe.flags.tlc_post_lock = True


def log_post_lock(doc, method=None):
    """Attendance Request on_submit: record the adjustment on the locked period (paid with the next payroll)."""
    if doc.get("tlc_correction_type") != POST_LOCK:
        return
    frappe.flags.tlc_post_lock = False
    period = locked_period(doc.employee, doc.from_date, doc.to_date)
    if period:
        frappe.get_doc("TLC Attendance Period", period.name).add_comment(
            "Info", _("Điều chỉnh sau chốt {0}: {1}, {2} – {3}. Lý do: {4}. Tính vào kỳ lương kế tiếp.").format(
                doc.name, doc.employee_name, frappe.format(doc.from_date, "Date"), frappe.format(doc.to_date, "Date"), doc.explanation))
