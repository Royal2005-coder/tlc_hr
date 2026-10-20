"""Shifts, work sites and check-in settings of TLC on the standard HRMS doctypes (idempotent, after every migration).

Factory and office people check in from the Frappe HR app with their position; HRMS compares it with the Shift Location of their
shift assignment and turns the check-ins into Attendance on its own schedule (auto attendance, last sync updated hourly).
"""

import frappe

# name -> (start, end, colour); hours are counted per IN/OUT pair, so the lunch break between two pairs is not paid time.
SHIFTS = {
    "TLC Hành chính": ("08:00:00", "17:00:00", "Blue"),
    "TLC Ca đêm": ("22:00:00", "06:00:00", "Violet"),
    "TLC Cao điểm": ("07:00:00", "19:00:00", "Orange"),
}
SHIFT_OF_CALENDAR = {"office": "TLC Hành chính", "warehouse_night": "TLC Ca đêm", "warehouse_peak": "TLC Cao điểm"}

# Work sites: demo coordinates (replace with the surveyed position of each gate); radius in metres.
SITES = {
    "Hội sở TLC": (10.776889, 106.700806, 200),
    "Nhà máy 1": (10.850632, 106.772010, 200),
    "Nhà máy 2": (10.980410, 106.651871, 200),
    "Nhà máy 3": (10.957413, 106.842687, 200),
}
# department name (without the company suffix) -> site; every other department works at the head office
SITE_OF_DEPARTMENT = {"Nhà máy 1": "Nhà máy 1", "Nhà máy 2": "Nhà máy 2", "Nhà máy 3": "Nhà máy 3"}
HEAD_OFFICE = "Hội sở TLC"
FIRST_DAY = "2026-01-01"


def site_of(department):
    return SITE_OF_DEPARTMENT.get((department or "").rsplit(" - ", 1)[0], HEAD_OFFICE)


def ensure_shift_types():
    """No holiday list on the shift: HRMS then uses the Holiday List Assignment of the employee or company for each year."""
    for name, (start, end, colour) in SHIFTS.items():
        doc = frappe.get_doc("Shift Type", name) if frappe.db.exists("Shift Type", name) else frappe.new_doc("Shift Type")
        doc.update({
            "name": name, "start_time": start, "end_time": end, "color": colour,
            "enable_auto_attendance": 1, "auto_update_last_sync": 1,
            "determine_check_in_and_check_out": "Strictly based on Log Type in Employee Checkin",
            "working_hours_calculation_based_on": "Every Valid Check-in and Check-out",
            "begin_check_in_before_shift_start_time": 60, "allow_check_out_after_shift_end_time": 240,
            "late_entry_grace_period": 10, "early_exit_grace_period": 10,
            "enable_late_entry_marking": 1, "enable_early_exit_marking": 1,
            "working_hours_threshold_for_half_day": 4, "working_hours_threshold_for_absent": 2,
        })
        doc.holiday_list = None
        if doc.is_new():
            doc.process_attendance_after = FIRST_DAY
        doc.flags.ignore_permissions = True
        doc.save() if not doc.is_new() else doc.insert()


def ensure_sites():
    for name, (latitude, longitude, radius) in SITES.items():
        doc = frappe.get_doc("Shift Location", name) if frappe.db.exists("Shift Location", name) else frappe.new_doc("Shift Location")
        doc.update({"location_name": name, "latitude": latitude, "longitude": longitude, "checkin_radius": radius})
        doc.flags.ignore_permissions = True
        doc.save() if not doc.is_new() else doc.insert()


def ensure_settings():
    settings = frappe.get_single("HR Settings")
    if not (settings.allow_geolocation_tracking and settings.allow_employee_checkin_from_mobile_app):
        settings.allow_geolocation_tracking = 1
        settings.allow_employee_checkin_from_mobile_app = 1
        settings.flags.ignore_permissions = True
        settings.save()


def ensure_all():
    ensure_sites()
    ensure_shift_types()
    ensure_settings()


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
