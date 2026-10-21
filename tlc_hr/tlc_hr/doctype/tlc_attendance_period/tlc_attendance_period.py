"""Kỳ công tháng: HR tổng hợp, trưởng nhà máy xác nhận (khối nhà máy), HR đối soát, CEO ký và khoá.

The rules live in domain/attendance.py and application/attendance.py; this controller only hands the document to the adapter.
"""

from frappe.model.document import Document

from tlc_hr.interface import attendance


class TLCAttendancePeriod(Document):
    def validate(self):
        attendance.period_validate(self)

    def on_submit(self):
        attendance.period_on_submit(self)

    def before_cancel(self):
        attendance.period_before_cancel(self)

    def on_cancel(self):
        attendance.period_on_cancel(self)
