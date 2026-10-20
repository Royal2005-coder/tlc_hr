"""Everything tlc_hr adds to a site on install and after every migration: roles, custom fields, approval workflows, 2026 payroll values."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tlc_hr.setup.roles import ensure_roles
from tlc_hr.vn.statutory import apply_settings

LEAVE_WORKFLOW = "TLC Nghỉ phép"
DRAFT, TO_MANAGER, TO_HR, APPROVED, REJECTED, CANCELLED = (
    "Nháp", "Chờ quản lý duyệt", "Chờ nhân sự duyệt", "Đã duyệt", "Từ chối", "Đã hủy")

# Only the leave approver named on the request may decide at the manager level, and nobody decides on their own request.
IS_MY_REPORT = "doc.leave_approver == frappe.session.user"

CUSTOM_FIELDS = {
    "Employee": [
        {"fieldname": "tlc_section", "label": "TLC", "fieldtype": "Section Break", "insert_after": "reports_to", "collapsible": 1},
        {"fieldname": "tlc_key", "label": "Mã TLC", "fieldtype": "Data", "insert_after": "tlc_section", "unique": 1, "read_only": 1},
        {"fieldname": "tlc_workforce", "label": "Khối", "fieldtype": "Select", "options": "head_office\nfactory",
         "default": "head_office", "insert_after": "tlc_key"},
        {"fieldname": "tlc_monthly_wage", "label": "Lương tháng (VND)", "fieldtype": "Currency", "options": "salary_currency",
         "insert_after": "tlc_workforce", "permlevel": 1},
        {"fieldname": "tlc_dependents", "label": "Số người phụ thuộc", "fieldtype": "Int", "insert_after": "tlc_monthly_wage"},
    ],
    "Department": [
        {"fieldname": "tlc_head", "label": "Trưởng bộ phận", "fieldtype": "Link", "options": "Employee", "insert_after": "department_name"},
        {"fieldname": "tlc_wage_region", "label": "Vùng lương tối thiểu", "fieldtype": "Select", "options": "I\nII\nIII\nIV",
         "default": "I", "insert_after": "tlc_head", "description": "Vùng theo Nghị định 293/2025/NĐ-CP của nơi làm việc; quyết định trần đóng BHTN."},
    ],
    "Leave Application": [
        {"fieldname": "tlc_reject_reason", "label": "Lý do từ chối", "fieldtype": "Small Text", "insert_after": "status",
         "depends_on": "eval:doc.workflow_state", "description": "Bắt buộc khi từ chối đơn.", "permlevel": 1},
        {"fieldname": "tlc_rejected_stage", "label": "Bị từ chối ở bước", "fieldtype": "Data", "insert_after": "tlc_reject_reason",
         "read_only": 1, "hidden": 1},
    ],
}


# Who reads and who writes the reason to reject (permlevel 1 of Leave Application): the employee reads it on their request.
REASON_PERMS = {"Employee": (1, 0), "Leave Approver": (1, 1), "TLC HR Lead": (1, 1), "TLC HR Officer": (1, 1), "TLC Director": (1, 1),
                "HR Manager": (1, 1), "HR User": (1, 1)}


def ensure_reason_permissions():
    from frappe.permissions import add_permission, update_permission_property

    for role, (read, write) in REASON_PERMS.items():
        if not frappe.db.exists("Custom DocPerm", {"parent": "Leave Application", "role": role, "permlevel": 1}):
            add_permission("Leave Application", role, 1)
        update_permission_property("Leave Application", role, 1, "read", read)
        update_permission_property("Leave Application", role, 1, "write", write)


# HRMS e-mails the approver when a request arrives and the employee when it is decided; without templates it stops the user
# with a message on every save. The templates render with the fields of the Leave Application.
EMAIL_TEMPLATES = {
    "leave_approval_notification_template": (
        "TLC Đơn nghỉ cần duyệt",
        "Đơn nghỉ phép {{ name }} của {{ employee_name }} cần bạn duyệt",
        "<p>{{ employee_name }} xin {{ leave_type }} từ {{ frappe.format(from_date, 'Date') }} đến {{ frappe.format(to_date, 'Date') }}"
        " ({{ total_leave_days }} ngày).</p><p>Lý do: {{ description or '' }}</p>"
        "<p>Trạng thái: <b>{{ workflow_state }}</b>. Mở đơn trên TLC HRM để duyệt hoặc từ chối.</p>",
    ),
    "leave_status_notification_template": (
        "TLC Kết quả đơn nghỉ",
        "Đơn nghỉ phép {{ name }}: {{ workflow_state }}",
        "<p>Đơn {{ leave_type }} từ {{ frappe.format(from_date, 'Date') }} đến {{ frappe.format(to_date, 'Date') }}"
        " ({{ total_leave_days }} ngày) của bạn: <b>{{ workflow_state }}</b>.</p>"
        "{% if tlc_reject_reason %}<p>Lý do từ chối: {{ tlc_reject_reason }}</p>{% endif %}",
    ),
}


def ensure_email_templates():
    for field, (name, subject, body) in EMAIL_TEMPLATES.items():
        doc = frappe.get_doc("Email Template", name) if frappe.db.exists("Email Template", name) else frappe.new_doc("Email Template")
        doc.update({"name": name, "subject": subject, "use_html": 1, "response_html": body, "response": body})
        if doc.is_new():
            doc.insert(ignore_permissions=True)
        else:
            doc.save(ignore_permissions=True)
        if frappe.db.get_single_value("HR Settings", field) != name:
            frappe.db.set_single_value("HR Settings", field, name)


def after_migrate():
    ensure_roles()
    ensure_email_templates()
    create_custom_fields(CUSTOM_FIELDS, update=True)
    ensure_reason_permissions()
    ensure_workflow_states()
    ensure_leave_workflow()
    apply_settings()
    from tlc_hr.setup.accounts import ensure_accounts

    for company in frappe.get_all("Company", pluck="name"):
        ensure_accounts(company)
    from tlc_hr.setup.attendance import ensure_all as ensure_attendance

    ensure_attendance()
    from tlc_hr.setup.workspaces import ensure_all

    ensure_all()
    frappe.db.commit()


def ensure_workflow_states():
    styles = {DRAFT: "", TO_MANAGER: "Warning", TO_HR: "Warning", APPROVED: "Success", REJECTED: "Danger", CANCELLED: "Inverse"}
    for state, style in styles.items():
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert(ignore_permissions=True)
    for action in ("Gửi duyệt", "Duyệt", "Từ chối", "Hủy"):
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(ignore_permissions=True)


def ensure_leave_workflow():
    """Leave: the employee submits, the reporting manager approves, then the HR lead; a rejection needs a reason (see events.py)."""
    states = [
        {"state": DRAFT, "doc_status": "0", "allow_edit": "Employee", "update_field": "status", "update_value": "Open"},
        {"state": TO_MANAGER, "doc_status": "0", "allow_edit": "Leave Approver", "update_field": "status", "update_value": "Open"},
        {"state": TO_HR, "doc_status": "0", "allow_edit": "TLC HR Officer", "update_field": "status", "update_value": "Open"},
        {"state": APPROVED, "doc_status": "1", "allow_edit": "TLC HR Lead", "update_field": "status", "update_value": "Approved"},
        {"state": REJECTED, "doc_status": "1", "allow_edit": "TLC HR Lead", "update_field": "status", "update_value": "Rejected"},
        {"state": CANCELLED, "doc_status": "2", "allow_edit": "TLC HR Lead", "update_field": "status", "update_value": "Cancelled"},
    ]
    transitions = [
        {"state": DRAFT, "action": "Gửi duyệt", "next_state": TO_MANAGER, "allowed": "Employee", "allow_self_approval": 1},
        {"state": TO_MANAGER, "action": "Duyệt", "next_state": TO_HR, "allowed": "Leave Approver", "allow_self_approval": 0,
         "condition": IS_MY_REPORT},
        {"state": TO_MANAGER, "action": "Từ chối", "next_state": REJECTED, "allowed": "Leave Approver", "allow_self_approval": 0,
         "condition": IS_MY_REPORT},
        # The HR level is the HR department: the HR lead or an HR officer (an HR officer decides on the HR lead's own leave).
        {"state": TO_HR, "action": "Duyệt", "next_state": APPROVED, "allowed": "TLC HR Lead", "allow_self_approval": 0},
        {"state": TO_HR, "action": "Từ chối", "next_state": REJECTED, "allowed": "TLC HR Lead", "allow_self_approval": 0},
        {"state": TO_HR, "action": "Duyệt", "next_state": APPROVED, "allowed": "TLC HR Officer", "allow_self_approval": 0},
        {"state": TO_HR, "action": "Từ chối", "next_state": REJECTED, "allowed": "TLC HR Officer", "allow_self_approval": 0},
        {"state": APPROVED, "action": "Hủy", "next_state": CANCELLED, "allowed": "TLC HR Lead", "allow_self_approval": 0},
    ]
    if frappe.db.exists("Workflow", LEAVE_WORKFLOW):
        workflow = frappe.get_doc("Workflow", LEAVE_WORKFLOW)
        workflow.states, workflow.transitions = [], []
    else:
        workflow = frappe.get_doc({"doctype": "Workflow", "workflow_name": LEAVE_WORKFLOW, "document_type": "Leave Application"})
    workflow.update({"is_active": 1, "workflow_state_field": "workflow_state", "send_email_alert": 0, "override_status": 0})
    for row in states:
        workflow.append("states", row)
    for row in transitions:
        workflow.append("transitions", row)
    workflow.save(ignore_permissions=True)
