"""Frappe implementations of the ports the overtime use cases need."""

from collections import defaultdict
from datetime import date

import frappe
from frappe.utils import flt, getdate

from tlc_hr.domain.overtime import Proposer
from tlc_hr.domain.ports import ICalendar, IDirectory, INotifier, IOvertimeRepository
from tlc_hr.domain.shared import CANCELLED, REJECTED

OVERTIME = "TLC Overtime Request"


class FrappeOvertimeRepository(IOvertimeRepository):
    def live_hours(self, employee, year, exclude):
        rows = frappe.get_all(OVERTIME, filters={"employee": employee, "name": ["!=", exclude or ""], "docstatus": ["<", 2],
                                                 "workflow_state": ["not in", (REJECTED, CANCELLED)],
                                                 "ot_date": ["between", [f"{year}-01-01", f"{year}-12-31"]]},
                              fields=["ot_date", "hours"])
        return [(getdate(r.ot_date), flt(r.hours)) for r in rows]

    def approved_hours(self, employee, start, end):
        hours = defaultdict(float)
        for r in frappe.get_all(OVERTIME, filters={"employee": employee, "docstatus": 1, "ot_date": ["between", [start, end]]},
                                fields=["ot_date", "hours"]):
            hours[getdate(r.ot_date)] += flt(r.hours)
        return dict(hours)


class FrappeCalendar(ICalendar):
    def weekly_off(self, employee, day: date):
        from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

        holiday_list = get_holiday_list_for_employee(employee, raise_exception=False)
        if not holiday_list:
            return None
        weekly_off = frappe.db.get_value("Holiday", {"parent": holiday_list, "holiday_date": day}, "weekly_off")
        return None if weekly_off is None else bool(weekly_off)


class FrappeDirectory(IDirectory):
    def proposer(self, user, employee):
        approver, department = frappe.db.get_value("Employee", employee, ["leave_approver", "department"])
        head = frappe.db.get_value("Department", department, "tlc_head") if department else None
        head_user = frappe.db.get_value("Employee", head, "user_id") if head else None
        return Proposer(user=user, roles=frozenset(frappe.get_roles(user)), is_line_manager=user == approver,
                        is_department_head=bool(head_user) and user == head_user, above_in_reporting_line=employee in scope_of(user))

    def user_of(self, employee):
        return frappe.db.get_value("Employee", employee, "user_id")


def scope_of(user):
    """Employees below a user in the reporting tree, and the user's own record."""
    me = frappe.db.get_value("Employee", {"user_id": user})
    if not me:
        return []
    return [me] + (frappe.db.get_descendants("Employee", me) or [])


class FrappeNotifier(INotifier):
    def notify(self, user, subject, message, doctype, name):
        if not user:
            return
        frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "document_type": doctype, "document_name": name,
                        "subject": subject, "from_user": frappe.session.user}).insert(ignore_permissions=True)
        # A workflow may address a User id that is not an email (or has none): the bell is enough.
        recipient = user if "@" in user else (frappe.db.get_value("User", user, "email") or "")
        if "@" not in recipient:
            return
        try:
            frappe.sendmail(recipients=[recipient], subject=subject, message=message, reference_doctype=doctype, reference_name=name)
        except Exception as exc:
            # Mail is a courtesy; an unusable outgoing server must not block the approval itself.
            frappe.logger("tlc_hr.notify").warning(f"{doctype} {name} -> {recipient}: {exc}")
