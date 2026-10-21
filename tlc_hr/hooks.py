"""Frappe hooks of tlc_hr. TLC behaviour is added here; frappe, erpnext, hrms and erpnextvn are not modified."""

app_name = "tlc_hr"
app_title = "TLC HR"
app_publisher = "TLC HRM team"
app_description = "TLC HRM on Frappe HR: roles, workflows, Vietnamese rules, role workspaces, demo seed"
app_email = "boygia757@gmail.com"
app_license = "GPL-3.0"

required_apps = ["frappe", "erpnext", "hrms", "erpnextvn"]

# Roles, custom fields, approval workflows and the 2026 payroll values, on install and after every migration.
after_install = "tlc_hr.setup.install.after_migrate"
after_migrate = ["tlc_hr.setup.install.after_migrate"]

# Time data of a locked attendance period cannot change (attendance/lock.py): checked on save, cancel and delete.
LOCK = "tlc_hr.attendance.lock.guard"
LOCKED = {"validate": LOCK, "before_cancel": LOCK, "on_trash": LOCK}

doc_events = {
    "Leave Application": {**LOCKED, "validate": ["tlc_hr.events.leave_application_validate", LOCK]},
    "Employee": {"validate": "tlc_hr.events.employee_validate"},
    "Employee Checkin": {**LOCKED, "validate": ["tlc_hr.attendance.checkin.validate", LOCK]},
    "Attendance Request": {**LOCKED, "validate": ["tlc_hr.events.attendance_request_validate", LOCK],
                           "before_submit": "tlc_hr.attendance.lock.allow_post_lock", "on_submit": "tlc_hr.attendance.lock.log_post_lock"},
    "Attendance": LOCKED,
    "TLC Overtime Request": LOCKED,
    "Shift Assignment": LOCKED,
    "Overtime Slip": {"validate": "tlc_hr.attendance.overtime.cap_to_approved"},
}

OVERTIME = "tlc_hr.tlc_hr.doctype.tlc_overtime_request.tlc_overtime_request"
PERIOD = "tlc_hr.tlc_hr.doctype.tlc_attendance_period.tlc_attendance_period"
permission_query_conditions = {"TLC Overtime Request": f"{OVERTIME}.query_conditions", "TLC Attendance Period": f"{PERIOD}.query_conditions"}
has_permission = {"TLC Overtime Request": f"{OVERTIME}.has_permission", "TLC Attendance Period": f"{PERIOD}.has_permission"}

# The reason dialog of "Từ chối" for every TLC approval workflow on the desk.
app_include_js = ["/assets/tlc_hr/js/tlc_workflow.js"]

# TLC additions to the standard Leave Application form (decision support for the approver, reason to reject).
doctype_js = {"Leave Application": "public/js/leave_application.js"}
