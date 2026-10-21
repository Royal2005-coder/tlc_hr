"""Native Desk document hooks. Register the explicit integrations in ORGANIZATION.md."""
import frappe
from frappe.utils import getdate, nowdate

from tlc_hr.application.organization import OrganizationService
from tlc_hr.contracts.organization import AssignEmployee, AssessHeadcount, ResolveApprovers
from tlc_hr.domain.organization import mismatch, validate_change_shape
from tlc_hr.domain.shared import DomainError, NotAllowed
from tlc_hr.infrastructure.frappe.organization import FrappeOrganizationRepository, period


def _run(action):
    try:
        return action()
    except NotAllowed as exc:
        frappe.throw(exc.message, frappe.PermissionError)
    except DomainError as exc:
        frappe.throw(f"[{exc.code}] {exc.message}")


def _company(doctype, name, expected):
    if frappe.db.get_value(doctype, name, "company") != expected:
        raise DomainError("org.company", "Nhân viên, đơn vị và vị trí phải cùng công ty.")


def validate(doc, method=None):
    return _run(lambda: _validate(doc))


def _validate(doc):
    repo = FrappeOrganizationRepository()
    service = OrganizationService(repo)
    if doc.doctype == "Department":
        if not doc.tlc_organization_code:
            doc.tlc_organization_code = "ORG-" + frappe.generate_hash(length=12).upper()
        if doc.parent_department and frappe.db.get_value("Department", doc.parent_department, "company"):
            _company("Department", doc.parent_department, doc.company)
    elif doc.doctype == "TLC Organization Position":
        _company("Department", doc.department, doc.company)
        if not (doc.job_description or "").strip():
            raise DomainError("org.jd", "Vị trí phải có mô tả công việc.")
    elif doc.doctype == "TLC Organization Assignment":
        _company("Employee", doc.employee, doc.company)
        _company("Department", doc.department, doc.company)
        position = frappe.get_doc("TLC Organization Position", doc.position)
        if position.company != doc.company or position.department != doc.department:
            raise DomainError("org.position_department", "Vị trí không thuộc đơn vị được phân công.")
        service.assess_assignment(AssignEmployee(name=doc.name, employee=doc.employee, department=doc.department,
            position=doc.position, start=getdate(doc.start_date), end=getdate(doc.end_date) if doc.end_date else None,
            primary=bool(doc.is_primary)))
        employee_department = frappe.db.get_value("Employee", doc.employee, "department")
        doc.organization_warning = ("Phân công chính khác phòng ban trên Employee; HR cần đối chiếu ngày hiệu lực."
                                    if doc.is_primary and period(doc).contains(getdate(nowdate()))
                                    and employee_department != doc.department else "")
        if doc.organization_warning:
            frappe.msgprint(doc.organization_warning, indicator="orange")
    elif doc.doctype == "TLC Organization Reporting Line":
        period(doc).validate()
        _company("Department", doc.department, doc.company)
        _company("Employee", doc.leader, doc.company)
        if not frappe.db.get_value("Employee", doc.leader, "user_id"):
            raise DomainError("org.leader_user", "Người duyệt phải có tài khoản đăng nhập.")
        if doc.employee:
            _company("Employee", doc.employee, doc.company)
        repo.validate_reporting(doc)
    elif doc.doctype == "TLC Organization Headcount":
        _company("TLC Organization Position", doc.position, doc.company)
        position_department = frappe.db.get_value("TLC Organization Position", doc.position, "department")
        doc.department = position_department
        result = service.headcount(AssessHeadcount(position=doc.position, day=getdate(doc.as_on), capacity=int(doc.capacity)))
        doc.used, doc.vacant, doc.excess = result.used, result.vacant, result.excess
    elif doc.doctype == "TLC Organization Change":
        validate_change_shape(doc.change_type, doc.changes)
        repo.validate_change(doc)
        previous = doc.get_doc_before_save()
        if not previous and doc.applied_on:
            raise DomainError("org.applied_readonly", "Ngày áp dụng do hệ thống ghi nhận.")
        for row in doc.changes:
            row.previous_parent, row.previous_title = frappe.db.get_value("Department", row.target_department,
                                                                 ["parent_department", "department_name"])
    elif doc.doctype == "Shift Location":
        if doc.tlc_organization_shift_type and not doc.tlc_organization_holiday_list:
            raise DomainError("org.location_calendar", "Địa điểm gắn ca phải có lịch nghỉ; phân ca thực tế bằng Shift Assignment.")


def on_submit(doc, method=None):
    return _run(lambda: FrappeOrganizationRepository().apply_change(doc, getdate(nowdate())))


def before_cancel(doc, method=None):
    if doc.applied_on:
        frappe.throw("Quyết định đã áp dụng không được hủy; lập quyết định hiệu lực mới để điều chỉnh.")


def warn_recorded_department(doc, method=None):
    if not doc.employee or not doc.department:
        return
    day = getdate(doc.get("attendance_date") or doc.get("from_date") or nowdate())
    employee_department = frappe.db.get_value("Employee", doc.employee, "department")
    assignments = FrappeOrganizationRepository().assignments(doc.employee)
    allowed = {a.department for a in assignments if a.period.contains(day)}
    if mismatch(employee_department, allowed, doc.department):
        frappe.msgprint("Cảnh báo cơ cấu: phòng ban ghi nhận khác Employee và các phân công có hiệu lực.", indicator="orange")


def apply_due_changes():
    """Daily scheduler; each decision is atomic and failures remain visible in Error Log."""
    for name in frappe.get_all("TLC Organization Change", filters={"docstatus": 1, "applied_on": ["is", "not set"],
                                                                 "effective_date": ["<=", nowdate()]}, pluck="name"):
        frappe.db.savepoint("organization_change")
        try:
            _run(lambda: FrappeOrganizationRepository().apply_change(
                frappe.get_doc("TLC Organization Change", name), getdate(nowdate())))
        except Exception:
            frappe.db.rollback(save_point="organization_change")
            frappe.log_error(title=f"Organization change {name}", message=frappe.get_traceback())


def approval_users(employee, department, day):
    """Internal provider: equal-authority users; no first-leader or reports_to fallback."""
    return OrganizationService(FrappeOrganizationRepository()).approvers(
        ResolveApprovers(employee=employee, department=department, day=getdate(day)))


@frappe.whitelist()
def assess_headcount(name):
    doc = frappe.get_doc("TLC Organization Headcount", name)
    doc.check_permission("write")
    validate(doc)
    return {field: doc.get(field) for field in ("used", "vacant", "excess")}
