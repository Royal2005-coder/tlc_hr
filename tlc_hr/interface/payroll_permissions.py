"""Salary access is independent of the manager's workforce reporting scope."""

import frappe

PAYROLL_READ_ROLES = frozenset({"TLC Payroll", "TLC HR Lead", "TLC Director", "Accounts User", "Accounts Manager", "System Manager"})


def is_payroll_reader(user):
    return user == "Administrator" or bool(PAYROLL_READ_ROLES.intersection(frappe.get_roles(user)))


def query_conditions(user=None):
    user = user or frappe.session.user
    if is_payroll_reader(user):
        return ""
    return (
        "`tabSalary Slip`.docstatus = 1 AND `tabSalary Slip`.employee IN "
        "(SELECT name FROM `tabEmployee` WHERE user_id = " + frappe.db.escape(user) + ")"
    )


def has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if is_payroll_reader(user):
        return True  # Native role and company permissions still apply.
    if ptype not in (None, "read", "select", "print", "email") or doc.docstatus != 1:
        return False
    return bool(doc.employee and frappe.db.get_value("Employee", doc.employee, "user_id") == user)
