"""Frappe implementation of the payroll port, and the payroll actions on HRMS documents."""

from collections import defaultdict

import frappe
from frappe.utils import flt, getdate

from tlc_hr.domain.attendance import scope_of_department
from tlc_hr.domain.overtime import NORMAL_DAILY_HOURS
from tlc_hr.domain.payroll_ports import IPayrollRepository
from tlc_hr.infrastructure.frappe.attendance import FrappeAttendanceRepository


class FrappePayrollRepository(IPayrollRepository):
    def scope_of(self, department):
        return scope_of_department(department, FrappeAttendanceRepository().factories())

    def locked_scopes(self, company, month):
        return set(frappe.get_all("TLC Attendance Period", filters={"company": company, "period_month": month, "docstatus": 1}, pluck="scope"))

    def base_salary(self, employee, on):
        return flt(frappe.db.get_value("Salary Structure Assignment", {"employee": employee, "docstatus": 1, "from_date": ["<=", on]},
                                       "base", order_by="from_date desc"))

    def working_days(self, employee, start, end):
        from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
        from hrms.utils.holiday_list import get_holiday_dates_between

        holiday_list = get_holiday_list_for_employee(employee, raise_exception=False)
        days = (getdate(end) - getdate(start)).days + 1
        return days - (len(get_holiday_dates_between(holiday_list, start, end)) if holiday_list else 0)

    def shift_hours(self, employee):
        # The clock span includes lunch or overtime; TLC's normal paid workday is eight hours.
        return NORMAL_DAILY_HOURS

    def approved_overtime(self, employee, start, end):
        hours = defaultdict(float)
        for r in frappe.get_all("TLC Overtime Request", filters={"employee": employee, "docstatus": 1, "ot_date": ["between", [start, end]]},
                                fields=["hours", "day_type"]):
            hours[r.day_type] += flt(r.hours)
        return dict(hours)


def add_salary(entry, employee, abbr, amount):
    """An Additional Salary of the payroll entry (skipped when it already exists)."""
    component = frappe.db.get_value("Salary Component", {"salary_component_abbr": abbr})
    if not amount or frappe.db.exists("Additional Salary", {"employee": employee, "salary_component": component, "docstatus": 1,
                                                            "ref_doctype": "Payroll Entry", "ref_docname": entry.name}):
        return
    frappe.get_doc({"doctype": "Additional Salary", "employee": employee, "company": entry.company, "salary_component": component,
                    "amount": amount, "payroll_date": entry.end_date, "overwrite_salary_structure_amount": 1,
                    "ref_doctype": "Payroll Entry", "ref_docname": entry.name}).insert(ignore_permissions=True).submit()


def cancel_salaries(entry):
    for name in frappe.get_all("Additional Salary", filters={"ref_doctype": "Payroll Entry", "ref_docname": entry.name, "docstatus": 1},
                               pluck="name"):
        frappe.get_doc("Additional Salary", name).cancel()


def draft_slips(entry):
    return frappe.db.count("Salary Slip", {"payroll_entry": entry.name, "docstatus": 0})


def post_payment(entry, month):
    """The bank entry of the payroll, with the reference of the bank transfer."""
    journal = entry.make_bank_entry()
    if journal:
        journal.cheque_no, journal.cheque_date = entry.tlc_bank_reference, entry.tlc_paid_on
        journal.user_remark = f"Chi lương {month}, chứng từ {entry.tlc_bank_reference}"
        if entry.get("tlc_bank_proof"):
            journal.user_remark += f" (đính kèm {entry.tlc_bank_proof})"
        journal.flags.ignore_permissions = True
        journal.save()
        journal.submit()
    return journal


def summary(entry_name):
    """What the CEO and the accountant look at: people, gross, deductions, net, overtime, employer contributions, slips."""
    slips = frappe.get_all("Salary Slip", filters={"payroll_entry": entry_name}, fields=["name", "gross_pay", "total_deduction", "net_pay",
                                                                                       "docstatus"])
    names = [s.name for s in slips] or [""]
    by_component = defaultdict(float)
    for d in frappe.get_all("Salary Detail", filters={"parent": ["in", names], "parenttype": "Salary Slip"}, fields=["abbr", "amount"]):
        by_component[d.abbr] += flt(d.amount)
    return {"slips": len(slips), "draft": sum(1 for s in slips if s.docstatus == 0), "gross": sum(flt(s.gross_pay) for s in slips),
            "deductions": sum(flt(s.total_deduction) for s in slips), "net": sum(flt(s.net_pay) for s in slips),
            "overtime": by_component["OT"] + by_component["OTP"], "pit": by_component["TNCN"],
            "employer": sum(by_component[k] for k in ("BHXH_DN_TLC", "BHYT_DN_TLC", "BHTN_DN_TLC", "KPCD_DN_TLC"))}
