"""Transactional native services. Resource-row locks serialize booking, lending and meals."""
from datetime import timedelta
import frappe
from frappe.utils import getdate, get_datetime, nowdate, now_datetime
from tlc_hr.domain.services import (require, transition, working_due, working_elapsed, meal_cutoff,
                                     SERVICE_EDGES, LOAN_EDGES, MAIL_EDGES)
from tlc_hr.domain.shared import HR_ROLES


def hr(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or bool(set(frappe.get_roles(user)) & HR_ROLES)


def employee(user=None):
    return frappe.db.get_value("Employee", {"user_id": user or frappe.session.user, "status": "Active"}, "name")


def own(emp, user=None):
    return emp == employee(user)


def lock(doctype, name):
    # The doctype is selected by code, never supplied by a caller.
    frappe.db.sql(f"select name from `tab{doctype}` where name=%s for update", name)


def notify(user, doc, text):
    if user:
        frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": text,
                        "document_type": doc.doctype, "document_name": doc.name}).insert(ignore_permissions=True)


def notify_hr(doc, text):
    users = frappe.get_all("Has Role", filters={"role": ["in", list(HR_ROLES)]}, pluck="parent")
    for user in set(users):
        if frappe.db.get_value("User", user, "enabled"):
            notify(user, doc, text)


def calendar(name):
    cal = frappe.get_doc("Holiday List", name)
    return {getdate(x.holiday_date) for x in cal.holidays}, getdate(cal.from_date), getdate(cal.to_date)


def due(name, start, days):
    holidays, begins, ends = calendar(name)
    require(begins <= start <= ends, "calendar_missing", "Ngày yêu cầu nằm ngoài lịch SLA")
    return working_due(start, days, holidays, ends)


def validate(doc):
    old = doc.get_doc_before_save()
    elevated = hr() or bool(doc.flags.get("absence_effect"))
    if doc.get("employee"):
        require(elevated or own(doc.employee) or (old and doc.doctype == "TLC Service Request" and old.handler == frappe.session.user), "service_scope", "Không được xử lý hồ sơ của người khác")
        if old:
            require(doc.employee == old.employee, "immutable_employee", "Không được đổi nhân viên")
    if doc.doctype == "TLC Service Catalog":
        require(hr() and doc.sla_days > 0, "catalog_admin", "Chỉ HR quản lý danh mục; SLA phải lớn hơn 0")
    elif doc.doctype in ("TLC Meeting Room", "TLC Library Book"):
        require(hr(), "resource_admin", "Chỉ HR quản lý danh mục")
        if doc.doctype == "TLC Meeting Room":
            require(doc.capacity > 0, "room_capacity", "Sức chứa phải lớn hơn 0")
    elif doc.doctype == "TLC Service Request":
        validate_request(doc, old)
    elif doc.doctype == "TLC Room Reservation":
        validate_reservation(doc, old)
    elif doc.doctype == "TLC Meal Enrollment":
        validate_meal(doc, old, elevated)
    elif doc.doctype == "TLC Book Loan":
        validate_loan(doc, old)
    elif doc.doctype == "TLC Official Correspondence":
        validate_mail(doc, old)


def validate_request(doc, old):
    if not old:
        require(doc.status == "Requested", "request_initial", "Yêu cầu mới phải ở trạng thái Requested")
        spec = frappe.get_doc("TLC Service Catalog", doc.service)
        require(spec.enabled, "service_disabled", "Dịch vụ đang tạm ngừng")
        doc.handler, doc.holiday_list, doc.sla_days = spec.handler, spec.holiday_list, spec.sla_days
        doc.due_date = due(doc.holiday_list, getdate(nowdate()), doc.sla_days)
        doc.paused_on = None
        require(not doc.satisfaction and not doc.resolution, "request_initial", "Chưa có kết quả để xác nhận")
        return
    require(all(doc.get(k) == old.get(k) for k in ("service", "handler", "holiday_list", "sla_days")), "sla_immutable", "Không sửa cấu hình SLA của hồ sơ đang xử lý")
    transition(old.status, doc.status, SERVICE_EDGES)
    handler = hr() or frappe.session.user == doc.handler
    requester = own(doc.employee)
    if doc.status != old.status:
        if doc.status == "Closed":
            require(requester and bool(doc.satisfaction), "request_close", "Người gửi phải xác nhận mức hài lòng khi đóng")
        elif doc.status == "Cancelled":
            require(requester or handler, "request_cancel", "Không có quyền hủy")
        else:
            require(handler, "request_handler", "Chỉ người xử lý thay đổi tiến độ")
    if doc.status in ("Cancelled", "Waiting Information"):
        require(bool(doc.reason), "request_reason", "Cần ghi lý do")
    if doc.resolution != old.resolution:
        require(handler, "request_resolution", "Chỉ người xử lý nhập kết quả")
    if doc.satisfaction != old.satisfaction:
        require(requester and doc.status == "Closed", "request_rating", "Chỉ người gửi đánh giá khi đóng")
    if doc.status == "Resolved":
        require(bool(doc.resolution), "request_resolution", "Cần nhập kết quả xử lý")
    doc.due_date, doc.paused_on = old.due_date, old.paused_on
    if old.status != "Waiting Information" and doc.status == "Waiting Information":
        doc.paused_on = nowdate()
    elif old.status == "Waiting Information" and doc.status != old.status:
        holidays, begins, ends = calendar(doc.holiday_list)
        today = getdate(nowdate())
        require(begins <= getdate(old.paused_on) <= today <= ends, "calendar_missing", "Cần bổ sung lịch SLA")
        paused_days = working_elapsed(getdate(old.paused_on), today, holidays)
        doc.due_date = due(doc.holiday_list, getdate(old.due_date), paused_days) if paused_days else old.due_date
        doc.paused_on = None


def validate_reservation(doc, old):
    require(doc.status in ("Booked", "Cancelled"), "room_status", "Trạng thái không hợp lệ")
    require(get_datetime(doc.starts_at) < get_datetime(doc.ends_at), "room_interval", "Giờ kết thúc phải sau giờ bắt đầu")
    if old:
        require(doc.room == old.room, "room_immutable", "Hủy lịch cũ trước khi chuyển phòng")
        require(old.status != "Cancelled" or doc.status == "Cancelled", "room_cancelled", "Không mở lại lịch đã hủy")
    if doc.status == "Cancelled":
        require(bool(doc.reason), "room_cancel_reason", "Cần lý do hủy")
        return
    lock("TLC Meeting Room", doc.room)
    require(frappe.db.get_value("TLC Meeting Room", doc.room, "enabled"), "room_disabled", "Phòng tạm ngừng sử dụng")
    conflicts = frappe.db.sql("""select name from `tabTLC Room Reservation` where room=%s and status='Booked'
        and name != %s and starts_at < %s and ends_at > %s limit 1 for update""",
        (doc.room, doc.name or "", doc.ends_at, doc.starts_at))
    require(not conflicts, "room_conflict", "Phòng đã được đặt trong khoảng thời gian này")


def approved_absence(emp, day):
    if frappe.db.sql("select name from `tabLeave Application` where employee=%s and docstatus=1 and status='Approved' and from_date<=%s and to_date>=%s limit 1 for update", (emp, day, day)):
        return True
    if frappe.get_meta("Travel Request").has_field("tlc_approved_on"):
        for trip in frappe.db.sql("select tlc_from_date, tlc_to_date, tlc_report_approved_on, tlc_actual_from_date, tlc_actual_to_date from `tabTravel Request` where employee=%s and docstatus=1 and tlc_approved_on is not null for update", emp, as_dict=True):
            start, end = (trip.tlc_actual_from_date, trip.tlc_actual_to_date) if trip.tlc_report_approved_on else (trip.tlc_from_date, trip.tlc_to_date)
            if start and end and getdate(start) <= getdate(day) <= getdate(end):
                return True
    return False


def validate_meal(doc, old, elevated):
    require(doc.status in ("Enrolled", "Cancelled"), "meal_status", "Trạng thái không hợp lệ")
    lock("Employee", doc.employee)
    if old:
        require(getdate(doc.meal_date) == getdate(old.meal_date), "meal_date", "Không đổi ngày của đăng ký đã lưu")
    if not doc.flags.get("absence_effect"):
        meal_cutoff(getdate(doc.meal_date), getdate(nowdate()), hr(), doc.reason)
        require(not doc.absence_source or (old and doc.absence_source == old.absence_source), "meal_source", "Không tự nhập hồ sơ vắng mặt")
    duplicate = frappe.db.sql("select name from `tabTLC Meal Enrollment` where employee=%s and meal_date=%s and name != %s limit 1 for update", (doc.employee, doc.meal_date, doc.name or ""))
    require(not duplicate, "meal_duplicate", "Đã có đăng ký của nhân viên trong ngày; hãy sửa hồ sơ đó")
    if doc.status == "Enrolled":
        require(not approved_absence(doc.employee, doc.meal_date), "meal_absent", "Ngày nghỉ/công tác đã duyệt không được đăng ký ăn")
    if doc.status == "Cancelled":
        require(bool(doc.reason), "meal_reason", "Cần lý do hủy suất ăn")


def validate_loan(doc, old):
    lock("TLC Library Book", doc.book)
    if not old:
        require(doc.status == "Requested", "loan_initial", "Phiếu mới phải ở trạng thái Requested")
        doc.lent_on = doc.returned_on = None
    else:
        require(doc.book == old.book, "loan_book", "Không đổi bản sách trên phiếu đã lưu")
        transition(old.status, doc.status, LOAN_EDGES)
        if doc.status != old.status:
            require(hr() or doc.status == "Cancelled", "loan_librarian", "Chỉ HR xác nhận mượn/trả sách")
        if not hr():
            require(doc.due_date == old.due_date, "loan_due", "Chỉ HR đổi hạn trả")
        doc.lent_on, doc.returned_on = old.lent_on, old.returned_on
    if doc.status in ("Requested", "Lent"):
        require(frappe.db.get_value("TLC Library Book", doc.book, "enabled"), "book_disabled", "Sách không cho mượn")
        busy = frappe.db.sql("select name from `tabTLC Book Loan` where book=%s and status='Lent' and name != %s limit 1 for update", (doc.book, doc.name or ""))
        if busy and doc.status == "Requested":
            doc.status = "Waitlisted"
        elif doc.status == "Lent":
            require(not busy, "book_lent", "Bản sách đã được cho mượn")
            require(bool(doc.due_date) and getdate(doc.due_date) >= getdate(nowdate()), "loan_due", "Hạn trả không được trước ngày mượn")
            if not old or old.status != "Lent":
                doc.lent_on = nowdate()
    if doc.status in ("Rejected", "Cancelled"):
        require(bool(doc.reason), "loan_reason", "Cần ghi lý do")
    if old and old.status == "Lent" and doc.status == "Returned":
        doc.returned_on = nowdate()


def validate_mail(doc, old):
    if not old:
        if doc.direction == "Incoming":
            require(hr(), "mail_incoming", "Chỉ HR tiếp nhận văn thư đến")
            doc.status = "New Incoming"
        else:
            require(doc.status == "Need Dispatch", "mail_initial", "Văn thư gửi mới phải ở trạng thái Need Dispatch")
    else:
        require(doc.direction == old.direction, "mail_direction", "Không đổi chiều văn thư")
        transition(old.status, doc.status, MAIL_EDGES)
        if doc.status != old.status or doc.courier != old.courier or doc.tracking_number != old.tracking_number:
            require(hr(), "mail_handler", "Chỉ HR cập nhật giao nhận")
    if doc.status in ("With Courier", "Delivered"):
        require(bool(doc.courier) and bool(doc.tracking_number), "mail_tracking", "Cần đơn vị vận chuyển và mã vận đơn")


def on_update(doc):
    old = doc.get_doc_before_save()
    changed = not old or doc.get("status") != old.get("status")
    if doc.doctype == "TLC Meal Enrollment":
        notify_hr(doc, "Thay đổi suất ăn: " + doc.employee + " / " + str(doc.meal_date))
    elif changed and doc.get("employee"):
        notify(frappe.db.get_value("Employee", doc.employee, "user_id"), doc, doc.doctype + ": " + str(doc.get("status")))
        if doc.doctype == "TLC Service Request":
            notify(doc.handler, doc, "Yêu cầu dịch vụ: " + doc.subject)
    if doc.doctype == "TLC Book Loan" and doc.status == "Returned" and changed:
        next_loan = frappe.get_all("TLC Book Loan", filters={"book": doc.book, "status": "Waitlisted"}, fields=["name", "employee"], order_by="creation asc, name asc", limit=1)
        if next_loan:
            notify(frappe.db.get_value("Employee", next_loan[0].employee, "user_id"), doc, "Sách đã được trả; vui lòng xác nhận còn muốn mượn với HR")


def cancel_meals_for_absence(emp, start, end, source_doctype, source_name):
    lock("Employee", emp)
    names = frappe.get_all("TLC Meal Enrollment", filters={"employee": emp, "meal_date": ["between", [start, end]], "status": "Enrolled"}, pluck="name")
    for name in names:
        doc = frappe.get_doc("TLC Meal Enrollment", name)
        doc.flags.absence_effect = True
        doc.status, doc.reason, doc.absence_source = "Cancelled", "Tự hủy do nghỉ/công tác đã duyệt", source_doctype + ":" + source_name
        doc.save(ignore_permissions=True)
    return len(names)


def permission(doc, user=None, permission_type=None):
    if hr(user):
        return True
    if doc.doctype in ("TLC Service Catalog", "TLC Meeting Room", "TLC Library Book"):
        return permission_type in (None, "read", "select")
    handler = None if doc.is_new() else frappe.db.get_value("TLC Service Request", doc.name, "handler") if doc.doctype == "TLC Service Request" else None
    return own(doc.get("employee"), user) or handler == (user or frappe.session.user)


def query(doctype, user=None):
    user = user or frappe.session.user
    if hr(user):
        return ""
    emp = frappe.db.escape(employee(user) or "__no_employee__")
    scope = f"`tab{doctype}`.employee = {emp}"
    if doctype == "TLC Service Request":
        scope = "(" + scope + " OR `tabTLC Service Request`.handler = " + frappe.db.escape(user) + ")"
    return scope


def reminders():
    today = nowdate()
    for typ, filters in (("TLC Service Request", {"status": ["in", ["Requested", "Processing"]], "due_date": ["<=", today]}),
                         ("TLC Book Loan", {"status": "Lent", "due_date": ["<=", today]})):
        for row in frappe.get_all(typ, filters=filters, pluck="name"):
            doc = frappe.get_doc(typ, row)
            notify(doc.get("handler") or frappe.db.get_value("Employee", doc.employee, "user_id"), doc, "Đến hạn / quá hạn: " + row)
