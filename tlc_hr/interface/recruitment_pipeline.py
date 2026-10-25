"""TonomyX six-step AI hiring pipeline on the native Job Applicant.

AI operates the intake and the criteria comparison (steps 1-2), but every step that commits the company (invitation,
interview outcome, offer, closure) is an explicit human decision recorded with its actor. A validate hook refuses step
edits made by dragging the Kanban or typing in the form: the gate actions below are the only way. Each action also
appends a line to TLC AI Trace Log, which the form renders as the activity ledger of the file.
"""

import json
import os
import re

import frappe
from frappe.utils import flt, format_datetime, get_datetime, getdate, now_datetime, nowdate

from tlc_hr.interface import recruitment_ai as ai

STEPS = (
    "1. Tiếp nhận hồ sơ",
    "2. Đối chiếu tiêu chí",
    "3. Quyết định mời phỏng vấn",
    "4. Thư mời và lịch hẹn",
    "5. Phỏng vấn và quyết định offer",
    "6. Kết quả và lưu vết",
)
REJECTED, TALENT = "Từ chối", "Talent Pool"
HR = {"TLC HR Lead", "TLC HR Officer", "System Manager"}
DIRECTOR = {"TLC Director", "System Manager"}
MODEL = ai.MODEL
INTERVIEW_TYPE = "TLC Recruitment Final"
NATIVE_STATUS = {"Pass": "Cleared", "Fail": "Rejected", "Hold": "Pending"}
TRACE = ai.TRACE
NATIVE_STAGE = {STEPS[0]: "New", STEPS[1]: "CV Screening", STEPS[2]: "HR Interview", STEPS[3]: "Technical Interview",
                STEPS[4]: "Final Interview", STEPS[5]: "Offer Accepted", REJECTED: "Rejected", TALENT: "Talent Pool"}


def _require(roles):
    if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(roles):
        frappe.throw("Bạn không có quyền thực hiện bước tuyển dụng này.", frappe.PermissionError)


def can_hr(roles=None):
    """The gate every whitelisted recruitment action passes through."""
    _require(roles or (HR | DIRECTOR))


def _file_text(url):
    if not url:
        return ""
    found = frappe.get_all("File", filters={"file_url": url}, fields=["name"], limit=1)
    if not found:
        return ""
    doc = frappe.get_doc("File", found[0].name)
    path = doc.get_full_path()
    if not path or not os.path.exists(path):
        return ""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md", ".csv"):
        return open(path, encoding="utf-8", errors="ignore").read()[:20000]
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)[:20000]
        except Exception:
            return ""
    if ext == ".docx":
        try:
            import docx
            return "\n".join(p.text for p in docx.Document(path).paragraphs)[:20000]
        except Exception:
            return ""
    return ""


def _cv_text(doc):
    text = _file_text(doc.resume_attachment) or _file_text(doc.resume_link) or doc.tlc_cv_text or ""
    return re.sub(r"\s+", " ", text).strip()[:12000]


def _save(doc, **values):
    for key, value in values.items():
        doc.set(key, value)
    frappe.flags.tlc_gate_ok = True
    try:
        doc.save()
    finally:
        frappe.flags.tlc_gate_ok = False


def _trace(doc, event, detail="", **kwargs):
    kwargs.setdefault("step", doc.tlc_step)
    ai.trace(doc.name, event, detail, **kwargs)


@frappe.whitelist()
def screen(name):
    """AI reads the CV and the job description, draws the score, and may move the file 1 -> 2 only."""
    _require(HR)
    doc = frappe.get_doc("Job Applicant", name)
    doc.check_permission("read")
    payload, fields, cv = _screen(doc, actor=frappe.session.user)
    step = STEPS[1] if (doc.tlc_step or STEPS[0]) == STEPS[0] else doc.tlc_step
    _save(doc, tlc_step=step, tlc_step_owner=frappe.session.user, tlc_cv_text=cv[:20000],
          tlc_pipeline=NATIVE_STAGE.get(step, doc.tlc_pipeline), **fields)
    _trace(doc, "ai.screening.done", f"Điểm {payload['score']}/100 · {payload['verdict']} · bước {step}",
           actor="AI", model=MODEL)
    frappe.db.commit()
    return {"name": doc.name, "score": payload["score"], "verdict": payload["verdict"], "step": step,
            "summary": payload["summary"], "questions": payload["questions"], "missing": payload["missing"]}


def _screen(doc, actor=None):
    """Steps 1-2 of the loop: extraction, weighted criteria, and the ledger lines in between."""
    cv = _cv_text(doc)
    if not cv:
        _trace(doc, "ai.screening.error", "Hồ sơ chưa có nội dung CV để chấm (đính kèm CV hoặc nhập CV text).",
               actor="AI", model=MODEL, status="error")
        frappe.db.commit()
        frappe.throw("Hồ sơ chưa có nội dung CV để chấm (đính kèm CV hoặc nhập CV text).")
    _save(doc, tlc_ai_status="Đang chấm")
    try:
        payload, fields = ai.run_screen(doc, cv, actor=actor)
    except Exception as exc:
        _save(doc, tlc_ai_status="Lỗi")
        _trace(doc, "ai.screening.error", f"Lỗi gọi trợ lý: {str(exc)[:500]}", actor="AI", model=MODEL, status="error")
        frappe.db.commit()
        raise
    _save(doc, **fields)
    return payload, fields, cv


def _payload(payload):
    if isinstance(payload, str):
        return json.loads(payload or "{}")
    return payload or {}


def record_final_round(doc):
    """Mirror the outcome in the native Interview, because the offer guard only trusts a submitted final round."""
    user = frappe.db.get_value("Employee", doc.tlc_interviewer, "user_id") if doc.tlc_interviewer else None
    existing = frappe.db.get_value("Interview", {"job_applicant": doc.name, "interview_type": INTERVIEW_TYPE},
                                  ["name", "docstatus"], as_dict=True)
    if existing and existing.docstatus == 1:
        return existing.name
    interview = frappe.get_doc("Interview", existing.name) if existing else frappe.new_doc("Interview")
    interview.update({
        "job_applicant": doc.name, "job_opening": doc.job_title, "interview_type": INTERVIEW_TYPE,
        "designation": doc.designation, "scheduled_on": getdate(doc.tlc_interview_at),
        "from_time": "09:00:00", "to_time": "10:30:00",
        "status": NATIVE_STATUS.get(doc.tlc_interview_result, "Pending"),
        "interview_summary": (doc.tlc_interview_notes or "")[:1500],
    })
    interview.set("interview_details", [])
    interview.append("interview_details", {"interviewer": user or frappe.session.user})
    if not existing:
        interview.insert(ignore_permissions=True)
    else:
        interview.save(ignore_permissions=True)
    interview.reload()  # native Time values after insert; avoids a false set-only-once change on submit
    interview.flags.ignore_permissions = True
    interview.submit()
    _trace(doc, "interview.finalised", f"Vòng cuối {interview.name} lưu trên phân hệ tuyển dụng native, trạng thái "
                                       f"{interview.status}", actor=frappe.session.user)
    return interview.name


@frappe.whitelist(methods=["POST"])
def advance(name, action, payload=None):
    """The only way a hiring step moves: each action checks its gate and records the human actor."""
    can_hr()
    doc = frappe.get_doc("Job Applicant", name)
    doc.check_permission("read")
    values = _payload(payload)
    step = doc.tlc_step or STEPS[0]
    reason = (values.get("reason") or "").strip()
    if action == "invite":
        if step not in (STEPS[1], STEPS[2]):
            frappe.throw(f"Chỉ mời phỏng vấn từ bước 2 (đang ở {step}).")
        if doc.tlc_ai_status != "Đã chấm":
            frappe.throw("AI phải chấm CV xong trước khi người duyệt quyết định mời phỏng vấn.")
        if doc.tlc_ai_verdict == "Không đạt" and not set(frappe.get_roles()) & DIRECTOR:
            frappe.throw("AI đánh giá Không đạt: cần Giám đốc bỏ qua có lý do.")
        if doc.tlc_ai_missing and not reason:
            frappe.throw("Hồ sơ còn thiếu tiêu chí bắt buộc: người duyệt phải ghi lý do.")
        if not values.get("interviewer") or not values.get("interview_at"):
            frappe.throw("Cần chọn người phỏng vấn và thời gian phỏng vấn.")
        _save(doc, tlc_step=STEPS[2], tlc_interviewer=values["interviewer"],
              tlc_interview_at=get_datetime(values["interview_at"]), tlc_decision_by=frappe.session.user,
              tlc_decision_on=now_datetime(), tlc_decision_reason=reason, tlc_step_owner=frappe.session.user,
              tlc_pipeline=NATIVE_STAGE[STEPS[2]])
        _trace(doc, "decision.invite", f"{frappe.session.user} quyết định mời phỏng vấn {values['interview_at']} "
                                       f"(cùng người phỏng vấn {values['interviewer']}). Lý do: {reason}",
               actor=frappe.session.user)
        _trace(doc, "step.advanced", f"{step} → {STEPS[2]}", actor=frappe.session.user)
    elif action == "invitation":
        if step != STEPS[2]:
            frappe.throw(f"Thư mời chỉ gửi từ bước 3 (đang ở {step}).")
        if not doc.tlc_interview_at or not doc.tlc_interviewer:
            frappe.throw("Chưa có lịch và người phỏng vấn.")
        if not doc.email_id:
            frappe.throw("Hồ sơ thiếu email để gửi thư mời.")
        if not values.get("communication"):
            # HR did not open the composer (an API or scheduled send): render the same approved template and queue it.
            letter = ai.compose(doc.name, "invitation")
            frappe.flags.tlc_no_advance = True
            try:
                frappe.sendmail(recipients=[doc.email_id], subject=letter["subject"], message=letter["message"],
                                reference_doctype="Job Applicant", reference_name=doc.name, now=True)
            finally:
                frappe.flags.tlc_no_advance = False
        _save(doc, tlc_step=STEPS[3], tlc_decision_by=frappe.session.user, tlc_decision_on=now_datetime(),
              tlc_step_owner=frappe.session.user, tlc_pipeline=NATIVE_STAGE[STEPS[3]])
        _trace(doc, "step.advanced", f"{step} → {STEPS[3]} · thư mời đã gửi tới {doc.email_id} cho "
                                     f"{format_datetime(doc.tlc_interview_at, 'dd/MM/yyyy HH:mm')}",
               actor=frappe.session.user)
    elif action == "interview":
        if step != STEPS[3]:
            frappe.throw(f"Ghi nhận phỏng vấn từ bước 4 (đang ở {step}).")
        if not (values.get("interview_notes") or "").strip() or values.get("interview_result") not in ("Pass", "Fail", "Hold"):
            frappe.throw("Cần ghi biên bản và kết quả phỏng vấn (Pass/Fail/Hold).")
        _save(doc, tlc_step=STEPS[4], tlc_interview_notes=values["interview_notes"][:5000],
              tlc_interview_result=values["interview_result"], tlc_decision_by=frappe.session.user,
              tlc_decision_on=now_datetime(), tlc_decision_reason=reason, tlc_step_owner=frappe.session.user,
              tlc_pipeline=NATIVE_STAGE[STEPS[4]])
        _trace(doc, "interview.recorded", f"Kết quả {values['interview_result']}. Biên bản: {values['interview_notes'][:600]}"
                                          + (f" Lý do: {reason}" if reason else ""), actor=frappe.session.user)
        record_final_round(doc)
        _trace(doc, "step.advanced", f"{step} → {STEPS[4]}", actor=frappe.session.user)
    elif action == "offer":
        if step != STEPS[4]:
            frappe.throw(f"Quyết định offer từ bước 5 (đang ở {step}).")
        if not set(frappe.get_roles()) & DIRECTOR:
            frappe.throw("Chỉ Giám đốc quyết định offer.", frappe.PermissionError)
        if doc.tlc_interview_result != "Pass" and not reason:
            frappe.throw("Kết quả phỏng vấn chưa Pass: Giám đốc phải ghi lý do bỏ qua.")
        if not values.get("salary") or not values.get("joining_date"):
            frappe.throw("Cần mức lương và ngày vào làm trong quyết định offer.")
        offer = frappe.get_doc("Job Offer", doc.tlc_job_offer) if doc.tlc_job_offer else None
        if not offer:
            department = values.get("department") or frappe.db.get_value("Employee", {"user_id": doc.email_id}, "department")
            offer = frappe.get_doc({
                "doctype": "Job Offer", "job_applicant": doc.name, "applicant_name": doc.applicant_name,
                "applicant_email": doc.email_id, "offer_date": nowdate(),
                "designation": values.get("designation") or doc.designation or "Nhân viên",
                "company": "TLC Demo", "status": "Awaiting Response",
                "tlc_department": department, "tlc_salary": flt(values["salary"]),
                "tlc_joining_date": getdate(values["joining_date"]), "tlc_work_mode": "Onsite",
                "tlc_offer_stage": "Draft",
            }).insert(ignore_permissions=True)
        _save(doc, tlc_step=STEPS[5], tlc_job_offer=offer.name, tlc_decision_by=frappe.session.user,
              tlc_decision_on=now_datetime(), tlc_decision_reason=reason, tlc_step_owner=frappe.session.user,
              tlc_pipeline=NATIVE_STAGE[STEPS[5]], status="Accepted")
        _trace(doc, "offer.decided", f"Giám đốc quyết định offer {offer.name}: {flt(values['salary']):,.0f} VND, "
                                     f"vào làm {values['joining_date']}. " + (reason or ""), actor=frappe.session.user)
        _trace(doc, "step.advanced", f"{step} → {STEPS[5]}", actor=frappe.session.user)
    elif action == "complete":
        if step != STEPS[5]:
            frappe.throw(f"Hoàn tất từ bước 6 (đang ở {step}).")
        if not doc.tlc_job_offer:
            frappe.throw("Chưa có Job Offer để bàn giao onboarding.")
        offer = frappe.get_doc("Job Offer", doc.tlc_job_offer)
        joining = offer.tlc_joining_date or offer.offer_date
        onboarding = frappe.get_doc({
            "doctype": "Employee Onboarding", "job_offer": offer.name, "company": offer.company,
            "date_of_joining": joining, "boarding_begins_on": joining,
        }).insert(ignore_permissions=True)
        todo = frappe.get_doc({"doctype": "ToDo", "allocated_to": "hoa@demo.example", "status": "Open",
                               "date": nowdate(), "priority": "High",
                               "description": f"Vào việc {doc.applicant_name} ({doc.name}) — hoàn tất Employee Onboarding "
                                              f"{onboarding.name} từ offer {offer.name}."}).insert(ignore_permissions=True)
        _save(doc, tlc_decision_by=frappe.session.user, tlc_decision_on=now_datetime(),
              tlc_step_owner=frappe.session.user, tlc_pipeline="Joined", status="Accepted")
        _trace(doc, "pipeline.completed", f"Bàn giao Employee Onboarding {onboarding.name} và ToDo {todo.name} từ offer "
                                          f"{offer.name}", actor=frappe.session.user)
    elif action in ("reject", "talent"):
        target = REJECTED if action == "reject" else TALENT
        if not reason:
            frappe.throw("Ghi lý do trước khi kết thúc hồ sơ.")
        _save(doc, tlc_step=target, tlc_decision_by=frappe.session.user, tlc_decision_on=now_datetime(),
              tlc_decision_reason=reason, tlc_step_owner=frappe.session.user,
              tlc_pipeline=NATIVE_STAGE[target], status="Rejected" if action == "reject" else doc.status)
        _trace(doc, "candidate.rejected" if action == "reject" else "candidate.talent_pool", reason,
               actor=frappe.session.user, step=target)
    else:
        frappe.throw(f"Hành động tuyển dụng không hỗ trợ: {action}")
    frappe.db.commit()
    doc.reload()
    return {"name": doc.name, "step": doc.tlc_step, "pipeline": doc.tlc_pipeline}


def guard_step_field(doc=None, user=None, permission_type=None):
    """The Kanban drag and generic set_value calls cannot move the step; only advance() can."""
    if permission_type != "write":
        return True
    form = frappe.form_dict or {}
    fieldname = form.get("fieldname")
    if isinstance(fieldname, (list, tuple)):
        fieldname = "tlc_step" if "tlc_step" in fieldname else None
    if form.get("doctype") in (None, "Job Applicant") and fieldname == "tlc_step":
        frappe.throw("Bước tuyển dụng chỉ chuyển bằng hành động trên hồ sơ (AI vận hành, người quyết định).", frappe.PermissionError)
    return True


def validate_applicant(doc, method=None):
    """Kanban drags and form edits cannot move the step; only the gate actions can."""
    before = doc.get_doc_before_save()
    if before and before.tlc_step != doc.tlc_step and not frappe.flags.get("tlc_gate_ok"):
        frappe.throw("Chuyển bước tuyển dụng phải bấm hành động trên form (AI vận hành, người quyết định).", frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def intake_now():
    """HR pulls the hiring mailbox now (Mailpit API) instead of waiting for the scheduler tick."""
    _require(HR)
    return poll_mailpit()


def _mailpit():
    import requests
    base = os.environ.get("MAILPIT_URL", "http://mailpit:8025").rstrip("/")
    return base, requests


def poll_mailpit():
    """Turn new CV e-mails into step-1 applicants, then let the AI compare them with the job description."""
    try:
        base, requests = _mailpit()
        listing = requests.get(f"{base}/api/v1/messages", timeout=15).json()
    except Exception as exc:
        print(f"recruitment intake skipped: {exc}", flush=True)
        return {"queued": 0, "reason": "mailpit-unreachable"}
    jobs_address = (frappe.db.get_value("Email Account", {"name": "Jobs"}, "email_id") or "jobs@demo.example").lower()
    created = []
    for row in (listing.get("messages") or [])[:60]:
        message_id = row.get("ID")
        if not message_id or ai.seen(message_id):
            continue
        try:
            detail = requests.get(f"{base}/api/v1/message/{message_id}", timeout=15).json()
        except Exception:
            continue
        recipients = ", ".join(
            f"{(item or {}).get('Address', '')}" for item in (detail.get("To") or []) + (detail.get("Cc") or [])
        ).lower()
        subject = (detail.get("Subject") or "").lower()
        if jobs_address not in recipients and "ứng tuyển" not in subject and "cv" not in subject:
            continue
        sender = detail.get("From") or {}
        email = (sender.get("Address") or "").strip().lower()
        name = (sender.get("Name") or email.split("@")[0] or "Ứng viên").strip()
        if not email or "@" not in email:
            continue
        existing = frappe.db.get_value("Job Applicant", {"email_id": email}, "name")
        opening = (frappe.db.get_value("Job Opening", {"status": "Open", "job_title": "TLC Tuyển dụng AI 6 bước (demo)"}, "name")
                   or frappe.db.get_value("Job Opening", {"status": "Open"}, "name", order_by="modified desc"))
        if existing:
            ai.trace(existing, "email.received", f"Thư bổ sung: {(detail.get('Subject') or '')[:200]} — người gửi {email}",
                     actor="Mailpit", message_id=message_id)
            frappe.db.commit()
            continue
        applicant = frappe.get_doc({
            "doctype": "Job Applicant", "applicant_name": name, "email_id": email,
            "job_title": opening, "designation": frappe.db.get_value("Job Opening", opening, "designation") if opening else None,
            "status": "Open", "source": "Other", "tlc_pipeline": "New", "tlc_step": STEPS[0],
            "tlc_intake_source": "Email", "tlc_intake_message": message_id,
            "cover_letter": (detail.get("Text") or "")[:5000],
        }).insert(ignore_permissions=True)
        ai.trace(applicant.name, "email.received", f"Thư ứng tuyển từ {name} <{email}>: {(detail.get('Subject') or '')[:200]}",
                 actor="Mailpit", message_id=message_id, step=STEPS[0])
        ai.trace(applicant.name, "candidate.created", f"Tạo hồ sơ {applicant.name} từ hộp thư jobs, nguồn Email",
                 actor="Mailpit", step=STEPS[0])
        for attachment in detail.get("Attachments") or []:
            filename = attachment.get("FileName") or "cv.pdf"
            if not re.search(r"\.(pdf|docx?|txt|md)$", filename, re.I):
                continue
            part = requests.get(f"{base}/api/v1/message/{message_id}/part/{attachment.get('PartID')}", timeout=30)
            if not part.ok:
                continue
            file_doc = frappe.get_doc({"doctype": "File", "file_name": filename, "is_private": 1,
                                       "attached_to_doctype": "Job Applicant", "attached_to_name": applicant.name,
                                       "content": part.content}).insert(ignore_permissions=True)
            applicant.db_set("resume_attachment", file_doc.file_url, update_modified=False)
        frappe.db.commit()
        try:
            _screen(applicant, actor="Mailpit")
            ai.trace(applicant.name, "ai.screening.done",
                     f"Điểm {applicant.tlc_ai_score}/100 · {applicant.tlc_ai_verdict} · bước "
                     f"{STEPS[1] if applicant.tlc_step == STEPS[0] else applicant.tlc_step}",
                     actor="AI", model=MODEL)
            if applicant.tlc_step == STEPS[0]:
                _save(applicant, tlc_step=STEPS[1], tlc_pipeline=NATIVE_STAGE[STEPS[1]])
                ai.trace(applicant.name, "step.advanced", f"{STEPS[0]} → {STEPS[1]} do AI đối chiếu xong",
                         actor="AI", model=MODEL)
        except Exception as exc:
            ai.trace(applicant.name, "ai.screening.error", f"AI lỗi: {str(exc)[:400]}", actor="AI", model=MODEL, status="error")
        frappe.db.commit()
        created.append(applicant.name)
    frappe.db.commit()
    return {"queued": len(created), "applicants": created}


def setup_board():
    """Idempotent: the six-step Kanban board used by the recruitment workspace."""
    name = "TLC Tuyển dụng 6 bước"
    if frappe.db.exists("Kanban Board", name):
        return name
    frappe.get_doc({"doctype": "Kanban Board", "kanban_board_name": name, "reference_doctype": "Job Applicant",
                    "field_name": "tlc_step", "title_field": "applicant_name", "show_labels": 1,
                    "private": 0}).insert(ignore_permissions=True)
    frappe.db.commit()
    return name
