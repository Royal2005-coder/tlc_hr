"""/tlc: one home page per TLC role with the approvals inbox, my requests and my leave balance."""

import frappe
from frappe import _
from frappe.utils import nowdate

from tlc_hr.setup.install import TO_HR, TO_MANAGER

no_cache = 1

HR = ("TLC HR Officer", "TLC HR Lead")
TILES = [
    # (roles that see the tile, empty for every employee; title; link)
    ((), "Xin nghỉ phép", "/app/leave-application/new"),
    ((), "Đơn của tôi", "/app/leave-application?employee={employee}"),
    ((), "Hồ sơ của tôi", "/app/employee/{employee}"),
    (("TLC Line Manager", "TLC Director"), "Nhân viên của tôi", "/app/employee?reports_to={employee}"),
    (HR, "Danh sách nhân sự", "/app/employee"),
    (HR + ("TLC Director",), "Báo cáo số dư phép", "/app/query-report/Employee Leave Balance"),
    (("TLC Payroll", "TLC HR Lead"), "Thiết lập lương Việt Nam", "/app/vn-payroll-settings"),
    (("TLC Director",), "Tổng quan nhân sự", "/app/hr"),
]


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/tlc"
        raise frappe.Redirect
    roles = set(frappe.get_roles())
    employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, ["name", "employee_name", "department"], as_dict=True)
    emp_name = employee.name if employee else ""
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("TLC HRM")
    context.person = employee
    context.tiles = [
        {"title": title, "link": link.format(employee=emp_name)}
        for needed, title, link in TILES if (not needed and employee) or roles.intersection(needed)
    ]
    context.inbox = approvals_inbox(roles)
    context.my_requests = frappe.get_all(
        "Leave Application", filters={"employee": emp_name}, order_by="creation desc", limit=10,
        fields=["name", "leave_type", "from_date", "to_date", "total_leave_days", "workflow_state"]) if employee else []
    context.balances = leave_balances(emp_name) if employee else []


def approvals_inbox(roles):
    """Leave requests waiting for this user: as the named leave approver, or as HR lead at the HR level. Never their own."""
    me = frappe.session.user
    fields = ["name", "employee_name", "leave_type", "from_date", "to_date", "total_leave_days", "workflow_state"]
    rows = frappe.get_all("Leave Application", filters={"workflow_state": TO_MANAGER, "leave_approver": me, "docstatus": 0},
                          fields=fields, order_by="from_date asc")
    if "TLC HR Lead" in roles:
        rows += frappe.get_all("Leave Application", filters={"workflow_state": TO_HR, "docstatus": 0},
                               fields=fields, order_by="from_date asc")
    own = frappe.db.get_value("Employee", {"user_id": me})
    return [row for row in rows if frappe.db.get_value("Leave Application", row.name, "employee") != own]


def leave_balances(employee):
    from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

    result = []
    for leave_type in frappe.get_all("Leave Allocation", filters={"employee": employee, "docstatus": 1}, pluck="leave_type", distinct=True):
        result.append({"leave_type": leave_type, "balance": get_leave_balance_on(employee, leave_type, nowdate())})
    return result
