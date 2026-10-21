"""Kỳ công tháng: HR tổng hợp, trưởng nhà máy xác nhận (khối nhà máy), HR đối soát, CEO ký và khoá.

The summary is rebuilt while the period is a draft; leaving the draft and signing need a month with nothing left open
(attendance/period.open_items). Signing submits the document, which locks the days (attendance/lock.py). Only the CEO reopens a
locked period (cancel, with a reason); HR then amends it.
"""

import calendar

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_fullname, now_datetime

from tlc_hr.attendance.period import SCOPES, head_user, open_items, summarize

DRAFT, TO_HEAD, TO_HR, TO_CEO, LOCKED, REOPENED = (
    "Nháp", "Chờ quản lý xác nhận", "Chờ nhân sự đối soát", "Chờ giám đốc ký", "Đã khoá", "Đã mở lại")
COMPANY_WIDE = ("TLC HR Lead", "TLC HR Officer", "TLC Director", "System Manager")
TOTALS = ("present_days", "half_days", "absent_days", "leave_days", "late_count", "ot_hours")


class TLCAttendancePeriod(Document):
    def validate(self):
        if self.scope not in SCOPES:
            frappe.throw(_("Phạm vi phải là một nhà máy hoặc Hội sở."))
        year, month = (int(x) for x in self.period_month.split("-"))
        self.from_date = f"{year}-{month:02d}-01"
        self.to_date = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        self.title = f"Kỳ công {month:02d}/{year} · {self.scope}"
        self.manager_user = head_user(self.scope, self.company)
        self.check_unique()
        if self.workflow_state in (DRAFT, None, ""):
            self.refresh_summary()
        moving = self.has_value_changed("workflow_state") and not self.is_new()
        if moving and self.workflow_state in (TO_HEAD, TO_HR, TO_CEO, LOCKED):
            self.refresh_open_items()
            if self.open_count:
                frappe.throw(_("Còn {0} việc chưa xử lý trong kỳ:<br>{1}").format(self.open_count, self.open_items.replace("\n", "<br>")),
                             title=_("Chưa chốt được kỳ công"))
        if moving and self.workflow_state == DRAFT:
            self.require_reason(_("trả lại kỳ công"))
            self.tlc_rejected_stage = self.get_doc_before_save().workflow_state
            self.refresh_summary()

    def require_reason(self, what):
        if not (self.tlc_reject_reason or "").strip():
            frappe.throw(_("Nhập lý do trước khi {0}.").format(what), title=_("Thiếu lý do"))

    def check_unique(self):
        other = frappe.db.get_value("TLC Attendance Period", {"company": self.company, "scope": self.scope, "period_month": self.period_month,
                                                              "docstatus": ["<", 2], "name": ["!=", self.name or ""]})
        if other:
            frappe.throw(_("Đã có {0} cho phạm vi và tháng này.").format(other))

    def refresh_summary(self):
        self.set("rows", summarize(self.scope, self.company, self.from_date, self.to_date))
        self.employee_count = len(self.rows)
        for field in TOTALS:
            self.set(field, sum(flt(r.get(field)) for r in self.rows))
        self.refresh_open_items()

    def refresh_open_items(self):
        items = open_items(self.scope, self.company, self.from_date, self.to_date)
        self.open_count = len(items)
        self.open_items = "\n".join(f"{name} · {person or ''} · {text}" for _doctype, name, person, text in items)

    def on_submit(self):
        self.db_set({"locked_at": now_datetime(), "locked_by": frappe.session.user})
        self.add_comment("Info", _("{0} ký và khoá kỳ công. Dữ liệu công của {1} người không sửa trực tiếp được nữa.").format(
            get_fullname(frappe.session.user), self.employee_count))

    def before_cancel(self):
        self.require_reason(_("mở lại kỳ công đã khoá"))

    def on_cancel(self):
        self.add_comment("Info", _("{0} mở lại kỳ công. Lý do: {1}").format(get_fullname(frappe.session.user), self.tlc_reject_reason))


@frappe.whitelist()
def refresh(name):
    """Button "Làm mới tổng hợp": rebuild the summary of a draft period from attendance, overtime and corrections."""
    doc = frappe.get_doc("TLC Attendance Period", name)
    doc.check_permission("write")
    if doc.workflow_state not in (DRAFT, None, ""):
        frappe.throw(_("Chỉ làm mới kỳ công đang Nháp."))
    doc.save()
    return doc.as_dict()


def has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if set(frappe.get_roles(user)).intersection(COMPANY_WIDE):
        return True
    return doc.manager_user == user


def query_conditions(user=None):
    user = user or frappe.session.user
    if set(frappe.get_roles(user)).intersection(COMPANY_WIDE):
        return ""
    return f"`tabTLC Attendance Period`.manager_user = {frappe.db.escape(user)}"
