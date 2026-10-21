"""Internal-service rules; dates are business-calendar dates, not elapsed hours."""
from datetime import timedelta
from tlc_hr.domain.shared import DomainError


def require(condition, code, message):
    if not condition:
        raise DomainError(code, message)


def transition(old, new, edges):
    require(old == new or new in edges.get(old, ()), "invalid_transition", "Chuyển trạng thái không hợp lệ")


def working_due(start, days, holidays, calendar_end):
    require(days > 0, "sla_days", "SLA phải lớn hơn 0 ngày làm việc")
    day = start
    remaining = days
    while remaining:
        day += timedelta(days=1)
        require(day <= calendar_end, "calendar_missing", "Cần bổ sung lịch ngày làm việc cho hạn SLA")
        if day not in holidays:
            remaining -= 1
    return day


def working_elapsed(start, end, holidays):
    return sum(start + timedelta(days=n) not in holidays for n in range(1, (end-start).days+1))


def intervals_overlap(start, end, other_start, other_end):
    return start < other_end and end > other_start


def meal_cutoff(day, today, hr, reason):
    require(day > today or (hr and bool(reason)), "meal_cutoff", "Đổi suất ăn muộn phải do HR xử lý và ghi lý do")


SERVICE_EDGES = {"Requested": ("Processing", "Cancelled"), "Processing": ("Waiting Information", "Resolved", "Cancelled"),
                 "Waiting Information": ("Processing", "Cancelled"), "Resolved": ("Closed", "Processing")}
LOAN_EDGES = {"Requested": ("Waitlisted", "Lent", "Rejected", "Cancelled"), "Waitlisted": ("Requested", "Lent", "Cancelled"), "Lent": ("Returned",)}
MAIL_EDGES = {"Need Dispatch": ("With Courier",), "With Courier": ("Delivered",), "New Incoming": ("Handed Over",)}
