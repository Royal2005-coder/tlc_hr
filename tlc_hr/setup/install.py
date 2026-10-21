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
    "Attendance Request": [
        {"fieldname": "tlc_correction_type", "label": "Loại điều chỉnh", "fieldtype": "Select", "insert_after": "reason",
         "options": "\nQuên chấm vào\nQuên chấm ra\nMáy chấm công lỗi\nĐi công tác / làm việc ngoài\nĐiều chỉnh sau chốt",
         "description": "Điều chỉnh sau chốt: chỉ HR tạo, cho ngày thuộc kỳ công đã khoá; tính vào kỳ lương kế tiếp."},
        {"fieldname": "tlc_approver", "label": "Quản lý duyệt", "fieldtype": "Link", "options": "User", "read_only": 1,
         "insert_after": "explanation"},
        {"fieldname": "tlc_reject_reason", "label": "Lý do từ chối", "fieldtype": "Small Text", "insert_after": "tlc_approver",
         "depends_on": "eval:doc.workflow_state", "permlevel": 1},
        {"fieldname": "tlc_rejected_stage", "label": "Bị từ chối ở bước", "fieldtype": "Data", "insert_after": "tlc_reject_reason",
         "read_only": 1, "hidden": 1},
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


# Doctypes whose reason to reject sits at permlevel 1.
REASON_DOCTYPES = ["Leave Application", "Attendance Request"]  # TLC Overtime Request keeps it at level 0: the worker refuses too


def ensure_reason_permissions():
    from frappe.permissions import add_permission, update_permission_property

    for doctype in REASON_DOCTYPES:
        if not frappe.db.exists("DocType", doctype):
            continue
        for role, (read, write) in REASON_PERMS.items():
            if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 1}):
                add_permission(doctype, role, 1)
            update_permission_property(doctype, role, 1, "read", read)
            update_permission_property(doctype, role, 1, "write", write)


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
    ensure_attendance_workflow()
    apply_settings()
    from tlc_hr.setup.accounts import ensure_accounts

    for company in frappe.get_all("Company", pluck="name"):
        ensure_accounts(company)
    from tlc_hr.setup.attendance import ensure_all as ensure_attendance

    ensure_attendance()
    from tlc_hr.setup.overtime import ensure_all as ensure_overtime

    ensure_overtime()
    from tlc_hr.setup.period import ensure_all as ensure_period

    ensure_period()
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


def ensure_workflow(name, doctype, states, transitions, states_style=None):
    """Create or rebuild a workflow from its states and transitions (the definition here is the only source)."""
    if frappe.db.exists("Workflow", name):
        workflow = frappe.get_doc("Workflow", name)
        workflow.states, workflow.transitions = [], []
    else:
        workflow = frappe.get_doc({"doctype": "Workflow", "workflow_name": name, "document_type": doctype})
    workflow.update({"is_active": 1, "workflow_state_field": "workflow_state", "send_email_alert": 0, "override_status": 0})
    for row in states:
        workflow.append("states", row)
    for row in transitions:
        workflow.append("transitions", row)
    workflow.save(ignore_permissions=True)


def ensure_leave_workflow():
    """Leave: the employee submits, the reporting manager approves, then HR (lead or officer); a rejection needs a reason."""
    states = [
        {"state": DRAFT, "doc_status": "0", "allow_edit": "Employee", "update_field": "status", "update_value": "Open"},
        {"state": TO_MANAGER, "doc_status": "0", "allow_edit": "Leave Approver", "update_field": "status", "update_value": "Open"},
        {"state": TO_HR, "doc_status": "0", "allow_edit": "TLC HR Officer", "update_field": "status", "update_value": "Open"},
        {"state": APPROVED, "doc_status": "1", "allow_edit": "TLC HR Lead", "update_field": "status", "update_value": "Approved"},
        {"state": REJECTED, "doc_status": "1", "allow_edit": "TLC HR Lead", "update_field": "status", "update_value": "Rejected"},
        {"state": CANCELLED, "doc_status": "2", "allow_edit": "TLC HR Lead", "update_field": "status", "update_value": "Cancelled"},
    ]
    ensure_workflow(LEAVE_WORKFLOW, "Leave Application", states, two_level_transitions(IS_MY_REPORT))


def two_level_transitions(manager_condition):
    """Send, line manager (named on the request), then HR lead or officer; both levels may refuse; HR lead cancels."""
    rows = [{"state": DRAFT, "action": "Gửi duyệt", "next_state": TO_MANAGER, "allowed": "Employee", "allow_self_approval": 1}]
    for action, target in (("Duyệt", TO_HR), ("Từ chối", REJECTED)):
        rows.append({"state": TO_MANAGER, "action": action, "next_state": target, "allowed": "Leave Approver",
                     "allow_self_approval": 0, "condition": manager_condition})
    for role in ("TLC HR Lead", "TLC HR Officer"):
        for action, target in (("Duyệt", APPROVED), ("Từ chối", REJECTED)):
            rows.append({"state": TO_HR, "action": action, "next_state": target, "allowed": role, "allow_self_approval": 0})
    rows.append({"state": APPROVED, "action": "Hủy", "next_state": CANCELLED, "allowed": "TLC HR Lead", "allow_self_approval": 0})
    return rows


def ensure_attendance_workflow():
    """Attendance corrections: line manager then HR. A refused request stays a draft (submitting would create attendance)."""
    states = [
        {"state": DRAFT, "doc_status": "0", "allow_edit": "Employee"},
        {"state": TO_MANAGER, "doc_status": "0", "allow_edit": "Leave Approver"},
        {"state": TO_HR, "doc_status": "0", "allow_edit": "TLC HR Officer"},
        {"state": APPROVED, "doc_status": "1", "allow_edit": "TLC HR Lead"},
        {"state": REJECTED, "doc_status": "0", "allow_edit": "TLC HR Lead"},
        {"state": CANCELLED, "doc_status": "2", "allow_edit": "TLC HR Lead"},
    ]
    ensure_workflow("TLC Điều chỉnh công", "Attendance Request", states,
                    two_level_transitions("doc.tlc_approver == frappe.session.user"))