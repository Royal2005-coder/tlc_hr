"""Working-time limits of the Labour Code applied by TLC (Bộ luật Lao động 2019 điều 107, Nghị định 145/2020/NĐ-CP điều 60).

Overtime may not exceed 40 hours a month and 200 hours a year (300 only in the sectors listed by the decree: not TLC).
In one day: at most 50% of the normal hours on a working day; on a weekly rest day or a public holiday, normal hours plus
overtime at most 12 hours. Values are dated so a change of the law is a new row, not an edit.
"""

from datetime import date

NORMAL_DAILY_HOURS = 8
# (effective from, month cap, year cap)
OVERTIME_CAPS = [("2021-01-01", 40, 200)]
WORKING_DAY, REST_DAY, HOLIDAY = "Ngày thường", "Ngày nghỉ tuần", "Ngày lễ"


def caps_on(day):
    day = day if isinstance(day, date) else date.fromisoformat(str(day))
    found = None
    for start, month, year in OVERTIME_CAPS:
        if day >= date.fromisoformat(start):
            found = (month, year)
    if not found:
        raise ValueError(f"no overtime cap in force on {day}")
    return found


def daily_cap(day_type):
    return NORMAL_DAILY_HOURS * 0.5 if day_type == WORKING_DAY else 12


def check(day, day_type, day_hours, month_hours, year_hours):
    """Problems of an overtime request (empty when allowed). The day, month and year totals already include this request."""
    month_cap, year_cap = caps_on(day)
    problems = []
    if day_hours > daily_cap(day_type):
        problems.append(f"Quá {daily_cap(day_type):g} giờ tăng ca trong một {day_type.lower()} (Bộ luật Lao động 2019 điều 107).")
    if month_hours > month_cap:
        problems.append(f"Quá {month_cap} giờ tăng ca trong tháng: tổng {month_hours:g} giờ (Bộ luật Lao động 2019 điều 107).")
    if year_hours > year_cap:
        problems.append(f"Quá {year_cap} giờ tăng ca trong năm: tổng {year_hours:g} giờ (Bộ luật Lao động 2019 điều 107).")
    return problems
