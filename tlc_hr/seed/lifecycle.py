"""Explicit demo fixtures for native Desk UAT; never invoked by imports or migrations."""
import frappe
from frappe.utils import add_days, getdate, today
from frappe.utils.file_manager import save_file


def _insert(doctype, filters, values):
    existing = frappe.db.get_value(doctype, filters, "name")
    if existing:
        return existing
    doc = frappe.get_doc({"doctype": doctype, **values})
    doc.insert(ignore_permissions=True)
    return doc.name


def run(data=None):
    """Run after config apply and the main employee seed. Leaves all approval fixtures in draft."""
    employee = frappe.db.get_value("Employee", {"user_id": "an@demo.example"}, "name")
    if not employee:
        frappe.throw("Seed lifecycle cần nhân viên an@demo.example từ seed chính.")
    evidence_file = frappe.db.get_value("File", {"file_name": "tlc-lifecycle-demo-evidence.txt", "is_private": 1}, "file_url")
    if not evidence_file:
        evidence_file = save_file("tlc-lifecycle-demo-evidence.txt",
                                 "TLC W4 DEMO ONLY. Hồ sơ mẫu cho UAT; không phải hợp đồng/giấy tờ pháp lý thực tế.\n",
                                 "Employee", employee, is_private=1).file_url
    templates = {}
    for kind, title, activities in (
        ("Employee Onboarding Template", "TLC W4 Office", ["HR nhận hồ sơ", "IT giao tài khoản", "Bàn giao tài sản", "Đào tạo hội nhập"]),
        ("Employee Onboarding Template", "TLC W4 Factory", ["HR nhận hồ sơ", "Giao bảo hộ", "An toàn lao động", "Đào tạo vận hành"]),
        ("Employee Separation Template", "TLC W4 Clearance", ["Bàn giao công việc", "Thu hồi tài sản", "Khóa tài khoản", "Quyết toán nghỉ việc"])):
        templates[title] = _insert(kind, {"title": title}, {"title": title, "activities": [
            {"activity_name": item, "role": "TLC HR Officer", "begin_on": index, "duration": 1,
             "required_for_employee_creation": int(kind == "Employee Onboarding Template")} for index, item in enumerate(activities)]})
    start = getdate(today())
    contract = _insert("TLC Employment Contract", {"contract_number": "TLC-UAT-W4-001"}, {
        "employee": employee, "contract_number": "TLC-UAT-W4-001", "contract_type": "Fixed term",
        "signed_on": start, "valid_from": start, "valid_to": add_days(start, 365), "signatory": "TLC DEMO HR",
        "evidence": evidence_file})
    change = _insert("TLC Employee Change Request", {"employee": employee, "reason": "TLC UAT W4 address change"}, {
        "employee": employee, "field": "current_address", "new_value": "TLC UAT - địa chỉ được HR xác nhận",
        "effective_on": add_days(start, 2), "reason": "TLC UAT W4 address change", "evidence": evidence_file})
    dependent = _insert("TLC Employee Dependent", {"employee": employee, "identity_number": "DEMO-W4-DEPENDENT"}, {
        "employee": employee, "dependent_name": "TLC DEMO Dependent", "date_of_birth": "2020-01-01", "relationship": "Child",
        "identity_number": "DEMO-W4-DEPENDENT", "valid_from": start, "status": "Pending", "evidence": evidence_file})
    # An indefinite contract needs 45 calendar days of notice; the last day equals the earliest valid last day.
    last_day = add_days(start, 45)
    separation = _insert("Employee Separation", {"employee": employee, "custom_tlc_reason": "TLC UAT W4 notice and clearance"}, {
        "employee": employee, "custom_tlc_case_type": "Employee resignation", "custom_tlc_submitted_on": start,
        "custom_tlc_last_day": last_day, "custom_tlc_effective_on": last_day,
        "custom_tlc_reason": "TLC UAT W4 notice and clearance", "custom_tlc_contract_category": "Indefinite",
        "boarding_begins_on": start, "separation_template": templates.get("TLC W4 Clearance"),
        "boarding_status": "Pending"})
    return {"employee": employee, "contract": contract, "change_request": change, "dependent": dependent,
            "separation": separation, "templates": templates}


FIXTURES = (
    ("Employee Separation", {"custom_tlc_reason": "TLC UAT W4 notice and clearance"}),
    ("TLC Employment Contract", {"contract_number": "TLC-UAT-W4-001"}),
    ("TLC Employee Change Request", {"reason": "TLC UAT W4 address change"}),
    ("TLC Employee Dependent", {"identity_number": "DEMO-W4-DEPENDENT"}),
)


def _drop(doctype, names):
    for name in names:
        doc = frappe.get_doc(doctype, name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)


def reset():
    """Demo and UAT only: drop the workflow fixtures a run approves, so the next run starts in draft."""
    if not frappe.conf.get("allow_tests") and not frappe.flags.in_test:
        frappe.throw("reset_lifecycle runs only on a test site (site config allow_tests)")
    for doctype, filters in FIXTURES:
        _drop(doctype, frappe.get_all(doctype, filters=filters, pluck="name"))
    print("reset: lifecycle fixtures deleted")
    run()
