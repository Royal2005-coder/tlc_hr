"""Frappe persistence and native HRMS integration for lifecycle evidence."""
import json
from datetime import timedelta
import frappe
from frappe.utils import getdate, now_datetime, today
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
from erpnext.setup.doctype.holiday_list.holiday_list import is_holiday
from tlc_hr.domain.lifecycle import require

SNAPSHOT_FIELDS = ("department", "designation", "reports_to", "branch", "grade", "employment_type", "ctc", "company", "status")


class FrappeLifecycleRepository:
    def is_working(self, employee, day):
        calendar = get_holiday_list_for_employee(employee, as_on=day)
        require(calendar, "LC-CALENDAR", "Nhân viên phải có lịch ngày nghỉ để tính ngày làm việc.")
        return not is_holiday(calendar, day)

    def probation_exists(self, employee, job, excluding):
        return bool(frappe.db.exists("TLC Probation Review", {"employee": employee, "job": job,
                    "name": ["!=", excluding], "docstatus": ["!=", 2]}))

    def completion_blockers(self, doctype, name, employee):
        doc = frappe.get_doc(doctype, name)
        blockers = []
        for row in doc.get("custom_tlc_evidence") or []:
            accepted = ("Received", "Not Applicable") if doctype == "Employee Onboarding" else ("Returned", "Disabled", "Not Applicable")
            if row.required and (row.status not in accepted or not row.confirmed_by or not row.confirmed_on or not row.evidence):
                blockers.append(row.item)
        if not doc.get("custom_tlc_evidence"):
            blockers.append("Chưa có checklist hồ sơ/tài sản/tài khoản")
        for row in doc.activities:
            if not row.task or frappe.db.get_value("Task", row.task, "status") != "Completed":
                blockers.append(row.activity_name)
        if doctype == "Employee Separation":
            from tlc_hr.infrastructure.frappe.people_ops import clearance_blockers
            blockers.extend(clearance_blockers(employee))
            if not doc.get("custom_tlc_decision"):
                blockers.append("Quyết định nghỉ việc")
            if not doc.get("custom_tlc_handover"):
                blockers.append("Biên bản bàn giao")
            if not doc.get("exit_interview") or not doc.get("custom_tlc_rehire_decision"):
                blockers.append("Exit interview và kết luận tái tuyển")
            statement = doc.get("custom_tlc_final_statement")
            if not statement:
                blockers.append("Quyết toán nghỉ việc")
            else:
                ff = frappe.get_doc("Full and Final Statement", statement)
                if ff.employee != employee or ff.docstatus != 1 or ff.status != "Paid":
                    blockers.append("Quyết toán phải cùng nhân viên, đã nộp và đã thanh toán")
        return blockers


def snapshot(employee, source_doctype, source_name, effective):
    """Close the prior effective record and retain the previous snapshot; never overwrite its contents."""
    old = frappe.get_all("TLC Employment Snapshot", filters={"employee": employee, "docstatus": 1,
                         "valid_to": ["is", "not set"]}, fields=["name", "valid_from"])
    for row in old:
        require(getdate(effective) > getdate(row.valid_from), "CORE-ORDER", "Quyết định phải sau ngày hiệu lực bản ghi hiện tại.")
        frappe.db.set_value("TLC Employment Snapshot", row.name, "valid_to", getdate(effective) - timedelta(days=1))
    emp = frappe.get_doc("Employee", employee)
    data = {field: emp.get(field) for field in SNAPSHOT_FIELDS}
    record = frappe.get_doc({"doctype": "TLC Employment Snapshot", "employee": employee,
                            "valid_from": effective, "source_doctype": source_doctype,
                            "source_name": source_name, "snapshot_json": json.dumps(data, ensure_ascii=False, default=str)})
    record.insert(ignore_permissions=True)
    record.flags.ignore_permissions = True
    record.submit()


def apply_change(doc):
    if doc.applied_on or getdate(doc.effective_on) > getdate(today()):
        return
    employee = frappe.get_doc("Employee", doc.employee)
    employee.flags.tlc_approved_change = doc.name
    employee.set(doc.field, doc.new_value)
    employee.save(ignore_permissions=True)
    doc.db_set("applied_on", now_datetime())


def apply_due_changes():
    for name in frappe.get_all("TLC Employee Change Request", filters={"docstatus": 1,
                               "effective_on": ["<=", today()], "applied_on": ["is", "not set"]}, pluck="name"):
        apply_change(frappe.get_doc("TLC Employee Change Request", name))


def verified_dependents(employee, as_of):
    """Payroll/PIT port: return only HR-confirmed deduction records effective on the requested date."""
    rows = frappe.get_all("TLC Employee Dependent", filters={"employee": employee, "docstatus": 1,
                          "status": "Verified", "valid_from": ["<=", as_of]},
                          fields=["name", "dependent_name", "identity_number", "tax_number", "valid_from", "valid_to"])
    return [row for row in rows if not row.valid_to or getdate(row.valid_to) >= getdate(as_of)]


def remind_expiries():
    """Daily native Notification Logs; no assumed email delivery or AI/legal recommendation."""
    apply_due_changes()
    recipients = frappe.get_all("Has Role", filters={"role": ["in", ["TLC HR Lead", "TLC HR Officer"]],
                                "parenttype": "User"}, pluck="parent")
    current = getdate(today())
    for doctype, field in (("TLC Employment Contract", "valid_to"), ("TLC Employee Document", "expires_on"),
                          ("TLC Probation Review", "end_date"), ("Employee Separation", "custom_tlc_settlement_due")):
        for row in frappe.get_all(doctype, filters={"docstatus": ["!=", 2], field: ["is", "set"]}, fields=["name", "employee", field]):
            days = (getdate(row[field]) - current).days
            if days not in (60, 30, 7, 1, 0, -1):
                continue
            employee_user = frappe.db.get_value("Employee", row.employee, "reports_to")
            manager_user = frappe.db.get_value("Employee", employee_user, "user_id") if employee_user else None
            subject = f"{doctype} {row.name}: còn {days} ngày ({row[field]})"
            for user in set(recipients) | ({manager_user} if manager_user else set()):
                if not frappe.db.get_value("User", user, "enabled"):
                    continue
                if frappe.db.exists("Notification Log", {"for_user": user, "subject": subject}):
                    continue
                frappe.get_doc({"doctype": "Notification Log", "subject": subject, "for_user": user,
                                "type": "Alert", "document_type": doctype, "document_name": row.name}).insert(ignore_permissions=True)
