"""Role landing defaults only; document/module permissions remain authoritative."""

import frappe

# Business roles first: a person who holds System Manager and a business role works the business queue,
# the technical workspace is only the landing page for someone whose sole admin role is System Manager.
WORKSPACE_OF = (
    ("TLC Director", "TLC Điều hành"),
    ("TLC HR Lead", "TLC Nhân sự"),
    ("TLC Payroll", "TLC Tác nghiệp lương"),
    ("TLC HR Officer", "TLC Nhân sự"),
    ("Accounts Manager", "TLC Kế toán chi trả"),
    ("Accounts User", "TLC Kế toán chi trả"),
    ("TLC Line Manager", "TLC Quản lý"),
    ("System Manager", "TLC Quản trị kỹ thuật"),
    ("TLC Role Admin", "TLC Quản trị kỹ thuật"),
)


def has_app_permission():
    roles = set(frappe.get_roles())
    return "TLC Self Service" in roles or any(role in roles for role, _ in WORKSPACE_OF)


def apply_user_route(user):
    """Set the same defaults for seeded and real users without granting any roles."""
    if not user or user == "Guest":
        return None
    roles = set(frappe.get_roles(user))
    workspace = next((title for role, title in WORKSPACE_OF if role in roles), None)
    if workspace and not frappe.db.exists("Workspace", workspace):
        # Keep the intended app, rather than silently sending a business user to ESS.
        workspace = None
    business_user = any(role in roles for role, _ in WORKSPACE_OF)
    if not business_user and not roles.intersection({"Employee", "Employee Self Service", "TLC Self Service"}):
        return None
    wanted = {"default_app": "tlc_hr" if business_user else "hrms", "default_workspace": workspace or ""}
    current = frappe.db.get_value("User", user, list(wanted), as_dict=True)
    if current and any((current.get(key) or "") != value for key, value in wanted.items()):
        frappe.db.set_value("User", user, wanted, update_modified=False)
        frappe.clear_cache(user=user)
    return workspace


def on_session_creation(login_manager=None):
    apply_user_route(login_manager.user if login_manager else frappe.session.user)
