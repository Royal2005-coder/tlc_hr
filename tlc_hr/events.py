"""Document events of tlc_hr (registered in hooks.doc_events)."""

import frappe
from frappe import _

from tlc_hr.setup.install import REJECTED


def leave_application_validate(doc, method=None):
    """Fill the approver from the employee, require a reason to reject, and refuse a decision on a request of one's own."""
    if not doc.get("leave_approver"):
        # HRMS fills it only in the browser form; requests made through the API or the portal need it too.
        doc.leave_approver = frappe.db.get_value("Employee", doc.employee, "leave_approver")
    before = doc.get_doc_before_save()
    if doc.get("workflow_state") == REJECTED and before and before.get("workflow_state") != REJECTED:
        doc.tlc_rejected_stage = before.get("workflow_state")  # which level said no: line manager or HR
    if doc.get("workflow_state") == REJECTED and not (doc.get("tlc_reject_reason") or "").strip():
        frappe.throw(_("Nhập lý do từ chối trước khi từ chối đơn."), title=_("Thiếu lý do từ chối"))
    if doc.has_value_changed("workflow_state") and doc.get("workflow_state") != "Nháp":
        own_user = frappe.db.get_value("Employee", doc.employee, "user_id")
        is_decision = doc.get_doc_before_save() and doc.get_doc_before_save().get("workflow_state") != "Nháp"
        if is_decision and own_user and own_user == frappe.session.user:
            frappe.throw(_("Bạn không thể tự duyệt hay từ chối đơn của chính mình."), title=_("Không được tự duyệt"))
