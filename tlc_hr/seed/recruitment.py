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
    ai_opening = ensure_ai_opening(employee, company)
    ensure_ai_candidates(ai_opening, employee)
    return {"opening": opening, "cleared_application": applicants[0], "uncleared_application": applicants[1],
            "ai_opening": ai_opening}


AI_OPENING = "TLC Tuyển dụng AI 6 bước (demo)"
AI_EMAILS = ("tran.minhanh@demo.example", "le.thuha@demo.example", "pham.quocbao@demo.example",
             "vo.ngoclan@demo.example", "dang.huuphuc@demo.example", "hoang.mai@demo.example")
AI_FIXTURES = (
    {"name": "Trần Minh Anh", "email": AI_EMAILS[0], "step": "1. Tiếp nhận hồ sơ", "designation": "Analyst",
     "cv": "Trần Minh Anh - 5 năm phân tích dữ liệu bán hàng, SQL, Power BI, từng xây dashboard doanh số cho chuỗi bán lẻ.",
     "score": None, "verdict": "", "summary": "", "source": "LinkedIn"},
    {"name": "Lê Thu Hà", "email": AI_EMAILS[1], "step": "2. Đối chiếu tiêu chí", "designation": "Consultant",
     "cv": "Lê Thu Hà - 7 năm tư vấn giải pháp B2B, đàm phán hợp đồng, tiếng Anh C1, chứng chỉ quản lý dự án PMP.",
     "score": 84, "verdict": "Đạt", "summary": "Kinh nghiệm B2B vượt yêu cầu, tiếng Anh C1 và PMP phù hợp JD tư vấn.", "source": "TopCV"},
    {"name": "Phạm Quốc Bảo", "email": AI_EMAILS[2], "step": "2. Đối chiếu tiêu chí", "designation": "Engineer",
     "cv": "Phạm Quốc Bảo - 4 năm vận hành nhà máy, quen ISO 9001, ca đêm, chưa có kinh nghiệm quản lý đội 30 người.",
     "score": 58, "verdict": "Cân nhắc", "summary": "Đáp ứng kỹ thuật vận hành nhưng thiếu kinh nghiệm quản lý đội lớn.", "source": "VietnamWorks"},
    {"name": "Võ Ngọc Lan", "email": AI_EMAILS[3], "step": "3. Quyết định mời phỏng vấn", "designation": "Manager",
     "cv": "Võ Ngọc Lan - 9 năm quản lý bán hàng khu vực, đội 45 người, tăng trưởng 32% trong 2 năm, thành thạo CRM.",
     "score": 91, "verdict": "Đạt", "summary": "Kinh nghiệm quản lý bán hàng khu vực rất sát JD, có thành tích tăng trưởng rõ ràng.", "source": "Headhunter"},
    {"name": "Đặng Hữu Phúc", "email": AI_EMAILS[4], "step": "5. Phỏng vấn và quyết định offer", "designation": "Executive Assistant",
     "cv": "Đặng Hữu Phúc - 6 năm hành chính - nhân sự, điều phối lịch họp ban lãnh đạo, thạo tiếng Anh giao tiếp.",
     "score": 78, "verdict": "Đạt", "summary": "Phù hợp hỗ trợ điều hành, cần hỏi thêm về xử lý dữ liệu lương.", "source": "Facebook"},
    {"name": "Hoàng Mai", "email": AI_EMAILS[5], "step": "6. Kết quả và lưu vết", "designation": "Accountant",
     "cv": "Hoàng Mai - 8 năm kế toán tổng hợp, thuế TNCN, quyết toán năm, thành thạo MISA và Excel nâng cao.",
     "score": 88, "verdict": "Đạt", "summary": "Đáp ứng toàn bộ tiêu chí kế toán, kinh nghiệm quyết toán thuế phù hợp.", "source": "Internal Referral"},
)


def ensure_ai_opening(employee, company):
    opening = frappe.db.get_value("Job Opening", {"job_title": AI_OPENING, "company": company})
    if opening:
        return opening
    return frappe.get_doc({
        "doctype": "Job Opening", "job_title": AI_OPENING, "designation": employee.designation,
        "company": company, "department": employee.department, "status": "Open", "vacancies": 3,
        "tlc_required": 3, "tlc_needed_by": add_days(nowdate(), 30),
        "description": ("Tuyển dụng AI 6 bước của TLC: vị trí Kinh doanh (HR-SALES), Vận hành (HR-OPS), ESG (HR-ESG). "
                        "AI đối chiếu CV với JD; con người quyết định mời phỏng vấn, kết quả và offer."),
        "route": "jobs/tlc-ai-recruitment-demo", "prevent_duplicate_applicant": 0,
    }).insert(ignore_permissions=True).name


def ensure_ai_candidates(opening, employee):
    interviewer = frappe.db.get_value("Employee", {"user_id": "quang@demo.example"}, "name")
    for fixture in AI_FIXTURES:
        if frappe.db.exists("Job Applicant", {"email_id": fixture["email"]}):
            continue
        doc = frappe.get_doc({
            "doctype": "Job Applicant", "applicant_name": fixture["name"], "email_id": fixture["email"],
            "phone_number": "0900000000", "job_title": opening, "designation": fixture["designation"],
            "status": "Open", "source": fixture["source"], "tlc_pipeline": "New",
            "tlc_step": fixture["step"], "tlc_step_owner": "hoa@demo.example",
            "tlc_intake_source": "Manual", "tlc_cv_text": fixture["cv"],
            "cover_letter": fixture["cv"],
        })
        if fixture["score"] is not None:
            doc.tlc_ai_status = "Đã chấm"
            doc.tlc_ai_score = fixture["score"]
            doc.tlc_ai_verdict = fixture["verdict"]
            doc.tlc_ai_summary = fixture["summary"]
            doc.tlc_ai_model = "seed-fixture"
            doc.tlc_ai_checked_on = nowdate()
        if fixture["step"] not in ("1. Tiếp nhận hồ sơ", "2. Đối chiếu tiêu chí"):
            doc.tlc_decision_by = "hoa@demo.example"
            doc.tlc_decision_on = nowdate()
            doc.tlc_decision_reason = "Quyết định mẫu cho UAT (dữ liệu hư cấu)."
        if fixture["step"] == "3. Quyết định mời phỏng vấn":
            doc.tlc_interviewer = interviewer
            doc.tlc_interview_at = add_days(nowdate(), 3) + " 09:00:00"
        if fixture["step"] == "5. Phỏng vấn và quyết định offer":
            doc.tlc_interviewer = interviewer
            doc.tlc_interview_at = add_days(nowdate(), -2) + " 09:00:00"
            doc.tlc_interview_notes = "Ứng viên trả lời tốt về quy trình hành chính; cần kiểm tra thêm tiếng Anh."
            doc.tlc_interview_result = "Pass"
        doc.insert(ignore_permissions=True)
        from frappe.utils.file_manager import save_file
        cv_file = save_file(f"cv-{fixture['email'].split('@')[0]}.txt", fixture["cv"], "Job Applicant", doc.name, is_private=1)
        frappe.db.set_value("Job Applicant", doc.name, "resume_attachment", cv_file.file_url, update_modified=False)


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
    emails = tuple(DEMO_APPLICANTS) + tuple(AI_EMAILS)
    applicants = frappe.get_all("Job Applicant", filters={"email_id": ["in", emails]}, pluck="name")
    for log in frappe.get_all("TLC Recruitment AI Log", filters={"applicant": ["in", applicants or [""]]}, pluck="name"):
        frappe.delete_doc("TLC Recruitment AI Log", log, force=1, ignore_permissions=True)
    offers = frappe.get_all("Job Offer", filters={"job_applicant": ["in", applicants or [""]]}, pluck="name")
    offers += frappe.get_all("Job Offer", filters={"applicant_email": ["in", emails]}, pluck="name")
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
    for opening in frappe.get_all("Job Opening", filters={"job_title": ["in", ["TLC Recruitment Demo Vacancy", AI_OPENING]]}, fields=["name", "tlc_required", "vacancies"]):
        required = int(opening.tlc_required or opening.vacancies or 0)
        frappe.db.set_value("Job Opening", opening.name, {"tlc_accepted": 0, "tlc_remaining": required,
                                                          "tlc_progress": 0, "status": "Open", "closed_on": None})
    print("reset: recruitment offers, interviews, applicants and onboarding deleted")
    run()  # recreate the cleared/uncleared demo applications the journey starts from
