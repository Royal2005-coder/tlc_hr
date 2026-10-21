"""Guard native status shortcuts and author sensitive review sections at the correct step."""
import frappe
from frappe.utils import getdate, today
from tlc_hr.domain.lifecycle import completion_gate, require
from tlc_hr.domain.shared import DomainError
from tlc_hr.infrastructure.frappe.lifecycle import FrappeLifecycleRepository


def validate(doc, event=None):
    try:
        old = doc.get_doc_before_save()
        if doc.doctype == "Employee" and old and old.status != "Left" and doc.status == "Left":
            name = frappe.db.get_value("Employee Separation", {"employee": doc.name, "docstatus": 1,
                                       "boarding_status": "Completed"}, "name")
            require(name, "EXIT-CLEARANCE", "Phải hoàn tất hồ sơ nghỉ việc có kiểm tra trước khi chuyển Đã nghỉ.")
            separation = frappe.get_doc("Employee Separation", name)
            require(getdate(separation.custom_tlc_effective_on) <= getdate(today()), "EXIT-FUTURE", "Chưa đến ngày nghỉ chính thức.")
            completion_gate(FrappeLifecycleRepository().completion_blockers("Employee Separation", name, doc.name))
        if doc.doctype == "TLC Probation Review":
            state = old.get("workflow_state") if old else "Nháp"
            roles = set(frappe.get_roles())
            employee_user = frappe.db.get_value("Employee", doc.employee, "user_id")
            manager = frappe.db.get_value("Employee", doc.employee, "reports_to")
            manager_user = frappe.db.get_value("Employee", manager, "user_id") if manager else None
            for field, allowed in (("self_review", employee_user == frappe.session.user and state in ("Nháp", "Từ chối")),
                                   ("manager_review", manager_user == frappe.session.user and state == "Chờ quản lý duyệt"),
                                   ("hr_review", bool(roles & {"TLC HR Lead", "TLC HR Officer"}) and state == "Chờ nhân sự duyệt"),
                                   ("decision", "TLC Director" in roles and state == "Chờ giám đốc duyệt")):
                changed = doc.get(field) != (old.get(field) if old else None)
                require(not changed or not doc.get(field) or allowed or "System Manager" in roles,
                        "OB-AUTHOR", "Nội dung đánh giá chỉ được ghi bởi đúng người tại đúng bước.")
        if doc.doctype == "TLC Employee Dependent" and doc.status == "Verified":
            matches = frappe.get_all("TLC Employee Dependent", filters={"identity_number": doc.identity_number,
                                     "docstatus": 1, "status": "Verified", "name": ["!=", doc.name]},
                                     fields=["valid_from", "valid_to"])
            for row in matches:
                left = max(getdate(row.valid_from), getdate(doc.valid_from))
                right = min(getdate(row.valid_to) if row.valid_to else getdate("9999-12-31"),
                            getdate(doc.valid_to) if doc.valid_to else getdate("9999-12-31"))
                require(left > right, "CORE-DEPENDENT-OVERLAP", "Định danh người phụ thuộc đã có thời gian giảm trừ được xác nhận trùng.")
    except DomainError as exc:
        frappe.throw(f"[{exc.code}] {exc.message}")


def prevent_cancel_applied(doc, event=None):
    if doc.doctype == "TLC Employee Change Request" and doc.applied_on:
        frappe.throw("Thay đổi đã có hiệu lực: lập yêu cầu mới để lưu lịch sử, không hủy bản đã áp dụng.")
    if doc.doctype in ("Employee Promotion", "Employee Transfer"):
        frappe.throw("Quyết định đã có hiệu lực: lập quyết định ngược có phê duyệt, không ghi đè lịch sử.")
