"""Native Desk lifecycle adapters. All state/evidence authorization is enforced server-side."""
import frappe
from frappe.utils import getdate, now_datetime, today
from tlc_hr.application.lifecycle import LifecycleService
from tlc_hr.contracts.lifecycle import EmployeeChange, ProbationCommand, SeparationCommand
from tlc_hr.domain.lifecycle import effective_interval, require, settlement_due
from tlc_hr.domain.shared import DomainError, NotAllowed
from tlc_hr.infrastructure.frappe.lifecycle import FrappeLifecycleRepository, apply_change, snapshot

REPOSITORY = FrappeLifecycleRepository()
SERVICE = LifecycleService(REPOSITORY)
HR = {"TLC HR Lead", "TLC HR Officer", "System Manager"}
EMPLOYEE_RECORDS = {"TLC Employee Change Request", "TLC Employee Dependent", "TLC Employee Document", "TLC Probation Review"}
SENSITIVE_FIELDS = {"bank_ac_no", "bank_name", "pan_number", "custom_tax_code", "custom_social_insurance_number", "passport_number"}


def _error(exc):
    frappe.throw(f"[{exc.code}] {exc.message}", frappe.PermissionError if isinstance(exc, NotAllowed) else frappe.ValidationError)


def _hr():
    if not HR.intersection(frappe.get_roles()):
        raise NotAllowed("LC-HR", "Chỉ HR được xác nhận hồ sơ vòng đời nhân viên.")


def _employee_scope(doc):
    if doc.doctype not in EMPLOYEE_RECORDS or HR.intersection(frappe.get_roles()):
        return
    own = frappe.db.get_value("Employee", doc.employee, "user_id") == frappe.session.user
    manager = frappe.db.get_value("Employee", doc.employee, "reports_to")
    manager_user = frappe.db.get_value("Employee", manager, "user_id") if manager else None
    old = doc.get_doc_before_save()
    review_step = old and old.get("workflow_state") == "Chờ quản lý duyệt" and manager_user == frappe.session.user
    director_step = old and old.get("workflow_state") == "Chờ giám đốc duyệt" and "TLC Director" in frappe.get_roles()
    if not (own or (doc.doctype == "TLC Probation Review" and (review_step or director_step))):
        raise NotAllowed("LC-SCOPE", "Chỉ được sửa hồ sơ bản thân hoặc đánh giá được phân công.")


def _evidence(doc):
    previous = {row.name: row for row in (doc.get_doc_before_save().get("custom_tlc_evidence") or [])} if doc.get_doc_before_save() else {}
    for row in doc.get("custom_tlc_evidence") or []:
        old = previous.get(row.name)
        changed = not old or any(row.get(key) != old.get(key) for key in ("status", "evidence", "confirmed_by", "confirmed_on"))
        if changed and row.status != "Pending":
            require(row.evidence, "LC-EVIDENCE", "Xác nhận phải có chứng từ.")
            require(not row.confirmed_by or row.confirmed_by == frappe.session.user, "LC-SIGNER", "Không được xác nhận thay người khác.")
            row.confirmed_by = frappe.session.user
            row.confirmed_on = now_datetime()


def validate(doc, event=None):
    try:
        _employee_scope(doc)
        if doc.doctype.startswith("TLC ") and doc.get("valid_from"):
            effective_interval(getdate(doc.valid_from), getdate(doc.valid_to) if doc.get("valid_to") else None)
        if doc.doctype == "TLC Employee Change Request":
            command = EmployeeChange(employee=doc.employee, field=doc.field, value=doc.new_value,
                                     effective_on=getdate(doc.effective_on), reason=doc.reason, evidence=doc.evidence)
            require(frappe.get_meta("Employee").has_field(command.field), "CORE-FIELD", "Trường chưa được cấu hình trên Employee.")
            if doc.is_new():
                doc.old_value = str(frappe.db.get_value("Employee", doc.employee, command.field) or "")
        elif doc.doctype == "TLC Probation Review":
            command = ProbationCommand(employee=doc.employee, job=doc.job, category=doc.category,
                                       start=getdate(doc.start_date), end=getdate(doc.end_date))
            doc.counted_days = SERVICE.validate_probation(command, doc.name or "")
            state = doc.get("workflow_state")
            if state in ("Chờ nhân sự duyệt", "Chờ giám đốc duyệt", "Đã duyệt"):
                require(doc.manager_review, "OB-MANAGER", "Cần đánh giá của quản lý.")
            if state in ("Chờ giám đốc duyệt", "Đã duyệt"):
                require(doc.hr_review, "OB-HR", "Cần đánh giá của HR.")
        elif doc.doctype == "TLC Employee Dependent":
            if doc.status == "Verified":
                require(doc.evidence and doc.identity_number, "CORE-DEPENDENT", "Xác nhận người phụ thuộc cần định danh và chứng từ.")
                if doc.get_doc_before_save() and doc.get_doc_before_save().status != "Verified":
                    _hr()
            if doc.valid_to:
                require(doc.end_reason, "CORE-DEPENDENT-END", "Ngừng giảm trừ cần lý do.")
        elif doc.doctype == "TLC Employment Contract":
            if doc.contract_type == "Fixed term" and not doc.parent_contract:
                count = frappe.db.count("TLC Employment Contract", {"employee": doc.employee, "contract_type": "Fixed term", "docstatus": 1, "parent_contract": ["is", "not set"], "name": ["!=", doc.name]})
                if count >= 2:
                    require(doc.legal_exception and doc.legal_evidence, "CORE-FIXED-LIMIT", "Vượt số lần hợp đồng xác định thời hạn: cần căn cứ ngoại lệ pháp lý.")
        elif doc.doctype in ("Employee Onboarding", "Employee Separation"):
            _evidence(doc)
            if doc.doctype == "Employee Separation":
                result = SERVICE.check_notice(SeparationCommand(employee=doc.employee, category=doc.custom_tlc_contract_category,
                    submitted=getdate(doc.custom_tlc_submitted_on), last_day=getdate(doc.custom_tlc_last_day),
                    exception=doc.custom_tlc_notice_exception or "", legal_evidence=doc.custom_tlc_legal_evidence or "",
                    legal_reviewer=doc.custom_tlc_legal_reviewer or ""))
                doc.custom_tlc_earliest_last_day = result.earliest
                if doc.custom_tlc_notice_exception:
                    _validate_legal_reviewer(doc)
                require(getdate(doc.custom_tlc_effective_on) >= getdate(doc.custom_tlc_last_day), "EXIT-EFFECTIVE", "Ngày nghỉ chính thức không trước ngày cuối.")
                doc.custom_tlc_settlement_due = settlement_due(getdate(doc.custom_tlc_effective_on), lambda day: REPOSITORY.is_working(doc.employee, day),
                    bool(doc.custom_tlc_settlement_extended), doc.custom_tlc_legal_evidence or "", doc.custom_tlc_legal_reviewer or "")
                if doc.custom_tlc_settlement_extended:
                    _validate_legal_reviewer(doc)
                if not result.sufficient:
                    frappe.msgprint(f"Chưa đủ báo trước. Ngày cuối hợp lệ sớm nhất: {result.earliest}", indicator="orange", alert=True)
            if doc.boarding_status == "Completed" and not doc.is_new():
                SERVICE.complete(doc.doctype, doc.name, doc.get("employee"))
        elif doc.doctype == "Employee":
            old = doc.get_doc_before_save()
            if old and not doc.flags.get("tlc_approved_change"):
                require(not any(doc.get(field) != old.get(field) for field in SENSITIVE_FIELDS if doc.meta.has_field(field)), "CORE-CHANGE-REQUIRED", "Thông tin nhạy cảm phải qua yêu cầu cập nhật có chứng từ và HR duyệt.")
            if old and old.status == "Left" and doc.status == "Active":
                episode = doc.get("custom_tlc_rehire_episode")
                require(episode, "EXIT-REHIRE", "Tái tuyển phải dùng quyết định trên cùng mã nhân viên.")
                approved = frappe.get_doc("TLC Employment Episode", episode)
                require(approved.employee == doc.name and approved.docstatus == 1 and approved.event == "Rehired" and getdate(approved.start_date) <= getdate(today()), "EXIT-REHIRE", "Quyết định tái tuyển chưa hợp lệ.")
                doc.custom_tlc_lifecycle_state = "Rehired"
        elif doc.doctype in ("Task", "Project"):
            if (doc.doctype == "Task" and doc.status == "Completed" and doc.project) or (doc.doctype == "Project" and doc.status == "Completed"):
                project = doc.project if doc.doctype == "Task" else doc.name
                for kind in ("Employee Onboarding", "Employee Separation"):
                    name = frappe.db.get_value(kind, {"project": project, "docstatus": 1}, "name")
                    if name:
                        boarding = frappe.get_doc(kind, name)
                        blockers = REPOSITORY.completion_blockers(kind, name, boarding.get("employee"))
                        # A Task may complete independently; the last task cannot close the native Project before evidence clears.
                        others = [a for a in boarding.activities if a.task != doc.name and (not a.task or frappe.db.get_value("Task", a.task, "status") != "Completed")]
                        if doc.doctype == "Project" or not others:
                            from tlc_hr.domain.lifecycle import completion_gate
                            completion_gate([b for b in blockers if doc.doctype != "Task" or b != doc.subject.split(" : ")[0]])
    except DomainError as exc:
        _error(exc)


def _validate_legal_reviewer(doc):
    old = doc.get_doc_before_save()
    changed = not old or any(doc.get(key) != old.get(key) for key in ("custom_tlc_notice_exception", "custom_tlc_legal_evidence", "custom_tlc_legal_reviewer", "custom_tlc_settlement_extended"))
    if changed:
        _hr()
        require(doc.custom_tlc_legal_reviewer == frappe.session.user, "EXIT-LEGAL-SIGNER", "Người xác nhận pháp lý phải là HR đang đăng nhập.")


def before_submit(doc, event=None):
    try:
        if doc.doctype in ("TLC Employee Change Request", "TLC Employee Dependent", "TLC Employee Document", "TLC Employment Contract", "TLC Employment Episode"):
            _hr()
        if doc.doctype == "TLC Employee Dependent":
            require(doc.status in ("Verified", "Stopped"), "CORE-DEPENDENT-VERIFY", "HR phải xác nhận trước khi có hiệu lực giảm trừ.")
        if doc.doctype == "TLC Probation Review":
            require("TLC Director" in frappe.get_roles() or "System Manager" in frappe.get_roles(), "OB-DIRECTOR", "Giám đốc duyệt kết quả thử việc.")
            require(doc.decision in ("Official", "Extend", "End"), "OB-DECISION", "Cần quyết định kết thúc thử việc.")
            if doc.decision == "Official":
                require(doc.result_contract and frappe.db.get_value("TLC Employment Contract", doc.result_contract, "employee") == doc.employee, "OB-CONTRACT", "Cần hợp đồng chính thức cùng nhân viên.")
            if doc.decision == "End":
                require(doc.result_separation and frappe.db.get_value("Employee Separation", doc.result_separation, "employee") == doc.employee, "OB-SEPARATION", "Cần hồ sơ nghỉ việc cùng nhân viên.")
        if doc.doctype in ("Employee Promotion", "Employee Transfer"):
            require(doc.custom_tlc_reason and doc.custom_tlc_decision, "CORE-DECISION", "Quyết định nhân sự cần lý do và chứng từ.")
            if doc.doctype == "Employee Transfer":
                require(not doc.create_new_employee_id, "CORE-EMPLOYEE-CODE", "Điều chuyển TLC giữ nguyên mã nhân viên.")
            effective = doc.get("promotion_date") or doc.get("transfer_date")
            if not frappe.db.exists("TLC Employment Snapshot", {"employee": doc.employee, "docstatus": 1}):
                joined = frappe.db.get_value("Employee", doc.employee, "date_of_joining")
                require(getdate(joined) < getdate(effective), "CORE-ORDER", "Ngày quyết định phải sau ngày nhận việc.")
                snapshot(doc.employee, doc.doctype, doc.name, joined)
    except DomainError as exc:
        _error(exc)


def on_submit(doc, event=None):
    if doc.doctype == "TLC Employee Change Request":
        apply_change(doc)
    elif doc.doctype in ("Employee Promotion", "Employee Transfer"):
        snapshot(doc.employee, doc.doctype, doc.name, doc.get("promotion_date") or doc.get("transfer_date"))
    elif doc.doctype == "TLC Probation Review" and doc.decision == "Official":
        frappe.db.set_value("Employee", doc.employee, {"custom_tlc_lifecycle_state": "Official", "final_confirmation_date": doc.end_date})


@frappe.whitelist(methods=["POST"])
def complete_boarding(doctype, name):
    try:
        _hr()
        require(doctype in ("Employee Onboarding", "Employee Separation"), "LC-TYPE", "Loại hồ sơ không hợp lệ.")
        doc = frappe.get_doc(doctype, name)
        doc.check_permission("write")
        require(doc.docstatus == 1, "LC-SUBMIT", "Phải duyệt hồ sơ trước khi hoàn tất.")
        SERVICE.complete(doctype, name, doc.get("employee"))
        doc.db_set("boarding_status", "Completed")
        doc.db_set("custom_tlc_completed_by", frappe.session.user)
        if doctype == "Employee Separation":
            require(getdate(doc.custom_tlc_effective_on) <= getdate(today()), "EXIT-FUTURE", "Chưa đến ngày nghỉ chính thức.")
            employee = frappe.get_doc("Employee", doc.employee)
            employee.status, employee.relieving_date = "Left", doc.custom_tlc_effective_on
            employee.custom_tlc_lifecycle_state = "Left"
            employee.save(ignore_permissions=True)
            if employee.user_id:
                frappe.db.set_value("User", employee.user_id, "enabled", 0)
                from frappe.sessions import clear_sessions
                clear_sessions(user=employee.user_id, keep_current=False)
        doc.add_comment("Info", "Hoàn tất có kiểm tra chứng từ và xác nhận bởi " + frappe.session.user)
        return doc.name
    except DomainError as exc:
        _error(exc)


def provisioning(doc, event=None):
    """Native onboarding activities remain assigned Tasks; create only explicitly linked resource requests."""
    if doc.doctype != "Employee Onboarding" or not doc.employee:
        return
    from tlc_hr.infrastructure.frappe.people_ops import provision_onboarding
    assets, licenses = [], []
    for row in doc.get("custom_tlc_evidence") or []:
        # Item references are explicit identifiers, never guessed from a description.
        if row.category == "Asset" and frappe.db.exists("Asset", row.item):
            assets.append(row.item)
        elif row.category == "Account" and frappe.db.exists("TLC People Ops License", row.item):
            licenses.append(row.item)
    if assets or licenses:
        provision_onboarding(doc.employee, asset_items=tuple(assets), account_licenses=tuple(licenses))
