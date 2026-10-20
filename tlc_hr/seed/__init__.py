"""TLC demo seed for Frappe HR: company, sites as departments, jobs, people, users, roles, leave.

Source: seed/tlc_demo.json, converted from the SeedPack tlc-hrm-demo of the Odoo stage (made-up people, e-mail demo.example, money).
Run: bench --site <site> execute tlc_hr.seed.run   (idempotent: existing records are kept)
The demo password comes from the environment variable DEMO_PASSWORD (Secret tlc-hr, key demo-password); it is never written to Git.
"""

import json
import os
import random
from pathlib import Path

import frappe
from frappe.utils import add_days, add_years, getdate, nowdate

from tlc_hr.setup.roles import FRAPPE_ROLES_OF, ensure_roles

COMPANY = "TLC Demo"
ABBR = "TLC"
EMAIL_DOMAIN = "demo.example"
SEED_FILE = Path(__file__).with_name("tlc_demo.json")
LEAVE_TYPE_NAMES = {"annual": "Phép năm", "sick": "Nghỉ ốm"}


def load():
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def run():
    """Create the whole demo step by step; each finished step is committed, so a rerun continues where a failure stopped."""
    data = load()
    for step in (setup_company, holidays, departments, designations, people, leave):
        step(data)
        frappe.db.commit()
        print("seed:", step.__name__, "done")


def setup_company(data):
    """Finish the setup wizard once (Vietnam, VND, Asia/Ho_Chi_Minh); later runs only check that the company exists."""
    ensure_roles()
    if frappe.db.exists("Company", COMPANY):
        return
    from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

    year = getdate(nowdate()).year
    setup_complete({
        "language": "English",
        "country": "Vietnam",
        "timezone": "Asia/Ho_Chi_Minh",
        "currency": "VND",
        "company_name": COMPANY,
        "company_abbr": ABBR,
        "chart_of_accounts": "Standard",
        "fy_start_date": f"{year}-01-01",
        "fy_end_date": f"{year}-12-31",
        "full_name": "Quản trị TLC",
        "email": f"admin@{EMAIL_DOMAIN}",
        "setup_demo": 0,
    })
    frappe.db.commit()
    if not frappe.db.exists("Company", COMPANY):
        frappe.throw(f"setup wizard finished without creating {COMPANY}")
    frappe.db.set_single_value("System Settings", "language", "vi")


def holidays(data):
    """Holiday list of the year: Saturdays and Sundays off plus the demo public holidays; default list of the company."""
    year = getdate(nowdate()).year
    name = f"TLC {year}"
    if not frappe.db.exists("Holiday List", name):
        holiday_list = frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": name,
                                       "from_date": f"{year}-01-01", "to_date": f"{year}-12-31"})
        for day in ("Saturday", "Sunday"):
            holiday_list.weekly_off = day
            holiday_list.get_weekly_off_dates()
        for holiday in data.get("holidays", []):
            if str(holiday["date"]).startswith(str(year)):
                holiday_list.append("holidays", {"holiday_date": holiday["date"], "description": holiday["name"]})
        holiday_list.insert()
    frappe.db.set_value("Company", COMPANY, "default_holiday_list", name)


def department_name(code, data):
    dept = next(d for d in data["departments"] if d["code"] == code)
    return f"{dept['name']} - {ABBR}"


def departments(data):
    for dept in data["departments"]:
        if not frappe.db.exists("Department", department_name(dept["code"], data)):
            frappe.get_doc({"doctype": "Department", "department_name": dept["name"], "company": COMPANY,
                            "parent_department": "All Departments"}).insert()


def designations(data):
    for job in data["jobs"]:
        if not frappe.db.exists("Designation", job["name"]):
            frappe.get_doc({"doctype": "Designation", "designation_name": job["name"]}).insert()


def expand_people(data):
    """Named people plus the bulk rows (prefix01, prefix02 ...) with a stable made-up name and a wage inside the given range."""
    rows = [dict(p) for p in data["people"]]
    rng = random.Random(20261020)
    first_names = ["An", "Bình", "Chi", "Dũng", "Giang", "Hạnh", "Khoa", "Linh", "Minh", "Ngọc", "Phúc", "Quyên", "Sơn", "Trang", "Uyên", "Việt"]
    family_names = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi"]
    for bulk in data.get("bulk", []):
        low, high = bulk["wage"]
        for i in range(1, bulk["count"] + 1):
            rows.append({"key": f"{bulk['prefix']}{i:02d}",
                         "name": f"{rng.choice(family_names)} Văn {rng.choice(first_names)}",
                         "department": bulk["department"], "job": bulk["job"], "manager": bulk["manager"],
                         "wage": round(rng.randint(low, high), -5), "workforce": bulk.get("workforce", "head_office")})
    return rows


def email_of(key):
    return f"{key}@{EMAIL_DOMAIN}"


def people(data):
    """Users first (with their roles), then employees ordered so that every manager exists before the people reporting to them."""
    jobs = {job["code"]: job["name"] for job in data["jobs"]}
    rows = expand_people(data)
    password = os.environ.get("DEMO_PASSWORD")
    by_key = {row["key"]: row for row in rows}
    for row in rows:
        user_for(row, password)
    created, pending = {}, list(rows)
    while pending:
        ready = [row for row in pending if not row.get("manager") or row["manager"] in created]
        if not ready:
            frappe.throw("manager loop in the seed people: " + ", ".join(row["key"] for row in pending))
        for row in ready:
            boss = row.get("manager")
            created[row["key"]] = employee_for(row, jobs, data, created.get(boss), by_key.get(boss))
            pending.remove(row)
    for dept in data["departments"]:
        head = created.get(dept.get("manager"))
        if head:
            frappe.db.set_value("Department", department_name(dept["code"], data), "tlc_head", head)


def user_for(row, password):
    email = email_of(row["key"])
    if frappe.db.exists("User", email):
        return
    family, _, given = row["name"].rpartition(" ")
    user = frappe.get_doc({"doctype": "User", "email": email, "first_name": given, "last_name": family,
                           "language": "vi", "time_zone": "Asia/Ho_Chi_Minh", "send_welcome_email": 0,
                           "user_type": "System User"})
    user.flags.no_welcome_mail = True
    if password:
        user.new_password = password
    user.insert(ignore_permissions=True)
    roles = {"Employee", "Employee Self Service"}
    for tlc_role in row.get("roles", []):
        roles.update(FRAPPE_ROLES_OF.get(tlc_role, ()))
    user.add_roles(*sorted(roles))


def employee_for(row, jobs, data, manager_employee, manager_row):
    existing = frappe.db.get_value("Employee", {"user_id": email_of(row["key"])})
    if existing:
        return existing
    family, _, given = row["name"].rpartition(" ")
    seq = sum(ord(c) for c in row["key"])
    employee = frappe.get_doc({
        "doctype": "Employee", "first_name": given, "last_name": family,
        "gender": "Female" if " Thị " in row["name"] else "Male",
        "date_of_birth": add_years(getdate("1990-01-01"), -(seq % 15)),
        "date_of_joining": add_days(getdate(nowdate()), -400 - seq % 900),
        "company": COMPANY, "status": "Active", "user_id": email_of(row["key"]),
        "department": department_name(row["department"], data), "designation": jobs[row["job"]],
        "reports_to": manager_employee, "ctc": row.get("wage", 0) * 12, "salary_currency": "VND",
        "holiday_list": frappe.db.get_value("Company", COMPANY, "default_holiday_list"),
        "tlc_key": row["key"], "tlc_workforce": row.get("workforce", "head_office"),
        "tlc_dependents": row.get("dependents", 0), "tlc_monthly_wage": row.get("wage", 0),
    })
    if manager_row:
        employee.leave_approver = email_of(manager_row["key"])
        employee.expense_approver = email_of(manager_row["key"])
    employee.insert()
    return employee.name


def leave(data):
    """Leave types of the seed and the annual allocation of the year for every active employee."""
    for leave_type in data.get("leave_types", []):
        name = LEAVE_TYPE_NAMES.get(leave_type["code"], leave_type["name"])
        if not frappe.db.exists("Leave Type", name):
            frappe.get_doc({"doctype": "Leave Type", "leave_type_name": name,
                            "max_leaves_allowed": 12 if leave_type["code"] == "annual" else 0,
                            "include_holiday": 0, "is_lwp": 0}).insert()
    year = getdate(nowdate()).year
    for allocation in data.get("allocations", []):
        leave_type = LEAVE_TYPE_NAMES.get(allocation["leave_type"], allocation["leave_type"])
        for employee in frappe.get_all("Employee", filters={"company": COMPANY, "status": "Active"}, pluck="name"):
            if frappe.db.exists("Leave Allocation", {"employee": employee, "leave_type": leave_type, "docstatus": 1}):
                continue
            frappe.get_doc({"doctype": "Leave Allocation", "employee": employee, "leave_type": leave_type,
                            "from_date": f"{year}-01-01", "to_date": f"{year}-12-31",
                            "new_leaves_allocated": allocation["days"]}).submit()
