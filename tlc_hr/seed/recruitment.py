"""Idempotent recruitment demo data; call after customizing and the base people seed."""

import frappe
from frappe.utils import add_days, nowdate


def run(data=None):
    company = "TLC Demo"
    employee = frappe.db.get_value("Employee", {"user_id": "quang@demo.example"},
                                   ["name", "department", "designation"], as_dict=True)
    if not employee:
        frappe.throw("Recruitment seed requires the TLC Demo people seed (quang@demo.example).")
    for source in ("LinkedIn", "VietnamWorks", "TopCV", "Facebook", "Internal Referral", "Headhunter", "Other"):
        if not frappe.db.exists("Job Applicant Source", source):
            frappe.get_doc({"doctype": "Job Applicant Source", "source_name": source}).insert(ignore_permissions=True)
    if not frappe.db.exists("Skill", "TLC Recruitment Communication"):
        frappe.get_doc({"doctype": "Skill", "skill_name": "TLC Recruitment Communication"}).insert(ignore_permissions=True)
    if not frappe.db.exists("Interview Type", "TLC Recruitment Final"):
        frappe.get_doc({"doctype": "Interview Type", "interview_type_name": "TLC Recruitment Final", "tlc_final_round": 1,
                        "expected_average_rating": 0.6,
                        "expected_skill_set": [{"skill": "TLC Recruitment Communication"}]}).insert(ignore_permissions=True)
    title = "TLC Recruitment Demo Vacancy"
    opening = frappe.db.get_value("Job Opening", {"job_title": title, "company": company})
    if not opening:
        opening = frappe.get_doc({
            "doctype": "Job Opening", "job_title": title, "designation": employee.designation,
            "company": company, "department": employee.department, "status": "Open", "vacancies": 2,
            "tlc_required": 2, "tlc_needed_by": add_days(nowdate(), 30),
            "description": "TLC demo recruitment vacancy; use native Desk interviews and offer workflow.",
            "route": "jobs/tlc-recruitment-demo", "prevent_duplicate_applicant": 0,
        }).insert(ignore_permissions=True).name
    applicants = []
    for index, email in enumerate(("recruitment.candidate@demo.example", "recruitment.alias@demo.example"), 1):
        applicant = frappe.db.get_value("Job Applicant", {"email_id": email, "job_title": opening})
        if not applicant:
            applicant = frappe.get_doc({
                "doctype": "Job Applicant", "applicant_name": "Ứng viên tuyển dụng TLC Demo", "email_id": email,
                "phone_number": "0912345678" if index == 1 else "+84 912 345 678",
                "tlc_identity": "TLC-DEMO-RECRUITMENT", "job_title": opening, "designation": employee.designation,
                "status": "Open", "source": "LinkedIn", "tlc_pipeline": "Final Interview",
            }).insert(ignore_permissions=True).name
        applicants.append(applicant)
    if not frappe.db.exists("Interview", {"job_applicant": applicants[0], "interview_type": "TLC Recruitment Final", "docstatus": 1}):
        interview = frappe.get_doc({
            "doctype": "Interview", "job_applicant": applicants[0], "job_opening": opening,
            "interview_type": "TLC Recruitment Final", "designation": employee.designation,
            "scheduled_on": nowdate(), "from_time": "09:00:00", "to_time": "10:00:00", "status": "Cleared",
            "interview_details": [{"interviewer": "hoa@demo.example"}],
        }).insert(ignore_permissions=True)
        interview.reload()  # native Time values after insert; avoids a false set-only-once change on submit
        interview.flags.ignore_permissions = True
        interview.submit()
    return {"opening": opening, "cleared_application": applicants[0], "uncleared_application": applicants[1]}


DEMO_APPLICANTS = ("recruitment.candidate@demo.example", "recruitment.alias@demo.example")


def _drop(doctype, names):
    for name in names:
        doc = frappe.get_doc(doctype, name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)


def reset():
    """Demo and UAT only: remove the recruitment records a UAT run creates, keeping seed master data."""
    if not frappe.conf.get("allow_tests") and not frappe.flags.in_test:
        frappe.throw("reset_recruitment runs only on a test site (site config allow_tests)")
    applicants = frappe.get_all("Job Applicant", filters={"email_id": ["in", DEMO_APPLICANTS]}, pluck="name")
    offers = frappe.get_all("Job Offer", filters={"job_applicant": ["in", applicants or [""]]}, pluck="name")
    offers += frappe.get_all("Job Offer", filters={"applicant_email": ["in", DEMO_APPLICANTS]}, pluck="name")
    offers = list(dict.fromkeys(offers))
    # Onboarding references the offer; drop it first so the offer can be deleted.
    _drop("Employee Onboarding", frappe.get_all("Employee Onboarding", filters={"job_offer": ["in", offers or [""]]}, pluck="name"))
    # An accepted offer refuses cancellation by design; this is demo data, so clear the acceptance flag first.
    for name in offers:
        frappe.db.set_value("Job Offer", name, "status", "Awaiting Response", update_modified=False)
    _drop("Job Offer", offers)
    _drop("Interview", frappe.get_all("Interview", filters={"job_applicant": ["in", applicants or [""]]}, pluck="name"))
    _drop("Job Applicant", applicants)
    # Re-open the demo vacancy at full headcount so the next run starts clean.
    for opening in frappe.get_all("Job Opening", filters={"job_title": "TLC Recruitment Demo Vacancy"}, fields=["name", "tlc_required", "vacancies"]):
        required = int(opening.tlc_required or opening.vacancies or 0)
        frappe.db.set_value("Job Opening", opening.name, {"tlc_accepted": 0, "tlc_remaining": required,
                                                          "tlc_progress": 0, "status": "Open", "closed_on": None})
    print("reset: recruitment offers, interviews, applicants and onboarding deleted")
    run()  # recreate the cleared/uncleared demo applications the journey starts from
