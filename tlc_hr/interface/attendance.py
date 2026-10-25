"""Adapters of attendance: Employee Checkin, Attendance Request (corrections), the lock of a closed month on six doctypes, and the
controller of TLC Attendance Period. Each turns the Frappe document into plain values, calls AttendanceService, and maps errors."""

import frappe
from frappe import _
from frappe.utils import get_datetime, get_fullname, getdate, now_datetime, nowdate

from tlc_hr.application.attendance import AttendanceService
from tlc_hr.contracts.attendance import Correction, PeriodKey
from tlc_hr.domain import attendance as rules
from tlc_hr.domain.shared import COMPANY_WIDE_ROLES
from tlc_hr.infrastructure.frappe.attendance import FrappeAttendanceRepository
from tlc_hr.interface.approval import apply_common
from tlc_hr.interface.errors import domain_errors

# doctype -> (start field, end field) of the days a document touches
GUARDED = {"Attendance": ("attendance_date", "attendance_date"), "Employee Checkin": ("time", "time"),
           "Leave Application": ("from_date", "to_date"), "Attendance Request": ("from_date", "to_date"),
           "TLC Overtime Request": ("ot_date", "ot_date"), "Shift Assignment": ("start_date", "end_date")}


def service():
    return AttendanceService(FrappeAttendanceRepository())


# ---------------------------------------------------------------- check-in and corrections

def checkin_validate(doc, method=None):
    with domain_errors():
        service().check_in(doc.employee, doc.shift, get_datetime(doc.time))


def correction_validate(doc, method=None):
    """Corrections: the line manager decides first; forgetting to check in is declared after the day, never ahead."""
    if doc.get("tlc_correction_type") and doc.reason != "Work From Home":
        doc.reason = "On Duty"
    before = doc.get_doc_before_save()
    creating_adjustment = doc.get("tlc_correction_type") == rules.POST_LOCK and (not before or before.get("tlc_correction_type") != rules.POST_LOCK)
    authorized_creation = False
    if creating_adjustment and doc.get("tlc_travel_effect_key"):
        from tlc_hr.interface.travel_adjustments import validate_generated_correction

        authorized_creation = validate_generated_correction(doc)
    with domain_errors():
        correction = Correction(employee=doc.employee, from_date=getdate(doc.from_date), to_date=getdate(doc.to_date),
                                kind=doc.get("tlc_correction_type") or None, shift=doc.get("shift") or None, explanation=doc.get("explanation"),
                                is_new=bool(doc.is_new() or creating_adjustment), roles=frozenset(frappe.get_roles()), today=getdate(nowdate()),
                                post_lock_creation_authorized=authorized_creation)
        doc.shift = service().correct(correction)
    apply_common(doc, approver_field="tlc_approver")


def allow_post_lock(doc, method=None):
    """Attendance Request before_submit: HRMS writes Attendance on submit; let an approved post-lock adjustment through."""
    if doc.get("tlc_correction_type") == rules.POST_LOCK:
        frappe.flags.tlc_post_lock = {"employee": doc.employee, "start": getdate(doc.from_date), "end": getdate(doc.to_date)}


def log_post_lock(doc, method=None):
    """Attendance Request on_submit: record the adjustment on the locked period (paid with the next payroll)."""
    if doc.get("tlc_correction_type") != rules.POST_LOCK:
        return
    frappe.flags.tlc_post_lock = False
    period = FrappeAttendanceRepository().locked_period(doc.employee, getdate(doc.from_date), getdate(doc.to_date))
    if period:
        frappe.get_doc("TLC Attendance Period", period[0]).add_comment(
            "Info", _("Điều chỉnh sau chốt {0}: {1}, {2} – {3}. Lý do: {4}. Tính vào kỳ lương kế tiếp.").format(
                doc.name, doc.employee_name, frappe.format(doc.from_date, "Date"), frappe.format(doc.to_date, "Date"), doc.explanation))


# ---------------------------------------------------------------- lock of a closed month

def days_of(doc):
    start_field, end_field = GUARDED[doc.doctype]
    start = doc.get(start_field)
    end = doc.get(end_field) or ("9999-12-31" if doc.doctype == "Shift Assignment" else start)
    return (getdate(start), getdate(end)) if start else (None, None)


def guard(doc, method=None):
    """validate / before_cancel / on_trash of the six doctypes: no change to a day of a locked month."""
    if frappe.flags.in_install or frappe.flags.in_migrate or not doc.get("employee"):
        return
    post_lock = doc.doctype == "Attendance Request" and doc.get("tlc_correction_type") == rules.POST_LOCK
    versions = [doc]
    before = doc.get_doc_before_save() if method == "validate" else None
    if before and before.get("employee"):
        versions.append(before)  # moving a document out of a locked day is a change of that day too
    for version in versions:
        start, end = days_of(version)
        if start:
            with domain_errors():
                context = frappe.flags.tlc_post_lock
                related_write = (isinstance(context, dict) and version.doctype == "Attendance"
                                 and version.employee == context["employee"] and context["start"] <= start <= end <= context["end"])
                service().check_unlocked(version.employee, start, end, post_lock_adjustment=post_lock or related_write)


# ---------------------------------------------------------------- TLC Attendance Period

@frappe.whitelist()
def period_open_items(name):
    """Current blocking items of a period, read-only (the stored field is the snapshot of the last transition)."""
    doc = frappe.get_doc("TLC Attendance Period", name)
    doc.check_permission("read")
    return {"name": name, "open_items": service().open_items(key_of(doc))}


def key_of(doc):
    return PeriodKey(company=doc.company, scope=doc.scope, month=doc.period_month)


def refresh_summary(doc):
    summary = service().summarize(key_of(doc))
    doc.update({"from_date": summary.from_date, "to_date": summary.to_date, "title": summary.title, "manager_user": summary.manager_user,
                "employee_count": len(summary.rows), "open_count": len(summary.open_items), "open_items": "\n".join(summary.open_items),
                **summary.totals})
    doc.set("rows", [r.model_dump() for r in summary.rows])


def period_validate(doc):
    repository = FrappeAttendanceRepository()
    if doc.scope not in (*repository.factories(), rules.HEAD_OFFICE):
        frappe.throw(_("Phạm vi phải là một nhà máy hoặc Hội sở."))
    before = doc.get_doc_before_save()
    before_state = None if doc.is_new() or not before else before.get("workflow_state")
    with domain_errors():
        service().check_unique(key_of(doc), None if doc.is_new() else doc.name)
        if doc.workflow_state in (rules.DRAFT, None, "") or doc.is_new():
            refresh_summary(doc)
            open_items = doc.open_items.split("\n") if doc.open_count else []
        else:
            start, end, month = rules.period_dates(doc.period_month)
            doc.update({"title": f"Kỳ công {month} · {doc.scope}", "manager_user": repository.head_user(doc.company, doc.scope),
                        "from_date": start, "to_date": end})
            open_items = service().open_items(key_of(doc)) if doc.workflow_state != before_state else []
            doc.open_count, doc.open_items = len(open_items), "\n".join(open_items)
        stage = rules.check_move(before_state, doc.workflow_state, open_items, doc.tlc_reject_reason)
    if stage:
        doc.tlc_rejected_stage = stage


def period_on_submit(doc):
    doc.db_set({"locked_at": now_datetime(), "locked_by": frappe.session.user})
    doc.add_comment("Info", _("{0} ký và khoá kỳ công. Dữ liệu công của {1} người không sửa trực tiếp được nữa.").format(
        get_fullname(frappe.session.user), doc.employee_count))


def period_before_cancel(doc):
    with domain_errors():
        rules.check_reopen(doc.tlc_reject_reason)


def period_on_cancel(doc):
    doc.add_comment("Info", _("{0} mở lại kỳ công. Lý do: {1}").format(get_fullname(frappe.session.user), doc.tlc_reject_reason))


@frappe.whitelist()
def refresh_period(name):
    """Button "Làm mới tổng hợp": rebuild the summary of a draft period from attendance, overtime and corrections."""
    doc = frappe.get_doc("TLC Attendance Period", name)
    doc.check_permission("write")
    if doc.workflow_state not in (rules.DRAFT, None, ""):
        frappe.throw(_("Chỉ làm mới kỳ công đang Nháp."))
    doc.save()
    return doc.as_dict()


def period_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    return bool(set(frappe.get_roles(user)) & COMPANY_WIDE_ROLES) or doc.manager_user == user


def period_query_conditions(user=None):
    user = user or frappe.session.user
    if set(frappe.get_roles(user)) & COMPANY_WIDE_ROLES:
        return ""
    return f"`tabTLC Attendance Period`.manager_user = {frappe.db.escape(user)}"
