"""Check-in rules of TLC on top of HRMS (doc_events Employee Checkin validate).

HRMS checks the distance only when the check-in falls in a shift whose assignment has a work site, and passes silently otherwise.
TLC closes those gaps: a check-in must fall in one of the person's shifts and that shift must be assigned at a work site.
"""

import frappe
from frappe import _


def validate(doc, method=None):
    if not frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking"):
        return
    if not doc.shift:
        frappe.throw(_("Giờ này không thuộc ca làm việc nào của bạn. Liên hệ quản lý nếu bạn được điều động làm ca khác."),
                     title=_("Ngoài giờ ca"))
    located = frappe.get_all(
        "Shift Assignment",
        filters={"employee": doc.employee, "shift_type": doc.shift, "docstatus": 1, "status": "Active",
                 "start_date": ["<=", doc.time], "shift_location": ["is", "set"]},
        or_filters=[["end_date", ">=", doc.time], ["end_date", "is", "not set"]],
        limit=1,
    )
    if not located:
        frappe.throw(_("Ca {0} của bạn chưa được gắn địa điểm làm việc nên không thể chấm công. Liên hệ phòng Nhân sự.").format(doc.shift),
                     title=_("Chưa có địa điểm chấm công"))
