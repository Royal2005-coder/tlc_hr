"""Native HRMS persistence. All writes participate in the caller's Frappe transaction."""

from hashlib import sha256

import frappe
from frappe.utils import getdate, nowdate

from tlc_hr.domain.recruitment import vacancy_progress


class FrappeRecruitmentRepository:
    def resolve_candidate(self, keys: tuple[tuple[str, str], ...], profile: dict) -> str:
        # A persistent metadata row serializes first sightings as well as merges until commit.
        frappe.db.sql("select name from tabDocType where name=%s for update", "TLC Recruitment Candidate")
        names = [sha256(f"{kind}:{value}".encode()).hexdigest() for kind, value in keys]
        matches = frappe.get_all("TLC Recruitment Identifier", filters={"name": ["in", names]},
                                 fields=["candidate"], order_by="creation asc, name asc")
        candidates = list(dict.fromkeys(row.candidate for row in matches))
        candidate = frappe.get_doc("TLC Recruitment Candidate", candidates[0]) if candidates else frappe.new_doc("TLC Recruitment Candidate")
        for field, value in profile.items():
            if value and not candidate.get(field):
                candidate.set(field, value)
        if candidate.is_new():
            candidate.insert(ignore_permissions=True)
        else:
            candidate.save(ignore_permissions=True)
        for other in candidates[1:]:
            old = frappe.get_doc("TLC Recruitment Candidate", other)
            for field in profile:
                if not candidate.get(field) and old.get(field):
                    candidate.set(field, old.get(field))
            for doctype, field in (("Job Applicant", "tlc_candidate"), ("TLC Recruitment Identifier", "candidate")):
                for record in frappe.get_all(doctype, filters={field: other}, pluck="name"):
                    frappe.db.set_value(doctype, record, field, candidate.name)
            old.merged_into = candidate.name
            old.save(ignore_permissions=True)
        if len(candidates) > 1:
            candidate.save(ignore_permissions=True)
        for name, (kind, value) in zip(names, keys, strict=True):
            if not frappe.db.exists("TLC Recruitment Identifier", name):
                frappe.get_doc({"doctype": "TLC Recruitment Identifier", "name": name,
                                "identifier_type": kind, "normalized_value": value,
                                "candidate": candidate.name}).insert(ignore_permissions=True)
        return candidate.name

    def has_final_round(self, application: str) -> bool:
        types = frappe.get_all("Interview Type", filters={"tlc_final_round": 1}, pluck="name")
        return bool(types and frappe.db.exists("Interview", {
            "job_applicant": application, "interview_type": ["in", types], "status": "Cleared", "docstatus": 1,
        }))

    def open_vacancies(self, requisition: str) -> list[str]:
        frappe.db.sql("select name from `tabJob Requisition` where name=%s for update", requisition)
        source = frappe.get_doc("Job Requisition", requisition)
        positions = source.get("tlc_positions") or [frappe._dict(
            name="primary", designation=source.designation, quantity=source.no_of_positions,
            department=source.department, location=source.get("tlc_location"))]
        result = []
        for position in positions:
            key = f"{source.name}:{position.name}"
            opening = frappe.db.get_value("Job Opening", {"tlc_position_key": key})
            if not opening:
                doc = frappe.get_doc({
                    "doctype": "Job Opening", "job_title": position.designation, "designation": position.designation,
                    "company": source.company, "department": position.department or source.department,
                    "location": position.location or source.get("tlc_location"), "status": "Open",
                    "job_requisition": source.name, "vacancies": position.quantity,
                    "tlc_required": position.quantity, "tlc_remaining": position.quantity,
                    "tlc_position_key": key, "tlc_needed_by": source.expected_by,
                    "tlc_jd": source.tlc_jd, "tlc_request_type": source.tlc_request_type,
                    "tlc_replaced_employee": source.get("tlc_replaced_employee"),
                    "tlc_reason": source.reason_for_requesting, "lower_range": source.expected_compensation,
                    "currency": frappe.db.get_value("Company", source.company, "default_currency"),
                    "description": source.description, "prevent_duplicate_applicant": 0,
                    "route": "jobs/tlc-" + sha256(key.encode()).hexdigest()[:20],
                }).insert(ignore_permissions=True)
                opening = doc.name
            result.append(opening)
        return result

    def accepted_count(self, opening: str, exclude: str = "") -> int:
        rows = frappe.db.sql(
            "select count(*) from `tabJob Offer` o inner join `tabJob Applicant` a on a.name=o.job_applicant "
            "where a.job_title=%s and o.status='Accepted' and o.docstatus=1 and o.name!=%s",
            (opening, exclude),
        )
        return int(rows[0][0])

    def lock_opening(self, opening: str) -> None:
        frappe.db.sql("select name from `tabJob Opening` where name=%s for update", opening)

    def refresh_opening(self, opening: str) -> None:
        self.lock_opening(opening)
        doc = frappe.get_doc("Job Opening", opening)
        accepted = self.accepted_count(opening)
        remaining, progress = vacancy_progress(int(doc.tlc_required or doc.vacancies or 0), accepted)
        values = {"tlc_accepted": accepted, "tlc_remaining": remaining, "tlc_progress": progress}
        if not remaining:
            values.update(status="Closed", closed_on=nowdate(), closes_on=None)
        frappe.db.set_value("Job Opening", opening, values)
        if doc.job_requisition:
            openings = frappe.get_all("Job Opening", filters={"job_requisition": doc.job_requisition},
                                      fields=["status", "tlc_remaining"])
            filled = all(row.status == "Closed" and not row.tlc_remaining for row in openings)
            frappe.db.set_value("Job Requisition", doc.job_requisition, {
                "status": "Filled" if filled else "Open & Approved", "completed_on": nowdate() if filled else None,
            })

    def accept_offer(self, offer: str) -> str:
        doc = frappe.get_doc("Job Offer", offer)
        # The offer row lock also serializes idempotent onboarding creation.
        frappe.db.sql("select name from `tabJob Offer` where name=%s for update", offer)
        existing = frappe.db.get_value("Employee Onboarding", {"job_offer": offer, "docstatus": ["!=", 2]})
        if not existing:
            existing = frappe.get_doc({
                "doctype": "Employee Onboarding", "job_offer": doc.name, "job_applicant": doc.job_applicant,
                "company": doc.company, "employee_name": doc.applicant_name, "department": doc.tlc_department,
                "designation": doc.designation, "employee_grade": doc.get("tlc_grade"),
                "date_of_joining": getdate(doc.tlc_joining_date), "boarding_begins_on": nowdate(),
                "boarding_status": "Pending",
            }).insert(ignore_permissions=True).name
        opening = frappe.db.get_value("Job Applicant", doc.job_applicant, "job_title")
        if opening:
            self.refresh_opening(opening)
        frappe.db.set_value("Job Applicant", doc.job_applicant, "tlc_pipeline", "Offer Accepted")
        return existing
