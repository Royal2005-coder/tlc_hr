"""Idempotent recruitment demo data; call after customizing and the base people seed."""

import json

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from tlc_hr.interface.recruitment_ai import TRACE, criteria_brief, profile_brief, verdict_of, weighted_score

STEP_ORDER = ("1. Tiếp nhận hồ sơ", "2. Đối chiếu tiêu chí", "3. Quyết định mời phỏng vấn",
              "4. Thư mời và lịch hẹn", "5. Phỏng vấn và quyết định offer", "6. Kết quả và lưu vết")
# The six criteria the assistant maps for the demo opening. Weights decide the score, so a seeded number can never
# drift away from the chart the way a hand-typed score could.
AI_CRITERIA = (
    ("Kinh nghiệm đúng lĩnh vực", "Kinh nghiệm", 5, 1),
    ("Chuyên môn phù hợp chức danh", "Chuyên môn", 4, 0),
    ("Kỹ năng công cụ (Excel, ERP, CRM)", "Kỹ năng", 3, 0),
    ("Ngoại ngữ", "Ngoại ngữ", 2, 0),
    ("Học vấn phù hợp", "Học vấn", 2, 0),
    ("Kinh nghiệm quản lý đội nhóm", "Thái độ", 3, 0),
)
AI_RISK = {
    "Đạt": "Không có rủi ro lớn; làm rõ thêm kết quả cụ thể của từng dự án.",
    "Cân nhắc": "Còn khoảng trống giữa kinh nghiệm thực tế và yêu cầu quản lý đội lớn.",
    "Không đạt": "Hồ sơ lệch yêu cầu chính của mô tả công việc.",
}
AI_QUESTIONS = ("Chị/anh mô tả một dự án tiêu biểu kèm số đo kết quả cụ thể?",
                "Khi dữ liệu hoặc lịch làm việc bị thiếu, chị/anh xử lý thế nào?",
                "Chị/anh dùng công cụ nào để báo cáo cho cấp trên?")
AI_LEDGER = (
    ("1. Tiếp nhận hồ sơ", "email.received", "Thư ứng tuyển tới hộp thư jobs (dữ liệu trình diễn)", "Mailpit"),
    ("1. Tiếp nhận hồ sơ", "candidate.created", "Tạo hồ sơ ứng viên từ hộp thư tuyển dụng", "Mailpit"),
    ("2. Đối chiếu tiêu chí", "ai.screening.queued", "Trợ lý nhận việc đối chiếu hồ sơ với mô tả công việc", "AI"),
    ("2. Đối chiếu tiêu chí", "ai.screening.running", "Trích thông tin cá nhân và quá trình làm việc từ CV", "AI"),
    ("2. Đối chiếu tiêu chí", "ai.profile.extracted", "{profile}", "AI"),
    ("2. Đối chiếu tiêu chí", "ai.criteria.matched", "{criteria}", "AI"),
    ("2. Đối chiếu tiêu chí", "ai.screening.done", "Hoàn tất đối chiếu, hồ sơ chờ người duyệt", "AI"),
    ("3. Quyết định mời phỏng vấn", "decision.invite", "HR quyết định mời phỏng vấn — quyết định của người, không phải của AI", "hoa@demo.example"),
    ("3. Quyết định mời phỏng vấn", "step.advanced", "2. Đối chiếu tiêu chí → 3. Quyết định mời phỏng vấn", "hoa@demo.example"),
    ("4. Thư mời và lịch hẹn", "email.drafted", "Soạn “Thư mời phỏng vấn” từ mẫu TLC Thư mời phỏng vấn", "hoa@demo.example"),
    ("4. Thư mời và lịch hẹn", "email.sent", "Thư mời đã gửi tới email ứng viên", "hoa@demo.example"),
    ("5. Phỏng vấn và quyết định offer", "interview.recorded", "Biên bản phỏng vấn và kết quả được ghi nhận", "hoa@demo.example"),
    ("5. Phỏng vấn và quyết định offer", "ai.interview.summarised", "Trợ lý đối chiếu biên bản với từng tiêu chí JD", "AI"),
    ("5. Phỏng vấn và quyết định offer", "interview.finalised", "Vòng cuối lưu trên phân hệ tuyển dụng native, trạng thái Cleared", "hoa@demo.example"),
    ("6. Kết quả và lưu vết", "offer.decided", "Giám đốc quyết định offer và ngày vào làm", "thanh@demo.example"),
    ("6. Kết quả và lưu vết", "pipeline.completed", "Bàn giao onboarding cho bộ phận Nhân sự", "hoa@demo.example"),
)

AI_OPENING = "TLC Tuyển dụng AI 6 bước (demo)"
AI_EMAILS = ("tran.minhanh@demo.example", "le.thuha@demo.example", "pham.quocbao@demo.example",
             "vo.ngoclan@demo.example", "dang.huuphuc@demo.example", "hoang.mai@demo.example")
AI_FIXTURES = (
    {"name": "Trần Minh Anh", "email": AI_EMAILS[0], "step": STEP_ORDER[0], "designation": "Analyst",
     "cv": "Trần Minh Anh - 5 năm phân tích dữ liệu bán hàng, SQL, Power BI, từng xây dashboard doanh số cho chuỗi bán lẻ.",
     "years": 5, "skills": ("SQL", "Power BI", "Excel"), "ratings": ("Đạt", "Đạt", "Đạt", "Một phần", "Đạt", "Thiếu"),
     "summary": "Hồ sơ mới tiếp nhận; kinh nghiệm phân tích dữ liệu bán hàng phù hợp khung vị trí Analyst.", "source": "LinkedIn"},
    {"name": "Lê Thu Hà", "email": AI_EMAILS[1], "step": STEP_ORDER[1], "designation": "Consultant",
     "cv": "Lê Thu Hà - 7 năm tư vấn giải pháp B2B, đàm phán hợp đồng, tiếng Anh C1, chứng chỉ quản lý dự án PMP.",
     "years": 7, "skills": ("Tư vấn B2B", "Đàm phán hợp đồng", "PMP"), "ratings": ("Đạt", "Đạt", "Đạt", "Đạt", "Đạt", "Một phần"),
     "summary": "Kinh nghiệm B2B vượt yêu cầu, tiếng Anh C1 và PMP phù hợp JD tư vấn.", "source": "TopCV"},
    {"name": "Phạm Quốc Bảo", "email": AI_EMAILS[2], "step": STEP_ORDER[1], "designation": "Engineer",
     "cv": "Phạm Quốc Bảo - 4 năm vận hành nhà máy, quen ISO 9001, ca đêm, chưa có kinh nghiệm quản lý đội 30 người.",
     "years": 4, "skills": ("ISO 9001", "Vận hành nhà máy"), "ratings": ("Một phần", "Đạt", "Đạt", "Thiếu", "Đạt", "Thiếu"),
     "summary": "Đáp ứng kỹ thuật vận hành nhưng thiếu kinh nghiệm quản lý đội lớn.", "source": "VietnamWorks"},
    {"name": "Võ Ngọc Lan", "email": AI_EMAILS[3], "step": STEP_ORDER[2], "designation": "Manager",
     "cv": "Võ Ngọc Lan - 9 năm quản lý bán hàng khu vực, đội 45 người, tăng trưởng 32% trong 2 năm, thành thạo CRM.",
     "years": 9, "skills": ("Quản lý bán hàng", "CRM"), "ratings": ("Đạt", "Đạt", "Đạt", "Đạt", "Đạt", "Đạt"),
     "summary": "Kinh nghiệm quản lý bán hàng khu vực rất sát JD, có thành tích tăng trưởng rõ ràng.", "source": "Headhunter"},
    {"name": "Đặng Hữu Phúc", "email": AI_EMAILS[4], "step": STEP_ORDER[4], "designation": "Executive Assistant",
     "cv": "Đặng Hữu Phúc - 6 năm hành chính - nhân sự, điều phối lịch họp ban lãnh đạo, thạo tiếng Anh giao tiếp.",
     "years": 6, "skills": ("Hành chính", "Điều phối lịch", "Tiếng Anh"), "ratings": ("Đạt", "Đạt", "Một phần", "Đạt", "Đạt", "Một phần"),
     "summary": "Phù hợp hỗ trợ điều hành, cần hỏi thêm về xử lý dữ liệu lương.", "source": "Facebook"},
    {"name": "Hoàng Mai", "email": AI_EMAILS[5], "step": STEP_ORDER[5], "designation": "Accountant",
     "cv": "Hoàng Mai - 8 năm kế toán tổng hợp, thuế TNCN, quyết toán năm, thành thạo MISA và Excel nâng cao.",
     "years": 8, "skills": ("Kế toán tổng hợp", "Thuế TNCN", "MISA", "Excel"), "ratings": ("Đạt", "Đạt", "Đạt", "Một phần", "Đạt", "Đạt"),
     "summary": "Đáp ứng toàn bộ tiêu chí kế toán, kinh nghiệm quyết toán thuế phù hợp.", "source": "Internal Referral",
     "salary": 28000000, "joining_offset": 21},
)


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


def fixture_criteria(ratings):
    """The criteria map of a demo file, in exactly the shape the assistant returns."""
    return [{"name": name, "group": group, "weight": weight, "must": must, "rating": rating,
             "evidence": ("Nêu rõ trong CV" if rating == "Đạt" else
                          "CV chỉ nêu một phần" if rating == "Một phần" else "Không thấy trong CV"),
             "note": "Dữ liệu trình diễn cho vòng sàng lọc."}
            for (name, group, weight, must), rating in zip(AI_CRITERIA, ratings)]


def fixture_profile(fixture):
    return {"full_name": fixture["name"], "email": fixture["email"], "phone": "0900000000", "location": "Hà Nội",
            "birth_date": "", "years_experience": fixture["years"], "current_role": fixture["designation"],
            "current_company": "Doanh nghiệp đối tác (dữ liệu trình diễn)", "expected_salary": "", "availability": "Trong 30 ngày",
            "education": [{"school": "Đại học (dữ liệu trình diễn)", "major": fixture["designation"], "degree": "Cử nhân", "year": ""}],
            "work": [{"company": "Doanh nghiệp đối tác", "role": fixture["designation"], "period": f"{fixture['years']} năm",
                      "highlight": fixture["cv"][:160]}],
            "skills": list(fixture["skills"]),
            "languages": [{"name": "Tiếng Việt", "level": "Bản ngữ"}, {"name": "Tiếng Anh", "level": "Giao tiếp"}],
            "certifications": [], "source": "seed-fixture"}


def ensure_ai_candidates(opening, employee):
    interviewer = frappe.db.get_value("Employee", {"user_id": "quang@demo.example"}, "name")
    for fixture in AI_FIXTURES:
        if frappe.db.exists("Job Applicant", {"email_id": fixture["email"]}):
            continue
        criteria = fixture_criteria(fixture["ratings"])
        score, missing = weighted_score(criteria)
        verdict = verdict_of(score, missing)
        profile = fixture_profile(fixture)
        doc = frappe.get_doc({
            "doctype": "Job Applicant", "applicant_name": fixture["name"], "email_id": fixture["email"],
            "phone_number": "0900000000", "job_title": opening, "designation": fixture["designation"],
            "status": "Open", "source": fixture["source"], "tlc_pipeline": "New",
            "tlc_step": fixture["step"], "tlc_step_owner": "hoa@demo.example",
            "tlc_intake_source": "Manual", "tlc_cv_text": fixture["cv"], "cover_letter": fixture["cv"],
        })
        if fixture["step"] != STEP_ORDER[0]:
            doc.update({"tlc_cv_profile": json.dumps(profile, ensure_ascii=False),
                        "tlc_jd_criteria": json.dumps(criteria, ensure_ascii=False),
                        "tlc_ai_status": "Đã chấm", "tlc_ai_score": score, "tlc_ai_match": score,
                        "tlc_ai_verdict": verdict, "tlc_ai_summary": fixture["summary"],
                        "tlc_ai_missing": chr(10).join(missing), "tlc_ai_risks": AI_RISK[verdict],
                        "tlc_ai_questions": chr(10).join(f"- {q}" for q in AI_QUESTIONS),
                        "tlc_ai_model": "seed-fixture", "tlc_ai_checked_on": add_days(now_datetime(), -6)})
        if fixture["step"] not in (STEP_ORDER[0], STEP_ORDER[1]):
            doc.update({"tlc_decision_by": "hoa@demo.example", "tlc_decision_on": add_days(now_datetime(), -4),
                        "tlc_decision_reason": "Điểm đối chiếu và kinh nghiệm thực tế phù hợp yêu cầu vị trí; "
                                               "mời phỏng vấn vòng 1."})
        if fixture["step"] in (STEP_ORDER[2], STEP_ORDER[3]):
            doc.update({"tlc_interviewer": interviewer, "tlc_interview_at": add_days(nowdate(), 3) + " 09:00:00"})
        if fixture["step"] in (STEP_ORDER[4], STEP_ORDER[5]):
            doc.update({"tlc_interviewer": interviewer, "tlc_interview_at": add_days(now_datetime(), -2),
                        "tlc_interview_notes": "Ứng viên trả lời tốt về quy trình hành chính; cần kiểm tra thêm tiếng Anh.",
                        "tlc_interview_result": "Pass",
                        "tlc_interview_summary": "Hội đồng đánh giá ứng viên nắm quy trình hành chính chắc; phần xử lý dữ liệu "
                                                 "lương cần kiểm tra thêm ở vòng sau.\n- Kinh nghiệm đúng lĩnh vực: Đạt"
                                                 "\n- Ngoại ngữ: Một phần"})
        doc.insert(ignore_permissions=True)
        from frappe.utils.file_manager import save_file
        cv_file = save_file(f"cv-{fixture['email'].split('@')[0]}.txt", fixture["cv"], "Job Applicant", doc.name, is_private=1)
        frappe.db.set_value("Job Applicant", doc.name, "resume_attachment", cv_file.file_url, update_modified=False)
        if fixture["step"] in (STEP_ORDER[4], STEP_ORDER[5]):
            ensure_final_interview(doc, opening)
        if fixture.get("salary"):
            offer = frappe.get_doc({
                "doctype": "Job Offer", "job_applicant": doc.name, "applicant_name": doc.applicant_name,
                "applicant_email": doc.email_id, "offer_date": nowdate(), "designation": doc.designation,
                "company": "TLC Demo", "status": "Awaiting Response",
                "tlc_department": employee.department, "tlc_salary": fixture["salary"],
                "tlc_joining_date": add_days(nowdate(), fixture["joining_offset"]), "tlc_work_mode": "Onsite",
                "tlc_offer_stage": "Draft",
            }).insert(ignore_permissions=True)
            frappe.db.set_value("Job Applicant", doc.name, "tlc_job_offer", offer.name, update_modified=False)
        ensure_traces(doc, profile, criteria, missing)


def ensure_final_interview(doc, opening):
    """The offer guard only trusts a submitted final round, so a demo file that reached step 5-6 has one on record."""
    name = frappe.db.get_value("Interview", {"job_applicant": doc.name, "interview_type": "TLC Recruitment Final"}, "name")
    if name:
        return name
    interview = frappe.get_doc({
        "doctype": "Interview", "job_applicant": doc.name, "job_opening": opening,
        "interview_type": "TLC Recruitment Final", "designation": doc.designation,
        "scheduled_on": add_days(nowdate(), -2), "from_time": "09:00:00", "to_time": "10:30:00",
        "status": "Cleared", "interview_summary": (doc.tlc_interview_notes or "")[:600],
        "interview_details": [{"interviewer": "quang@demo.example"}],
    }).insert(ignore_permissions=True)
    interview.reload()  # native Time values after insert; avoids a false set-only-once change on submit
    interview.flags.ignore_permissions = True
    interview.submit()
    return interview.name


def ensure_traces(doc, profile, criteria, missing):
    """Replay the story of a demo file so the ledger under the form reads like a live one, oldest event first."""
    from tlc_hr.interface.recruitment_ai import trace

    reached = STEP_ORDER.index(doc.tlc_step)
    brief = criteria_brief(criteria, doc.tlc_ai_score or 0, missing)
    rows = [row for row in AI_LEDGER if STEP_ORDER.index(row[0]) <= reached]
    total = len(rows)
    for index, (step, event, detail, actor) in enumerate(rows):
        trace(doc.name, event, detail.replace("{profile}", profile_brief(profile)).replace("{criteria}", brief),
              actor=actor, model="seed-fixture" if actor == "AI" else "",
              duration_ms=(900 + index * 170) if event.startswith("ai.") else 0, step=step,
              created_on=add_to_date(now_datetime(), hours=-(24 * (total - index))))
    frappe.db.commit()


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
    for log in frappe.get_all(TRACE, filters={"candidate": ["in", applicants or [""]]}, pluck="name"):
        frappe.delete_doc(TRACE, log, force=1, ignore_permissions=True)
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
    print("reset: recruitment offers, interviews, applicants, traces and onboarding deleted")
    run()  # recreate the cleared/uncleared demo applications the journey starts from
