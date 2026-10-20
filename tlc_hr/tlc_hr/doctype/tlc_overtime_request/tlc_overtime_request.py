"""Đề nghị tăng ca: the line manager proposes, the worker consents (or refuses with a reason), the director approves.

Hours are checked against the Labour Code limits counting the worker's other requests that are not refused or cancelled.
Approved requests are what payroll pays (base part taxable, premium part exempt from PIT).
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime, getdate, now_datetime

from tlc_hr.vn import labour
from tlc_hr.workflow_rules import no_self_decision, record_rejection

TO_SEND, TO_WORKER, TO_DIRECTOR = "Nháp", "Chờ người lao động đồng ý", "Chờ giám đốc duyệt"
INACTIVE = ("Từ chối", "Đã hủy")
COMPANY_WIDE = ("TLC HR Lead", "TLC HR Officer", "TLC Director", "System Manager")
FIXED = ("employee", "ot_date", "from_time", "to_time", "reason")


class TLCOvertimeRequest(Document):
    def validate(self):
        self.compute_hours()
        self.compute_day_type()
        self.compute_totals()
        problems = labour.check(self.ot_date, self.day_type, self.day_hours, self.month_hours, self.year_hours)
        if problems and self.workflow_state not in INACTIVE:
            frappe.throw("<br>".join(problems), title=_("Vượt giới hạn tăng ca"))
        self.check_requester()
        self.check_fixed()
        if self.has_value_changed("workflow_state") and self.workflow_state == TO_DIRECTOR:
            self.consent_at = now_datetime()
        record_rejection(self)
        before = self.get_doc_before_save()
        if before and before.get("workflow_state") == TO_DIRECTOR:
            no_self_decision(self, self.employee_user)  # consenting is the worker's own decision, approving is not

    def on_update(self):
        if self.has_value_changed("workflow_state") and self.workflow_state == TO_WORKER:
            notify_worker(self)

    def compute_hours(self):
        start = get_datetime(f"{self.ot_date} {self.from_time}")
        end = get_datetime(f"{self.ot_date} {self.to_time}")
        if end <= start:
            end += timedelta(days=1)  # over midnight
        self.hours = round((end - start).total_seconds() / 3600, 2)
        if not self.hours:
            frappe.throw(_("Giờ kết thúc phải sau giờ bắt đầu."))

    def compute_day_type(self):
        from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

        holiday_list = get_holiday_list_for_employee(self.employee, raise_exception=False)
        weekly_off = frappe.db.get_value("Holiday", {"parent": holiday_list, "holiday_date": self.ot_date}, "weekly_off") if holiday_list else None
        self.day_type = labour.WORKING_DAY if weekly_off is None else labour.REST_DAY if weekly_off else labour.HOLIDAY

    def compute_totals(self):
        day = getdate(self.ot_date)
        others = frappe.get_all("TLC Overtime Request", filters={"employee": self.employee, "name": ["!=", self.name or ""],
                                                                 "workflow_state": ["not in", INACTIVE], "docstatus": ["<", 2],
                                                                 "ot_date": ["between", [f"{day.year}-01-01", f"{day.year}-12-31"]]},
                                fields=["ot_date", "hours"])
        self.year_hours = flt(self.hours) + sum(flt(o.hours) for o in others)
        self.day_hours = flt(self.hours) + sum(flt(o.hours) for o in others if getdate(o.ot_date) == day)  # not stored
        self.month_hours = flt(self.hours) + sum(flt(o.hours) for o in others if getdate(o.ot_date).month == day.month)

    def check_requester(self):
        """Only the worker's line manager, the head of their department, HR or the director proposes overtime for them."""
        if not (self.is_new() or (self.has_value_changed("workflow_state") and self.workflow_state == TO_WORKER)):
            return
        user = frappe.session.user
        if set(frappe.get_roles(user)).intersection(COMPANY_WIDE):
            return
        approver, department = frappe.db.get_value("Employee", self.employee, ["leave_approver", "department"])
        head = frappe.db.get_value("Department", department, "tlc_head")
        head_user = frappe.db.get_value("Employee", head, "user_id") if head else None
        if user not in (approver, head_user) and self.employee not in my_scope(user):
            frappe.throw(_("Bạn chỉ đề nghị tăng ca cho người thuộc quyền quản lý của mình."), frappe.PermissionError)


    def check_fixed(self):
        """What the worker consented to is what the director approves: once sent, the request itself does not change."""
        before = self.get_doc_before_save()
        if not before or before.get("workflow_state") in (TO_SEND, None, ""):
            return
        if any(str(before.get(f) or "") != str(self.get(f) or "") for f in FIXED):
            frappe.throw(_("Đơn đã gửi thì không sửa người, ngày, giờ hay lý do. Từ chối đơn này và tạo đơn mới."), title=_("Đơn đã gửi"))


def notify_worker(doc):
    """E-mail and bell notification: the worker is asked to consent."""
    if not doc.employee_user:
        return
    subject = _("Đề nghị tăng ca {0}: {1} giờ ngày {2} cần bạn đồng ý").format(doc.name, f"{doc.hours:g}", frappe.format(doc.ot_date, "Date"))
    frappe.get_doc({"doctype": "Notification Log", "for_user": doc.employee_user, "type": "Alert", "document_type": doc.doctype,
                    "document_name": doc.name, "subject": subject, "from_user": frappe.session.user}).insert(ignore_permissions=True)
    frappe.sendmail(recipients=[doc.employee_user], subject=subject, reference_doctype=doc.doctype, reference_name=doc.name,
                    message=_("{0} đề nghị bạn tăng ca từ {1} đến {2} ngày {3} ({4}). Lý do: {5}. Mở đơn để Đồng ý hoặc Từ chối.").format(
                        frappe.utils.get_fullname(frappe.session.user), doc.from_time, doc.to_time, frappe.format(doc.ot_date, "Date"),
                        doc.day_type, doc.reason))


def my_scope(user):
    """Employees a user may see in overtime requests: themself and everyone below them in the reporting tree."""
    me = frappe.db.get_value("Employee", {"user_id": user})
    if not me:
        return []
    return [me] + (frappe.db.get_descendants("Employee", me) or [])


def query_conditions(user=None):
    user = user or frappe.session.user
    if set(frappe.get_roles(user)).intersection(COMPANY_WIDE):
        return ""
    scope = my_scope(user)
    if not scope:
        return "1=0"
    return "`tabTLC Overtime Request`.employee in ({})".format(", ".join(frappe.db.escape(e) for e in scope))


def has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if set(frappe.get_roles(user)).intersection(COMPANY_WIDE):
        return True
    return doc.employee in my_scope(user)
