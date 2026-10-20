"""TLC roles and how each TLC level maps to the roles of Frappe HR."""

import frappe

# Roles that exist only for TLC (desk access, used by workflows and by the /tlc portal).
TLC_ROLES = ("TLC Director", "TLC HR Lead", "TLC HR Officer", "TLC Payroll", "TLC Line Manager", "TLC Role Admin")

# TLC level of the seed -> Frappe roles given to the user. Every person also gets Employee and Employee Self Service.
FRAPPE_ROLES_OF = {
    "director": ("TLC Director", "Leave Approver", "Expense Approver"),
    "cfo": ("TLC Director", "Accounts Manager", "Leave Approver", "Expense Approver"),
    "hr_director": ("TLC HR Lead", "HR Manager", "HR User", "Leave Approver"),
    "hr_officer": ("TLC HR Officer", "HR User"),
    "period_controller": ("TLC HR Officer", "HR User"),
    "payroll_officer": ("TLC Payroll", "HR User"),
    "manager": ("TLC Line Manager", "Leave Approver", "Expense Approver"),
    "accountant": ("Accounts User",),
    "role_admin": ("TLC Role Admin",),
}


def ensure_roles():
    """Create the TLC roles with desk access (idempotent)."""
    for role in TLC_ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
