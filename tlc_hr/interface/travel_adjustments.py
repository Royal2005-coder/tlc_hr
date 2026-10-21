"""Travel reports change the next payroll, never the locked attendance snapshot."""
from decimal import Decimal

import frappe
from frappe.utils import getdate
from hrms.hr.doctype.attendance_request.attendance_request import AttendanceRequest
from hrms.hr.utils import validate_active_employee, validate_dates

from tlc_hr.domain import travel_finance as rules
from tlc_hr.domain.shared import DomainError
from tlc_hr.infrastructure.frappe.attendance import FrappeAttendanceRepository
from tlc_hr.infrastructure.frappe.payroll import FrappePayrollRepository
from tlc_hr.infrastructure.frappe.travel_finance import money, window_of
from tlc_hr.interface.errors import domain_errors


def validate_generated_correction(doc):
    """Exempt only initial trusted creation from HR authoring, not common approval/lock checks."""
    if not doc.is_new() or not doc.flags.get("tlc_travel_adjustment"):
        return False
    with domain_errors():
        _validate_source(doc)
    return True


def _validate_source(doc):
    if not doc.tlc_travel_request or not doc.tlc_travel_effect_key:
        raise DomainError("travel.adjustment_source", "Thiếu nguồn điều chỉnh công tác.")
    trip = frappe.get_doc("Travel Request", doc.tlc_travel_request)
    day = getdate(doc.from_date)
    if trip.docstatus != 1 or not trip.tlc_approved_on or trip.employee != doc.employee or getdate(doc.to_date) != day:
        raise DomainError("travel.adjustment_scope", "Điều chỉnh phải cùng nhân viên và một ngày thuộc công tác được duyệt.")
    if not FrappeAttendanceRepository().locked_period(doc.employee, day, day):
        raise DomainError("travel.adjustment_lock", "Điều chỉnh công tác sau chốt phải thuộc kỳ đã khóa.")
    planned = dict(window_of(trip).days())
    actual = dict(window_of(trip, actual=True).days()) if trip.get("tlc_report_approved_on") else planned
    if trip.workflow_state == rules.CANCELLED:
        actual = {}
    if day not in set(planned) | set(actual):
        raise DomainError("travel.adjustment_date", "Ngày điều chỉnh nằm ngoài chuyến đi.")
    mark = frappe.db.get_value("Attendance", {"employee": doc.employee, "attendance_date": day, "docstatus": 1},
                               ["tlc_travel_request", "tlc_duty_sessions"], as_dict=True)
    old = (mark.tlc_duty_sessions or "").split(",") if mark and mark.tlc_travel_request == trip.name else []
    sessions = actual.get(day, ())
    delta = Decimal(len(sessions) - len(old)) / 2
    expected_key = f"{trip.name}:{day}:{','.join(sessions)}"
    if money(doc.tlc_workday_delta) != delta or doc.tlc_travel_effect_key != expected_key or not delta:
        raise DomainError("travel.adjustment_delta", "Chênh lệch phải được tính từ báo cáo đã duyệt và ảnh chụp công cũ.")
    if frappe.db.exists("Attendance Request", {"tlc_travel_effect_key": expected_key, "name": ["!=", doc.name]}):
        raise DomainError("travel.adjustment_duplicate", "Điều chỉnh cho nguồn này đã tồn tại.")
    before = doc.get_doc_before_save()
    if before and any(before.get(f) != doc.get(f) for f in ("employee", "from_date", "to_date", "tlc_travel_request",
            "tlc_travel_effect_key", "tlc_workday_delta")):
        raise DomainError("travel.adjustment_fixed", "Không sửa nguồn hoặc số công điều chỉnh tự sinh.")


class TravelAttendanceRequest(AttendanceRequest):
    """Normal HRMS requests are unchanged; signed-delta requests have no historical Attendance side effect."""
    def validate(self):
        if not self.get("tlc_travel_effect_key"):
            return super().validate()
        validate_active_employee(self.employee)
        validate_dates(self, self.from_date, self.to_date, False)
        with domain_errors():
            _validate_source(self)

    def on_submit(self):
        if not self.get("tlc_travel_effect_key"):
            return super().on_submit()
        self.add_comment("Info", f"Đã duyệt {self.tlc_workday_delta} ngày công từ {self.tlc_travel_request}; chuyển kỳ lương tiếp theo, không sửa kỳ khóa.")

    def on_cancel(self):
        if not self.get("tlc_travel_effect_key"):
            return super().on_cancel()
        if self.tlc_adjustment_payroll:
            frappe.throw("Hủy bảng lương đã dùng điều chỉnh trước khi hủy yêu cầu này.")


def pending_adjustments(employee, payroll_start):
    """Approved deltas from earlier periods, serialized against competing payrolls by apply_adjustments."""
    return frappe.get_all("Attendance Request", filters={"employee": employee, "docstatus": 1,
        "workflow_state": "Đã duyệt", "tlc_travel_effect_key": ["is", "set"], "to_date": ["<", payroll_start],
        "tlc_adjustment_payroll": ["is", "not set"]}, fields=["name", "employee", "from_date", "to_date", "tlc_workday_delta"])


def apply_adjustments(entry):
    """Call before generating salary slips. One native Additional Salary per approved source."""
    payroll = FrappePayrollRepository()
    created = []
    for employee_row in entry.employees:
        employee = employee_row.employee
        frappe.db.sql("select name from `tabEmployee` where name=%s for update", employee)
        for correction in pending_adjustments(employee, entry.start_date):
            # Lock and re-read consumption: a second payroll must not pay the same approved delta.
            frappe.db.sql("select name from `tabAttendance Request` where name=%s for update", correction.name)
            source = frappe.get_doc("Attendance Request", correction.name)
            if source.tlc_adjustment_payroll:
                continue
            existing = frappe.db.get_value("Additional Salary", {"tlc_travel_adjustment": source.name, "docstatus": ["<", 2]}, "name")
            if existing:
                salary = frappe.get_doc("Additional Salary", existing)
                if salary.ref_docname != entry.name:
                    frappe.throw(f"{source.name} đã được phân bổ bảng lương {salary.ref_docname}.")
            else:
                # Historical wage and working-day denominator preserve the source period's value.
                original_start = getdate(source.from_date).replace(day=1)
                import calendar
                original_end = original_start.replace(day=calendar.monthrange(original_start.year, original_start.month)[1])
                days = payroll.working_days(employee, original_start, original_end)
                if days <= 0:
                    frappe.throw(f"Không có ngày công chuẩn để định giá {source.name}.")
                base = money(payroll.base_salary(employee, source.from_date))
                delta = Decimal(str(source.tlc_workday_delta))
                amount = (base * abs(delta) / Decimal(days)).quantize(Decimal("1"))
                if amount <= 0:
                    frappe.throw(f"Thiếu mức lương hoặc số điều chỉnh hợp lệ cho {source.name}.")
                component = "Điều chỉnh công sau chốt" if delta > 0 else "Khấu trừ công sau chốt"
                salary = frappe.get_doc({"doctype": "Additional Salary", "employee": employee, "company": entry.company,
                    "currency": frappe.db.get_value("Company", entry.company, "default_currency"), "salary_component": component,
                    "payroll_date": entry.end_date, "amount": float(amount), "overwrite_salary_structure_amount": 0,
                    "ref_doctype": "Payroll Entry", "ref_docname": entry.name, "tlc_travel_adjustment": source.name})
                salary.flags.tlc_travel_adjustment = True
                salary.insert(ignore_permissions=True)
                salary.submit()
            source.db_set({"tlc_adjustment_payroll": entry.name, "tlc_adjustment_salary": salary.name})
            created.append(salary.name)
    return created


def release_adjustments(entry):
    """Call after slips cancel, before/with payroll cancellation. Cancellation frees the source atomically."""
    names = frappe.get_all("Attendance Request", filters={"tlc_adjustment_payroll": entry.name}, pluck="name")
    for name in names:
        frappe.db.sql("select name from `tabAttendance Request` where name=%s for update", name)
        source = frappe.get_doc("Attendance Request", name)
        if source.tlc_adjustment_salary:
            salary = frappe.get_doc("Additional Salary", source.tlc_adjustment_salary)
            if salary.docstatus == 1:
                salary.flags.ignore_permissions = True
                salary.cancel()
            # Unique source link must be reusable on the replacement Additional Salary.
            salary.db_set("tlc_travel_adjustment", None)
        source.db_set({"tlc_adjustment_payroll": None, "tlc_adjustment_salary": None})


def validate_adjustment_salary(doc, method=None):
    if not doc.get("tlc_travel_adjustment"):
        return
    source = frappe.get_doc("Attendance Request", doc.tlc_travel_adjustment)
    if source.docstatus != 1 or doc.employee != source.employee or doc.ref_doctype != "Payroll Entry":
        frappe.throw("Khoản điều chỉnh công phải có yêu cầu đã duyệt đúng nhân viên và bảng lương.")
    if not doc.flags.get("tlc_travel_adjustment") and doc.is_new():
        frappe.throw("Điều chỉnh công chỉ do tiến trình tính lương tạo.", frappe.PermissionError)
    if source.tlc_adjustment_payroll and source.tlc_adjustment_payroll != doc.ref_docname:
        frappe.throw("Điều chỉnh đã được dùng ở bảng lương khác.")
