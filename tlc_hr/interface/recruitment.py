"""Thin doc_events adapters for native recruitment documents."""

import frappe
from frappe.utils import getdate

from tlc_hr.application.recruitment import RecruitmentService
from tlc_hr.contracts.recruitment import ApplicationCommand, CandidateCommand, OfferCommand
from tlc_hr.domain.recruitment import (
    APPROVED, CEO_REVIEW, COMPENSATION_FIELDS, DRAFT, HR_REVIEW,
    freeze_compensation, validate_offer_stage, validate_requisition, validate_terminal, vacancy_progress,
)
from tlc_hr.domain.shared import DomainError
from tlc_hr.infrastructure.frappe.recruitment import FrappeRecruitmentRepository


def _run(action):
    try:
        return action()
    except DomainError as error:
        frappe.throw(f"[{error.code}] {error.message}", exc=frappe.ValidationError)


def _service():
    return RecruitmentService(FrappeRecruitmentRepository())


def _canonical(value):
    # An update-after-submit payload keeps text where the stored document holds typed dates and numbers.
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(round(float(value), 6))
    return str(value)


def _snapshot(doc):
    values = {key: _canonical(doc.get(key)) for key in COMPENSATION_FIELDS}
    values["offer_terms"] = [(_canonical(row.offer_term), _canonical(row.value)) for row in doc.get("offer_terms", [])]
    return values


def validate_requisition_doc(doc, method=None):
    state = doc.get("workflow_state") or DRAFT
    positions = doc.get("tlc_positions") or []
    quantities = tuple(int(row.quantity or 0) for row in positions) if positions else (int(doc.no_of_positions or 0),)
    _run(lambda: validate_requisition(doc.get("tlc_jd") or "", getdate(doc.expected_by) if doc.expected_by else None,
                                     doc.get("tlc_request_type") or "", doc.get("tlc_replaced_employee") or "",
                                     quantities, state != DRAFT))
    old = doc.get_doc_before_save()
    if old and old.get("workflow_state") == APPROVED:
        immutable = ("company", "designation", "department", "no_of_positions", "expected_compensation", "expected_by",
                     "description", "reason_for_requesting", "tlc_jd", "tlc_request_type", "tlc_replaced_employee", "tlc_location")
        old_rows = [(r.name, r.designation, r.quantity, r.department, r.location) for r in old.get("tlc_positions", [])]
        new_rows = [(r.name, r.designation, r.quantity, r.department, r.location) for r in positions]
        if old_rows != new_rows or any(old.get(key) != doc.get(key) for key in immutable):
            frappe.throw("Đề nghị đã duyệt không được đổi nội dung; tạo đề nghị mới.")
    if positions:
        doc.no_of_positions = sum(quantities)
    if state == APPROVED:
        doc.status = "Open & Approved" if doc.status not in ("Filled", "Cancelled") else doc.status


def requisition_updated(doc, method=None):
    if doc.get("workflow_state") == APPROVED:
        _run(lambda: _service().approve_requisition(doc.name))


def validate_applicant(doc, method=None):
    old = doc.get_doc_before_save()
    if old and old.job_title != doc.job_title and frappe.db.exists(
        "Job Offer", {"job_applicant": doc.name, "docstatus": 1, "status": "Accepted"}
    ):
        frappe.throw("Hồ sơ đã nhận offer không được chuyển vacancy; tạo hồ sơ ứng tuyển mới.")
    if doc.status == "Rejected":
        doc.tlc_pipeline = "Rejected"
    _run(lambda: validate_terminal(doc.get("tlc_pipeline") or "New", doc.get("tlc_disposition_reason") or ""))
    command = CandidateCommand(
        applicant_name=doc.applicant_name or doc.email_id or "", email=doc.email_id or "", phone=doc.phone_number or "",
        identity=doc.get("tlc_identity") or "", date_of_birth=str(doc.get("tlc_birth_date") or ""),
        gender=doc.get("tlc_gender") or "", address=doc.get("tlc_address") or "",
        education=doc.get("tlc_education") or "", experience=doc.get("tlc_experience") or "",
        portfolio=doc.get("tlc_portfolio") or "", cv=doc.resume_attachment or "",
    )
    doc.tlc_candidate = _run(lambda: _service().candidate(command))
    if doc.get("tlc_pipeline") == "Talent Pool":
        frappe.db.set_value("TLC Recruitment Candidate", doc.tlc_candidate, "talent_pool", 1)
    if not doc.get("tlc_received_on"):
        doc.tlc_received_on = getdate()


def validate_opening(doc, method=None):
    if not doc.get("tlc_required"):
        doc.tlc_required = int(doc.vacancies or 0)
    repo = FrappeRecruitmentRepository()
    if not doc.is_new():
        repo.lock_opening(doc.name)
    accepted = repo.accepted_count(doc.name) if not doc.is_new() else 0
    remaining, progress = _run(lambda: vacancy_progress(int(doc.tlc_required), accepted))
    doc.tlc_accepted, doc.tlc_remaining, doc.tlc_progress = accepted, remaining, progress
    if doc.status == "Closed" and remaining and not doc.get("tlc_cancellation_approved_by"):
        frappe.throw("Chỉ đóng vacancy khi tuyển đủ hoặc có Giám đốc phê duyệt hủy tuyển.")
    old = doc.get_doc_before_save()
    if doc.get("tlc_cancellation_approved_by") and (not old or old.get("tlc_cancellation_approved_by") != doc.tlc_cancellation_approved_by):
        if "TLC Director" not in frappe.get_roles() or doc.tlc_cancellation_approved_by != frappe.session.user:
            frappe.throw("Chỉ Giám đốc được ghi nhận chính mình phê duyệt hủy tuyển.", frappe.PermissionError)
    if doc.get("closes_on"):
        frappe.throw("Dùng Ngày cần nhân sự TLC; không dùng tự đóng quá hạn của HRMS.")
    if doc.job_requisition and frappe.db.get_value("Job Requisition", doc.job_requisition, "workflow_state") != APPROVED:
        frappe.throw("Đề nghị tuyển dụng chưa được duyệt.")


def opening_updated(doc, method=None):
    if doc.job_requisition:
        _run(lambda: FrappeRecruitmentRepository().refresh_opening(doc.name))


def validate_offer(doc, method=None):
    if doc.docstatus == 2:
        return
    service = _service()
    _run(lambda: service.check_offer(ApplicationCommand(application=doc.job_applicant or "")))
    if not doc.get("tlc_joining_date") or not doc.get("tlc_department"):
        frappe.throw("Offer cần phòng ban và ngày nhận việc dự kiến.")
    old = doc.get_doc_before_save()
    workflow = doc.get("workflow_state") or DRAFT
    frozen = bool(old and (old.docstatus == 1 or old.get("workflow_state") == APPROVED
                          or (old.get("workflow_state") == CEO_REVIEW and workflow != DRAFT)))
    _run(lambda: freeze_compensation(_snapshot(old) if old else {}, _snapshot(doc), frozen))
    stage = doc.get("tlc_offer_stage") or "Draft"
    before = old.get("tlc_offer_stage") or "Draft" if old else "Draft"
    if workflow in {HR_REVIEW, CEO_REVIEW}:
        stage = "Pending Approval"
    elif workflow == APPROVED and before in {"Draft", "Pending Approval"}:
        stage = "Approved"
    elif workflow == DRAFT and before == "Pending Approval":
        stage = "Draft"
    if doc.status == "Accepted":
        stage = "Accepted"
    elif doc.status == "Rejected":
        stage = "Rejected"
    if doc.status == "Cancelled":
        frappe.throw("Dùng Cancel For Amendment; không sửa trực tiếp trạng thái Cancelled.")
    if old and old.status == "Accepted" and doc.status != "Accepted":
        frappe.throw("Offer đã nhận không được đổi phản hồi trực tiếp.")
    if stage == "Accepted" and doc.status != "Accepted":
        frappe.throw("Ghi nhận phản hồi qua trường Status = Accepted.")
    if stage == "Rejected" and doc.status != "Rejected":
        frappe.throw("Ghi nhận phản hồi qua trường Status = Rejected.")
    approved = workflow == APPROVED and doc.docstatus == 1
    _run(lambda: validate_offer_stage(before, stage, approved, doc.get("tlc_offer_rejection_reason") or ""))
    doc.tlc_offer_stage = stage
    if stage == "Accepted":
        opening = frappe.db.get_value("Job Applicant", doc.job_applicant, "job_title")
        if not opening:
            frappe.throw("Ứng tuyển phải liên kết vacancy trước khi nhận offer.")
        repo = FrappeRecruitmentRepository()
        repo.lock_opening(opening)
        required = int(frappe.db.get_value("Job Opening", opening, "tlc_required") or 0)
        if (not old or old.status != "Accepted") and frappe.db.get_value("Job Opening", opening, "status") != "Open":
            frappe.throw("Vacancy đã đóng, không thể nhận thêm offer.")
        _run(lambda: vacancy_progress(required, repo.accepted_count(opening, doc.name) + 1))


def offer_updated(doc, method=None):
    if doc.docstatus == 1 and doc.status == "Rejected":
        reason = "Salary" if doc.get("tlc_offer_rejection_reason") == "Salary" else "Other"
        frappe.db.set_value("Job Applicant", doc.job_applicant, {
            "tlc_pipeline": "Rejected", "tlc_disposition_reason": reason,
        })
    if doc.docstatus == 1 and doc.status == "Accepted":
        _run(lambda: _service().accept_offer(OfferCommand(offer=doc.name)))


def before_cancel_offer(doc, method=None):
    old = doc.get_doc_before_save()
    if doc.status == "Accepted" or (old and old.status == "Accepted"):
        frappe.throw("Offer đã nhận phải xử lý onboarding trước; không hủy để sửa lương.")


def before_print_offer(doc, method=None, **kwargs):
    if doc.docstatus != 1 or doc.get("workflow_state") != APPROVED:
        frappe.throw("Chỉ in hoặc phát hành offer sau khi HR và Giám đốc duyệt.")


def validate_offer_communication(doc, method=None):
    if doc.get("reference_doctype") == "Job Offer" and doc.get("sent_or_received") == "Sent":
        offer = frappe.get_doc("Job Offer", doc.reference_name)
        before_print_offer(offer)
        if offer.tlc_offer_stage not in {"Sent", "Negotiating", "Accepted", "Rejected", "Expired"}:
            frappe.throw("Đánh dấu offer Đã gửi (Sent) trước khi gửi email từ Desk.")
