"""Additive demo data; call run(data=None) after the base people/designations seed."""
import frappe
from frappe.utils import nowdate


def _ensure(doctype, filters, values):
    existing = frappe.db.exists(doctype, filters)
    if existing:
        return existing
    doc = frappe.get_doc({"doctype": doctype, **values})
    doc.insert(ignore_permissions=True)
    return doc.name


def run(data=None):
    company = "TLC Demo"
    if not frappe.db.exists("Company", company):
        frappe.throw("Run the base TLC demo seed before organization.run.")
    for row in frappe.get_all("Department", filters={"company": company}, fields=["name", "tlc_organization_code"]):
        if not row.tlc_organization_code:
            doc = frappe.get_doc("Department", row.name)
            doc.tlc_organization_code = "ORG-" + frappe.generate_hash(length=12).upper()
            doc.save(ignore_permissions=True)
    people = {}
    for account in ("an", "quang", "hoa"):
        person = frappe.db.get_value("Employee", {"company": company, "user_id": f"{account}@demo.example"},
                                     ["name", "department", "designation"], as_dict=True)
        if not person or not person.department:
            frappe.throw(f"Base demo employee {account}@demo.example with department is required.")
        people[account] = person
    grade = _ensure("Employee Grade", "TLC Organization Demo Grade", {"name": "TLC Organization Demo Grade"})
    for code, person, title in (("ORG-DEMO-SALES", people["an"], "Sales specialist"),
                                ("ORG-DEMO-HR", people["hoa"], "Cross-department HR liaison")):
        if not person.designation:
            frappe.throw("Base demo designations are required before the organization seed.")
        _ensure("TLC Organization Position", code, {"position_code": code, "position_title": title,
            "company": company, "department": person.department, "designation": person.designation, "grade": grade,
            "job_description": "Demo: maintain customer and people-service coordination within the assigned unit."})
    for position, department, primary in (("ORG-DEMO-SALES", people["an"].department, 1),
                                           ("ORG-DEMO-HR", people["hoa"].department, 0)):
        filters = {"employee": people["an"].name, "position": position}
        _ensure("TLC Organization Assignment", filters, {**filters, "company": company,
            "department": department, "start_date": "2026-01-01", "is_primary": primary})
    for account in ("quang", "hoa"):
        filters = {"department": people["an"].department, "leader": people[account].name, "employee": ["is", "not set"]}
        _ensure("TLC Organization Reporting Line", filters, {"company": company,
            "department": people["an"].department, "leader": people[account].name, "start_date": "2026-01-01"})
    _ensure("TLC Organization Headcount", {"position": "ORG-DEMO-SALES", "as_on": nowdate()},
        {"company": company, "position": "ORG-DEMO-SALES", "as_on": nowdate(), "capacity": 2})
