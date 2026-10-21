"""`bench tlc doctor`: the checks HR and IT run before a payroll month or after a change; each returns (ok, title, detail)."""

import datetime

import frappe

from tlc_hr.attendance.period import SCOPES


def run_checks():
    return [check() for check in (customizing_matches, everyone_has_a_located_shift, factories_have_heads, everyone_has_an_approver,
                                  company_accounts_set, last_month_closed)]


def customizing_matches():
    from tlc_hr.infrastructure.customizing import engine

    changes = engine.plan()
    return (not changes, "Cấu hình site khớp YAML", f"{len(changes)} khác biệt, chạy `tlc config plan`" if changes else "")


def everyone_has_a_located_shift():
    active = set(frappe.get_all("Employee", filters={"status": "Active"}, pluck="name"))
    located = set(frappe.get_all("Shift Assignment", filters={"docstatus": 1, "status": "Active", "shift_location": ["is", "set"]},
                                 pluck="employee"))
    missing = sorted(active - located)
    return (not missing, "Mỗi nhân sự có ca và địa điểm chấm công", ", ".join(missing[:10]))


def factories_have_heads():
    missing = []
    for company, abbr in frappe.get_all("Company", fields=["name", "abbr"], as_list=True):
        for scope in SCOPES[:-1]:
            head = frappe.db.get_value("Department", f"{scope} - {abbr}", "tlc_head")
            if not (head and frappe.db.get_value("Employee", head, "user_id")):
                missing.append(f"{scope} ({company})")
    return (not missing, "Mỗi nhà máy có trưởng nhà máy có tài khoản", ", ".join(missing))


def everyone_has_an_approver():
    missing = frappe.get_all("Employee", filters={"status": "Active", "user_id": ["is", "set"], "leave_approver": ["is", "not set"],
                                                  "reports_to": ["is", "set"]}, pluck="name")
    return (not missing, "Mỗi nhân sự có người duyệt trực tiếp", ", ".join(missing[:10]))


def company_accounts_set():
    fields = ["default_payroll_payable_account", "default_employee_advance_account", "default_expense_claim_payable_account"]
    missing = [f"{c}.{f}" for c in frappe.get_all("Company", pluck="name") for f in fields if not frappe.db.get_value("Company", c, f)]
    return (not missing, "Tài khoản mặc định cho lương, tạm ứng, chi phí", ", ".join(missing))


def last_month_closed():
    month = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
    locked = set(frappe.get_all("TLC Attendance Period", filters={"period_month": month, "docstatus": 1}, pluck="scope"))
    missing = [s for s in SCOPES if s not in locked]
    return (not missing, f"Kỳ công {month} đã khoá", "chưa khoá: " + ", ".join(missing) if missing else "")
