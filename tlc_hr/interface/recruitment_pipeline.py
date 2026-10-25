"""TonomyX six-step AI hiring pipeline on the native Job Applicant.

AI operates the intake and the criteria comparison (steps 1-2), but every step that
commits the company (invitation, interview outcome, offer, closure) is an explicit
human decision recorded with its actor. A validate hook refuses step edits made by
dragging the Kanban or typing in the form: the gate actions below are the only way.
"""

import json
import os
import re

import frappe
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime, nowdate, strip_html, today

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
MODEL = "ministral-14b-latest"
LOG = "TLC Recruitment AI Log"
NATIVE_STAGE = {STEPS[0]: "New", STEPS[1]: "CV Screening", STEPS[2]: "HR Interview", STEPS[3]: "Technical Interview",
                STEPS[4]: "Final Interview", STEPS[5]: "Offer Accepted", REJECTED: "Rejected", TALENT: "Talent Pool"}
SYSTEM = (
    "Bạn là trợ lý sàng lọc tuyển dụng của TLC. Chỉ đánh giá hồ sơ so với JD, không quyết định tuyển dụng, "
    "không suy diễn thông tin không có trong CV. Trả về JSON đúng các khóa: score (số nguyên 0-100), "
    "verdict (một trong Đạt, Cân nhắc, Không đạt), summary (2-3 câu tiếng Việt), "
    "risks (các điểm cần hỏi lại, tiếng Việt), questions (mảng 3-5 câu hỏi phỏng vấn tiếng Việt)."
)


def _require(roles):
    if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(roles):
        frappe.throw("Bạn không có quyền thực hiện bước tuyển dụng này.", frappe.PermissionError)


def _log(applicant, action, detail="", model="", score=None, verdict="", message_id=""):
    frappe.get_doc({"doctype": LOG, "applicant": applicant, "action": action, "actor": frappe.session.user,
                    "model": model, "score": score, "verdict": verdict, "detail": detail,
                    "message_id": message_id}).insert(ignore_permissions=True)


def _jd_text(doc):
    parts = []
    if doc.job_title:
        opening = frappe.db.get_value("Job Opening", doc.job_title, ["description", "designation"], as_dict=True)
        if opening:
            parts.append(strip_html(opening.description or ""))
            if opening.designation:
                parts.append(f"Chức danh: {opening.designation}")
    for field in ("tlc_education", "tlc_experience"):
        if doc.get(field):
            parts.append(str(doc.get(field)))
    return "\n".join(parts)[:8000]


def _file_text(url):
    if not url:
        return ""
    file = frappe.get_all("File", filters={"file_url": url}, fields=["name"], limit=1)
    if not file:
        return ""
    doc = frappe.get_doc("File", file[0].name)
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


def _chat_json(system, user):
    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not key:
        frappe.throw("Thiếu MISTRAL_API_KEY trong pod; không thể chấm CV.")
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url="https://api.mistral.ai/v1")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    raw = ""
    for use_json_mode in (True, False):
        try:
            kwargs = {"model": MODEL, "temperature": 0.1, "max_tokens": 1300, "messages": messages}
            if use_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            raw = (client.chat.completions.create(**kwargs).choices[0].message.content or "").strip()
        except Exception:
            if use_json_mode:
                continue
            raise
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.S)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        messages = messages + [{"role": "assistant", "content": raw},
                               {"role": "user", "content": "Chỉ trả lại đúng một JSON hợp lệ với các khóa score, verdict, summary, risks, questions. Không thêm chữ nào khác."}]
    frappe.throw("Trợ lý không trả JSON hợp lệ; thử lại hoặc kiểm tra hồ sơ.", frappe.ValidationError)


def _save(doc, **values):
    for key, value in values.items():
        doc.set(key, value)
    frappe.flags.tlc_gate_ok = True
    try:
        doc.save()
    finally:
        frappe.flags.tlc_gate_ok = False


@frappe.whitelist()
def screen(name):
    """AI reads the JD and the CV and writes an advisory score; it may move 1 -> 2 only."""
    _require(HR)
    doc = frappe.get_doc("Job Applicant", name)
    doc.check_permission("read")
    cv = _cv_text(doc)
    if not cv:
        frappe.throw("Hồ sơ chưa có nội dung CV để chấm (đính kèm CV hoặc nhập CV text).")
    doc.db_set({"tlc_ai_status": "Đang chấm"}, commit=False)
    frappe.db.commit()
    try:
        result = _chat_json(SYSTEM, f"Vị trí ứng tuyển: {doc.job_title or doc.designation or '(chưa chọn)'}\n"
                                    f"Mô tả/JD:\n{_jd_text(doc)}\n\nCV ứng viên:\n{cv}")
    except Exception as exc:
        doc.db_set({"tlc_ai_status": "Lỗi"}, commit=False)
        frappe.db.commit()
        _log(doc.name, "Screen", f"Lỗi gọi trợ lý: {str(exc)[:500]}", MODEL)
        frappe.db.commit()
        raise
    score = max(0, min(100, flt(result.get("score"))))
    verdict = result.get("verdict") if result.get("verdict") in ("Đạt", "Cân nhắc", "Không đạt") else "Cân nhắc"
    questions = result.get("questions") or []
    if isinstance(questions, list):
        questions = "\n".join(f"- {q}" for q in questions)
    step = doc.tlc_step or STEPS[0]
    if step == STEPS[0]:
        step = STEPS[1]
    _save(doc, tlc_ai_status="Đã chấm", tlc_ai_score=score, tlc_ai_verdict=verdict,
          tlc_ai_summary=_as_text(result.get("summary"))[:2000], tlc_ai_risks=_as_text(result.get("risks"))[:2000],
          tlc_ai_questions=questions[:4000], tlc_ai_model=MODEL, tlc_ai_checked_on=now_datetime(),
          tlc_cv_text=cv[:20000], tlc_step=step, tlc_step_owner=frappe.session.user,
          tlc_pipeline=NATIVE_STAGE.get(step, doc.tlc_pipeline))
    _log(doc.name, "Screen", _ai_detail(result, score, verdict), MODEL, score, verdict)
    frappe.db.commit()
    return {"name": doc.name, "score": score, "verdict": verdict, "step": step,
            "summary": doc.tlc_ai_summary, "questions": questions}


def _ai_detail(result, score, verdict):
    return json.dumps({"score": score, "verdict": verdict, "summary": result.get("summary"),
                       "risks": result.get("risks"), "questions": result.get("questions")},
                      ensure_ascii=False, default=str)[:8000]


def _as_text(value):
    if isinstance(value, list):
        return chr(10).join(f"- {item}" for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


def _payload(payload):
    if isinstance(payload, str):
        return json.loads(payload or "{}")
    return payload or {}


@frappe.whitelist(methods=["POST"])
def advance(name, action, payload=None):
    """The only way a hiring step moves: each action checks its gate and records the human actor."""
    _require(HR | DIRECTOR)
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
        if doc.tlc_ai_verdict == "Không đạt" and set(frappe.get_roles()) & DIRECTOR is None:
            frappe.throw("AI đánh giá Không đạt: cần Giám đốc bỏ qua có lý do.")
        if not values.get("interviewer") or not values.get("interview_at"):
            frappe.throw("Cần chọn người phỏng vấn và thời gian phỏng vấn.")
        if not reason:
            frappe.throw("Ghi lý do quyết định mời phỏng vấn.")
        _save(doc, tlc_step=STEPS[2], tlc_interviewer=values["interviewer"],
              tlc_interview_at=get_datetime(values["interview_at"]), tlc_decision_by=frappe.session.user,
              tlc_decision_on=now_datetime(), tlc_decision_reason=reason, tlc_step_owner=frappe.session.user,
              tlc_pipeline=NATIVE_STAGE[STEPS[2]])
        _log(doc.name, "Invite", json.dumps({**values, "from": step, "to": STEPS[2]}, ensure_ascii=False, default=str))
    elif action == "invitation":
        if step != STEPS[2]:
            frappe.throw(f"Thư mời chỉ gửi từ bước 3 (đang ở {step}).")
        if not doc.tlc_interview_at or not doc.tlc_interviewer:
            frappe.throw("Chưa có lịch và người phỏng vấn.")
        if not doc.email_id:
            frappe.throw("Hồ sơ thiếu email để gửi thư mời.")
        when = get_datetime(doc.tlc_interview_at).strftime("%d/%m/%Y %H:%M")
        interviewer = frappe.db.get_value("Employee", doc.tlc_interviewer, "employee_name") or doc.tlc_interviewer
        frappe.sendmail(recipients=[doc.email_id],
                        subject=f"Thư mời phỏng vấn - {doc.applicant_name}",
                        message=(f"Chào {doc.applicant_name},<br><br>Bạn được mời phỏng vấn cho vị trí "
                                 f"<b>{doc.job_title or doc.designation or ''}</b>.<br>Thời gian: <b>{when}</b>.<br>"
                                 f"Người phỏng vấn: {interviewer}.<br>Địa điểm/link sẽ được HR gửi kèm.<br><br>"
                                 "Trân trọng,<br>TLC HR"), now=True)
        _save(doc, tlc_step=STEPS[3], tlc_decision_by=frappe.session.user, tlc_decision_on=now_datetime(),
              tlc_step_owner=frappe.session.user, tlc_pipeline=NATIVE_STAGE[STEPS[3]])
        _log(doc.name, "Invitation", f"Đã xếp hàng thư mời tới {doc.email_id} cho {when}")
    elif action == "interview":
        if step != STEPS[3]:
            frappe.throw(f"Ghi nhận phỏng vấn từ bước 4 (đang ở {step}).")
        if not (values.get("interview_notes") or "").strip() or values.get("interview_result") not in ("Pass", "Fail", "Hold"):
            frappe.throw("Cần ghi biên bản và kết quả phỏng vấn (Pass/Fail/Hold).")
        _save(doc, tlc_step=STEPS[4], tlc_interview_notes=values["interview_notes"][:5000],
              tlc_interview_result=values["interview_result"], tlc_decision_by=frappe.session.user,
              tlc_decision_on=now_datetime(), tlc_decision_reason=reason, tlc_step_owner=frappe.session.user,
              tlc_pipeline=NATIVE_STAGE[STEPS[4]])
        _log(doc.name, "Interview", json.dumps(values, ensure_ascii=False, default=str))
    elif action == "offer":
        if step != STEPS[4]:
            frappe.throw(f"Quyết định offer từ bước 5 (đang ở {step}).")
        if set(frappe.get_roles()) & DIRECTOR is None:
            frappe.throw("Chỉ Giám đốc quyết định offer.", frappe.PermissionError)
        if doc.tlc_interview_result != "Pass" and not reason:
            frappe.throw("Kết quả phỏng vấn chưa Pass: Giám đốc phải ghi lý do bỏ qua.")
        if not values.get("salary") or not values.get("joining_date"):
            frappe.throw("Cần mức lương và ngày vào làm trong quyết định offer.")
        offer = None
        if doc.tlc_job_offer:
            offer = frappe.get_doc("Job Offer", doc.tlc_job_offer)
        else:
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
        _log(doc.name, "Offer", f"Offer {offer.name}: {flt(values['salary']):,.0f} VND, vào làm {values['joining_date']}. {reason}")
    elif action == "complete":
        if step != STEPS[5]:
            frappe.throw(f"Hoàn tất từ bước 6 (đang ở {step}).")
        if not doc.tlc_job_offer:
            frappe.throw("Chưa có Job Offer để bàn giao onboarding.")
        todo = frappe.get_doc({"doctype": "ToDo", "allocated_to": "hoa@demo.example", "status": "Open",
                               "date": nowdate(), "priority": "High",
                               "description": f"Vào việc {doc.applicant_name} ({doc.name}) — tạo Employee và Employee Onboarding từ offer {doc.tlc_job_offer}."}).insert(ignore_permissions=True)
        _save(doc, tlc_decision_by=frappe.session.user, tlc_decision_on=now_datetime(),
              tlc_step_owner=frappe.session.user, tlc_pipeline="Joined", status="Accepted")
        _log(doc.name, "Complete", f"Bàn giao onboarding, ToDo {todo.name}, offer {doc.tlc_job_offer}")
    elif action in ("reject", "talent"):
        target = REJECTED if action == "reject" else TALENT
        if not reason:
            frappe.throw("Ghi lý do trước khi kết thúc hồ sơ.")
        _save(doc, tlc_step=target, tlc_decision_by=frappe.session.user, tlc_decision_on=now_datetime(),
              tlc_decision_reason=reason, tlc_step_owner=frappe.session.user,
              tlc_pipeline=NATIVE_STAGE[target], status="Rejected" if action == "reject" else doc.status)
        _log(doc.name, "Reject" if action == "reject" else "Talent Pool", reason)
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
    """Turn new CV e-mails into step-1 applicants, then let the AI compare them with the JD."""
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
        if not message_id or frappe.db.exists(LOG, {"message_id": message_id}):
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
            _log(existing, "Intake", f"Email bổ sung {message_id} từ {email}: {detail.get('Subject') or ''}", message_id=message_id)
            frappe.db.commit()
            continue
        applicant = frappe.get_doc({
            "doctype": "Job Applicant", "applicant_name": name, "email_id": email,
            "job_title": opening, "designation": frappe.db.get_value("Job Opening", opening, "designation") if opening else None,
            "status": "Open", "source": "Other", "tlc_pipeline": "New", "tlc_step": STEPS[0],
            "tlc_intake_source": "Email", "tlc_intake_message": message_id,
            "cover_letter": (detail.get("Text") or "")[:5000],
        }).insert(ignore_permissions=True)
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
        try:
            screen(applicant.name)
        except Exception as exc:
            _log(applicant.name, "Intake", f"AI lỗi: {str(exc)[:400]}", MODEL, message_id=message_id)
        _log(applicant.name, "Intake", f"Email {email}: {detail.get('Subject') or ''}", message_id=message_id)
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
