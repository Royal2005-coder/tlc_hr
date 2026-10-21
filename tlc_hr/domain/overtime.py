"""Overtime under the Labour Code (Bộ luật Lao động 2019 điều 107, Nghị định 145/2020/NĐ-CP điều 60) and the TLC consent route.

Overtime may not exceed 40 hours a month and 200 hours a year. In one day: at most 50 % of the normal hours on a working day;
on a weekly rest day or a public holiday, at most 12 hours. The caps are dated so a change of the law is a new row, not an edit.
The line manager of the worker (or the head of their department, or HR) proposes; the worker consents; the director approves;
once sent, what the worker consented to does not change.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from tlc_hr.domain.shared import COMPANY_WIDE_ROLES, DomainError, NotAllowed

NORMAL_DAILY_HOURS = 8
OVERTIME_CAPS = [(date(2021, 1, 1), 40, 200)]  # (effective from, month cap, year cap)
WORKING_DAY, REST_DAY, HOLIDAY = "Ngày thường", "Ngày nghỉ tuần", "Ngày lễ"
MULTIPLIER = {WORKING_DAY: 1.5, REST_DAY: 2.0, HOLIDAY: 3.0}  # Bộ luật Lao động 2019 điều 98
FIXED_FIELDS = ("employee", "ot_date", "from_time", "to_time", "reason")


@dataclass(frozen=True)
class Slot:
    day: date
    start: time
    end: time

    def hours(self) -> float:
        start, end = datetime.combine(self.day, self.start), datetime.combine(self.day, self.end)
        if end == start:
            return 0.0  # an empty request, not a 24-hour one
        if end < start:
            end += timedelta(days=1)  # over midnight
        return round((end - start).total_seconds() / 3600, 2)


@dataclass(frozen=True)
class Totals:
    """Hours of the worker's other live requests (not refused or cancelled), and this one."""

    day: float
    month: float
    year: float


@dataclass(frozen=True)
class Proposer:
    """Who proposes and how they relate to the worker."""

    user: str
    roles: frozenset
    is_line_manager: bool
    is_department_head: bool
    above_in_reporting_line: bool


def caps_on(day: date) -> tuple[int, int]:
    found = None
    for start, month, year in OVERTIME_CAPS:
        if day >= start:
            found = (month, year)
    if not found:
        raise ValueError(f"no overtime cap in force on {day}")
    return found


def daily_cap(day_type: str) -> float:
    return NORMAL_DAILY_HOURS * 0.5 if day_type == WORKING_DAY else 12


def day_type_of(weekly_off: bool | None) -> str:
    """None: not in the holiday list (working day); True: weekly rest day; False: public holiday."""
    return WORKING_DAY if weekly_off is None else REST_DAY if weekly_off else HOLIDAY


def problems(day: date, day_type: str, totals: Totals) -> list[str]:
    """What breaks the law in a request (empty when allowed)."""
    month_cap, year_cap = caps_on(day)
    found = []
    if totals.day > daily_cap(day_type):
        found.append(f"Quá {daily_cap(day_type):g} giờ tăng ca trong một {day_type.lower()} (Bộ luật Lao động 2019 điều 107).")
    if totals.month > month_cap:
        found.append(f"Quá {month_cap} giờ tăng ca trong tháng: tổng {totals.month:g} giờ (Bộ luật Lao động 2019 điều 107).")
    if totals.year > year_cap:
        found.append(f"Quá {year_cap} giờ tăng ca trong năm: tổng {totals.year:g} giờ (Bộ luật Lao động 2019 điều 107).")
    return found


def check_hours(slot: Slot) -> float:
    hours = slot.hours()
    if not hours:
        raise DomainError("overtime.empty", "Giờ kết thúc phải sau giờ bắt đầu.")
    return hours


def check_limits(day: date, day_type: str, totals: Totals) -> None:
    found = problems(day, day_type, totals)
    if found:
        raise DomainError("overtime.over_limit", "<br>".join(found), "Vượt giới hạn tăng ca")


def check_proposer(proposer: Proposer) -> None:
    if proposer.roles & COMPANY_WIDE_ROLES:
        return
    if not (proposer.is_line_manager or proposer.is_department_head or proposer.above_in_reporting_line):
        raise NotAllowed("overtime.not_your_people", "Bạn chỉ đề nghị tăng ca cho người thuộc quyền quản lý của mình.")


def check_fixed(before: dict, after: dict, sent: bool) -> None:
    """What the worker consented to is what the director approves: once sent, the request itself does not change."""
    if sent and any(str(before.get(f) or "") != str(after.get(f) or "") for f in FIXED_FIELDS):
        raise DomainError("overtime.fixed_after_send", "Đơn đã gửi thì không sửa người, ngày, giờ hay lý do. Từ chối đơn này và tạo đơn mới.",
                          "Đơn đã gửi")


def premium_split(hours_by_day_type: dict[str, float]) -> tuple[float, float]:
    """Hours paid at 100 % (taxed) and premium hours (free of PIT) of a month of approved overtime."""
    hours = sum(hours_by_day_type.values())
    premium = sum(h * (MULTIPLIER.get(t, 1.5) - 1) for t, h in hours_by_day_type.items())
    return hours, premium
