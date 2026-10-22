"""`bench tlc doctor`: the checks HR and IT run before a payroll month or after a change; each returns (ok, title, detail)."""

import datetime

import frappe

from tlc_hr.domain.attendance import HEAD_OFFICE
from tlc_hr.infrastructure.frappe.attendance import FrappeAttendanceRepository


def run_checks():
    return [check() for check in (customizing_matches, everyone_has_a_located_shift, factories_have_heads, everyone_has_an_approver,
                                  company_wide_roles_unrestricted, company_accounts_set, last_month_closed,
                                  salary_assignment_follows_declaration)]


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
        for scope in FrappeAttendanceRepository().factories():
            head = frappe.db.get_value("Department", f"{scope} - {abbr}", "tlc_head")
            if not (head and frappe.db.get_value("Employee", head, "user_id")):
                missing.append(f"{scope} ({company})")
    return (not missing, "Mỗi nhà máy có trưởng nhà máy có tài khoản", ", ".join(missing))


def everyone_has_an_approver():
    missing = frappe.get_all("Employee", filters={"status": "Active", "user_id": ["is", "set"], "leave_approver": ["is", "not set"],
                                                  "reports_to": ["is", "set"]}, pluck="name")
    return (not missing, "Mỗi nhân sự có người duyệt trực tiếp", ", ".join(missing[:10]))


COMPANY_WIDE = ("TLC Director", "TLC HR Lead", "TLC HR Officer", "TLC Payroll", "Accounts User", "Accounts Manager")


def company_wide_roles_unrestricted():
    """HRMS limits a user linked to an employee to that employee's records; payroll, HR, finance and the CEO work company-wide."""
    users = set(frappe.get_all("Has Role", filters={"role": ["in", COMPANY_WIDE], "parenttype": "User"}, pluck="parent"))
    limited = sorted(set(frappe.get_all("User Permission", filters={"allow": "Employee", "user": ["in", list(users) or [""]]},
                                        pluck="user")))
    return (not limited, "HR, lương, kế toán, CEO không bị giới hạn theo hồ sơ", ", ".join(limited))


def company_accounts_set():
    fields = ["default_payroll_payable_account", "default_employee_advance_account", "default_expense_claim_payable_account"]
    missing = [f"{c}.{f}" for c in frappe.get_all("Company", pluck="name") for f in fields if not frappe.db.get_value("Company", c, f)]
    return (not missing, "Tài khoản mặc định cho lương, tạm ứng, chi phí", ", ".join(missing))


def last_month_closed():
    month = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
    locked = set(frappe.get_all("TLC Attendance Period", filters={"period_month": month, "docstatus": 1}, pluck="scope"))
    missing = [s for s in (*FrappeAttendanceRepository().factories(), HEAD_OFFICE) if s not in locked]
    return (not missing, f"Kỳ công {month} đã khoá", "chưa khoá: " + ", ".join(missing) if missing else "")

def salary_assignment_follows_declaration():
    """Phân công lương phải trỏ đúng cấu trúc đang khai báo, và cấu trúc đó phải có đủ dòng đóng phí doanh nghiệp.

    Đây là cách duy nhất phát hiện sớm việc đổi tên cấu trúc trong YAML mà phân công cũ bị bỏ lại: khi đó HRMS vẫn tính
    lương ra số nhưng không có dòng nào của phía doanh nghiệp, nên chi phí thực và tệp xuất đều thiếu.
    """
    from tlc_hr.infrastructure.customizing.loader import load_bundle

    specification = load_bundle().payroll
    if not specification:
        return (False, "Phân công cấu trúc lương theo khai báo", "payroll.yaml không khai báo cấu trúc nào")
    structure = specification.structure.name
    declared = len(specification.structure.employer_contributions or [])
    have = frappe.db.count("Salary Detail", {"parent": structure, "parentfield": "employer_contributions",
                                             "parenttype": "Salary Structure"})
    if declared and have != declared:
        return (False, "Phân công cấu trúc lương theo khai báo",
                f"{structure}: khai báo {declared} dòng đóng góp doanh nghiệp, site có {have}")
    first = datetime.date.today().replace(day=1)
    rows = frappe.db.sql(
        """select x.employee, x.salary_structure from `tabSalary Structure Assignment` x
           join `tabEmployee` e on e.name = x.employee
           where x.docstatus = 1 and e.status = 'Active' and e.company = x.company
             and x.from_date = (select max(y.from_date) from `tabSalary Structure Assignment` y
                                where y.employee = x.employee and y.docstatus = 1 and y.from_date <= %s)""",
        (first,), as_dict=True)
    stale = sorted({f"{r.employee} → {r.salary_structure}" for r in rows if r.salary_structure != structure})
    return (not stale, "Phân công cấu trúc lương theo khai báo",
            f"{len(stale)} phân công còn ở cấu trúc cũ: " + ", ".join(stale[:6]) if stale else "")

