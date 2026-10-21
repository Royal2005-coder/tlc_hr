"""Native permission checks remain mandatory, even on this narrower demo-only surface."""
import frappe

from tlc_hr.domain.assistant import AssistantIdentity, IAssistantRepository
from tlc_hr.domain.shared import NotAllowed

DEMO_USERS = frozenset(f"{name}@demo.example" for name in (
    "an", "binh", "f2w01", "f3w01", "hung", "nm2", "nm3", "hoa", "lan", "thanh", "phuong", "chi", "quang"))


class FrappeAssistantRepository(IAssistantRepository):
    def identity(self):
        user = frappe.session.user
        enabled = bool(frappe.conf.get("tlc_ai_demo_enabled")) and frappe.local.site == "tlc-hr.local" and user in DEMO_USERS
        if not enabled:
            return AssistantIdentity(user, "", False)
        # get_list applies User Permissions and permission-query hooks; never get_all/db.get_value for HR data.
        rows = frappe.get_list("Employee", filters={"user_id": user, "status": "Active", "company": "TLC Demo"},
                               fields=["name"], limit_page_length=2)
        return AssistantIdentity(user, rows[0].name if len(rows) == 1 else "", enabled)

    def read_self(self, topic, employee):
        if topic == "profile":
            rows = frappe.get_list("Employee", filters={"name": employee, "user_id": frappe.session.user, "company": "TLC Demo"},
                                   fields=["name", "employee_name", "department", "company"], limit_page_length=1)
        else:
            doctype, fields, filters = {
                "attendance": ("Attendance", ["name", "attendance_date", "status"], {"docstatus": 1}),
                "leave": ("Leave Application", ["name", "leave_type", "from_date", "to_date", "status", "docstatus"], {}),
                "payslip": ("Salary Slip", ["name", "start_date", "end_date", "gross_pay", "total_deduction", "net_pay", "currency"], {"docstatus": 1}),
            }[topic]
            rows = frappe.get_list(doctype, filters={"employee": employee, "company": "TLC Demo", **filters},
                                   fields=fields, order_by="creation desc", limit_page_length=10)
        return {"topic": topic, "employee": employee, "records": [dict(row) for row in rows],
                "scope": "self_only", "limit": 10, "demo_data": True}

    def create_leave_draft(self, employee, command):
        doc = frappe.get_doc({"doctype": "Leave Application", "employee": employee, "company": "TLC Demo",
                              "leave_type": command.leave_type, "from_date": command.from_date, "to_date": command.to_date,
                              "description": command.reason, "status": "Open", "docstatus": 0})
        # Native HRMS validation and TLC doc_events run, exactly as a UI save. Never submit or apply_workflow.
        doc.insert()
        if doc.docstatus != 0:
            raise NotAllowed("AI_DRAFT_ONLY", "Trợ lý chỉ được tạo bản nháp.")
        return {"doctype": doc.doctype, "document_id": doc.name, "docstatus": 0,
                "workflow_state": doc.get("workflow_state"), "url": f"/hrms/leave-applications/{doc.name}",
                "message": "Đã tạo bản nháp. Bạn phải mở đơn, kiểm tra và tự gửi duyệt."}

    def audit(self, action, employee, outcome):
        # File logging survives a denied HTTP transaction rollback. Never log salaries, prompts or provider keys.
        frappe.logger("tlc_ai_audit", allow_site=True).info({"actor": frappe.session.user, "action": action,
                                                         "employee": employee, "outcome": outcome})
