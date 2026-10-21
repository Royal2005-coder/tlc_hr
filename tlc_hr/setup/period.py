"""Monthly attendance closing (workflow TLC Chốt công) and the leave carried into the next year (idempotent, after every migration).

Factory: HR sends, the factory head confirms, HR reconciles, the CEO signs and locks. Head office: HR, then the CEO.
Every level may return the period to HR with a reason; only the CEO reopens a locked period (cancel, with a reason).
"""

import frappe

from tlc_hr.attendance.period import HEAD_OFFICE
from tlc_hr.setup.install import DRAFT, ensure_workflow

WORKFLOW = "TLC Chốt công"
TO_HEAD, TO_HR, TO_CEO, LOCKED, REOPENED = "Chờ quản lý xác nhận", "Chờ nhân sự đối soát", "Chờ giám đốc ký", "Đã khoá", "Đã mở lại"
HR_ROLES = ("TLC HR Lead", "TLC HR Officer")
# Leave of the year may be used until 30 March of the next year (TLC policy, BRD HR-CP-12): the carried part of an allocation
# starting 1 January expires after 89 days (31 + 28 + 30). In a leap year it ends one day earlier, on 29 March.
ANNUAL_LEAVE, CARRY_FORWARD_DAYS = "Phép năm", 89


def ensure_period_workflow():
    for state, style in ((TO_HEAD, "Warning"), (TO_HR, "Warning"), (TO_CEO, "Warning"), (LOCKED, "Success"), (REOPENED, "Inverse")):
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert(ignore_permissions=True)
    for action in ("Gửi xác nhận", "Gửi đối soát", "Xác nhận", "Trả lại", "Đối soát xong", "Ký và khoá", "Mở lại kỳ"):
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(ignore_permissions=True)
    states = [
        {"state": DRAFT, "doc_status": "0", "allow_edit": "TLC HR Officer"},
        {"state": TO_HEAD, "doc_status": "0", "allow_edit": "TLC Line Manager"},
        {"state": TO_HR, "doc_status": "0", "allow_edit": "TLC HR Officer"},
        {"state": TO_CEO, "doc_status": "0", "allow_edit": "TLC Director"},
        {"state": LOCKED, "doc_status": "1", "allow_edit": "TLC Director"},
        {"state": REOPENED, "doc_status": "2", "allow_edit": "TLC Director"},
    ]
    factory, head_office = f'doc.scope != "{HEAD_OFFICE}"', f'doc.scope == "{HEAD_OFFICE}"'
    is_head = "doc.manager_user == frappe.session.user"
    rows = []
    for role in HR_ROLES:
        rows += [{"state": DRAFT, "action": "Gửi xác nhận", "next_state": TO_HEAD, "allowed": role, "condition": factory},
                 {"state": DRAFT, "action": "Gửi đối soát", "next_state": TO_HR, "allowed": role, "condition": head_office},
                 {"state": TO_HR, "action": "Đối soát xong", "next_state": TO_CEO, "allowed": role},
                 {"state": TO_HR, "action": "Trả lại", "next_state": DRAFT, "allowed": role}]
    rows += [{"state": TO_HEAD, "action": action, "next_state": target, "allowed": "TLC Line Manager", "condition": is_head}
             for action, target in (("Xác nhận", TO_HR), ("Trả lại", DRAFT))]
    rows += [{"state": TO_CEO, "action": action, "next_state": target, "allowed": "TLC Director"}
             for action, target in (("Ký và khoá", LOCKED), ("Trả lại", DRAFT))]
    rows += [{"state": LOCKED, "action": "Mở lại kỳ", "next_state": REOPENED, "allowed": "TLC Director"}]
    for row in rows:
        row["allow_self_approval"] = 1  # people decide on a period of many people, not on a request of their own
    ensure_workflow(WORKFLOW, "TLC Attendance Period", states, rows)


def ensure_carry_forward():
    if frappe.db.exists("Leave Type", ANNUAL_LEAVE):
        frappe.db.set_value("Leave Type", ANNUAL_LEAVE, {"is_carry_forward": 1, "expire_carry_forwarded_leaves_after_days": CARRY_FORWARD_DAYS})


def ensure_all():
    ensure_period_workflow()
    ensure_carry_forward()
