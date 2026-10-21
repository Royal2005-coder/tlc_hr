"""Additive row restrictions for native role surfaces, never role/field permission grants.

HRMS v16 has no permission_query_conditions/has_permission hooks for these native
DocTypes. Its controller methods and role permissions alone do not express TLC's
reporting-tree scope. Reuse the same tree as overtime, including the user's own
Employee. Frappe combines query hook conditions with AND and all document hooks
can veto. Returning True here only permits the remaining native checks to run.

Payroll is company-wide for Employee lookup only; this does not grant access to
Salary Slip, sensitive field permlevels, attendance, or finance documents.
"""

import frappe

from tlc_hr.infrastructure.frappe.overtime import scope_of

WORKFORCE = frozenset({"Employee", "Attendance", "Shift Assignment", "Employee Checkin", "Attendance Request", "Leave Application"})
COMPANY_ROLES = frozenset({"TLC HR Lead", "TLC HR Officer", "TLC Director", "HR Manager"})


def employee_scope(user, doctype):
    """None is unrestricted by this adapter; an empty tuple is explicitly denied."""
    roles = frozenset(frappe.get_roles(user))
    if user == "Administrator" or "System Manager" in roles or roles & COMPANY_ROLES:
        return None
    if doctype == "Employee" and "TLC Payroll" in roles:
        return None
    if "TLC Line Manager" in roles:
        return tuple(scope_of(user))
    employee = frappe.db.get_value("Employee", {"user_id": user})
    return (employee,) if employee else ()


def query_conditions(user=None, doctype=None):
    user = user or frappe.session.user
    if doctype not in WORKFORCE:
        # Fail closed if the hook was wired to a different document by mistake.
        return "1=0"
    names = employee_scope(user, doctype)
    if names is None:
        return ""
    if not names:
        return "1=0"
    field = "name" if doctype == "Employee" else "employee"
    values = ", ".join(frappe.db.escape(name) for name in names)
    return f"`tab{doctype}`.`{field}` IN ({values})"


def has_permission(doc, user=None, permission_type=None, ptype=None):
    """Restrict reads and writes alike; sharing a record cannot bypass the scope."""
    if doc.doctype not in WORKFORCE:
        return False
    names = employee_scope(user or frappe.session.user, doc.doctype)
    if names is None:
        return True
    employee = doc.name if doc.doctype == "Employee" else doc.get("employee")
    return bool(employee and employee in names)
