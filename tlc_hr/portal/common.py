"""Shared context of the TLC People portal: who is signed in, what they may see, and the navigation for their role."""

import hashlib

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

HR_ROLES = ("TLC HR Officer", "TLC HR Lead")
MANAGER_ROLES = ("TLC Line Manager", "TLC Director")
WORKFORCE = {"head_office": "Hội sở", "factory": "Nhà máy"}
AVATAR_COLORS = ["#0b6e4f", "#1d5fa8", "#8a4fbf", "#b5541b", "#0f7c8c", "#a2385d", "#5b6b1f", "#6b4e2e"]

# (key, label, path, who sees it: "all", "approver", "manager", "company")
NAV = [
    ("home", "Trang chủ", "/tlc", "all"),
    ("leave", "Nghỉ phép", "/tlc/leave", "all"),
    ("me", "Hồ sơ", "/tlc/me", "all"),
    ("people", "Danh bạ", "/tlc/people", "all"),
    ("team", "Đội của tôi", "/tlc/team", "manager"),
    ("approvals", "Duyệt đơn", "/tlc/approvals", "approver"),
    ("reports", "Báo cáo", "/tlc/reports", "company"),
]


def require_login(path):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = f"/login?redirect-to={path}"
        raise frappe.Redirect


def initials(name):
    parts = [p for p in (name or "?").split() if p]
    return (parts[-1][0] + (parts[0][0] if len(parts) > 1 else "")).upper() if parts else "?"


def avatar_color(name):
    return AVATAR_COLORS[int(hashlib.md5((name or "").encode()).hexdigest(), 16) % len(AVATAR_COLORS)]


def site_of(department):
    return (department or "").rsplit(" - ", 1)[0]


def me():
    """The signed-in employee with the fields every page shows (None for a user without an employee record)."""
    employee = frappe.db.get_value(
        "Employee", {"user_id": frappe.session.user},
        ["name", "employee_name", "designation", "department", "tlc_workforce", "reports_to", "leave_approver",
         "date_of_joining", "date_of_birth", "gender", "company", "tlc_dependents", "tlc_key", "user_id"], as_dict=True)
    if employee:
        employee.site = site_of(employee.department)
        employee.workforce_label = WORKFORCE.get(employee.tlc_workforce, "")
        employee.first_name = (employee.employee_name or "").split()[-1]
        employee.manager_name = frappe.db.get_value("Employee", employee.reports_to, "employee_name") if employee.reports_to else ""
        employee.approver_name = frappe.db.get_value("User", employee.leave_approver, "full_name") if employee.leave_approver else ""
    return employee


def flags(roles):
    return frappe._dict(
        is_manager=bool(roles.intersection(MANAGER_ROLES)),
        is_hr=bool(roles.intersection(HR_ROLES)),
        is_director="TLC Director" in roles,
        is_hr_lead="TLC HR Lead" in roles,
        sees_company=bool(roles.intersection(HR_ROLES + ("TLC Director",))),
        is_approver=bool(roles.intersection(("Leave Approver",) + HR_ROLES)),
    )


def greeting():
    hour = frappe.utils.now_datetime().hour
    return "Chào buổi sáng" if hour < 11 else "Chào buổi chiều" if hour < 18 else "Chào buổi tối"


def base_context(context, active, path):
    """Fill what the layout needs; pages add their own data on top."""
    require_login(path)
    from tlc_hr.portal.data import approvals_inbox

    roles = set(frappe.get_roles())
    f = flags(roles)
    person = me()
    inbox_count = len(approvals_inbox(roles, person)) if f.is_approver else 0
    visible = {"all": True, "approver": f.is_approver, "manager": f.is_manager or f.sees_company, "company": f.sees_company}
    context.update({
        "no_cache": 1, "show_sidebar": False, "title": _("TLC People"), "active": active, "roles": roles, "f": f,
        "person": person, "today": getdate(nowdate()), "csrf_token": frappe.sessions.get_csrf_token(),
        "nav": [{"key": k, "label": label, "path": p, "badge": inbox_count if k == "approvals" else 0}
                for k, label, p, who in NAV if visible[who]],
        "inbox_count": inbox_count, "initials": initials, "avatar_color": avatar_color, "site_of": site_of,
        "can_desk": bool(roles.intersection(HR_ROLES + ("TLC Director", "System Manager", "TLC Payroll"))),
        "greeting": greeting(),
        "no_header": 1, "full_width": 1, "no_breadcrumbs": 1,
    })
    from tlc_hr.portal.data import balances

    context.balances_for_form = balances(person.name) if person and person.approver_name else []
    return context
