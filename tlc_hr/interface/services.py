"""Thin desktop adapters and doc-event integration for native internal services."""
from functools import wraps
import frappe
from frappe.utils import get_datetime
from tlc_hr.domain.shared import DomainError
from tlc_hr.infrastructure.frappe import services as repository


def guarded(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DomainError as exc:
            frappe.throw(exc.message, title=exc.code)
    return call


validate = guarded(repository.validate)
on_update = repository.on_update
has_permission = repository.permission


def service_request_query(user=None):
    return repository.query("TLC Service Request", user)


def room_reservation_query(user=None):
    return repository.query("TLC Room Reservation", user)


def meal_enrollment_query(user=None):
    return repository.query("TLC Meal Enrollment", user)


def book_loan_query(user=None):
    return repository.query("TLC Book Loan", user)


def correspondence_query(user=None):
    return repository.query("TLC Official Correspondence", user)


def cancel_meals_for_absence(employee, from_date, to_date, source_doctype, source_name):
    return guarded(repository.cancel_meals_for_absence)(employee, from_date, to_date, source_doctype, source_name)


def approved_leave(doc, method=None):
    if doc.docstatus == 1 and doc.status == "Approved":
        return cancel_meals_for_absence(doc.employee, doc.from_date, doc.to_date, doc.doctype, doc.name)


def daily_reminders():
    return repository.reminders()


@frappe.whitelist()
def room_availability(room, starts_at, ends_at):
    if frappe.session.user == "Guest":
        frappe.throw("Cần đăng nhập", frappe.PermissionError)
    frappe.has_permission("TLC Meeting Room", "read", throw=True)
    if get_datetime(starts_at) >= get_datetime(ends_at):
        frappe.throw("Giờ kết thúc phải sau giờ bắt đầu")
    rows = frappe.get_all("TLC Room Reservation", filters={"room": room, "status": "Booked", "starts_at": ["<", ends_at], "ends_at": [">", starts_at]}, fields=["starts_at", "ends_at"])
    return {"busy": rows, "external_calendar": "Export only; no Outlook synchronization"}


@frappe.whitelist()
def export_calendar(name):
    doc = frappe.get_doc("TLC Room Reservation", name)
    doc.check_permission("read")
    def escape(value):
        return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "").replace(",", "\\,").replace(";", "\\;")
    # Floating local time is explicit; Outlook import is a user action, not synchronization.
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TLC//Room Export//VI", "BEGIN:VEVENT", "UID:" + doc.name + "@tlc",
             "DTSTAMP:" + get_datetime(doc.modified).strftime("%Y%m%dT%H%M%S"),
             "DTSTART:" + get_datetime(doc.starts_at).strftime("%Y%m%dT%H%M%S"), "DTEND:" + get_datetime(doc.ends_at).strftime("%Y%m%dT%H%M%S"),
             "SUMMARY:" + escape(doc.subject), "LOCATION:" + escape(doc.room), "STATUS:" + ("CANCELLED" if doc.status == "Cancelled" else "CONFIRMED"), "END:VEVENT", "END:VCALENDAR"]
    frappe.local.response.filename = "tlc-room-" + doc.name + ".ics"
    frappe.local.response.filecontent = "\r\n".join(lines) + "\r\n"
    frappe.local.response.type = "download"
