"""Rules shared by every TLC approval workflow (leave, attendance corrections, overtime, travel, money, separation).

- the approver of the first level is the line manager of the employee (Employee.leave_approver), filled on the server;
- moving a request to "Từ chối" needs a reason, and the level that refused is recorded;
- nobody decides on a request about themself (the workflow's own self-approval check only looks at the owner of the document).
"""

import frappe
from frappe import _

from tlc_hr.setup.install import DRAFT, REJECTED


def fill_approver(doc, field):
    if not doc.get(field) and doc.get("employee"):
        doc.set(field, frappe.db.get_value("Employee", doc.employee, "leave_approver"))


def record_rejection(doc):
    before = doc.get_doc_before_save()
    if doc.get("workflow_state") == REJECTED and before and before.get("workflow_state") != REJECTED:
        if doc.meta.has_field("tlc_rejected_stage"):
            doc.tlc_rejected_stage = before.get("workflow_state")
    if doc.get("workflow_state") == REJECTED and not (doc.get("tlc_reject_reason") or "").strip():
        frappe.throw(_("Nhập lý do từ chối trước khi từ chối đơn."), title=_("Thiếu lý do từ chối"))


def no_self_decision(doc, subject_user=None):
    """A request leaving a pending state may not be decided by the person it is about."""
    before = doc.get_doc_before_save()
    if not before or not doc.has_value_changed("workflow_state"):
        return
    if before.get("workflow_state") in (DRAFT, None, ""):
        return  # sending one's own request is not a decision
    subject_user = subject_user or (frappe.db.get_value("Employee", doc.employee, "user_id") if doc.get("employee") else None)
    if subject_user and subject_user == frappe.session.user:
        frappe.throw(_("Bạn không thể tự duyệt hay từ chối đơn của chính mình."), title=_("Không được tự duyệt"))


def apply_common(doc, approver_field=None, subject_user=None):
    if approver_field:
        fill_approver(doc, approver_field)
    record_rejection(doc)
    no_self_decision(doc, subject_user)
