"""Native Payroll Entry adapter for TLC computation, signing and payment confirmation."""

import frappe
from frappe.utils import getdate

from tlc_hr.application.payroll import PayrollService
from tlc_hr.contracts.payroll import ComputeOvertime, ComputePayroll
from tlc_hr.domain import payroll as rules
from tlc_hr.infrastructure.frappe import payroll as actions
from tlc_hr.infrastructure.frappe.payroll import FrappePayrollRepository
from tlc_hr.interface.errors import domain_errors

COMPUTED, TO_CEO, SIGNED, PAID = "Đã tính lương", "Chờ giám đốc ký", "Đã ký", "Đã chi"


def service():
    return PayrollService(FrappePayrollRepository())


def before_submit(doc, method=None):
    start, end = getdate(doc.start_date), getdate(doc.end_date)
    payroll = service()
    with domain_errors():
        payroll.check_can_compute(ComputePayroll(company=doc.company, start=start,
                                                 departments=tuple(row.department for row in doc.employees)))
    # Approved post-lock travel deltas become native Additional Salary rows before
    # the payroll controller creates the slips of this entry.
    from tlc_hr.interface.travel_adjustments import apply_adjustments
    apply_adjustments(doc)
    for row in doc.employees:
        pay = payroll.overtime(ComputeOvertime(employee=row.employee, start=start, end=end))
        if pay:
            actions.add_salary(doc, row.employee, "OT", pay.taxed)
            actions.add_salary(doc, row.employee, "OTP", pay.premium)


def on_cancel(doc, method=None):
    from tlc_hr.interface.travel_adjustments import release_adjustments

    actions.cancel_salaries(doc)
    release_adjustments(doc)


def before_update_after_submit(doc, method=None):
    before = doc.get_doc_before_save()
    if not before or before.workflow_state == doc.workflow_state:
        return
    with domain_errors():
        if before.workflow_state == TO_CEO and doc.workflow_state == COMPUTED:
            rules.check_return(doc.tlc_reject_reason)
            doc.tlc_rejected_stage = before.workflow_state
        if doc.workflow_state == PAID:
            from tlc_hr.interface.payroll_compliance import private_evidence
            private_evidence(doc.tlc_bank_proof)
            rules.check_payment(doc.tlc_bank_reference, getdate(doc.tlc_paid_on) if doc.tlc_paid_on else None, actions.draft_slips(doc))


def on_update_after_submit(doc, method=None):
    before = doc.get_doc_before_save()
    if not before or before.workflow_state == doc.workflow_state:
        return
    if doc.workflow_state == SIGNED:
        doc.submit_salary_slips()
    elif doc.workflow_state == PAID:
        actions.post_payment(doc, getdate(doc.start_date).strftime("%m/%Y"))


@frappe.whitelist()
def payroll_summary(name):
    doc = frappe.get_doc("Payroll Entry", name)
    doc.check_permission("read")
    return actions.summary(name)
