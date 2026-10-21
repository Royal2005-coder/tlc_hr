"""Attendance rules of TLC: check-in at a work site, corrections, the monthly period and the lock of a closed month.

- A check-in must fall in one of the person's shifts and that shift must be assigned at a work site (HRMS passes silently otherwise).
- Forgetting to check in or out is declared after the day, never ahead; only a business trip may be declared ahead.
- A month is summed up per person for a scope: each factory on its own, every other department is the head office.
  HR sends, the factory head confirms (factories only), HR reconciles, the CEO signs and locks. Nothing may be left open in the
  month when the period moves on; returning it to HR and reopening a locked month need a reason.
- A locked month cannot change, except through a post-lock adjustment written by HR for a day of a locked period, with a reason.
"""

import calendar
from dataclasses import dataclass
from datetime import date

from tlc_hr.domain.shared import HR_ROLES, DomainError, NotAllowed

HEAD_OFFICE = "Hội sở"
PAST_ONLY = ("Quên chấm vào", "Quên chấm ra", "Máy chấm công lỗi")
POST_LOCK = "Điều chỉnh sau chốt"
DRAFT, TO_HEAD, TO_HR, TO_CEO, LOCKED, REOPENED = (
    "Nháp", "Chờ quản lý xác nhận", "Chờ nhân sự đối soát", "Chờ giám đốc ký", "Đã khoá", "Đã mở lại")
MOVING_ON = (TO_HEAD, TO_HR, TO_CEO, LOCKED)
# Attendance status -> summary column
STATUS_FIELD = {"Present": "present_days", "Work From Home": "present_days", "Half Day": "half_days", "Absent": "absent_days",
                "On Leave": "leave_days"}
TOTALS = ("present_days", "half_days", "absent_days", "leave_days", "late_count", "ot_hours")


@dataclass(frozen=True)
class Person:
    employee: str
    employee_name: str
    department: str | None


@dataclass(frozen=True)
class Mark:
    employee: str
    status: str
    late: bool
    early_exit: bool


def scope_of_department(department: str | None, factories: tuple[str, ...]) -> str:
    base = (department or "").rsplit(" - ", 1)[0]
    return base if base in factories else HEAD_OFFICE


def check_checkin(tracking_on: bool, shift: str | None, located: bool) -> None:
    if not tracking_on:
        return
    if not shift:
        raise DomainError("checkin.no_shift", "Giờ này không thuộc ca làm việc nào của bạn. Liên hệ quản lý nếu bạn được điều động làm ca khác.",
                          "Ngoài giờ ca")
    if not located:
        raise DomainError("checkin.no_site", f"Ca {shift} của bạn chưa được gắn địa điểm làm việc nên không thể chấm công. Liên hệ phòng Nhân sự.",
                          "Chưa có địa điểm chấm công")


def check_correction(kind: str | None, to_date: date, today: date, is_new: bool, roles: frozenset, locked: bool,
                     explanation: str | None, post_lock_creation_authorized: bool = False):
    if kind in PAST_ONLY and to_date > today:
        raise DomainError("correction.future", f"Chỉ giải trình {kind.lower()} cho ngày đã qua.")
    if kind != POST_LOCK:
        return
    if is_new and not roles & HR_ROLES and not post_lock_creation_authorized:
        raise NotAllowed("correction.post_lock_hr_only", "Chỉ nhân sự lập điều chỉnh sau chốt.")
    if not locked:
        raise DomainError("correction.not_locked", "Ngày này chưa thuộc kỳ công đã khoá: dùng giải trình công thông thường.")
    if not (explanation or "").strip():
        raise DomainError("correction.reason_required", "Ghi lý do điều chỉnh sau chốt.")


def check_lock(locked_title: str | None, post_lock_adjustment: bool) -> None:
    if locked_title and not post_lock_adjustment:
        raise DomainError("lock.locked", f"{locked_title} đã khoá: không sửa dữ liệu công của kỳ này. "
                                         "HR lập \"Điều chỉnh sau chốt\" (giải trình công) để thay đổi.", "Kỳ công đã khoá")


def carry_forward_expiry(start: date, end: date) -> date:
    """Annual carried leave expires on 30 March, including leap years, or the allocation end if earlier."""
    expiry = min(date(start.year, 3, 30), end)
    if expiry < start:
        raise DomainError("leave.carry_expired", "Phép năm chuyển tiếp chỉ được sử dụng đến hết ngày 30 tháng 3.")
    return expiry


def period_dates(month: str) -> tuple[date, date, str]:
    year, number = (int(x) for x in month.split("-"))
    return date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1]), f"{number:02d}/{year}"


def summarize(people: list[Person], marks: list[Mark], overtime: list[tuple[str, float]], corrections: list[str]) -> list[dict]:
    """One row per person: days present, half, absent, on leave, late arrivals, early exits, approved overtime and corrections."""
    rows = {p.employee: {"employee": p.employee, "employee_name": p.employee_name, "department": p.department, "present_days": 0,
                         "half_days": 0, "absent_days": 0, "leave_days": 0, "late_count": 0, "early_exit_count": 0, "ot_hours": 0,
                         "corrections": 0} for p in people}
    for m in marks:
        if m.employee in rows:
            row = rows[m.employee]
            row[STATUS_FIELD.get(m.status, "present_days")] += 1
            row["late_count"] += int(m.late)
            row["early_exit_count"] += int(m.early_exit)
    for employee, hours in overtime:
        if employee in rows:
            rows[employee]["ot_hours"] += hours
    for employee in corrections:
        if employee in rows:
            rows[employee]["corrections"] += 1
    return list(rows.values())


def check_move(before: str | None, after: str | None, open_items: list[str], reason: str | None) -> str | None:
    """Rules of a state change of the period; returns the stage that returned it to HR (if it was returned)."""
    if before == after or before is None:
        return None
    if after in MOVING_ON and open_items:
        raise DomainError("period.open_items", f"Còn {len(open_items)} việc chưa xử lý trong kỳ:<br>" + "<br>".join(open_items),
                          "Chưa chốt được kỳ công")
    if after == DRAFT:
        if not (reason or "").strip():
            raise DomainError("period.reason_required", "Nhập lý do trước khi trả lại kỳ công.", "Thiếu lý do")
        return before
    return None


def check_reopen(reason: str | None) -> None:
    if not (reason or "").strip():
        raise DomainError("period.reopen_reason", "Nhập lý do trước khi mở lại kỳ công đã khoá.", "Thiếu lý do")


def check_unique(other: str | None) -> None:
    if other:
        raise DomainError("period.duplicate", f"Đã có {other} cho phạm vi và tháng này.")
