"""Đề nghị tăng ca: the line manager proposes, the worker consents (or refuses with a reason), the director approves.

The rules live in domain/overtime.py and application/overtime.py; this controller only hands the document to the adapter.
"""

from frappe.model.document import Document

from tlc_hr.interface import overtime


class TLCOvertimeRequest(Document):
    def validate(self):
        overtime.validate(self)

    def on_update(self):
        overtime.on_update(self)
