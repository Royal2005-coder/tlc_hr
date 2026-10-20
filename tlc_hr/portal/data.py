"""Data of the TLC People portal. Every function returns plain dicts for the templates; scope is decided here, on the server.

Scope of people a user sees in shared widgets (who's out, celebrations, calendar):
- HR and the director: the whole company;
- a manager: everyone below them in the reporting tree, plus themselves;
- an employee: their own department.
The directory shows every active colleague with work fields only (name, job, department, workforce, manager), never private data.
"""

from collections import OrderedDict

import frappe
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from tlc_hr.portal.common import HR_ROLES, WORKFORCE, site_of
from tlc_hr.setup.install import APPROVED, TO_HR, TO_MANAGER

COMPANY = "TLC Demo"
PENDING = (TO_MANAGER, TO_HR)
WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
BASIC_FIELDS = ["name", "employee_name", "designation", "department", "tlc_workforce", "reports_to", "user_id",
                "date_of_birth", "date_of_joining", "gender"]


def today():
    return getdate(nowdate())


def employees(names=None, department=None):
    filters = {"status": "Active", "company": COMPANY}
    if names is not None:
        filters["name"] = ["in", names or [""]]
    if department:
        filters["department"] = department
    rows = frappe.get_all("Employee", filters=filters, fields=BASIC_FIELDS, order_by="employee_name asc")
    for row in rows:
        row.site = site_of(row.department)
        row.workforce_label = WORKFORCE.get(row.tlc_workforce, "")
    return rows


def descendants(employee):
    return frappe.db.get_descendants("Employee", employee) or []


def scope_names(person, f):
    if f.sees_company:
        return None  # everyone
    if not person:
        return []
    if f.is_manager:
        return descendants(person.name) + [person.name]
    return frappe.get_all("Employee", filters={"department": person.department, "status": "Active"}, pluck="name")


# ---------------------------------------------------------------------------------------------------- leave of one person

def balances(employee):
    """Per leave type: allocated, taken or approved, waiting for approval, remaining (approved future leave already deducted)."""
    from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

    allocated_by_type = OrderedDict()
    for alloc in frappe.get_all("Leave Allocation", filters={"employee": employee, "docstatus": 1, "to_date": [">=", today()]},
                                fields=["leave_type", "total_leaves_allocated"], order_by="leave_type asc"):
        allocated_by_type[alloc.leave_type] = allocated_by_type.get(alloc.leave_type, 0) + flt(alloc.total_leaves_allocated)
    result = []
    for leave_type, allocated in allocated_by_type.items():
        remaining = flt(get_leave_balance_on(employee, leave_type, nowdate(), consider_all_leaves_in_the_allocation_period=True))
        pending = sum(flt(d) for d in frappe.get_all(
            "Leave Application", filters={"employee": employee, "leave_type": leave_type, "workflow_state": ["in", PENDING], "docstatus": 0},
            pluck="total_leave_days"))
        result.append(frappe._dict(leave_type=leave_type, allocated=allocated, used=max(allocated - remaining, 0),
                                   pending=pending, remaining=remaining, after_pending=remaining - pending,
                                   used_pct=round(100 * max(allocated - remaining, 0) / allocated) if allocated else 0,
                                   pending_pct=round(100 * pending / allocated) if allocated else 0))
    return result


def requests_of(employee, limit=20):
    rows = frappe.get_all("Leave Application", filters={"employee": employee}, order_by="from_date desc", limit=limit,
                          fields=["name", "leave_type", "from_date", "to_date", "total_leave_days", "half_day", "workflow_state",
                                  "tlc_reject_reason", "tlc_rejected_stage", "description", "leave_approver", "modified"])
    for row in rows:
        row.steps = timeline(row.workflow_state, row.tlc_rejected_stage)
        row.can_withdraw = row.workflow_state in ("Nháp", TO_MANAGER, None, "")
        row.upcoming = getdate(row.to_date) >= today()
    return rows


def timeline(state, rejected_stage=None):
    """Progress of a request: sent, line manager, HR, result (done / current / todo / failed).

    A rejection marks the level that said no (line manager or HR) as failed; the levels after it were never reached.
    """
    order = ["Gửi đơn", "Quản lý duyệt", "Nhân sự duyệt", "Kết quả"]
    if state == "Từ chối":
        by_hr = rejected_stage == TO_HR
        return [{"label": "Gửi đơn", "status": "done"},
                {"label": "Quản lý duyệt" if by_hr else "Quản lý từ chối", "status": "done" if by_hr else "failed"},
                {"label": "Nhân sự từ chối" if by_hr else "Nhân sự duyệt", "status": "failed" if by_hr else "todo"},
                {"label": "Từ chối", "status": "failed"}]
    position = {"Nháp": 0, TO_MANAGER: 1, TO_HR: 2, APPROVED: 4, "Đã hủy": 4}.get(state, 0)
    steps = []
    for i, label in enumerate(order):
        status = "done" if i < position else "current" if i == position else "todo"
        if state == APPROVED and i == 3:
            label = "Đã duyệt"
        steps.append({"label": label, "status": status})
    return steps


# ---------------------------------------------------------------------------------------------------- shared widgets

def leaves_between(names, start, end, include_pending=True):
    states = [APPROVED] + (list(PENDING) if include_pending else [])
    filters = {"workflow_state": ["in", states], "from_date": ["<=", end], "to_date": [">=", start]}
    if names is not None:
        filters["employee"] = ["in", names or [""]]
    return frappe.get_all("Leave Application", filters=filters, order_by="from_date asc",
                          fields=["name", "employee", "employee_name", "department", "leave_type", "from_date", "to_date",
                                  "total_leave_days", "half_day", "workflow_state", "leave_approver"])


def whos_out(person, f, days=7):
    """Who is away (approved) or asked to be (pending) today and the next days, grouped by day, within the user's scope."""
    start, end = today(), add_days(today(), days)
    rows = leaves_between(scope_names(person, f), start, end)
    reports = set(descendants(person.name)) if person and f.is_manager else set()
    grouped = OrderedDict()
    day = start
    while day <= end:
        people = [r for r in rows if getdate(r.from_date) <= day <= getdate(r.to_date)]
        if people and day.weekday() < 5:
            label = "Hôm nay" if day == start else "Ngày mai" if day == add_days(start, 1) else f"{WEEKDAYS[day.weekday()]} {day.strftime('%d/%m')}"
            grouped[label] = [{"name": r.employee_name, "type": r.leave_type, "pending": r.workflow_state != APPROVED,
                               "report": r.employee in reports, "site": site_of(r.department), "half": r.half_day} for r in people]
        day = add_days(day, 1)
    return grouped


def celebrations(person, f, days=30):
    """Birthdays and work anniversaries of the next days in the user's scope (day and month only, never the year of birth)."""
    start = today()
    result = []
    for e in employees(scope_names(person, f)):
        for kind, base in (("birthday", e.date_of_birth), ("anniversary", e.date_of_joining)):
            if not base:
                continue
            base = getdate(base)
            try:
                this_year = base.replace(year=start.year)
            except ValueError:  # 29 February
                this_year = base.replace(year=start.year, day=28)
            if this_year < start:
                this_year = this_year.replace(year=start.year + 1)
            years = this_year.year - base.year
            if date_diff(this_year, start) <= days and (kind == "birthday" or years >= 1):
                result.append({"kind": kind, "name": e.employee_name, "date": this_year, "years": years, "site": e.site,
                               "label": "Sinh nhật" if kind == "birthday" else f"{years} năm gắn bó"})
    return sorted(result, key=lambda r: r["date"])[:8]


def holidays(limit=4):
    rows = frappe.db.sql(
        """select h.holiday_date, h.description from `tabHoliday` h join `tabHoliday List` l on l.name = h.parent
           where l.name like 'TLC %%' and ifnull(h.weekly_off, 0) = 0 and h.holiday_date >= %s order by h.holiday_date limit %s""",
        (today(), limit), as_dict=True)
    return rows


# ---------------------------------------------------------------------------------------------------- approvals

def approvals_inbox(roles, person):
    """Requests waiting for this user, with what helps decide: balance after approval, who else is away on those days."""
    me = frappe.session.user
    fields = ["name", "employee", "employee_name", "department", "leave_type", "from_date", "to_date", "total_leave_days",
              "half_day", "description", "workflow_state", "creation", "leave_approver"]
    rows = frappe.get_all("Leave Application", filters={"workflow_state": TO_MANAGER, "leave_approver": me, "docstatus": 0},
                          fields=fields, order_by="from_date asc")
    if roles.intersection(HR_ROLES):
        rows += frappe.get_all("Leave Application", filters={"workflow_state": TO_HR, "docstatus": 0}, fields=fields, order_by="from_date asc")
    own = person.name if person else None
    return [row for row in rows if row.employee != own]


def decision_support(rows):
    from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

    for row in rows:
        remaining = flt(get_leave_balance_on(row.employee, row.leave_type, nowdate(), consider_all_leaves_in_the_allocation_period=True))
        row.balance_now = remaining
        row.balance_after = remaining - flt(row.total_leave_days)
        same = frappe.get_all("Employee", filters={"department": row.department, "status": "Active"}, pluck="name")
        overlap = [r for r in leaves_between(same, row.from_date, row.to_date) if r.employee != row.employee]
        row.overlap = [{"name": r.employee_name, "pending": r.workflow_state != APPROVED} for r in overlap]
        row.team_size = len(same)
        row.site = site_of(row.department)
        row.waiting_days = date_diff(today(), getdate(row.creation))
        row.steps = timeline(row.workflow_state)
    return rows


# ---------------------------------------------------------------------------------------------------- team

def team_members(person, f, department=None):
    if f.sees_company:
        return employees(None, department)
    return employees(descendants(person.name)) if person else []


def team_calendar(members, start=None, days=14):
    """Grid of members × days: approved, pending, weekend, holiday."""
    start = getdate(start) if start else add_days(today(), -today().weekday())  # Monday of this week
    end = add_days(start, days - 1)
    rows = leaves_between([m.name for m in members], start, end)
    holiday_dates = {getdate(h.holiday_date): h.description for h in frappe.db.sql(
        """select h.holiday_date, h.description from `tabHoliday` h where h.parent like 'TLC %%' and ifnull(h.weekly_off, 0) = 0
           and h.holiday_date between %s and %s""", (start, end), as_dict=True)}
    day_list = []
    for i in range(days):
        day = add_days(start, i)
        day_list.append({"date": day, "label": WEEKDAYS[day.weekday()], "num": day.strftime("%d"), "weekend": day.weekday() >= 5,
                         "holiday": holiday_dates.get(day), "today": day == today()})
    by_member = {}
    for r in rows:
        for d in day_list:
            if getdate(r.from_date) <= d["date"] <= getdate(r.to_date) and not d["weekend"]:
                by_member.setdefault(r.employee, {})[d["date"]] = {"state": "approved" if r.workflow_state == APPROVED else "pending",
                                                                    "name": r.name, "type": r.leave_type, "half": r.half_day}
    return {"start": start, "end": end, "days": day_list, "cells": by_member,
            "prev": add_days(start, -days), "next": add_days(start, days)}


def team_rows(members):
    from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

    away = {r.employee for r in leaves_between([m.name for m in members], today(), today(), include_pending=False)}
    pending = {}
    for r in frappe.get_all("Leave Application", filters={"employee": ["in", [m.name for m in members] or [""]],
                                                          "workflow_state": ["in", PENDING]}, fields=["employee"]):
        pending[r.employee] = pending.get(r.employee, 0) + 1
    for m in members:
        m.away_today = m.name in away
        m.pending = pending.get(m.name, 0)
        m.annual_left = flt(get_leave_balance_on(m.name, "Phép năm", nowdate(), consider_all_leaves_in_the_allocation_period=True))
    return members


# ---------------------------------------------------------------------------------------------------- directory

def directory():
    rows = employees()
    names = {r.name: r.employee_name for r in rows}
    for r in rows:
        r.manager_name = names.get(r.reports_to, "")
        r.reports = sum(1 for x in rows if x.reports_to == r.name)
    sites = sorted({r.site for r in rows})
    return rows, sites


def org_tree(rows):
    children = {}
    for r in rows:
        children.setdefault(r.reports_to or "", []).append(r)

    def build(parent):
        return [{"e": r, "children": build(r.name)} for r in sorted(children.get(parent, []), key=lambda x: (x.designation or "", x.employee_name))]

    return build("")


# ---------------------------------------------------------------------------------------------------- reports

def company_report():
    rows = employees()
    t = today()
    by_site, by_workforce, by_gender, tenure = {}, {}, {}, OrderedDict((k, 0) for k in ("< 1 năm", "1-2 năm", "2-3 năm", "≥ 3 năm"))
    for r in rows:
        by_site[r.site] = by_site.get(r.site, 0) + 1
        by_workforce[r.workforce_label or "Khác"] = by_workforce.get(r.workforce_label or "Khác", 0) + 1
        gender = {"Male": "Nam", "Female": "Nữ"}.get(r.gender, "Khác")
        by_gender[gender] = by_gender.get(gender, 0) + 1
        years = date_diff(t, getdate(r.date_of_joining)) / 365.0 if r.date_of_joining else 0
        tenure["< 1 năm" if years < 1 else "1-2 năm" if years < 2 else "2-3 năm" if years < 3 else "≥ 3 năm"] += 1
    months = OrderedDict((m, 0.0) for m in range(1, 13))
    for r in frappe.get_all("Leave Application", filters={"workflow_state": APPROVED, "from_date": [">=", f"{t.year}-01-01"]},
                            fields=["from_date", "total_leave_days"]):
        months[getdate(r.from_date).month] += flt(r.total_leave_days)
    waiting = {TO_MANAGER: frappe.db.count("Leave Application", {"workflow_state": TO_MANAGER}),
               TO_HR: frappe.db.count("Leave Application", {"workflow_state": TO_HR})}
    away_today = leaves_between(None, t, t, include_pending=False)
    upcoming = leaves_between(None, add_days(t, 1), add_days(t, 14), include_pending=False)
    top = max(by_site.values()) if by_site else 1
    peak = max(months.values()) or 1
    return frappe._dict(
        headcount=len(rows), by_site=sorted(by_site.items(), key=lambda kv: -kv[1]), site_top=top,
        by_workforce=by_workforce, by_gender=by_gender, tenure=tenure, months=months, month_peak=peak,
        waiting=waiting, away_today=away_today, upcoming=upcoming,
        approved_days=sum(months.values()))


# ---------------------------------------------------------------------------------------------------- pay estimate

def pay_estimate(employee):
    """Monthly gross, employee insurance and PIT (5 brackets of 2026) for the signed-in employee only; an estimate, not a payslip."""
    from erpnextvn.payroll.insurance_calculator import calculate_insurance
    from erpnextvn.payroll.pit_calculator import calculate_pit

    wage, dependents = frappe.db.get_value("Employee", employee, ["tlc_monthly_wage", "tlc_dependents"])
    wage = flt(wage)
    if not wage:
        return None
    ins = calculate_insurance(wage, "I")
    settings = frappe.get_single("VN Payroll Settings")
    pit = calculate_pit(wage, insurance_deduction=ins.total_employee, num_dependents=cint(dependents),
                        personal_deduction=flt(settings.personal_deduction), dependent_deduction=flt(settings.dependent_deduction))
    net = wage - ins.total_employee - pit.tax_amount
    parts = [("Thực nhận", net, "net"), ("BHXH 8%", ins.si_employee, "si"), ("BHYT 1,5%", ins.hi_employee, "hi"),
             ("BHTN 1%", ins.ui_employee, "ui"), ("Thuế TNCN", pit.tax_amount, "pit")]
    return frappe._dict(
        wage=wage, dependents=cint(dependents), si=ins.si_employee, hi=ins.hi_employee, ui=ins.ui_employee,
        insurance=ins.total_employee, personal=flt(settings.personal_deduction), dependent=flt(settings.dependent_deduction),
        taxable=pit.taxable_income, pit=pit.tax_amount, bracket=pit.bracket, net=net, employer=ins.total_employer,
        parts=[{"label": label, "amount": amount, "key": key, "pct": round(100 * amount / wage, 1)} for label, amount, key in parts if amount],
        base_salary=flt(settings.base_salary))
