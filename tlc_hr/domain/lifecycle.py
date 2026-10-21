"""Vietnam employment lifecycle rules; dates use the employee's actual holiday calendar."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from tlc_hr.domain.shared import DomainError

PROBATION_LIMITS = {"Enterprise manager": (180, False), "College or higher": (60, False),
                    "Technical or vocational": (30, False), "Other work": (6, True)}
NOTICE_CATEGORIES = {"Indefinite": (45, False), "Fixed 12-36 months": (30, False),
                     "Fixed under 12 months": (3, True)}
# Catalog POL-EXIT-01 deliberately requires HR + Legal sign-off for special facts.
NOTICE_EXCEPTIONS = ("Statutory employee exception", "Special occupation", "Mutual agreement",
                     "Probation termination", "Contract expiry", "Employer termination")


def require(value, code, message):
    if not value:
        raise DomainError(code, message)


def add_working_days(start: date, days: int, is_working: Callable[[date], bool]) -> date:
    require(days >= 0, "LC-DAYS", "Số ngày không được âm.")
    current, count = start, 0
    # Calendar supplied by the repository, never assume factory weekends are holidays.
    for _ in range(days * 370 + 370):
        if count == days:
            return current
        current += timedelta(days=1)
        if is_working(current):
            count += 1
    raise DomainError("LC-CALENDAR", "Lịch làm việc không có ngày làm việc hợp lệ.")


def probation_days(category: str, start: date, end: date, is_working: Callable[[date], bool], repeated=False) -> int:
    require(category in PROBATION_LIMITS, "OB-CATEGORY", "Chọn nhóm thử việc theo BLLĐ.")
    require(end >= start, "OB-DATES", "Ngày kết thúc phải từ ngày bắt đầu.")
    require(not repeated, "OB-ONCE", "Chỉ được thử việc một lần cho cùng công việc.")
    limit, working = PROBATION_LIMITS[category]
    days = (end - start).days + 1
    if working:
        days = sum(is_working(start + timedelta(days=i)) for i in range(days))
    require(0 < days <= limit, "OB-LIMIT", f"Thử việc vượt giới hạn {limit} {'ngày làm việc' if working else 'ngày lịch'}.")
    return days


@dataclass(frozen=True)
class NoticeResult:
    earliest: date
    sufficient: bool
    days: int
    working_days: bool


def notice(category: str, submitted: date, last_day: date, is_working: Callable[[date], bool],
           exception: str = "", legal_evidence: str = "", legal_reviewer: str = "") -> NoticeResult:
    require(last_day >= submitted, "EXIT-DATES", "Ngày cuối không được trước ngày nộp.")
    if exception:
        require(exception in NOTICE_EXCEPTIONS, "EXIT-EXCEPTION", "Ngoại lệ phải thuộc danh mục pháp lý.")
        require(legal_evidence and legal_reviewer, "EXIT-LEGAL", "Ngoại lệ cần hồ sơ và người HR/Pháp chế xác nhận.")
        return NoticeResult(last_day, True, 0, False)
    require(category in NOTICE_CATEGORIES, "EXIT-CONTRACT", "Chọn nhóm hợp đồng để tính báo trước.")
    days, working = NOTICE_CATEGORIES[category]
    earliest = add_working_days(submitted, days, is_working) if working else submitted + timedelta(days=days)
    return NoticeResult(earliest, last_day >= earliest, days, working)


def settlement_due(relieving: date, is_working: Callable[[date], bool], exceptional=False,
                   legal_evidence="", legal_reviewer="") -> date:
    if exceptional:
        require(legal_evidence and legal_reviewer, "EXIT-SETTLEMENT-LEGAL", "Gia hạn thanh toán cần căn cứ luật và xác nhận pháp lý.")
        return relieving + timedelta(days=30)
    return add_working_days(relieving, 14, is_working)


def completion_gate(blockers):
    require(not blockers, "LC-INCOMPLETE", "Chưa thể hoàn tất: " + "; ".join(blockers))


def effective_interval(start, end):
    require(not end or end >= start, "CORE-DATES", "Ngày hết hiệu lực phải từ ngày hiệu lực.")


def deduction_count(dependents, as_of):
    return sum(1 for row in dependents if row["status"] == "Verified"
               and row["valid_from"] <= as_of and (not row.get("valid_to") or row["valid_to"] >= as_of))


def final_balance(salary, unused_leave, overtime, advances, deductions):
    values = [Decimal(str(value)) for value in (salary, unused_leave, overtime, advances, deductions)]
    require(all(value >= 0 for value in values), "EXIT-AMOUNT", "Các cấu phần quyết toán không được âm.")
    return sum(values[:3]) - sum(values[3:])
