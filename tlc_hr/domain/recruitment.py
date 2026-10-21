"""Recruitment rules independent of Desk and persistence."""

import re
from collections.abc import Mapping
from datetime import date
from typing import Protocol

from tlc_hr.domain.shared import DomainError

DRAFT = "Recruitment Draft"
HR_REVIEW = "Recruitment HR Review"
CEO_REVIEW = "Recruitment CEO Review"
APPROVED = "Recruitment Approved"
COMPENSATION_FIELDS = (
    "job_applicant", "designation", "company", "tlc_department", "tlc_grade", "tlc_hiring_manager",
    "tlc_location", "tlc_working_hours", "tlc_work_mode", "tlc_joining_date", "tlc_probation_months",
    "tlc_probation_salary", "tlc_salary", "tlc_allowances", "tlc_bonus", "tlc_benefits",
    "tlc_contract_type", "tlc_exception_file", "terms", "offer_terms",
)
TERMINAL_REASONS = {
    "Rejected": {"Technical fit", "Culture fit", "Salary", "Interview result", "Other"},
    "Withdrawn": {"Another offer", "Unavailable", "Personal", "Other"},
}
OFFER_REASONS = {"Salary", "Another offer", "Joining date", "Personal", "Other"}
OFFER_STAGES = {
    "Draft": {"Pending Approval"}, "Pending Approval": {"Draft", "Approved"},
    "Approved": {"Sent"}, "Sent": {"Negotiating", "Accepted", "Rejected", "Expired"},
    "Negotiating": {"Accepted", "Rejected", "Expired"}, "Accepted": set(), "Rejected": set(), "Expired": set(),
}


def identifiers(email: str = "", phone: str = "", identity: str = "") -> tuple[tuple[str, str], ...]:
    values = []
    if email.strip():
        values.append(("email", email.strip().casefold()))
    if phone.strip():
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("0084"):
            digits = "0" + digits[4:]
        elif digits.startswith("84") and len(digits) == 11:
            digits = "0" + digits[2:]
        if len(digits) < 8:
            raise DomainError("recruitment.phone", "Số điện thoại ứng viên không hợp lệ.")
        values.append(("phone", digits))
    if identity.strip():
        values.append(("identity", re.sub(r"[\s.-]", "", identity).upper()))
    if not values:
        raise DomainError("recruitment.identity", "Cần email, điện thoại hoặc CCCD để nhận diện ứng viên.")
    return tuple(values)


def validate_requisition(jd: str, needed_by: date | None, request_type: str, replaced: str,
                         quantities: tuple[int, ...], submitting: bool) -> None:
    if not quantities or any(q <= 0 for q in quantities):
        raise DomainError("recruitment.quantity", "Số lượng tuyển phải lớn hơn 0.")
    if submitting and (not jd or not needed_by):
        raise DomainError("recruitment.requisition", "Đính kèm JD và nhập ngày cần nhân sự trước khi gửi duyệt.")
    if submitting and request_type == "Replacement" and not replaced:
        raise DomainError("recruitment.replacement", "Tuyển thay thế phải chọn nhân viên được thay thế.")


def validate_terminal(stage: str, reason: str) -> None:
    if stage in TERMINAL_REASONS and reason not in TERMINAL_REASONS[stage]:
        raise DomainError("recruitment.reason", "Chọn lý do hợp lệ khi loại hoặc ứng viên rút.")


def require_final_round(cleared: bool) -> None:
    if not cleared:
        raise DomainError("recruitment.final_round", "Chỉ tạo offer sau khi vòng cuối của hồ sơ ứng tuyển đã đạt và được nộp.")


def freeze_compensation(before: Mapping, after: Mapping, frozen: bool) -> None:
    if not frozen:
        return
    changed = [key for key in COMPENSATION_FIELDS if before.get(key) != after.get(key)]
    if changed:
        raise DomainError("recruitment.compensation_frozen",
                          "Offer đã duyệt: hủy và Amend để trình HR, Giám đốc duyệt lại thay đổi (" + ", ".join(changed) + ").")


def validate_offer_stage(before: str, after: str, approved: bool, reason: str) -> None:
    if before != after and after not in OFFER_STAGES.get(before, set()):
        raise DomainError("recruitment.offer_stage", "Không thể chuyển trạng thái offer này.")
    if after in {"Approved", "Sent", "Negotiating", "Accepted", "Rejected", "Expired"} and not approved:
        raise DomainError("recruitment.offer_approval", "Offer phải được HR và Giám đốc duyệt trước khi phát hành hoặc ghi nhận phản hồi.")
    if after == "Rejected" and reason not in OFFER_REASONS:
        raise DomainError("recruitment.offer_reason", "Chọn lý do từ chối offer hợp lệ.")


def vacancy_progress(required: int, accepted: int) -> tuple[int, float]:
    if required <= 0 or accepted < 0 or accepted > required:
        raise DomainError("recruitment.capacity", "Vacancy không còn chỉ tiêu hoặc số lượng không hợp lệ.")
    return required - accepted, accepted * 100.0 / required


class RecruitmentRepository(Protocol):
    def resolve_candidate(self, keys: tuple[tuple[str, str], ...], profile: dict) -> str: ...
    def has_final_round(self, application: str) -> bool: ...
    def open_vacancies(self, requisition: str) -> list[str]: ...
    def accept_offer(self, offer: str) -> str: ...
