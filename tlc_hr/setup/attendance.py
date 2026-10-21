"""Work sites and shift assignment of TLC (shift types, sites and check-in settings are declared in customizing/records.yaml).

Factory and office people check in from the Frappe HR app with their position; HRMS compares it with the Shift Location of their
shift assignment and turns the check-ins into Attendance on its own schedule (auto attendance, last sync updated hourly).
"""

import frappe

SHIFT_OF_CALENDAR = {"office": "TLC Hành chính", "warehouse_night": "TLC Ca đêm", "warehouse_peak": "TLC Cao điểm"}

def sites():
    """Work sites declared in customizing/records.yaml: name -> (latitude, longitude, radius in metres)."""
    from tlc_hr.infrastructure.customizing.loader import load_bundle

    return {r.name: (r.values["latitude"], r.values["longitude"], r.values["checkin_radius"])
            for r in load_bundle().records if r.doctype == "Shift Location"}


# department name (without the company suffix) -> site; every other department works at the head office
SITE_OF_DEPARTMENT = {"Nhà máy 1": "Nhà máy 1", "Nhà máy 2": "Nhà máy 2", "Nhà máy 3": "Nhà máy 3"}
HEAD_OFFICE = "Hội sở TLC"
FIRST_DAY = "2026-01-01"


def site_of(department):
    return SITE_OF_DEPARTMENT.get((department or "").rsplit(" - ", 1)[0], HEAD_OFFICE)


def assign(employee, shift_type, site, company, start_date=FIRST_DAY):
    """Active, submitted Shift Assignment with its work site (skipped when the same one exists); also the default shift.

    Another active assignment of the person is set Inactive, so one shift is in force at a time.
    """
    if frappe.db.exists("Shift Assignment", {"employee": employee, "shift_type": shift_type, "docstatus": 1, "status": "Active"}):
        return
    for other in frappe.get_all("Shift Assignment", filters={"employee": employee, "docstatus": 1, "status": "Active"}, pluck="name"):
        frappe.db.set_value("Shift Assignment", other, "status", "Inactive")
    frappe.get_doc({"doctype": "Shift Assignment", "employee": employee, "shift_type": shift_type, "company": company,
                    "start_date": start_date, "status": "Active", "shift_location": site}).submit()
    frappe.db.set_value("Employee", employee, "default_shift", shift_type)
