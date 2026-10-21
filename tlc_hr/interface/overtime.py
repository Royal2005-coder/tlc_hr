"""Adapter of TLC Overtime Request (controller hooks, permissions) and of HRMS Overtime Slip (doc_events)."""

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

from tlc_hr.application.overtime import OvertimeService
from tlc_hr.contracts.overtime import AssessOvertime, SlipRow
from tlc_hr.domain import overtime as rules
from tlc_hr.domain.shared import CANCELLED, COMPANY_WIDE_ROLES, DRAFT, REJECTED
from tlc_hr.infrastructure.frappe.overtime import FrappeCalendar, FrappeDirectory, FrappeNotifier, FrappeOvertimeRepository, scope_of
from tlc_hr.interface.approval import no_self_decision, record_rejection
from tlc_hr.interface.errors import domain_errors
from tlc_hr.setup.overtime import TO_DIRECTOR, TO_WORKER


def service():
    return OvertimeService(FrappeOvertimeRepository(), FrappeCalendar(), FrappeDirectory())


def as_time(value):
    return get_datetime(f"2000-01-01 {value}").time()


def validate(doc):
    sent_now = doc.has_value_changed("workflow_state") and doc.workflow_state == TO_WORKER
    before = doc.get_doc_before_save()
    with domain_errors():
        command = AssessOvertime(request=None if doc.is_new() else doc.name, employee=doc.employee, ot_date=getdate(doc.ot_date),
                                 from_time=as_time(doc.from_time), to_time=as_time(doc.to_time), actor=frappe.session.user,
                                 active=doc.workflow_state not in (REJECTED, CANCELLED), proposing=bool(doc.is_new() or sent_now))
        result = service().assess(command)
        if before:
            rules.check_fixed(before.as_dict(), doc.as_dict(), sent=before.get("workflow_state") not in (DRAFT, None, ""))
    doc.update({"hours": result.hours, "day_type": result.day_type, "month_hours": result.month_hours, "year_hours": result.year_hours})
    if doc.has_value_changed("workflow_state") and doc.workflow_state == TO_DIRECTOR:
        doc.consent_at = now_datetime()
    record_rejection(doc)
    if before and before.get("workflow_state") == TO_DIRECTOR:
        no_self_decision(doc, doc.employee_user)  # consenting is the worker's own decision, approving is not


def on_update(doc):
    if doc.has_value_changed("workflow_state") and doc.workflow_state == TO_WORKER and doc.employee_user:
        subject = _("Đề nghị tăng ca {0}: {1} giờ ngày {2} cần bạn đồng ý").format(doc.name, f"{doc.hours:g}", frappe.format(doc.ot_date, "Date"))
        message = _("{0} đề nghị bạn tăng ca từ {1} đến {2} ngày {3} ({4}). Lý do: {5}. Mở đơn để Đồng ý hoặc Từ chối.").format(
            frappe.utils.get_fullname(frappe.session.user), doc.from_time, doc.to_time, frappe.format(doc.ot_date, "Date"), doc.day_type,
            doc.reason)
        FrappeNotifier().notify(doc.employee_user, subject, message, doc.doctype, doc.name)


def query_conditions(user=None):
    user = user or frappe.session.user
    if set(frappe.get_roles(user)) & COMPANY_WIDE_ROLES:
        return ""
    scope = scope_of(user)
    if not scope:
        return "1=0"
    return "`tabTLC Overtime Request`.employee in ({})".format(", ".join(frappe.db.escape(e) for e in scope))


def has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    return bool(set(frappe.get_roles(user)) & COMPANY_WIDE_ROLES) or doc.employee in scope_of(user)


def cap_overtime_slip(doc, method=None):
    """Overtime Slip validate: HRMS takes the hours past the shift from Attendance; TLC pays only what was approved."""
    if not doc.overtime_details:
        return
    with domain_errors():
        rows = [SlipRow(day=getdate(r.date), hours=float(r.overtime_duration or 0)) for r in doc.overtime_details]
        capped = service().cap_slip(doc.employee, getdate(doc.start_date), getdate(doc.end_date), rows)
    allowed = {r.day: r.hours for r in capped.rows}
    kept = [r for r in doc.overtime_details if getdate(r.date) in allowed]
    for idx, row in enumerate(kept, 1):
        row.idx, row.overtime_duration = idx, allowed[getdate(row.date)]
    doc.overtime_details = kept
    if doc.meta.has_field("total_overtime_duration"):
        doc.total_overtime_duration = sum(allowed.values())
    if capped.notes:
        frappe.msgprint("<br>".join(capped.notes), title=_("Giờ tăng ca được tính theo đơn đã duyệt"), indicator="orange")
