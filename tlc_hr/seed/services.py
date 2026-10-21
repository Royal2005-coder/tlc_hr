"""Idempotent master data seed for TLC internal services and anonymous surveys."""
import frappe
from frappe.utils import getdate, nowdate


def run(data=None):
    year = getdate(nowdate()).year
    holiday_list = f"TLC {year}" if frappe.db.exists("Holiday List", f"TLC {year}") else frappe.db.get_value("Holiday List", {}, "name")
    if not holiday_list:
        frappe.throw("Cần chạy dữ liệu ngày nghỉ trước khi tạo danh mục dịch vụ.")

    # 1. Service Catalog
    catalogs = [
        {"service_name": "Hành chính - Xác nhận công tác", "handler": "lan@demo.example", "holiday_list": holiday_list, "sla_days": 2, "instructions": "Cấp giấy xác nhận đi công tác."},
        {"service_name": "Hành chính - Cấp văn phòng phẩm", "handler": "lan@demo.example", "holiday_list": holiday_list, "sla_days": 1, "instructions": "Yêu cầu cấp phát văn phòng phẩm định kỳ."},
        {"service_name": "IT - Hỗ trợ kỹ thuật & Cấp quyền", "handler": "admin@demo.example", "holiday_list": holiday_list, "sla_days": 1, "instructions": "Xử lý sự cố máy tính, email, tài khoản."},
    ]
    for cat in catalogs:
        if not frappe.db.exists("TLC Service Catalog", cat["service_name"]):
            doc = frappe.get_doc({"doctype": "TLC Service Catalog", **cat, "enabled": 1})
            doc.insert(ignore_permissions=True)

    # 2. Meeting Rooms
    rooms = [
        {"room_name": "Phòng họp Hội sở 1 (Lớn)", "capacity": 16, "equipment": "TV 65 inch, Mic họp trực tuyến, Bảng trắng", "enabled": 1},
        {"room_name": "Phòng họp Hội sở 2 (Nhỏ)", "capacity": 6, "equipment": "TV 50 inch, Bảng viết", "enabled": 1},
        {"room_name": "Phòng họp Nhà máy 1", "capacity": 20, "equipment": "Máy chiếu, Bảng trắng", "enabled": 1},
    ]
    for rm in rooms:
        if not frappe.db.exists("TLC Meeting Room", rm["room_name"]):
            frappe.get_doc({"doctype": "TLC Meeting Room", **rm}).insert(ignore_permissions=True)

    # 3. Library Books
    books = [
        {"book_code": "TLCLIB-001", "title": "Bộ luật Lao động 2019 & Nghị định hướng dẫn thi hành", "author": "NXB Lao động", "enabled": 1},
        {"book_code": "TLCLIB-002", "title": "Quản trị Nhân sự Thực hành", "author": "Gary Dessler", "enabled": 1},
        {"book_code": "TLCLIB-003", "title": "Lean Manufacturing - Sản xuất Tinh gọn", "author": "Jeffrey Liker", "enabled": 1},
    ]
    for bk in books:
        if not frappe.db.exists("TLC Library Book", bk["book_code"]):
            frappe.get_doc({"doctype": "TLC Library Book", **bk}).insert(ignore_permissions=True)

    # 4. Survey Campaigns
    survey_title = "Khảo sát bữa ăn ca và dịch vụ nội bộ 2026"
    if not frappe.db.exists("TLC Survey Campaign", {"title": survey_title}):
        doc = frappe.get_doc({
            "doctype": "TLC Survey Campaign",
            "title": survey_title,
            "description": "<p>Khảo sát ẩn danh định kỳ về chất lượng bữa ăn và hỗ trợ hành chính.</p>",
            "status": "Draft",
            "opens_on": f"{year}-01-01",
            "closes_on": f"{year}-12-31",
            "minimum_results": 5,
            "questions": [
                {"question_key": "meal_quality", "label": "Chất lượng suất ăn hàng ngày", "options": "Rất hài lòng\nHài lòng\nBình thường\nChưa đạt", "hidden": 0},
                {"question_key": "portion_size", "label": "Khẩu phần suất ăn", "options": "Đầy đủ\nVừa đủ\nÍt", "hidden": 0},
                {"question_key": "admin_service", "label": "Thời gian giải quyết yêu cầu hành chính", "options": "Đúng hạn\nChậm trễ\nRất chậm", "hidden": 0},
            ]
        })
        doc.insert(ignore_permissions=True)
        # Open the campaign
        doc.status = "Open"
        doc.save(ignore_permissions=True)


UAT_DOCTYPES = ("TLC Service Request", "TLC Room Reservation", "TLC Book Loan",
                "TLC Meal Enrollment", "TLC Official Correspondence")


def _drop(doctype, names):
    for name in names:
        doc = frappe.get_doc(doctype, name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)


def reset():
    """Demo and UAT only: remove the service records a UAT run creates; the catalog stays."""
    if not frappe.conf.get("allow_tests") and not frappe.flags.in_test:
        frappe.throw("reset_services runs only on a test site (site config allow_tests)")
    for doctype in UAT_DOCTYPES:
        _drop(doctype, frappe.get_all(doctype, pluck="name"))
    _drop("Leave Application", frappe.get_all("Leave Application", filters={"description": ["like", "%UAT suất ăn%"]}, pluck="name"))
    print("reset: service requests, bookings, loans, meals and correspondence deleted")
