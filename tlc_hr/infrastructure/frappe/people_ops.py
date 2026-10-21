"""Frappe persistence, native custody and scoped people operations."""
from datetime import timedelta
import frappe
from frappe.utils import getdate, now_datetime, today
from tlc_hr.application.people_ops import PeopleOpsService

PREFIX = "TLC People Ops "
HR = {"TLC HR Lead", "TLC HR Officer"}


def is_hr(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or bool(HR.intersection(frappe.get_roles(user)))


def employee_user(employee):
    return frappe.db.get_value("Employee", employee, "user_id")


def is_self(employee, user=None):
    return bool(employee) and employee_user(employee) == (user or frappe.session.user)


def is_manager(employee, user=None):
    manager = frappe.db.get_value("Employee", employee, "reports_to")
    return bool(manager) and employee_user(manager) == (user or frappe.session.user)


def require(condition):
    if not condition:
        frappe.throw("Không có quyền thực hiện thao tác này.", frappe.PermissionError)


def lock(doctype, name):
    frappe.db.sql(f"select name from `tab{doctype}` where name=%s for update", name)


def private_evidence(url):
    if url:
        require(bool(frappe.db.exists("File", {"file_url": url, "is_private": 1})))


def clearance_blockers(employee):
    result = ["Tài sản chưa thu hồi: " + name for name in frappe.get_all("Asset", filters={"custodian": employee, "docstatus": ["!=", 2]}, pluck="name")]
    result += ["Tài khoản chưa khóa: " + name for name in frappe.get_all(PREFIX + "Account", filters={"employee": employee, "status": "Active"}, pluck="name")]
    pending = frappe.db.sql("""select distinct m.name from `tabAsset Movement` m join `tabAsset Movement Item` i on i.parent=m.name where m.docstatus=0 and (i.from_employee=%s or i.to_employee=%s)""", (employee, employee))
    result += ["Biên bản bàn giao chưa ghi sổ: " + row[0] for row in pending]
    return result


def provision_onboarding(employee, asset_items=(), account_licenses=()):
    require(is_hr())
    names = []
    company = frappe.db.get_value("Employee", employee, "company")
    for asset in asset_items:
        movement = frappe.get_doc({"doctype": "Asset Movement", "company": company, "purpose": "Issue", "tlc_ops_staff": frappe.session.user, "assets": [{"asset": asset, "to_employee": employee}]})
        movement.insert()
        names.append(movement.name)
    for license_name in account_licenses:
        doc = frappe.get_doc({"doctype": PREFIX + "Account", "employee": employee, "license": license_name, "account_identifier": employee_user(employee) or employee, "status": "Requested"}).insert()
        names.append(doc.name)
    return names


class FrappePeopleOpsRepository:
    def mandatory_training(self):
        return frappe.get_all(PREFIX + "Training Requirement", filters={"enabled": 1}, fields=["*"])

    def matching_employees(self, requirement):
        filters = {"status": "Active"}
        for field in ("designation", "branch"):
            if requirement.get(field):
                filters[field] = requirement.get(field)
        return frappe.get_all("Employee", filters=filters, pluck="name")

    def latest_completion(self, employee, program):
        value = frappe.db.get_value(PREFIX + "Certificate", {"employee": employee, "training_program": program, "status": "Completed"}, "completed_on", order_by="completed_on desc")
        return getdate(value) if value else None

    def ensure_training(self, employee, requirement):
        filters = {"employee": employee, "requirement": requirement.name, "status": "Pending"}
        existing = frappe.db.exists(PREFIX + "Certificate", filters)
        if existing:
            return existing
        return frappe.get_doc({"doctype": PREFIX + "Certificate", **filters, "training_program": requirement.training_program, "due_on": getdate(today()) + timedelta(days=requirement.due_days or 30)}).insert(ignore_permissions=True).name

    def certificates(self):
        rows = frappe.get_all(PREFIX + "Certificate", filters={"status": "Completed", "expires_on": ["is", "set"]}, fields=["name", "employee", "expires_on"])
        for row in rows:
            row.expires_on = getdate(row.expires_on)
        return rows

    def remind(self, doctype, name, employee, message, band):
        user = employee_user(employee)
        if not user:
            return
        subject = f"{message} [{name}:{band}]"
        if frappe.db.exists("Notification Log", {"document_type": doctype, "document_name": name, "subject": subject, "for_user": user}):
            return
        frappe.get_doc({"doctype": "Notification Log", "subject": subject, "for_user": user, "type": "Alert", "document_type": doctype, "document_name": name}).insert(ignore_permissions=True)
        if not frappe.db.exists("ToDo", {"reference_type": doctype, "reference_name": name, "allocated_to": user, "status": "Open"}):
            frappe.get_doc({"doctype": "ToDo", "allocated_to": user, "description": message, "reference_type": doctype, "reference_name": name, "date": today()}).insert(ignore_permissions=True)

    def pending_acknowledgments(self):
        return frappe.get_all(PREFIX + "Acknowledgment", filters={"acknowledged_at": ["is", "not set"]}, fields=["name", "employee"])

    def pending_health(self):
        return frappe.get_all(PREFIX + "Health Appointment", filters={"status": "Scheduled", "scheduled_at": ["<=", now_datetime() + timedelta(days=7)]}, fields=["name", "employee"])


def daily():
    PeopleOpsService(FrappePeopleOpsRepository()).daily(getdate(today()))


def publish_policy(doc):
    requirement = frappe._dict(designation=doc.designation, branch=doc.branch)
    repo = FrappePeopleOpsRepository()
    for employee in repo.matching_employees(requirement):
        if not frappe.db.exists(PREFIX + "Acknowledgment", {"employee": employee, "policy_version": doc.name}):
            frappe.get_doc({"doctype": PREFIX + "Acknowledgment", "employee": employee, "policy_version": doc.name, "policy_snapshot": doc.body}).insert(ignore_permissions=True)
