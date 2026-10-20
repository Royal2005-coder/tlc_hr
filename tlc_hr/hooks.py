"""Frappe hooks of tlc_hr. TLC behaviour is added here; the core apps are not modified."""

app_name = "tlc_hr"
app_title = "TLC HR"
app_publisher = "TLC HRM team"
app_description = "TLC HRM on Frappe HR: roles, workflows, Vietnamese rules, /tlc portal, demo seed"
app_email = "boygia757@gmail.com"
app_license = "GPL-3.0"

required_apps = ["frappe", "erpnext", "hrms", "erpnextvn"]

# The 2026 Vietnamese payroll parameters replace the older defaults of erpnextvn on install and after every migration.
after_install = "tlc_hr.vn.statutory.apply_settings"
after_migrate = ["tlc_hr.vn.statutory.apply_settings"]
