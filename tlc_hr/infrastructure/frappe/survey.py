"""Anonymous ballots are validated in memory and discarded after aggregation."""
import frappe
from frappe.utils import getdate, nowdate
from tlc_hr.domain.services import require, transition
from tlc_hr.domain.survey import ballot, validate_questions, aggregate_result
from tlc_hr.domain.survey_ports import ISurveyRepository
from tlc_hr.infrastructure.frappe.services import hr, employee, lock


def questions(doc):
    return [{"key": q.question_key, "label": q.label, "options": [o.strip() for o in q.options.splitlines() if o.strip()], "hidden": bool(q.hidden)} for q in doc.questions]


def validate(doc):
    require(hr(), "survey_admin", "Chỉ HR quản lý khảo sát ẩn danh")
    require(doc.minimum_results >= 5, "privacy_threshold", "Ngưỡng công bố tối thiểu là 5")
    require(getdate(doc.opens_on) <= getdate(doc.closes_on), "survey_dates", "Ngày đóng phải sau ngày mở")
    validate_questions(questions(doc))
    if doc.is_new():
        require(doc.status == "Draft", "survey_initial", "Khảo sát mới phải ở trạng thái Draft")
        doc.version = 1
        doc.previous_version = None
        if doc.flags.get("new_version_of"):
            prev = frappe.get_doc("TLC Survey Campaign", doc.flags.new_version_of)
            doc.version, doc.previous_version = prev.version + 1, prev.name
        return
    lock("TLC Survey Campaign", doc.name)
    old = frappe.get_doc("TLC Survey Campaign", doc.name)
    transition(old.status, doc.status, {"Draft": ("Open",), "Open": ("Paused", "Closed"), "Paused": ("Open", "Closed"), "Closed": ("Archived",)})
    require(doc.version == old.version and doc.previous_version == old.previous_version, "survey_version", "Không sửa số phiên bản")
    if old.status != "Draft":
        # A desk save sends dates and numbers as text while the stored row holds typed values.
        same = all(str(doc.get(key) or "") == str(old.get(key) or "") for key in
                   ("department", "minimum_results", "opens_on", "closes_on", "title", "description"))
        require(questions(doc) == questions(old) and same, "survey_frozen", "Khảo sát đã phát hành không sửa câu hỏi/phạm vi/ngưỡng; dùng Tạo phiên bản mới")


def on_update(doc):
    pass


def audience(doc, user=None):
    emp = employee(user)
    dept = frappe.db.get_value("Employee", emp, "department") if emp else None
    return bool(emp and dept and (not doc.department or doc.department == dept))


def permission(doc, user=None, permission_type=None):
    if hr(user):
        return True
    return permission_type in (None, "read", "select") and audience(doc, user)


def query(user=None):
    if hr(user):
        return ""
    emp = employee(user)
    dept = frappe.db.get_value("Employee", emp, "department") if emp else None
    if not dept:
        return "1=0"
    return "(`tabTLC Survey Campaign`.department is null or `tabTLC Survey Campaign`.department = '' or `tabTLC Survey Campaign`.department = " + frappe.db.escape(dept) + ")"


def internal_record(doctype, campaign, values):
    # Never persist the request user, request time, IP, ballot identifier or answer-set.
    stamp = campaign.creation
    doc = frappe.get_doc({"doctype": doctype, **values})
    doc.flags.ignore_permissions = True
    doc.flags.ignore_version = True
    doc.insert(ignore_permissions=True)
    frappe.db.set_value(doctype, doc.name, {"owner": "Administrator", "modified_by": "Administrator", "creation": stamp, "modified": stamp}, update_modified=False)
    return doc


class FrappeSurveyRepository(ISurveyRepository):
    def submit_anonymous(self, campaign, answers):
        lock("TLC Survey Campaign", campaign)
        doc = frappe.get_doc("TLC Survey Campaign", campaign)
        require(audience(doc), "survey_audience", "Không thuộc đối tượng khảo sát")
        require(doc.status == "Open" and getdate(doc.opens_on) <= getdate(nowdate()) <= getdate(doc.closes_on), "survey_closed", "Khảo sát chưa mở hoặc đã đóng")
        emp = employee()
        require(not frappe.db.exists("TLC Survey Participation", {"campaign": campaign, "employee": emp}), "survey_duplicate", "Bạn đã gửi phản hồi cho phiên bản khảo sát này")
        validated = ballot(questions(doc), answers)
        dept = frappe.db.get_value("Employee", emp, "department")
        # Every response contributes independently to a histogram; no row represents a ballot.
        for key, option in validated.items():
            filters = {"campaign": campaign, "department": dept, "question_key": key, "option_value": option}
            name = frappe.db.get_value("TLC Survey Aggregate", filters)
            if name:
                frappe.db.sql("update `tabTLC Survey Aggregate` set response_count=response_count+1 where name=%s", name)
            else:
                internal_record("TLC Survey Aggregate", doc, {**filters, "response_count": 1})
        internal_record("TLC Survey Participation", doc, {"campaign": campaign, "employee": emp})
        return {"submitted": True}

    def results(self, campaign, department):
        doc = frappe.get_doc("TLC Survey Campaign", campaign)
        emp = employee()
        roles = set(frappe.get_roles())
        managed_dept = frappe.db.get_value("Employee", emp, "department") if emp else None
        require(hr() or ("TLC Line Manager" in roles and managed_dept == department), "survey_result_scope", "Chỉ HR hoặc quản lý trong bộ phận được xem tổng hợp")
        require(not doc.department or doc.department == department, "survey_result_scope", "Bộ phận không thuộc phạm vi khảo sát")
        require(doc.status in ("Closed", "Archived"), "survey_results_closed", "Chỉ công bố kết quả sau khi đóng khảo sát")
        rows = frappe.get_all("TLC Survey Aggregate", filters={"campaign": campaign, "department": department}, fields=["question_key as question", "option_value as option", "response_count as count"])
        result = aggregate_result(questions(doc), rows, doc.minimum_results)
        # Access Log contains the report scope only, never a respondent or raw answer.
        frappe.get_doc({"doctype": "Access Log", "user": frappe.session.user, "export_from": "TLC Survey Campaign", "reference_document": campaign, "file_type": "JSON", "filters": frappe.as_json({"department": department, "version": doc.version})}).insert(ignore_permissions=True)
        return {"campaign": campaign, "version": doc.version, "department": department, **result}


def new_version(campaign):
    require(hr(), "survey_admin", "Chỉ HR tạo phiên bản khảo sát")
    lock("TLC Survey Campaign", campaign)
    old = frappe.get_doc("TLC Survey Campaign", campaign)
    require(old.status != "Draft", "survey_draft", "Hãy sửa bản nháp hiện tại")
    require(not frappe.db.exists("TLC Survey Campaign", {"previous_version": campaign}), "survey_version_exists", "Đã có phiên bản tiếp theo")
    doc = frappe.copy_doc(old)
    doc.status = "Draft"
    doc.flags.new_version_of = old.name
    doc.insert()
    return doc.name
