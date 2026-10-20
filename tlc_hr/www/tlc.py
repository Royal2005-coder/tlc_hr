"""/tlc: the TLC home. One page, sections by role: employee, approver, factory or line manager, HR, director."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from tlc_hr.setup.install import TO_HR, TO_MANAGER

no_cache = 1

HR_ROLES = ("TLC HR Officer", "TLC HR Lead")
MANAGER_ROLES = ("TLC Line Manager", "TLC Director")
WORKFORCE = {"head_office": "Hội sở", "factory": "Nhà máy"}
STATE_STYLE = {"Nháp": "muted", TO_MANAGER: "warn", TO_HR: "warn", "Đã duyệt": "ok", "Từ chối": "bad", "Đã hủy": "muted"}

DESK_LINKS = [
    # (roles that see the link, empty for every employee; title; link)
    ((), "Hồ sơ của tôi", "/desk/employee/{employee}"),
    ((), "Tất cả đơn nghỉ của tôi", "/desk/leave-application?employee={employee}"),
    (MANAGER_ROLES, "Danh sách nhân viên thuộc quyền", "/desk/employee?status=Active"),
    (HR_ROLES, "Danh sách nhân sự", "/desk/employee"),
    (HR_ROLES + ("TLC Director",), "Báo cáo số dư phép", "/desk/query-report/Employee Leave Balance"),
    (("TLC Payroll", "TLC HR Lead"), "Thiết lập lương Việt Nam", "/desk/vn-payroll-settings"),
]


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/tlc"
        raise frappe.Redirect
    roles = set(frappe.get_roles())
    employee = frappe.db.get_value(
        "Employee", {"user_id": frappe.session.user},
        ["name", "employee_name", "designation", "department", "tlc_workforce", "reports_to", "leave_approver"], as_dict=True)
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("TLC HRM")
    context.csrf_token = frappe.sessions.get_csrf_token()
    context.today = getdate(nowdate())
    context.state_style = STATE_STYLE
    context.person = employee
    context.roles = roles
    context.is_manager = bool(roles.intersection(MANAGER_ROLES))
    context.is_hr = bool(roles.intersection(HR_ROLES))
    context.is_director = "TLC Director" in roles
    context.inbox = approvals_inbox(roles)
    context.links = [{"title": title, "link": link.format(employee=employee.name if employee else "")}
                     for needed, title, link in DESK_LINKS if (not needed and employee) or roles.intersection(needed)]
    if employee:
        employee.workforce_label = WORKFORCE.get(employee.tlc_workforce, "")
        employee.manager_name = frappe.db.get_value("Employee", employee.reports_to, "employee_name") if employee.reports_to else ""
        employee.approver_name = frappe.db.get_value("User", employee.leave_approver, "full_name") if employee.leave_approver else ""
        context.balances = leave_balances(employee.name)
        context.my_requests = my_requests(employee.name)
        context.my_pending = sum(1 for r in context.my_requests if r.workflow_state in (TO_MANAGER, TO_HR))
    else:
        context.balances, context.my_requests, context.my_pending = [], [], 0
    if context.is_manager and employee:
        context.team = team_view(employee.name)
    if context.is_hr or context.is_director:
        context.company = company_view()


def approvals_inbox(roles):
    """Requests waiting for this user: as the named leave approver, or as HR (lead or officer) at the HR level. Never their own."""
    me = frappe.session.user
    fields = ["name", "employee", "employee_name", "department", "leave_type", "from_date", "to_date", "total_leave_days",
              "description", "workflow_state"]
    rows = frappe.get_all("Leave Application", filters={"workflow_state": TO_MANAGER, "leave_approver": me, "docstatus": 0},
                          fields=fields, order_by="from_date asc")
    if roles.intersection(HR_ROLES):
        rows += frappe.get_all("Leave Application", filters={"workflow_state": TO_HR, "docstatus": 0},
                               fields=fields, order_by="from_date asc")
    own = frappe.db.get_value("Employee", {"user_id": me})
    return [row for row in rows if row.employee != own]


def leave_balances(employee):
    from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

    result = []
    for leave_type in frappe.get_all("Leave Allocation", filters={"employee": employee, "docstatus": 1}, pluck="leave_type", distinct=True):
        # Every leave of the allocation period counts, so approved leave in the coming weeks is already deducted.
        balance = get_leave_balance_on(employee, leave_type, nowdate(), consider_all_leaves_in_the_allocation_period=True)
        result.append({"leave_type": leave_type, "balance": balance})
    return result


def my_requests(employee):
    return frappe.get_all(
        "Leave Application", filters={"employee": employee}, order_by="creation desc", limit=10,
        fields=["name", "leave_type", "from_date", "to_date", "total_leave_days", "workflow_state", "tlc_reject_reason", "leave_approver"])


def approved_leave_between(employees, start, end):
    if not employees:
        return []
    return frappe.get_all(
        "Leave Application",
        filters={"employee": ["in", employees], "status": "Approved", "docstatus": 1, "from_date": ["<=", end], "to_date": [">=", start]},
        fields=["employee", "employee_name", "leave_type", "from_date", "to_date", "total_leave_days"], order_by="from_date asc")


def team_view(manager):
    """Everyone below the manager in the reporting tree, who is away today and the approved leave of the next 14 days."""
    today = getdate(nowdate())
    members = frappe.get_all("Employee", filters={"status": "Active", "name": ["in", frappe.db.get_descendants("Employee", manager) or [""]]},
                             fields=["name", "employee_name", "designation", "tlc_workforce", "reports_to"], order_by="employee_name asc")
    ids = [m.name for m in members]
    upcoming = approved_leave_between(ids, today, add_days(today, 14))
    away_today = {row.employee for row in upcoming if getdate(row.from_date) <= today <= getdate(row.to_date)}
    for member in members:
        member.away_today = member.name in away_today
    return frappe._dict(members=members, size=len(members), away_today=len(away_today), upcoming=upcoming)


def company_view():
    """Headcount by site and by workforce, requests waiting at each level, people away today: for HR and the director."""
    today = getdate(nowdate())
    active = frappe.get_all("Employee", filters={"status": "Active", "company": "TLC Demo"}, fields=["name", "department", "tlc_workforce"])
    by_site, by_workforce = {}, {}
    for row in active:
        site = (row.department or "").rsplit(" - ", 1)[0]
        by_site[site] = by_site.get(site, 0) + 1
        label = WORKFORCE.get(row.tlc_workforce, "Khác")
        by_workforce[label] = by_workforce.get(label, 0) + 1
    away = approved_leave_between([row.name for row in active], today, today)
    return frappe._dict(
        headcount=len(active), by_site=sorted(by_site.items(), key=lambda kv: -kv[1]), by_workforce=by_workforce,
        waiting_manager=frappe.db.count("Leave Application", {"workflow_state": TO_MANAGER, "docstatus": 0}),
        waiting_hr=frappe.db.count("Leave Application", {"workflow_state": TO_HR, "docstatus": 0}),
        away_today=away)
