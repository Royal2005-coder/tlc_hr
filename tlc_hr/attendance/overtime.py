"""Overtime Slip (doc_events validate): HRMS takes the hours past the shift from Attendance; TLC pays only what was approved.

Each day of the slip is cut to the hours of the worker's approved TLC Overtime Requests on that day; days without an approved
request are dropped (staying late without a request is not overtime). The slip says what it cut so HR can explain it.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate


def approved_hours(employee, start, end):
    rows = frappe.get_all("TLC Overtime Request", filters={"employee": employee, "docstatus": 1, "ot_date": ["between", [start, end]]},
                          fields=["ot_date", "hours"])
    hours = defaultdict(float)
    for row in rows:
        hours[getdate(row.ot_date)] += flt(row.hours)
    return hours


def cap_to_approved(doc, method=None):
    if not doc.overtime_details:
        return
    allowed = approved_hours(doc.employee, doc.start_date, doc.end_date)
    kept, notes = [], []
    for row in doc.overtime_details:
        day, cap = getdate(row.date), allowed.get(getdate(row.date), 0)
        if cap <= 0:
            notes.append(_("{0}: {1:g} giờ ngoài ca không có đơn tăng ca được duyệt, không tính").format(frappe.format(day, "Date"), flt(row.overtime_duration)))
            continue
        if flt(row.overtime_duration) > cap:
            notes.append(_("{0}: {1:g} giờ ngoài ca, chỉ tính {2:g} giờ đã duyệt").format(frappe.format(day, "Date"), flt(row.overtime_duration), cap))
            row.overtime_duration = cap
        kept.append(row)
    for idx, row in enumerate(kept, 1):
        row.idx = idx
    doc.overtime_details = kept
    if doc.meta.has_field("total_overtime_duration"):
        doc.total_overtime_duration = sum(flt(r.overtime_duration) for r in kept)
    if notes:
        frappe.msgprint("<br>".join(notes), title=_("Giờ tăng ca được tính theo đơn đã duyệt"), indicator="orange")
