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

from tlc_hr.setup.roles import FRAPPE_ROLES_OF, SELF_SERVICE

COMPANY = "TLC Demo"
ABBR = "TLC"
EMAIL_DOMAIN = "demo.example"
SEED_FILE = Path(__file__).with_name("tlc_demo.json")
LEAVE_TYPE_NAMES = {"annual": "Phép năm", "sick": "Nghỉ ốm"}
# TLC levels that work on other people's records: HRMS must not restrict them to their own employee record.
# Public holidays of Vietnam on a fixed solar date (Bộ luật Lao động, điều 112). Lunar holidays (Tết, Giỗ Tổ) are set by HR every year.
VN_FIXED_HOLIDAYS = [("01-01", "Tết Dương lịch"), ("04-30", "Ngày Chiến thắng"), ("05-01", "Quốc tế Lao động"), ("09-02", "Quốc khánh")]
COMPANY_WIDE_LEVELS = {"director", "cfo", "hr_director", "hr_officer", "period_controller", "payroll_officer", "accountant"}


def load():
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def run():
    """Create the whole demo step by step; each finished step is committed, so a rerun continues where a failure stopped."""
    data = load()
    for step in (setup_company, accounts, holidays, departments, designations, people, payroll_fields, salary_assignments, leave,
                 shifts, checkins, demo_mail, overtime):
        step(data)
        frappe.db.commit()
        print("seed:", step.__name__, "done")
    from tlc_hr.seed import lifecycle, organization, payroll_compliance, people_ops, recruitment, services, travel_finance

    for module in (organization, recruitment, lifecycle, people_ops, payroll_compliance, travel_finance, services):
        module.run(data)
        frappe.db.commit()
        print("seed:", module.__name__, "done")


def setup_company(data):
    """Finish the setup wizard once (Vietnam, VND, Asia/Ho_Chi_Minh); later runs only check that the company exists."""
    from tlc_hr.infrastructure.customizing import engine

    engine.apply()  # roles, workflows, shifts, sites... before the users
    if frappe.db.exists("Company", COMPANY):
        return
    from frappe.desk.page.setup_wizard.setup_wizard import setup_complete
    from erpnextvn.accounting.chart_of_accounts import ensure_patched

    # erpnextvn registers its charts (TT99, TT200, TT133) only per web request; a CLI run must patch them in first.
    ensure_patched()

    year = getdate(nowdate()).year
    result = setup_complete({
        "language": "English",
        "country": "Vietnam",
        "timezone": "Asia/Ho_Chi_Minh",
        "currency": "VND",
        "company_name": COMPANY,
        "company_abbr": ABBR,
        "chart_of_accounts": "Vietnam - Hệ thống tài khoản TT200/2014",
        "fy_start_date": f"{year}-01-01",
        "fy_end_date": f"{year}-12-31",
        "full_name": "Quản trị TLC",
        "email": f"admin@{EMAIL_DOMAIN}",
        "setup_demo": 0,
    })
    frappe.db.commit()
    if not frappe.db.exists("Company", COMPANY):
        # setup_complete rolls back and only logs on failure: surface the logged traceback.
        last = frappe.get_all("Error Log", fields=["method", "error"], order_by="creation desc", limit=1)
        detail = chr(10).join([last[0].method, last[0].error]) if last else "no error log"
        frappe.throw(chr(10).join([f"setup wizard did not create {COMPANY}: {result}", detail]))
    frappe.db.set_single_value("System Settings", "language", "vi")


def accounts(data):
    from tlc_hr.infrastructure.customizing import engine

    engine.apply()  # account types and company defaults once the chart exists


def payroll_fields(data):
    """Employees created before the sync hook: copy wage and dependents into the fields payroll reads (idempotent)."""
    for row in frappe.get_all("Employee", filters={"company": COMPANY},
                              fields=["name", "tlc_monthly_wage", "tlc_dependents", "vn_insurance_salary", "vn_number_of_dependents"]):
        values = {}
        if row.tlc_monthly_wage and not row.vn_insurance_salary:
            values["vn_insurance_salary"] = row.tlc_monthly_wage
        if (row.vn_number_of_dependents or 0) != (row.tlc_dependents or 0):
            values["vn_number_of_dependents"] = row.tlc_dependents or 0
        if values:
            frappe.db.set_value("Employee", row.name, values)


def salary_assignments(data):
    """Assign the declared structure from its effective date without rewriting salary history."""
    from tlc_hr.infrastructure.customizing.loader import load_bundle

    specification = load_bundle().payroll
    if not specification:
        frappe.throw("Chưa khai báo cấu trúc lương TLC trong customizing/payroll.yaml.")
    structure = specification.structure.name
    if not frappe.db.exists("Salary Structure", {"name": structure, "company": COMPANY, "docstatus": 1}):
        frappe.throw(f"Cấu trúc lương {structure} chưa được áp dụng cho {COMPANY}.")
    effective = specification.structure.effective_from or getdate(f"{getdate(nowdate()).year}-01-01")
    for person in frappe.get_all("Employee", filters={"company": COMPANY, "status": "Active"},
                                 fields=["name", "tlc_monthly_wage", "date_of_joining"]):
        if not person.tlc_monthly_wage:
            continue
        start = max(effective, getdate(person.date_of_joining)) if person.date_of_joining else effective
        existing = frappe.db.get_value("Salary Structure Assignment",
                                        {"employee": person.name, "from_date": start, "docstatus": 1},
                                        ["name", "salary_structure"], as_dict=True)
        if existing:
            if existing.salary_structure != structure:
                if frappe.db.exists("Salary Slip", {"salary_structure": existing.salary_structure, "docstatus": 1}):
                    frappe.throw(f"{person.name}: đã có phiếu lương dùng cấu trúc {existing.salary_structure}; "
                                 "không tự đổi cấu trúc đã trả lương.")
                frappe.db.set_value("Salary Structure Assignment", existing.name, "salary_structure", structure)
            continue
        frappe.get_doc({"doctype": "Salary Structure Assignment", "employee": person.name, "salary_structure": structure,
                        "company": COMPANY, "from_date": start, "base": person.tlc_monthly_wage}).insert().submit()


def holidays(data):
    """Holiday lists of this year and next (Saturdays, Sundays and the demo public holidays), assigned to the company.

    HRMS v16 reads holidays from Holiday List Assignment, not from the company default alone.
    """
    this_year = getdate(nowdate()).year
    for year in (this_year, this_year + 1):
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
        holiday_list = frappe.get_doc("Holiday List", name)
        known = {str(h.holiday_date) for h in holiday_list.holidays}
        missing = [(f"{year}-{md}", label) for md, label in VN_FIXED_HOLIDAYS if f"{year}-{md}" not in known]
        for date, label in missing:
            holiday_list.append("holidays", {"holiday_date": date, "description": label, "weekly_off": 0})
        if missing:
            holiday_list.save()
        if not frappe.db.exists("Holiday List Assignment", {"holiday_list": name, "assigned_to": COMPANY, "docstatus": 1}):
            frappe.get_doc({"doctype": "Holiday List Assignment", "applicable_for": "Company", "assigned_to": COMPANY,
                            "holiday_list": name, "from_date": f"{year}-01-01"}).submit()
    frappe.db.set_value("Company", COMPANY, "default_holiday_list", f"TLC {this_year}")


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
                         "wage": round(rng.randint(low, high), -5), "workforce": bulk.get("workforce", "head_office"),
                         "calendar": bulk.get("calendar")})
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
    unrestrict_company_wide(rows)
    route_users(rows)
    fix_user_names(rows)
    for dept in data["departments"]:
        head = created.get(dept.get("manager"))
        if head:
            frappe.db.set_value("Department", department_name(dept["code"], data), "tlc_head", head)


def route_users(rows):
    from tlc_hr.interface.role_navigation import apply_user_route

    for row in rows:
        user = email_of(row["key"])
        workspace = apply_user_route(user)
        roles = set(frappe.get_roles(user))
        doc = frappe.get_doc("User", user)
        if workspace and SELF_SERVICE in roles:
            doc.remove_roles(SELF_SERVICE)
        elif not workspace and SELF_SERVICE not in roles:
            doc.add_roles(SELF_SERVICE)


def is_company_wide(row):
    return bool(COMPANY_WIDE_LEVELS.intersection(row.get("roles", [])))


def unrestrict_company_wide(rows):
    """Remove the own-record User Permission HRMS adds when an employee is linked to a user, for HR and the directors."""
    for row in rows:
        if is_company_wide(row):
            for name in frappe.get_all("User Permission", filters={"user": email_of(row["key"]), "allow": "Employee"}, pluck="name"):
                frappe.delete_doc("User Permission", name, ignore_permissions=True)


def fix_user_names(rows):
    """Users created before the name-order fix: rewrite first and last name (idempotent)."""
    for row in rows:
        family_and_middle, _, given = row["name"].rpartition(" ")
        user = frappe.get_doc("User", email_of(row["key"]))
        if (user.first_name, user.last_name, user.middle_name or "") != (family_and_middle, given, ""):
            user.update({"first_name": family_and_middle, "middle_name": "", "last_name": given})
            user.save(ignore_permissions=True)


def user_for(row, password):
    email = email_of(row["key"])
    if frappe.db.exists("User", email):
        return
    # Frappe shows first_name + last_name: family and middle names go first, the given name last, so the name reads in Vietnamese order
    # (and with both set, ERPNext does not split the employee name again into first, middle and last).
    family_and_middle, _, given = row["name"].rpartition(" ")
    user = frappe.get_doc({"doctype": "User", "email": email, "first_name": family_and_middle or given,
                           "last_name": given if family_and_middle else "",
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
    seq = sum(ord(c) for c in row["key"])
    employee = frappe.get_doc({
        "doctype": "Employee", "first_name": row["name"],
        "gender": "Female" if " Thị " in row["name"] else "Male",
        "date_of_birth": add_years(getdate("1990-01-01"), -(seq % 15)),
        "date_of_joining": add_days(getdate(nowdate()), -400 - seq % 900),
        "company": COMPANY, "status": "Active", "user_id": email_of(row["key"]),
        "create_user_permission": 0 if is_company_wide(row) else 1,
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


def demo_mail(data):
    """Default outgoing Email Account to the mail catcher of the environment (site config tlc_demo_smtp), so notifications work."""
    smtp = frappe.conf.get("tlc_demo_smtp")
    if not smtp:
        return
    name = "TLC Demo Mail"
    values = {"email_account_name": name, "email_id": "hrm@demo.example", "enable_outgoing": 1, "default_outgoing": 1,
              "smtp_server": smtp["server"], "smtp_port": smtp.get("port", 1025), "use_tls": 0, "use_ssl_for_outgoing": 0,
              "no_smtp_authentication": 1, "enable_incoming": 0, "awaiting_password": 0, "always_use_account_email_id_as_sender": 1}
    account = frappe.get_doc("Email Account", name) if frappe.db.exists("Email Account", name) else frappe.new_doc("Email Account")
    account.update(values)
    account.flags.ignore_validate = True
    account.save(ignore_permissions=True) if not account.is_new() else account.insert(ignore_permissions=True)


def shifts(data):
    """Each person works the shift of their calendar at the site of their department (office hours when no calendar)."""
    from tlc_hr.setup.attendance import SHIFT_OF_CALENDAR, assign, site_of
    calendar_of = {row["key"]: row.get("calendar") for row in expand_people(data)}
    for employee in frappe.get_all("Employee", filters={"company": COMPANY, "status": "Active"}, fields=["name", "tlc_key", "department"]):
        shift = SHIFT_OF_CALENDAR.get(calendar_of.get(employee.tlc_key) or "office", "TLC Hành chính")
        assign(employee.name, shift, site_of(employee.department), COMPANY)


# (IN, OUT) of each shift: hour, minute; OUT before IN means the next day
SHIFT_TIMES = {"TLC Hành chính": ((7, 52), (17, 8)), "TLC Ca đêm": ((21, 52), (6, 8)), "TLC Cao điểm": ((6, 52), (19, 8))}
DEMO_DAYS = 10


def checkins(data, days=DEMO_DAYS):
    """Check-ins of everyone for the last working days, at their work site; a few late arrivals and absences (stable random)."""
    import datetime as dt

    from tlc_hr.setup.attendance import site_of, sites

    SITES = sites()

    today = getdate(nowdate())
    first = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)  # last month is a full month to close
    window_start = (first - dt.timedelta(days=1)).replace(day=1)  # and the month before it: a second payable month
    work_days = []
    day = today - dt.timedelta(days=1)
    holidays = set(frappe.get_all("Holiday", filters={"parent": frappe.db.get_value("Company", COMPANY, "default_holiday_list")},
                                  pluck="holiday_date"))
    while len(work_days) < days or day >= window_start:
        if day.weekday() < 5 and day not in holidays:
            work_days.append(day)
        day -= dt.timedelta(days=1)
    work_days.reverse()
    employees = frappe.get_all("Employee", filters={"company": COMPANY, "status": "Active"}, fields=["name", "department", "default_shift"])
    uncovered = []
    for employee in employees:
        shift = employee.default_shift or "TLC Hành chính"
        (in_h, in_m), (out_h, out_m) = SHIFT_TIMES[shift]
        lat, lon, _radius = SITES[site_of(employee.department)]
        for work_day in work_days:
            rng = random.Random(f"{employee.name}/{work_day}")  # the same person and day get the same outcome on every run
            roll = rng.random()
            if roll < 0.02:
                continue  # absent
            late = 25 if roll > 0.95 else 0
            start = dt.datetime.combine(work_day, dt.time(in_h, in_m)) + dt.timedelta(minutes=late + rng.randint(0, 12))
            # idempotent: this shift already has its IN (the OUT of last night's shift falls on this date, so look at IN only)
            window = [start - dt.timedelta(hours=2), start + dt.timedelta(hours=2)]
            if frappe.db.exists("Employee Checkin", {"employee": employee.name, "log_type": "IN", "time": ["between", window]}):
                continue
            end_day = work_day + dt.timedelta(days=1) if out_h < in_h else work_day
            end = dt.datetime.combine(end_day, dt.time(out_h, out_m)) + dt.timedelta(minutes=rng.randint(0, 20))
            try:
                for log_type, when in (("IN", start), ("OUT", end)):
                    frappe.get_doc({"doctype": "Employee Checkin", "employee": employee.name, "log_type": log_type, "time": when,
                                    "latitude": lat + rng.uniform(-0.0004, 0.0004), "longitude": lon + rng.uniform(-0.0004, 0.0004)}).insert()
            except Exception as exc:  # a person hired (or re-shifted) mid-window has no covering shift assignment
                uncovered.append(f"{employee.name} {work_day}: {str(exc)[:70]}")
                break
    if uncovered:
        print(f"checkins: bỏ qua {len(uncovered)} nhân viên chưa có ca phủ ngày (ví dụ {uncovered[0]})")
    first = work_days[0]
    for shift in SHIFT_TIMES:
        doc = frappe.get_doc("Shift Type", shift)
        if not doc.process_attendance_after or getdate(doc.process_attendance_after) > first:  # process from the first demo day
            doc.process_attendance_after = first
        doc.last_sync_of_checkin = frappe.utils.now_datetime()
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        doc.process_auto_attendance()


# (from, to) of the overtime the factory heads propose: after office hours, before the night shift. Peak shifts are already 12 h.
OVERTIME_TIMES = {"TLC Hành chính": ("17:30:00", "20:30:00"), "TLC Ca đêm": ("18:30:00", "21:00:00")}


def overtime(data):
    """Overtime of factory people through the real workflow (head proposes, worker consents, director approves): two approved
    evenings earlier this month, and next week a request waiting for the worker or the director (no e-mail during the seed)."""
    import datetime as dt

    from frappe.model.workflow import apply_workflow

    today = getdate(nowdate())
    last_month = (today.replace(day=1) - dt.timedelta(days=1)).month
    past = [d for d in (today - dt.timedelta(days=n) for n in range(1, 50)) if d.weekday() < 5 and d.month in (today.month, last_month)]
    upcoming = next(d for d in (today + dt.timedelta(days=n) for n in range(7, 14)) if d.weekday() < 5)
    rng = random.Random(20261022)
    workers = frappe.get_all("Employee", filters={"company": COMPANY, "status": "Active", "tlc_workforce": "factory",
                                                  "leave_approver": ["is", "set"], "user_id": ["is", "set"]},
                             fields=["name", "user_id", "leave_approver", "default_shift"], order_by="name")
    frappe.flags.mute_emails = True
    try:
        for i, worker in enumerate(workers):
            times = OVERTIME_TIMES.get(worker.default_shift)
            if not times or "TLC Line Manager" not in frappe.get_roles(worker.leave_approver):
                continue
            plan = [(day, ("Đồng ý", "Duyệt")) for day in rng.sample(past, k=min(4, len(past)))]
            plan.append((upcoming, ((), ("Đồng ý",), None)[i % 3]))
            for day, actions in plan:
                if actions is None or frappe.db.exists("TLC Overtime Request", {"employee": worker.name, "ot_date": day}):
                    continue
                frappe.set_user(worker.leave_approver)
                doc = frappe.get_doc({"doctype": "TLC Overtime Request", "employee": worker.name, "ot_date": day, "from_time": times[0],
                                      "to_time": times[1], "reason": "Đơn hàng cuối tháng"}).insert()
                apply_workflow(doc, "Đề nghị")
                for action, user in zip(actions, (worker.user_id, email_of("thanh"))):
                    frappe.set_user(user)
                    apply_workflow(frappe.get_doc(doc.doctype, doc.name), action)
    finally:
        frappe.set_user("Administrator")
        frappe.flags.mute_emails = False


def reset_overtime_requests():
    """Demo and UAT only: delete every overtime request, then the seed step overtime puts the demo ones back."""
    if not frappe.conf.get("allow_tests") and not frappe.flags.in_test:
        frappe.throw("reset_overtime_requests runs only on a test site (site config allow_tests)")
    names = frappe.get_all("TLC Overtime Request", pluck="name")
    if names:
        frappe.db.delete("Workflow Action", {"reference_doctype": "TLC Overtime Request"})
        frappe.db.delete("Notification Log", {"document_type": "TLC Overtime Request"})
        frappe.db.delete("TLC Overtime Request", {"name": ["in", names]})
    overtime(load())
    frappe.db.commit()
    print(f"reset: {len(names)} overtime requests deleted, demo overtime seeded")


def reset_attendance_periods():
    """Demo and UAT only: delete the attendance periods and the attendance corrections (with the attendance they wrote), then
    let the check-in step mark those days again, so the monthly closing can be run again."""
    if not frappe.conf.get("allow_tests") and not frappe.flags.in_test:
        frappe.throw("reset_attendance_periods runs only on a test site (site config allow_tests)")
    periods = frappe.get_all("TLC Attendance Period", pluck="name")
    requests = frappe.get_all("Attendance Request", filters={"company": COMPANY}, pluck="name")
    for doctype, names in (("TLC Attendance Period", periods), ("Attendance Request", requests)):
        if names:
            frappe.db.delete("Comment", {"reference_doctype": doctype, "reference_name": ["in", names]})
            frappe.db.delete("Workflow Action", {"reference_doctype": doctype, "reference_name": ["in", names]})
            frappe.db.delete(doctype, {"name": ["in", names]})
    frappe.db.delete("TLC Attendance Period Row", {"parent": ["in", periods or [""]]})
    if requests:
        frappe.db.delete("Attendance", {"attendance_request": ["in", requests]})
    frappe.db.commit()  # the closing check reads the period through the cache: the month must be gone first
    checkins(load())
    frappe.db.commit()
    print(f"reset: {len(periods)} attendance periods and {len(requests)} corrections deleted, attendance re-marked")


def reset_payroll():
    """Demo and UAT only: delete the payroll entries of the demo company with their payslips, additional salaries and journal
    entries (ledger rows included), so a month can be computed again."""
    if not frappe.conf.get("allow_tests") and not frappe.flags.in_test:
        frappe.throw("reset_payroll runs only on a test site (site config allow_tests)")
    entries = frappe.get_all("Payroll Entry", filters={"company": COMPANY}, pluck="name")
    slips = frappe.get_all("Salary Slip", filters={"payroll_entry": ["in", entries or [""]]}, pluck="name")
    journals = list({r.parent for r in frappe.get_all("Journal Entry Account", filters={"reference_type": "Payroll Entry",
                                                                                        "reference_name": ["in", entries or [""]]}, fields=["parent"])})
    journals += frappe.get_all("Salary Slip", filters={"name": ["in", slips or [""]], "journal_entry": ["is", "set"]}, pluck="journal_entry")
    journals = sorted(set(journals))
    for table, field, names in (("GL Entry", "voucher_no", journals), ("Payment Ledger Entry", "voucher_no", journals),
                                ("Journal Entry Account", "parent", journals), ("Journal Entry", "name", journals),
                                ("Salary Detail", "parent", slips), ("Salary Slip", "name", slips),
                                ("Additional Salary", "ref_docname", entries), ("Payroll Employee Detail", "parent", entries),
                                ("Workflow Action", "reference_name", entries), ("Comment", "reference_name", entries),
                                ("Payroll Entry", "name", entries)):
        if names:
            frappe.db.delete(table, {field: ["in", names]})
    # A salary decision the UAT filed (base changed from a date inside a month) is demo data too: leaving it
    # behind makes the next run's payroll month a mid-period structure switch, which our own rule refuses.
    decisions = frappe.get_all("Salary Structure Assignment", filters={"company": COMPANY, "tlc_decision_reason": ["is", "set"]}, pluck="name")
    for table, field, names in (("Workflow Action", "reference_name", decisions), ("Comment", "reference_name", decisions),
                                ("Salary Structure Assignment", "name", decisions)):
        if names:
            frappe.db.delete(table, {field: ["in", names]})
    frappe.db.commit()
    # The compliance journey switches PDF encryption on; a reset returns the demo settings to their documented state.
    frappe.db.set_single_value("Payroll Settings", "encrypt_salary_slips_in_emails", 0)
    frappe.db.set_single_value("Payroll Settings", "password_policy", "")
    print(f"reset: {len(entries)} payroll entries, {len(slips)} payslips, {len(journals)} journal entries, {len(decisions)} salary decisions deleted")


def reset_attendance_demo():
    """Demo and test sites only: delete check-ins, attendance (not leave) and shift assignments, so the seed rebuilds them."""
    if not frappe.conf.get("allow_tests") and not frappe.flags.in_test:
        frappe.throw("reset_attendance_demo runs only on a test site (site config allow_tests)")
    frappe.db.delete("Employee Checkin")
    frappe.db.delete("Attendance", {"status": ["!=", "On Leave"]})
    frappe.db.delete("Shift Assignment")
    frappe.db.commit()
    print("reset: attendance demo deleted")


def reset_leave_requests():
    """Demo and UAT only: delete every leave request of the demo company and its ledger entries, so a UAT run starts clean."""
    if not frappe.conf.get("allow_tests") and not frappe.flags.in_test:
        frappe.throw("reset_leave_requests runs only on a test site (site config allow_tests)")
    names = frappe.get_all("Leave Application", filters={"company": COMPANY}, pluck="name")
    if names:
        frappe.db.delete("Leave Ledger Entry", {"transaction_type": "Leave Application", "transaction_name": ["in", names]})
        frappe.db.delete("Workflow Action", {"reference_doctype": "Leave Application", "reference_name": ["in", names]})
        frappe.db.delete("Leave Application", {"name": ["in", names]})
    frappe.db.commit()
    print(f"reset: {len(names)} leave requests deleted")
