"""Overtime on the standard HRMS chain (Shift Type -> Attendance -> Overtime Slip -> Additional Salary) plus the TLC approval
before the work: the line manager proposes, the worker consents, the director approves (idempotent, after every migration).

One Overtime Type carries the rates of the Labour Code art. 98: 150% on a working day, 200% on a weekly rest day, 300% on a
public holiday, computed from the basic salary component.
"""

import frappe

from tlc_hr.setup.install import APPROVED, CANCELLED, DRAFT, REJECTED, ensure_workflow

OVERTIME_TYPE = "TLC Tăng ca"
BASIC, OVERTIME = ("Lương cơ bản", "LCB"), ("Tiền tăng ca", "OT")
WORKFLOW = "TLC Tăng ca"
TO_WORKER, TO_DIRECTOR = "Chờ người lao động đồng ý", "Chờ giám đốc duyệt"
PROPOSERS = ("TLC Line Manager", "TLC HR Lead", "TLC HR Officer")


def ensure_component(name, abbr):
    if not frappe.db.exists("Salary Component", name):
        frappe.get_doc({"doctype": "Salary Component", "salary_component": name, "salary_component_abbr": abbr,
                        "type": "Earning", "depends_on_payment_days": 0}).insert(ignore_permissions=True)


def ensure_overtime_type():
    ensure_component(*BASIC)
    ensure_component(*OVERTIME)
    doc = frappe.get_doc("Overtime Type", OVERTIME_TYPE) if frappe.db.exists("Overtime Type", OVERTIME_TYPE) else frappe.new_doc("Overtime Type")
    doc.update({
        "name": OVERTIME_TYPE, "overtime_calculation_method": "Salary Component Based", "overtime_salary_component": OVERTIME[0],
        "standard_multiplier": 1.5, "applicable_for_weekend": 1, "weekend_multiplier": 2.0,
        "applicable_for_public_holiday": 1, "public_holiday_multiplier": 3.0, "maximum_overtime_hours_allowed": 12,
    })
    doc.set("applicable_salary_component", [{"salary_component": BASIC[0]}])
    doc.flags.ignore_permissions = True
    doc.save() if not doc.is_new() else doc.insert()


def ensure_shift_overtime():
    """Hours worked beyond the shift become overtime on the Attendance; only approved requests are paid (attendance/overtime.py)."""
    from tlc_hr.setup.attendance import SHIFTS

    for name in SHIFTS:
        if frappe.db.exists("Shift Type", name):
            frappe.db.set_value("Shift Type", name, {"allow_overtime": 1, "overtime_type": OVERTIME_TYPE})


def ensure_overtime_workflow():
    for state, style in ((TO_WORKER, "Warning"), (TO_DIRECTOR, "Warning")):
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert(ignore_permissions=True)
    for action in ("Đề nghị", "Đồng ý"):
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(ignore_permissions=True)
    states = [
        {"state": DRAFT, "doc_status": "0", "allow_edit": "TLC Line Manager"},
        {"state": TO_WORKER, "doc_status": "0", "allow_edit": "Employee"},
        {"state": TO_DIRECTOR, "doc_status": "0", "allow_edit": "TLC Director"},
        {"state": APPROVED, "doc_status": "1", "allow_edit": "TLC Director"},
        {"state": REJECTED, "doc_status": "0", "allow_edit": "TLC HR Lead"},
        {"state": CANCELLED, "doc_status": "2", "allow_edit": "TLC Director"},
    ]
    is_worker = "doc.employee_user == frappe.session.user"
    rows = [{"state": DRAFT, "action": "Đề nghị", "next_state": TO_WORKER, "allowed": role, "allow_self_approval": 1}
            for role in PROPOSERS]
    rows += [{"state": TO_WORKER, "action": action, "next_state": target, "allowed": "Employee", "allow_self_approval": 1,
              "condition": is_worker} for action, target in (("Đồng ý", TO_DIRECTOR), ("Từ chối", REJECTED))]
    rows += [{"state": TO_DIRECTOR, "action": action, "next_state": target, "allowed": "TLC Director", "allow_self_approval": 1}
             for action, target in (("Duyệt", APPROVED), ("Từ chối", REJECTED))]
    rows += [{"state": APPROVED, "action": "Hủy", "next_state": CANCELLED, "allowed": "TLC Director", "allow_self_approval": 1}]
    ensure_workflow(WORKFLOW, "TLC Overtime Request", states, rows)


def ensure_all():
    ensure_overtime_type()
    ensure_shift_overtime()
    ensure_overtime_workflow()
