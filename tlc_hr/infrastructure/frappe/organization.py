"""Frappe persistence for additive TLC organization records."""
from datetime import timedelta

import frappe
from frappe.utils import getdate

from tlc_hr.domain.organization import Assignment, Period, validate_reporting, validate_tree
from tlc_hr.domain.shared import DomainError


def period(row):
    return Period(getdate(row.start_date), getdate(row.end_date) if row.end_date else None)


class FrappeOrganizationRepository:
    def assignments(self, employee):
        rows = frappe.get_all("TLC Organization Assignment", filters={"employee": employee}, fields=[
            "name", "employee", "department", "position", "start_date", "end_date", "is_primary"])
        return [Assignment(r.name, r.employee, r.department, r.position, period(r), bool(r.is_primary)) for r in rows]

    def active_employees(self, position, day):
        rows = frappe.get_all("TLC Organization Assignment", filters={"position": position},
                              fields=["employee", "start_date", "end_date"])
        candidates = {r.employee for r in rows if period(r).contains(day)}
        if not candidates:
            return []
        return frappe.get_all("Employee", filters={"name": ["in", list(candidates)], "status": "Active"}, pluck="name")

    def approval_users(self, employee, department, day):
        rows = frappe.get_all("TLC Organization Reporting Line", filters={"department": department},
                              fields=["employee", "leader", "start_date", "end_date"])
        leaders = {r.leader for r in rows if (not r.employee or r.employee == employee)
                   and r.leader != employee and period(r).contains(day)}
        if not leaders:
            return []
        employees = frappe.get_all("Employee", filters={"name": ["in", list(leaders)], "status": "Active"}, fields=["user_id"])
        users = [r.user_id for r in employees if r.user_id]
        return frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="name") if users else []

    def validate_reporting(self, doc):
        rows = frappe.get_all("TLC Organization Reporting Line", filters={"name": ["!=", doc.name]},
                              fields=["employee", "leader", "department", "start_date", "end_date"])
        rows.append(doc)
        boundaries = {getdate(r.start_date) for r in rows}
        boundaries.update(getdate(r.end_date) + timedelta(days=1) for r in rows if r.end_date and getdate(r.end_date).year < 9999)
        assignments = frappe.get_all("TLC Organization Assignment", fields=["employee", "department", "start_date", "end_date"])
        boundaries.update(getdate(r.start_date) for r in assignments)
        boundaries.update(getdate(r.end_date) + timedelta(days=1) for r in assignments if r.end_date and getdate(r.end_date).year < 9999)
        employees = frappe.get_all("Employee", fields=["name", "department"])
        for day in boundaries:
            edges = []
            for row in rows:
                if not period(row).contains(day):
                    continue
                subjects = {row.employee} if row.employee else (
                    {e.name for e in employees if e.department == row.department}
                    | {a.employee for a in assignments if a.department == row.department and period(a).contains(day)})
                edges.extend((subject, row.leader) for subject in subjects if row.employee or subject != row.leader)
            validate_reporting(edges)

    def validate_change(self, doc):
        rows = frappe.get_all("Department", filters={"company": doc.company}, fields=["name", "parent_department"])
        parents = {r.name: r.parent_department for r in rows}
        for row in doc.changes:
            if row.source_department not in parents or row.target_department not in parents:
                raise DomainError("org.change_company", "Đơn vị nguồn và đích phải cùng công ty của thay đổi.")
            if row.new_parent and row.new_parent not in parents:
                raise DomainError("org.change_parent", "Đơn vị cha phải cùng công ty.")
            parents[row.target_department] = row.new_parent
        validate_tree(parents)

    def apply_change(self, doc, today):
        if doc.docstatus != 1 or doc.applied_on or getdate(doc.effective_date) > today:
            return
        self.validate_change(doc)
        # Save native Department documents so NestedSet maintains lft/rgt.
        for row in doc.changes:
            target = frappe.get_doc("Department", row.target_department)
            if (target.parent_department or "") != (row.previous_parent or "") or target.department_name != row.previous_title:
                raise DomainError("org.stale_change", "Cơ cấu đã thay đổi sau khi duyệt; cần lập quyết định mới.")
        pending = {r.target_department: r for r in doc.changes}
        while pending:
            progressed = False
            for name, row in list(pending.items()):
                # Parents are moved before children; final topology was checked above.
                if row.new_parent in pending:
                    continue
                target = frappe.get_doc("Department", name)
                target.parent_department = row.new_parent or None
                if row.new_title:
                    target.department_name = row.new_title
                target.save(ignore_permissions=True)
                del pending[name]
                progressed = True
            if not progressed:
                raise DomainError("org.change_order", "Không thể áp dụng thứ tự đơn vị cha/con.")
        frappe.db.set_value(doc.doctype, doc.name, "applied_on", today)
