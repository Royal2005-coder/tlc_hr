"""Explicit DEMO dependents for the payroll UAT; applies real native HR review transitions."""
import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils.file_manager import save_file


def run(data=None):
    employee = frappe.db.get_value("Employee", {"user_id": "quang@demo.example"}, "name")
    if not employee:
        frappe.throw("Seed phụ thuộc cần quang@demo.example.")
    original_user = frappe.session.user
    if original_user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw("Chỉ quản trị viên chạy seed DEMO.", frappe.PermissionError)
    created = []
    try:
        for index in (1, 2):
            identity = f"TLC-DEMO-QUANG-DEPENDENT-{index}"
            name = frappe.db.get_value("TLC Employee Dependent", {"employee": employee, "identity_number": identity}, "name")
            if name and frappe.db.get_value("TLC Employee Dependent", name, "docstatus") == 1:
                created.append(name)
                continue
            frappe.set_user(original_user)
            if not name:
                evidence = save_file(identity + ".txt", "TLC DEMO ONLY: người phụ thuộc mẫu UAT, không phải đăng ký thuế thực tế.\n",
                                     "Employee", employee, is_private=1).file_url
                doc = frappe.get_doc({"doctype": "TLC Employee Dependent", "employee": employee,
                    "dependent_name": f"TLC DEMO Quang Dependent {index}", "date_of_birth": f"201{index}-01-01",
                    "relationship": "Child", "identity_number": identity, "valid_from": "2020-01-01",
                    "status": "Pending", "evidence": evidence, "notes": "DEMO payroll UAT only; HR final confirmation recorded via workflow."})
                doc.insert(ignore_permissions=True)
                name = doc.name
            frappe.set_user("lan@demo.example")
            doc = frappe.get_doc("TLC Employee Dependent", name)
            if doc.workflow_state == "Nháp":
                apply_workflow(doc, "Gửi duyệt")
            frappe.set_user("hoa@demo.example")
            doc = frappe.get_doc("TLC Employee Dependent", name)
            doc.status = "Verified"
            doc.save()
            if doc.docstatus == 0:
                doc = apply_workflow(doc, "Duyệt")
            created.append(doc.name)
    finally:
        frappe.set_user(original_user)
    return created
