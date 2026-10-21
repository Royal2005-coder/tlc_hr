"""TLC roles (declared in customizing/roles.yaml) and how each TLC level of the demo maps to Frappe roles."""

SELF_SERVICE = "TLC Self Service"

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
