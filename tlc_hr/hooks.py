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

# Locked-period guards run on writes, cancellation and deletion.
LOCK = "tlc_hr.interface.attendance.guard"
LOCKED = {"validate": LOCK, "before_cancel": LOCK, "on_trash": LOCK}

PEOPLE = "tlc_hr.interface.people"
ORG = "tlc_hr.interface.organization"
LIFECYCLE = "tlc_hr.interface.lifecycle"
LIFEGUARD = "tlc_hr.interface.lifecycle_guards"
OPS = "tlc_hr.interface.people_ops"
PCOM = "tlc_hr.interface.payroll_compliance"
TRAVEL = "tlc_hr.interface.travel_finance"
FINANCE = "tlc_hr.interface.finance_documents"

# Custom lifecycle records are declared in customizing/lifecycle_records.yaml (no controller files).
LIFECYCLE_RECORDS = (
    "TLC Employment Contract", "TLC Employee Dependent", "TLC Employee Document", "TLC Employee Change Request",
    "TLC Probation Review", "TLC Employment Episode",
)


doc_events = {
    "Leave Application": {**LOCKED,
                          "validate": [f"{PEOPLE}.leave_application_validate", f"{ORG}.warn_recorded_department", LOCK],
                          "on_update": "tlc_hr.interface.services.approved_leave",
                          "on_submit": "tlc_hr.interface.services.approved_leave"},
    "Employee": {"validate": [f"{PEOPLE}.employee_validate", f"{LIFEGUARD}.validate", f"{LIFECYCLE}.validate"]},
    "Leave Ledger Entry": {"before_validate": f"{PEOPLE}.carried_leave_validate"},
    "Employee Checkin": {**LOCKED, "validate": ["tlc_hr.interface.attendance.checkin_validate", LOCK]},
    "Attendance Request": {**LOCKED, "validate": ["tlc_hr.interface.attendance.correction_validate", LOCK],
                           "before_submit": "tlc_hr.interface.attendance.allow_post_lock",
                           "on_submit": "tlc_hr.interface.attendance.log_post_lock"},
    "Attendance": {**LOCKED, "validate": ["tlc_hr.interface.organization.warn_recorded_department", LOCK]},
    "Shift Assignment": LOCKED,
    "TLC Overtime Request": LOCKED,
    "Overtime Slip": {"validate": "tlc_hr.interface.overtime.cap_overtime_slip"},

    # W2 payroll: HR computes once periods are locked, CEO signs, accounting confirms payment.
    "Payroll Entry": {"before_save": f"{PCOM}.entry_guard",
                      "before_submit": ["tlc_hr.interface.payroll.before_submit", f"{PCOM}.apply_awards"],
                      "on_cancel": ["tlc_hr.interface.payroll.on_cancel", f"{PCOM}.release_awards"],
                      "before_cancel": f"{PCOM}.prohibit_approved_change",
                      "on_trash": f"{PCOM}.prohibit_approved_change",
                      "before_update_after_submit": ["tlc_hr.interface.payroll.before_update_after_submit", f"{PCOM}.entry_guard"],
                      "on_update_after_submit": "tlc_hr.interface.payroll.on_update_after_submit"},
    "Salary Slip": {"before_validate": f"{PCOM}.prepare_slip",
                    "before_cancel": f"{PCOM}.prohibit_approved_change",
                    "on_trash": f"{PCOM}.prohibit_approved_change"},
    "Salary Structure Assignment": {"validate": f"{PCOM}.validate_assignment"},
    "TLC Payroll Review": {"validate": f"{PCOM}.validate_review"},
    "TLC Payroll Adjustment": {"validate": f"{PCOM}.validate_award", "before_cancel": f"{PCOM}.guard_source_cancel"},
    "TLC Payroll Bonus": {"validate": f"{PCOM}.validate_award", "before_cancel": f"{PCOM}.guard_source_cancel"},
    "TLC Insurance Change": {"validate": f"{PCOM}.validate_insurance"},
    "TLC Insurance Benefit": {"validate": f"{PCOM}.validate_insurance"},
    "TLC Salary Review": {"validate": f"{PCOM}.validate_salary_review", "on_submit": f"{PCOM}.approve_salary_review"},

    # W3 travel, advances and expense settlement.
    "Travel Request": {"validate": f"{TRAVEL}.validate_travel",
                       "on_update": [f"{TRAVEL}.travel_updated", f"{FINANCE}.snapshot"],
                       "on_update_after_submit": [f"{TRAVEL}.travel_updated", f"{FINANCE}.snapshot"]},
    "Employee Advance": {"validate": f"{TRAVEL}.validate_advance",
                         "on_update": [f"{TRAVEL}.finance_updated", f"{FINANCE}.snapshot"],
                         "on_update_after_submit": [f"{TRAVEL}.finance_updated", f"{FINANCE}.snapshot"]},
    "Expense Claim": {"validate": f"{TRAVEL}.validate_claim",
                      "on_update": [f"{TRAVEL}.finance_updated", f"{FINANCE}.snapshot"],
                      "on_update_after_submit": [f"{TRAVEL}.finance_updated", f"{FINANCE}.snapshot"]},
    "Payment Entry": {"validate": f"{TRAVEL}.validate_payment", "before_cancel": f"{TRAVEL}.payment_before_cancel"},
    "Additional Salary": {"validate": ["tlc_hr.interface.travel_adjustments.validate_adjustment_salary", f"{TRAVEL}.validate_additional_salary"]},
    "File": {"validate": f"{FINANCE}.guard_snapshot", "on_trash": f"{FINANCE}.guard_snapshot"},

    # W4 lifecycle: contracts, dependents, documents, changes, probation, episodes and native exits.
    "TLC Employment Contract": {"validate": f"{LIFECYCLE}.validate", "before_submit": f"{LIFECYCLE}.before_submit",
                                 "on_submit": f"{LIFECYCLE}.on_submit", "before_cancel": f"{LIFEGUARD}.prevent_cancel_applied"},
    "TLC Employee Dependent": {"validate": [f"{LIFECYCLE}.validate", f"{LIFEGUARD}.validate"],
                                "before_submit": f"{LIFECYCLE}.before_submit", "on_submit": f"{LIFECYCLE}.on_submit"},
    "TLC Employee Document": {"validate": f"{LIFECYCLE}.validate", "before_submit": f"{LIFECYCLE}.before_submit",
                               "on_submit": f"{LIFECYCLE}.on_submit"},
    "TLC Employee Change Request": {"validate": f"{LIFECYCLE}.validate", "before_submit": f"{LIFECYCLE}.before_submit",
                                     "on_submit": f"{LIFECYCLE}.on_submit", "before_cancel": f"{LIFEGUARD}.prevent_cancel_applied"},
    "TLC Probation Review": {"validate": [f"{LIFECYCLE}.validate", f"{LIFEGUARD}.validate"],
                              "before_submit": f"{LIFECYCLE}.before_submit", "on_submit": f"{LIFECYCLE}.on_submit"},
    "TLC Employment Episode": {"validate": f"{LIFECYCLE}.validate", "before_submit": f"{LIFECYCLE}.before_submit",
                                "on_submit": f"{LIFECYCLE}.on_submit"},
    "Employee Onboarding": {"validate": f"{LIFECYCLE}.validate", "on_submit": f"{LIFECYCLE}.provisioning"},
    "Employee Separation": {"validate": f"{LIFECYCLE}.validate"},
    "Employee Promotion": {"validate": f"{LIFECYCLE}.validate", "before_submit": f"{LIFECYCLE}.before_submit",
                           "on_submit": f"{LIFECYCLE}.on_submit", "before_cancel": f"{LIFEGUARD}.prevent_cancel_applied"},
    "Employee Transfer": {"validate": f"{LIFECYCLE}.validate", "before_submit": f"{LIFECYCLE}.before_submit",
                          "on_submit": f"{LIFECYCLE}.on_submit", "before_cancel": f"{LIFEGUARD}.prevent_cancel_applied"},
    "Task": {"validate": f"{LIFECYCLE}.validate"},
    "Project": {"validate": f"{LIFECYCLE}.validate"},

    # W5 people operations: assets, licenses, training, benefits, policy acknowledgment, goals.
    "Asset Movement": {"validate": f"{OPS}.movement_validate", "before_submit": f"{OPS}.movement_before_submit"},
    "Employee Grievance": {"validate": f"{OPS}.native_validate"},
    "Goal": {"validate": f"{OPS}.native_validate"},
    "Appraisal": {"validate": f"{OPS}.native_validate"},

    # W3 native recruitment.
    "Job Requisition": {"validate": "tlc_hr.interface.recruitment.validate_requisition_doc",
                        "on_update": "tlc_hr.interface.recruitment.requisition_updated"},
    "Job Opening": {"validate": "tlc_hr.interface.recruitment.validate_opening",
                    "on_update": "tlc_hr.interface.recruitment.opening_updated"},
    "Job Applicant": {"validate": ["tlc_hr.interface.recruitment.validate_applicant",
                                    "tlc_hr.interface.recruitment_pipeline.validate_applicant"]},
    "Job Offer": {"validate": "tlc_hr.interface.recruitment.validate_offer",
                  "before_update_after_submit": "tlc_hr.interface.recruitment.validate_offer",
                  "on_update": "tlc_hr.interface.recruitment.offer_updated",
                  "on_update_after_submit": "tlc_hr.interface.recruitment.offer_updated",
                  "before_cancel": "tlc_hr.interface.recruitment.before_cancel_offer",
                  "before_print": "tlc_hr.interface.recruitment.before_print_offer"},
    "Communication": {"before_insert": "tlc_hr.interface.recruitment.validate_offer_communication",
                      "after_insert": "tlc_hr.interface.recruitment_ai.communication_created"},

    # W8 organization structure.
    "Department": {"validate": f"{ORG}.validate"},
    "Shift Location": {"validate": f"{ORG}.validate"},
    "TLC Organization Position": {"validate": f"{ORG}.validate"},
    "TLC Organization Assignment": {"validate": f"{ORG}.validate"},
    "TLC Organization Reporting Line": {"validate": f"{ORG}.validate"},
    "TLC Organization Headcount": {"validate": f"{ORG}.validate"},
    "TLC Organization Change": {"validate": f"{ORG}.validate", "on_submit": f"{ORG}.on_submit",
                                 "before_cancel": f"{ORG}.before_cancel"},

    # W7 assistant safety hooks (Raven doctypes exist once Raven is installed).
    "Raven Message": {"validate": "tlc_hr.interface.assistant.guard_message"},
    "Raven Bot": {"validate": "tlc_hr.interface.assistant.validate_bot"},
    "Raven AI Function": {"validate": "tlc_hr.interface.assistant.validate_function"},
}

OVERTIME = "tlc_hr.interface.overtime"
PERIOD = "tlc_hr.interface.attendance"
ROLE = "tlc_hr.interface.role_experience"

permission_query_conditions = {
    "TLC Overtime Request": f"{OVERTIME}.query_conditions", "TLC Attendance Period": f"{PERIOD}.period_query_conditions",
    # W8 native workforce scope: employees see themselves, managers their reporting tree, HR/CEO the company.
    "Employee": f"{ROLE}.employee_query", "Attendance": f"{ROLE}.attendance_query",
    "Shift Assignment": f"{ROLE}.shift_assignment_query", "Employee Checkin": f"{ROLE}.checkin_query",
    "Attendance Request": f"{ROLE}.attendance_request_query", "Leave Application": f"{ROLE}.leave_query",
    "Salary Slip": "tlc_hr.interface.payroll_permissions.query_conditions",
    # W3 finance documents.
    "Travel Request": f"{TRAVEL}.travel_query", "Employee Advance": f"{TRAVEL}.advance_query",
    "Expense Claim": f"{TRAVEL}.claim_query",
    # W5 people operations.
    "Asset Movement": f"{OPS}.asset_movement_query", "Employee Grievance": f"{OPS}.grievance_query",
    "Goal": f"{OPS}.goal_query", "Appraisal": f"{OPS}.appraisal_query",
    "TLC People Ops Account": f"{OPS}.account_query", "TLC People Ops Acknowledgment": f"{OPS}.acknowledgment_query",
    "TLC People Ops Certificate": f"{OPS}.certificate_query", "TLC People Ops Benefit Claim": f"{OPS}.benefit_claim_query",
    "TLC People Ops Discipline": f"{OPS}.discipline_query", "TLC People Ops Health Appointment": f"{OPS}.health_query",
    "TLC Salary Review": f"{PCOM}.salary_review_query",
    # W6 internal services and anonymous surveys.
    "TLC Service Request": "tlc_hr.interface.services.service_request_query",
    "TLC Room Reservation": "tlc_hr.interface.services.room_reservation_query",
    "TLC Meal Enrollment": "tlc_hr.interface.services.meal_enrollment_query",
    "TLC Book Loan": "tlc_hr.interface.services.book_loan_query",
    "TLC Official Correspondence": "tlc_hr.interface.services.correspondence_query",
    "TLC Survey Campaign": "tlc_hr.interface.survey.permission_query",
}

has_permission = {
    "TLC Overtime Request": f"{OVERTIME}.has_permission", "TLC Attendance Period": f"{PERIOD}.period_has_permission",
    "Employee": f"{ROLE}.has_permission", "Attendance": f"{ROLE}.has_permission",
    "Shift Assignment": f"{ROLE}.has_permission", "Employee Checkin": f"{ROLE}.has_permission",
    "Attendance Request": f"{ROLE}.has_permission", "Leave Application": f"{ROLE}.has_permission",
    "Salary Slip": "tlc_hr.interface.payroll_permissions.has_permission",
    "Travel Request": f"{TRAVEL}.has_permission", "Employee Advance": f"{TRAVEL}.has_permission",
    "Expense Claim": f"{TRAVEL}.has_permission",
    "Asset Movement": f"{OPS}.scoped_permission",
    "Job Applicant": "tlc_hr.interface.recruitment_pipeline.guard_step_field", "Employee Grievance": f"{OPS}.scoped_permission",
    "Goal": f"{OPS}.scoped_permission", "Appraisal": f"{OPS}.scoped_permission",
    "TLC People Ops Account": f"{OPS}.scoped_permission", "TLC People Ops Acknowledgment": f"{OPS}.scoped_permission",
    "TLC People Ops Certificate": f"{OPS}.scoped_permission", "TLC People Ops Benefit Claim": f"{OPS}.scoped_permission",
    "TLC People Ops Discipline": f"{OPS}.scoped_permission", "TLC People Ops Health Appointment": f"{OPS}.scoped_permission",
    "TLC Salary Review": f"{PCOM}.salary_review_permission",
    "TLC Service Request": "tlc_hr.interface.services.has_permission",
    "TLC Room Reservation": "tlc_hr.interface.services.has_permission",
    "TLC Meal Enrollment": "tlc_hr.interface.services.has_permission",
    "TLC Book Loan": "tlc_hr.interface.services.has_permission",
    "TLC Official Correspondence": "tlc_hr.interface.services.has_permission",
    "TLC Service Catalog": "tlc_hr.interface.services.has_permission",
    "TLC Meeting Room": "tlc_hr.interface.services.has_permission",
    "TLC Library Book": "tlc_hr.interface.services.has_permission",
    "TLC Survey Campaign": "tlc_hr.interface.survey.has_permission",
}

override_doctype_class = {"Attendance Request": "tlc_hr.interface.travel_adjustments.TravelAttendanceRequest"}

scheduler_events = {
    "all": ["tlc_hr.interface.recruitment_pipeline.poll_mailpit"],
    "daily": [
        "tlc_hr.interface.organization.apply_due_changes",
        "tlc_hr.infrastructure.frappe.lifecycle.remind_expiries",
        "tlc_hr.interface.services.daily_reminders",
    ]
}

# The reason dialog of "Từ chối" for every TLC approval workflow on the desk.
# Frappe skips doctype_js for custom doctypes, so the scripts that also extend custom
# TLC doctypes (payroll decisions, people ops) are loaded desk-wide instead.
app_include_js = [
    "/assets/tlc_hr/js/tlc_workflow.js",
    "/assets/tlc_hr/js/payroll_decision.js",
    "/assets/tlc_hr/js/people_ops.js",
]

# TLC additions to standard forms (decision support, approval evidence, native completion actions).
doctype_js = {
    "Leave Application": "public/js/leave_application.js",
    "Payroll Entry": "public/js/payroll_entry.js",
    "Job Applicant": "public/js/recruitment_pipeline.js",
    "Employee Onboarding": "public/js/lifecycle_boarding.js",
    "Employee Separation": "public/js/lifecycle_boarding.js",
}

before_job = ["tlc_hr.interface.assistant.guard_job"]
app_home = "/desk/tlc-hr"


on_session_creation = ["tlc_hr.interface.role_navigation.on_session_creation"]
