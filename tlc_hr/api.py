"""Actions of the /tlc home: ask for leave and decide on a request in one call.

Both go through the workflow TLC Nghỉ phép, so its roles, conditions and the no-self-approval rule stay the only authority.
"""

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import cint, flt, getdate

from tlc_hr.setup.install import DRAFT, TO_HR, TO_MANAGER

DECISIONS = {"approve": "Duyệt", "reject": "Từ chối"}


def my_employee():
    employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"})
    if not employee:
        frappe.throw(_("Tài khoản này chưa gắn với hồ sơ nhân viên."), frappe.PermissionError)
    return employee


@frappe.whitelist(methods=["POST"])
def submit_leave(leave_type, from_date, to_date, reason, half_day=0, half_day_date=None):
    """Create the leave request of the signed-in employee and send it to their approver."""
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Nhập lý do xin nghỉ."))
    if getdate(to_date) < getdate(from_date):
        frappe.throw(_("Ngày kết thúc phải sau hoặc bằng ngày bắt đầu."))
    doc = frappe.get_doc({
        "doctype": "Leave Application",
        "employee": my_employee(),
        "leave_type": leave_type,
        "from_date": from_date,
        "to_date": to_date,
        "half_day": cint(half_day),
        "half_day_date": half_day_date or (from_date if cint(half_day) else None),
        "description": reason,
    })
    doc.insert()
    apply_workflow(doc, "Gửi duyệt")
    doc.reload()
    return {"name": doc.name, "workflow_state": doc.workflow_state, "leave_approver": doc.leave_approver,
            "total_leave_days": doc.total_leave_days}


@frappe.whitelist(methods=["POST"])
def decide(name, decision, reason=None):
    """Approve or reject a leave request waiting for the signed-in user; a rejection must give a reason."""
    if decision not in DECISIONS:
        frappe.throw(_("Quyết định không hợp lệ."))
    doc = frappe.get_doc("Leave Application", name)
    doc.check_permission("read")
    if decision == "reject":
        reason = (reason or "").strip()
        if not reason:
            frappe.throw(_("Nhập lý do từ chối."))
        doc.tlc_reject_reason = reason
        doc.save()
    apply_workflow(doc, DECISIONS[decision])
    doc.reload()
    return {"name": doc.name, "workflow_state": doc.workflow_state, "status": doc.status}


@frappe.whitelist(methods=["POST"])
def withdraw(name):
    """Withdraw one's own request while nobody has decided on it yet (draft or waiting for the line manager).

    The request is deleted; Frappe keeps a copy in Deleted Document for the audit trail.
    """
    doc = frappe.get_doc("Leave Application", name)
    if doc.employee != my_employee() or doc.docstatus != 0 or doc.workflow_state not in (DRAFT, TO_MANAGER, None, ""):
        frappe.throw(_("Chỉ rút được đơn của chính mình khi chưa ai duyệt."), frappe.PermissionError)
    frappe.delete_doc("Leave Application", name, ignore_permissions=True)
    return {"name": name, "deleted": True}


@frappe.whitelist(methods=["POST"])
def preview_leave(leave_type, from_date, to_date, half_day=0):
    """Working days of a planned request and the balance before and after it, for the request dialog."""
    from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on, get_number_of_leave_days

    employee = my_employee()
    if getdate(to_date) < getdate(from_date):
        frappe.throw(_("Ngày kết thúc phải sau hoặc bằng ngày bắt đầu."))
    days = flt(get_number_of_leave_days(employee, leave_type, from_date, to_date, cint(half_day), from_date if cint(half_day) else None))
    balance = flt(get_leave_balance_on(employee, leave_type, from_date, consider_all_leaves_in_the_allocation_period=True))
    pending = sum(flt(d) for d in frappe.get_all("Leave Application", filters={"employee": employee, "leave_type": leave_type,
                                                                              "workflow_state": ["in", (TO_MANAGER, TO_HR)], "docstatus": 0},
                                                 pluck="total_leave_days"))
    return {"days": days, "balance": balance - pending, "after": balance - pending - days}
