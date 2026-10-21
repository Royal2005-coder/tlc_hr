"""Adapter of the shared approval rules for any request doctype (called from the doc_events of each request)."""

import frappe

from tlc_hr.domain import approval
from tlc_hr.interface.errors import domain_errors


def state_change(doc, subject_user=None):
    before = doc.get_doc_before_save()
    if subject_user is None and doc.get("employee"):
        subject_user = frappe.db.get_value("Employee", doc.employee, "user_id")
    return approval.StateChange(before=before.get("workflow_state") if before else None, after=doc.get("workflow_state"),
                                reason=doc.get("tlc_reject_reason"), actor=frappe.session.user, subject=subject_user)


def record_rejection(doc):
    with domain_errors():
        stage = approval.rejected_stage(state_change(doc, subject_user=""))
    if stage and doc.meta.has_field("tlc_rejected_stage"):
        doc.tlc_rejected_stage = stage


def no_self_decision(doc, subject_user=None):
    if not doc.get_doc_before_save() or not doc.has_value_changed("workflow_state"):
        return
    with domain_errors():
        approval.check_not_self(state_change(doc, subject_user))


def fill_approver(doc, field):
    """The approver of the first level is the line manager of the employee (Employee.leave_approver), filled on the server."""
    if not doc.get(field) and doc.get("employee"):
        doc.set(field, frappe.db.get_value("Employee", doc.employee, "leave_approver"))


def apply_common(doc, approver_field=None, subject_user=None):
    if approver_field:
        fill_approver(doc, approver_field)
    record_rejection(doc)
    no_self_decision(doc, subject_user)
