"""Employees saved before Employee.tlc_wage_region existed: copy the region of their department (default region I).

Patches run before the after_migrate hook that applies the customizing, so the custom fields are applied here first."""

import frappe


def execute():
    from tlc_hr.infrastructure.customizing.loader import load_bundle
    from tlc_hr.infrastructure.customizing.metadata import CustomFieldApplier

    CustomFieldApplier().apply(load_bundle())
    for employee, department in frappe.get_all("Employee", fields=["name", "department"], as_list=True):
        region = frappe.db.get_value("Department", department, "tlc_wage_region") if department else None
        frappe.db.set_value("Employee", employee, "tlc_wage_region", region or "I", update_modified=False)
