"""Monthly attendance period of TLC: who is in a scope (a factory or the head office), the per-person summary that the factory
head, HR and the CEO sign, and what is still open in the month (an open item blocks the period from moving on).

Scopes follow the work sites of setup/attendance.py: each factory is its own scope, every other department is the head office.
"""

from collections import defaultdict

import frappe
from frappe.utils import add_days, flt, getdate

from tlc_hr.setup.attendance import SITE_OF_DEPARTMENT

HEAD_OFFICE = "Hội sở"
SCOPES = [*SITE_OF_DEPARTMENT, HEAD_OFFICE]
PENDING_LEAVE = ("Chờ quản lý duyệt", "Chờ nhân sự duyệt")
PENDING_OVERTIME = ("Chờ người lao động đồng ý", "Chờ giám đốc duyệt")
# Attendance status -> summary column
STATUS_FIELD = {"Present": "present_days", "Work From Home": "present_days", "Half Day": "half_days", "Absent": "absent_days",
                "On Leave": "leave_days"}


def scope_of_department(department):
    base = (department or "").rsplit(" - ", 1)[0]
    return base if base in SITE_OF_DEPARTMENT else HEAD_OFFICE


def scope_of_employee(employee):
    return scope_of_department(frappe.db.get_value("Employee", employee, "department"))


def employees_in(scope, company, start):
    """People of the scope working in the period: active, or left during or after it."""
    rows = frappe.get_all("Employee", filters={"company": company, "status": ["in", ["Active", "Left"]]},
                          fields=["name", "employee_name", "department", "status", "relieving_date"], order_by="employee_name")
    return [r for r in rows if scope_of_department(r.department) == scope
            and (r.status == "Active" or (r.relieving_date and getdate(r.relieving_date) >= getdate(start)))]


def head_user(scope, company):
    """Factory head who confirms the period (Department.tlc_head); the head office has none."""
    if scope == HEAD_OFFICE:
        return None
    abbr = frappe.db.get_value("Company", company, "abbr")
    head = frappe.db.get_value("Department", f"{scope} - {abbr}", "tlc_head")
    return frappe.db.get_value("Employee", head, "user_id") if head else None


def summarize(scope, company, start, end):
    """One row per person: days present, half, absent, on leave, late arrivals, early exits, approved overtime and corrections."""
    people = employees_in(scope, company, start)
    names = [p.name for p in people] or [""]
    rows = {p.name: {"employee": p.name, "employee_name": p.employee_name, "department": p.department, "present_days": 0,
                     "half_days": 0, "absent_days": 0, "leave_days": 0, "late_count": 0, "early_exit_count": 0, "ot_hours": 0,
                     "corrections": 0} for p in people}
    for a in frappe.get_all("Attendance", filters={"employee": ["in", names], "docstatus": 1, "attendance_date": ["between", [start, end]]},
                            fields=["employee", "status", "late_entry", "early_exit"]):
        row = rows[a.employee]
        row[STATUS_FIELD.get(a.status, "present_days")] += 1
        row["late_count"] += a.late_entry or 0
        row["early_exit_count"] += a.early_exit or 0
    for o in frappe.get_all("TLC Overtime Request", filters={"employee": ["in", names], "docstatus": 1, "ot_date": ["between", [start, end]]},
                            fields=["employee", "hours"]):
        rows[o.employee]["ot_hours"] += flt(o.hours)
    for c in frappe.get_all("Attendance Request", filters={"employee": ["in", names], "docstatus": 1, "from_date": ["<=", end],
                                                           "to_date": [">=", start]}, fields=["employee"]):
        rows[c.employee]["corrections"] += 1
    return list(rows.values())


def open_items(scope, company, start, end):
    """What must be decided before the month is closed: pending requests and check-ins not yet turned into attendance."""
    people = {p.name: p.employee_name for p in employees_in(scope, company, start)}
    names = list(people) or [""]
    items = []
    overlap = {"employee": ["in", names], "docstatus": 0, "from_date": ["<=", end], "to_date": [">=", start]}
    for doctype, label, states in (("Leave Application", "Đơn nghỉ chưa duyệt xong", PENDING_LEAVE),
                                   ("Attendance Request", "Giải trình công chưa duyệt xong", PENDING_LEAVE)):
        for d in frappe.get_all(doctype, filters={**overlap, "workflow_state": ["in", states]}, fields=["name", "employee", "workflow_state"]):
            items.append((doctype, d.name, people.get(d.employee), f"{label} ({d.workflow_state})"))
    for d in frappe.get_all("TLC Overtime Request", filters={"employee": ["in", names], "docstatus": 0, "workflow_state": ["in", PENDING_OVERTIME],
                                                             "ot_date": ["between", [start, end]]},
                            fields=["name", "employee", "workflow_state"]):
        items.append(("TLC Overtime Request", d.name, people.get(d.employee), f"Tăng ca chưa duyệt xong ({d.workflow_state})"))
    unprocessed = defaultdict(int)
    for c in frappe.get_all("Employee Checkin", filters={"employee": ["in", names], "skip_auto_attendance": 0, "attendance": ["is", "not set"],
                                                         "time": ["between", [f"{start} 00:00:00", f"{add_days(end, 1)} 00:00:00"]]},
                            fields=["employee"]):
        unprocessed[c.employee] += 1
    for employee, count in unprocessed.items():
        items.append(("Employee Checkin", employee, people.get(employee), f"{count} lần chấm công chưa ghi vào bảng công"))
    return items
