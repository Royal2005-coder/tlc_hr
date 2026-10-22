"""Frappe implementation of the attendance port."""

from collections import defaultdict

import frappe
from frappe.utils import flt, getdate

from tlc_hr.domain.attendance import Mark, Person, scope_of_department
from tlc_hr.domain.attendance_ports import IAttendanceRepository

PENDING = ("Chờ quản lý duyệt", "Chờ nhân sự duyệt")
PENDING_OVERTIME = ("Chờ người lao động đồng ý", "Chờ giám đốc duyệt")
PERIOD = "TLC Attendance Period"


class FrappeAttendanceRepository(IAttendanceRepository):

    def factories(self):
        from tlc_hr.setup.attendance import SITE_OF_DEPARTMENT

        return tuple(SITE_OF_DEPARTMENT)

    def tracking_on(self):
        return bool(frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking"))

    def located(self, employee, shift, at):
        return bool(frappe.get_all("Shift Assignment", filters={"employee": employee, "shift_type": shift, "docstatus": 1, "status": "Active",
                                                                "start_date": ["<=", getdate(at)], "shift_location": ["is", "set"]},
                                   or_filters=[["end_date", ">=", getdate(at)], ["end_date", "is", "not set"]], limit=1))

    def locked_period(self, employee, start, end):
        company, department = frappe.db.get_value("Employee", employee, ["company", "department"])
        found = frappe.db.get_value(PERIOD, {"docstatus": 1, "company": company, "scope": scope_of_department(department, self.factories()),
                                             "from_date": ["<=", getdate(end or start)], "to_date": [">=", getdate(start)]},
                                    ["name", "title"], as_dict=True)
        return (found.name, found.title) if found else None

    def shift_of(self, employee, day):
        return (frappe.db.get_value("Attendance", {"employee": employee, "attendance_date": day, "docstatus": 1}, "shift")
                or frappe.db.get_value("Employee", employee, "default_shift"))

    def people(self, company, scope, start):
        rows = frappe.get_all("Employee", filters={"company": company, "status": ["in", ["Active", "Left"]]},
                              fields=["name", "employee_name", "department", "status", "relieving_date"], order_by="employee_name")
        factories = self.factories()
        return [Person(r.name, r.employee_name, r.department) for r in rows
                if scope_of_department(r.department, factories) == scope
                and (r.status == "Active" or (r.relieving_date and getdate(r.relieving_date) >= getdate(start)))]

    def head_user(self, company, scope):
        if scope not in self.factories():
            return None
        abbr = frappe.db.get_value("Company", company, "abbr")
        head = frappe.db.get_value("Department", f"{scope} - {abbr}", "tlc_head")
        return frappe.db.get_value("Employee", head, "user_id") if head else None

    def marks(self, employees, start, end):
        return [Mark(a.employee, a.status, bool(a.late_entry), bool(a.early_exit)) for a in frappe.get_all(
            "Attendance", filters={"employee": ["in", employees or [""]], "docstatus": 1, "attendance_date": ["between", [start, end]]},
            fields=["employee", "status", "late_entry", "early_exit"])]

    def approved_overtime(self, employees, start, end):
        return [(o.employee, flt(o.hours)) for o in frappe.get_all(
            "TLC Overtime Request", filters={"employee": ["in", employees or [""]], "docstatus": 1, "ot_date": ["between", [start, end]]},
            fields=["employee", "hours"])]

    def approved_corrections(self, employees, start, end):
        return frappe.get_all("Attendance Request", filters={"employee": ["in", employees or [""]], "docstatus": 1, "from_date": ["<=", end],
                                                             "to_date": [">=", start]}, pluck="employee")

    def open_items(self, employees, start, end):
        names = {e.name: e.employee_name for e in frappe.get_all("Employee", filters={"name": ["in", employees or [""]]},
                                                                 fields=["name", "employee_name"])}
        items = []
        overlap = {"employee": ["in", employees or [""]], "docstatus": 0, "from_date": ["<=", end], "to_date": [">=", start]}
        for doctype, label in (("Leave Application", "Đơn nghỉ chưa duyệt xong"), ("Attendance Request", "Giải trình công chưa duyệt xong")):
            for d in frappe.get_all(doctype, filters={**overlap, "workflow_state": ["in", PENDING]}, fields=["name", "employee", "workflow_state"]):
                items.append(f"{d.name} · {names.get(d.employee, '')} · {label} ({d.workflow_state})")
        for d in frappe.get_all("TLC Overtime Request", filters={"employee": ["in", employees or [""]], "docstatus": 0,
                                                                 "workflow_state": ["in", PENDING_OVERTIME], "ot_date": ["between", [start, end]]},
                                fields=["name", "employee", "workflow_state"]):
            items.append(f"{d.name} · {names.get(d.employee, '')} · Tăng ca chưa duyệt xong ({d.workflow_state})")
        for d in frappe.get_all("Travel Request", filters={
            "employee": ["in", employees or [""]], "docstatus": ["<", 2],
            "tlc_from_date": ["<=", end], "tlc_to_date": [">=", start],
            "workflow_state": ["in", ["Chờ quản lý duyệt", "Chờ giám đốc duyệt", "Đã duyệt", "Chờ quản lý duyệt báo cáo", "Chờ giám đốc duyệt báo cáo", "Bổ sung báo cáo"]],
        }, fields=["name", "employee", "workflow_state"]):
            items.append(f"{d.name} · {names.get(d.employee, '')} · Công tác chưa hoàn tất báo cáo ({d.workflow_state})")
        unprocessed = defaultdict(int)
        for c in frappe.get_all("Employee Checkin", filters={"employee": ["in", employees or [""]], "skip_auto_attendance": 0,
                                                             "attendance": ["is", "not set"],
                                                             "time": ["between", [f"{start} 00:00:00", f"{end} 23:59:59.999999"]]},
                                fields=["employee"]):
            unprocessed[c.employee] += 1
        items += [f"{e} · {names.get(e, '')} · {n} lần chấm công chưa ghi vào bảng công" for e, n in unprocessed.items()]
        return items

    def other_period(self, key, name):
        return frappe.db.get_value(PERIOD, {"company": key.company, "scope": key.scope, "period_month": key.month, "docstatus": ["<", 2],
                                            "name": ["!=", name or ""]})

