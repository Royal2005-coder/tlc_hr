"""Native Desk payroll evidence, dated inputs and immutable approved payroll.

No statutory formula, bank certification or external tax/insurance submission lives here.
"""
import json
from datetime import timedelta

import frappe
from frappe.utils import flt, get_datetime, getdate, now_datetime

from tlc_hr.domain.payroll_compliance import effective_base, fingerprint, service_bonus, variance_percent
from tlc_hr.infrastructure.frappe import payroll_compliance_exports as exports

PAYROLL_ROLES = {"TLC Payroll", "TLC HR Lead", "TLC Director", "Accounts User", "System Manager"}
HR_ROLES = {"TLC Payroll", "TLC HR Lead", "System Manager"}
APPROVED = {"Đã ký", "Đã chi"}
DECISION_DOCTYPES = frozenset({
    "Salary Structure Assignment", "TLC Payroll Adjustment", "TLC Payroll Bonus", "TLC Salary Review",
})
DIRECTOR_ROLES = {"TLC Director", "System Manager"}


def require_roles(roles=PAYROLL_ROLES):
    if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(roles):
        frappe.throw("Không có quyền truy cập dữ liệu lương.", frappe.PermissionError)


def private_evidence(url):
    if not url or not frappe.db.exists("File", {"file_url": url, "is_private": 1}):
        frappe.throw("Cần chứng từ riêng tư trong File; không dùng liên kết công khai.")


def decision_scope(doc):
    """Read permission and native Employee scope are prerequisites, never bypassed."""
    doc.check_permission("read")
    if doc.doctype == "TLC Salary Review":
        employees = [row.employee for row in doc.employees]
    elif doc.doctype == "TLC Payroll Adjustment":
        original = frappe.get_doc("Salary Slip", doc.original_slip)
        original.check_permission("read")
        employees = [original.employee]
    else:
        employees = [doc.employee]
    if not employees:
        frappe.throw("Quyết định cần nhân viên thuộc phạm vi được phân quyền.")
    for name in employees:
        employee = frappe.get_doc("Employee", name)
        employee.check_permission("read")
        if doc.get("company") and employee.company != doc.company:
            frappe.throw("Nhân viên không thuộc công ty của quyết định.")
        if doc.doctype == "TLC Salary Review" and employee.department != doc.department:
            frappe.throw("Nhân viên không thuộc bộ phận của đợt xét.")
    return employees


def self_approval(doc):
    if doc.owner == frappe.session.user or doc.get("hr_reviewed_by") == frappe.session.user:
        return True
    employees = [row.employee for row in doc.employees] if doc.doctype == "TLC Salary Review" else [doc.employee]
    return any(frappe.db.get_value("Employee", employee, "user_id") == frappe.session.user for employee in employees)


def decision_blocker(doc):
    if doc.docstatus != 0:
        return "Quyết định không còn là bản nháp; không phê duyệt lại."
    if self_approval(doc):
        return "Người lập, người HR rà soát hoặc nhân viên hưởng lương không được tự phê duyệt."
    if doc.doctype == "TLC Salary Review" and (doc.review_stage != "HR Reviewed" or not doc.hr_reviewed_by):
        return "HR phải tổng hợp và rà soát trước Giám đốc duyệt."
    return None


def record_decision_approval(doc):
    require_roles(DIRECTOR_ROLES)
    decision_scope(doc)
    if self_approval(doc):
        frappe.throw("Không được tự phê duyệt quyết định lương.", frappe.PermissionError)
    doc.tlc_decision_approved_by = frappe.session.user
    doc.tlc_decision_approved_on = now_datetime()


@frappe.whitelist()
def decision_approval_context(doctype, name):
    require_roles(DIRECTOR_ROLES)
    if doctype not in DECISION_DOCTYPES:
        frappe.throw("Loại quyết định không được phép.", frappe.PermissionError)
    doc = frappe.get_doc(doctype, name)
    decision_scope(doc)
    reason = decision_blocker(doc)
    return {"can_approve": not reason, "reason": reason}


@frappe.whitelist(methods=["POST"])
def approve_decision(doctype, name, modified):
    """Approve only a persisted, locked draft; accept no editable document payload."""
    require_roles(DIRECTOR_ROLES)
    if doctype not in DECISION_DOCTYPES:
        frappe.throw("Loại quyết định không được phép.", frappe.PermissionError)
    doc = frappe.get_doc(doctype, name, for_update=True)
    decision_scope(doc)
    if get_datetime(modified) != get_datetime(doc.modified):
        frappe.throw("Quyết định đã thay đổi; tải lại và kiểm tra trước khi phê duyệt.", frappe.TimestampMismatchError)
    reason = decision_blocker(doc)
    if reason:
        frappe.throw(reason, frappe.ValidationError)
    record_decision_approval(doc)
    # Native submit requires both write and submit. The Director has read only:
    # bypass only those DocPerm checks, after explicit role/record/state checks.
    # All controller validation, evidence, hooks, Version and submit side effects run.
    doc.flags.ignore_permissions = True
    doc.submit()
    return {"doctype": doc.doctype, "name": doc.name, "docstatus": doc.docstatus,
            "approved_by": doc.tlc_decision_approved_by, "approved_on": doc.tlc_decision_approved_on}


def assignments(employee, end):
    return frappe.get_all("Salary Structure Assignment", filters={"employee": employee, "docstatus": 1,
                          "from_date": ["<=", end]}, fields=["name", "from_date", "base", "salary_structure",
                          "tlc_decision_reason", "tlc_decision_evidence", "tlc_decision_approved_by"], order_by="from_date asc")


def salary_segments(employee, start, end):
    """Use HRMS attendance/leave/half-day rules for each salary interval, without saving a slip."""
    start, end = getdate(start), getdate(end)
    employee_doc = frappe.get_cached_doc("Employee", employee)
    rows = assignments(employee, end)
    joined = getdate(employee_doc.date_of_joining) if employee_doc.date_of_joining else start
    actual_start = max(start, joined)
    active = [r for r in rows if getdate(r.from_date) <= actual_start]
    if not active:
        frappe.throw(f"{employee}: thiếu Salary Structure Assignment có hiệu lực {actual_start}.")
    relevant = [active[-1]] + [r for r in rows if actual_start < getdate(r.from_date) <= end]
    if len({r.salary_structure for r in relevant}) != 1:
        frappe.throw(f"{employee}: đổi cấu trúc lương giữa kỳ cần tách kỳ lương; không tự trộn công thức.")
    segments = []
    for index, row in enumerate(relevant):
        first = max(start, getdate(row.from_date))
        last = min(end, getdate(relevant[index + 1].from_date) - timedelta(days=1)) if index + 1 < len(relevant) else end
        probe = frappe.new_doc("Salary Slip")
        probe.update({"employee": employee, "company": employee_doc.company, "start_date": first, "end_date": last,
                      "joining_date": employee_doc.date_of_joining, "relieving_date": employee_doc.relieving_date,
                      "actual_start_date": max(first, joined), "actual_end_date": min(last, getdate(employee_doc.relieving_date))
                      if employee_doc.relieving_date else last})
        probe.get_working_days_details()
        segments.append({"assignment": row.name, "from_date": str(first), "to_date": str(last), "base": flt(row.base),
                         "payment_days": max(0, flt(probe.payment_days)), "working_days": flt(probe.total_working_days)})
    return segments


def prepare_slip(doc, method=None):
    if not doc.employee or not doc.start_date or not doc.end_date or doc.docstatus == 2:
        return
    if not doc.is_new() and frappe.db.get_value("Salary Slip", doc.name, "docstatus") == 1:
        return
    from tlc_hr.infrastructure.frappe.lifecycle import verified_dependents
    segments = salary_segments(doc.employee, doc.start_date, doc.end_date)
    doc.tlc_effective_base = float(effective_base(segments))
    doc.tlc_effective_dependents = len(verified_dependents(doc.employee, getdate(doc.end_date)))
    doc.tlc_salary_segments = json.dumps(segments, ensure_ascii=False)


def validate_assignment(doc, method=None):
    if doc.docstatus != 1 or not doc.is_new() and frappe.db.get_value(doc.doctype, doc.name, "docstatus") == 1:
        return
    previous = frappe.db.get_value("Salary Structure Assignment", {"employee": doc.employee, "docstatus": 1,
                                  "from_date": ["<", doc.from_date]}, ["name", "base"], order_by="from_date desc", as_dict=True)
    doc.tlc_previous_base = flt(previous.base) if previous else 0
    if previous and flt(previous.base) != flt(doc.base):
        if not doc.tlc_decision_reason:
            frappe.throw("Quyết định thay đổi lương cần lý do.")
        private_evidence(doc.tlc_decision_evidence)
        record_decision_approval(doc)
    elif not previous:
        doc.tlc_decision_approved_by = frappe.session.user


def slip_payload(doc):
    return {"name": doc.name, "employee": doc.employee, "start": str(doc.start_date), "end": str(doc.end_date),
            "structure": doc.salary_structure, "segments": doc.get("tlc_salary_segments"),
            "dependents": doc.get("tlc_effective_dependents"), "payment_days": flt(doc.payment_days),
            "gross": flt(doc.gross_pay), "net": flt(doc.net_pay),
            "rows": [(table, r.salary_component, flt(r.amount)) for table in ("earnings", "deductions", "employer_contributions")
                     for r in (doc.get(table) or [])]}


def entry_payload(entry):
    names = frappe.get_all("Salary Slip", filters={"payroll_entry": entry.name, "docstatus": ["!=", 2]},
                           pluck="name", order_by="name")
    return [slip_payload(frappe.get_doc("Salary Slip", name)) for name in names]


def review_issues(entry):
    threshold = frappe.db.get_value("Company", entry.company, "tlc_payroll_variance_percent")
    threshold = 20 if threshold is None else flt(threshold)
    if threshold < 0:
        frappe.throw("Ngưỡng biến động không được âm.")
    issues = []
    for payload in entry_payload(entry):
        current = fingerprint(payload)
        previous = frappe.db.get_value("Salary Slip", {"employee": payload["employee"], "company": entry.company,
                         "docstatus": 1, "end_date": ["<", entry.start_date]},
                         ["name", "gross_pay", "net_pay"], order_by="end_date desc", as_dict=True)
        if previous:
            gross = variance_percent(previous.gross_pay, payload["gross"])
            net = variance_percent(previous.net_pay, payload["net"])
            if max(gross, net) > threshold:
                issues.append({"employee": payload["employee"], "issue": "Variance", "fingerprint": current,
                               "details": f"Gross {gross:.2f}%; net {net:.2f}%; ngưỡng {threshold}%; kỳ trước {previous.name}"})
        for row in assignments(payload["employee"], entry.end_date):
            if getdate(entry.start_date) <= getdate(row.from_date) <= getdate(entry.end_date):
                earlier = frappe.db.exists("Salary Structure Assignment", {"employee": payload["employee"],
                                          "docstatus": 1, "from_date": ["<", row.from_date]})
                if earlier and not (row.tlc_decision_reason and row.tlc_decision_evidence and row.tlc_decision_approved_by):
                    issues.append({"employee": payload["employee"], "issue": "Salary decision", "fingerprint": current,
                                   "details": f"Thiếu quyết định được duyệt: {row.name}"})
    return issues


def gate_review(entry):
    if not entry_payload(entry):
        frappe.throw("Chưa có phiếu lương để rà soát.")
    unresolved = []
    for issue in review_issues(entry):
        if not frappe.db.exists("TLC Payroll Review", {"payroll_entry": entry.name, "employee": issue["employee"],
                               "issue": issue["issue"], "review_fingerprint": issue["fingerprint"], "docstatus": 1}):
            unresolved.append(f"{issue['employee']}: {issue['details']}")
    if unresolved:
        frappe.throw("Chưa xử lý sai lệch trước trình/ký: " + "; ".join(unresolved))


@frappe.whitelist()
def inspect_reviews(name):
    require_roles()
    entry = frappe.get_doc("Payroll Entry", name)
    entry.check_permission("read")
    return review_issues(entry)


@frappe.whitelist(methods=["POST"])
def new_review(name, employee, issue="Variance"):
    require_roles(HR_ROLES)
    entry = frappe.get_doc("Payroll Entry", name)
    entry.check_permission("read")
    if not frappe.has_permission("TLC Payroll Review", "create"):
        frappe.throw("Không có quyền lập phiếu rà soát.", frappe.PermissionError)
    if entry.workflow_state in APPROVED:
        frappe.throw("Bảng lương đã duyệt không mở rà soát lại; dùng phiếu điều chỉnh kỳ sau.")
    item = next((r for r in review_issues(entry) if r["employee"] == employee and r["issue"] == issue), None)
    if not item:
        frappe.throw("Không có sai lệch tương ứng.")
    doc = frappe.get_doc({"doctype": "TLC Payroll Review", "payroll_entry": name, "employee": employee,
                          "issue": issue, "review_fingerprint": item["fingerprint"], "reason": item["details"]})
    return doc.as_dict()


def validate_review(doc, method=None):
    require_roles(HR_ROLES)
    private_evidence(doc.evidence)
    entry = frappe.get_doc("Payroll Entry", doc.payroll_entry)
    entry.check_permission("read")
    if entry.workflow_state in APPROVED:
        frappe.throw("Không sửa rà soát của bảng lương đã duyệt.")
    issues = review_issues(entry)
    if not any(i["employee"] == doc.employee and i["issue"] == doc.issue and i["fingerprint"] == doc.review_fingerprint for i in issues):
        frappe.throw("Dữ liệu đã đổi hoặc không còn sai lệch; tạo lại phiếu rà soát.")
    if doc.issue == "Salary decision":
        frappe.throw("Phải hoàn thiện quyết định Salary Structure Assignment; giải trình không thay thế phê duyệt lương.")
    if doc.docstatus == 1:
        doc.reviewed_by, doc.reviewed_on = frappe.session.user, now_datetime()


def entry_guard(doc, method=None):
    before = doc.get_doc_before_save()
    if not before:
        return
    if before.workflow_state in APPROVED:
        if before.workflow_state == "Đã chi":
            allowed = {"modified", "modified_by"}
        else:
            allowed = {"modified", "modified_by", "workflow_state", "tlc_bank_reference", "tlc_paid_on", "tlc_bank_proof", "tlc_reject_reason", "tlc_rejected_stage"}
        before_values, after_values = before.as_dict(), doc.as_dict()
        child_meta = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
                      "parent", "parentfield", "parenttype", "doctype", "__islocal", "__unsaved"}
        for field in doc.meta.fields:
            key = field.fieldname
            if key in allowed:
                continue
            if field.fieldtype in ("Table", "Table MultiSelect"):
                rows = lambda values: [{k: v for k, v in row.items() if k not in child_meta}
                                       for row in values.get(key) or []]
                changed = fingerprint(rows(before_values)) != fingerprint(rows(after_values))
            else:
                changed = fingerprint(before_values.get(key)) != fingerprint(after_values.get(key))
            if changed:
                frappe.throw("Bảng lương đã duyệt bất biến; dùng phiếu điều chỉnh kỳ sau.")
        if doc.workflow_state not in APPROVED:
            frappe.throw("Không mở lại bảng lương đã duyệt.")
    if doc.workflow_state in {"Chờ giám đốc ký", "Đã ký"} and before.workflow_state != doc.workflow_state:
        gate_review(doc)
        if doc.workflow_state == "Đã ký":
            doc.tlc_approval_fingerprint = fingerprint(entry_payload(doc))


def prohibit_approved_change(doc, method=None):
    entry_name = doc.name if doc.doctype == "Payroll Entry" else doc.get("payroll_entry")
    if entry_name and frappe.db.get_value("Payroll Entry", entry_name, "workflow_state") in APPROVED:
        if method in ("on_trash", "before_cancel") or doc.doctype == "Salary Slip":
            frappe.throw("Bảng lương/phiếu lương đã duyệt bất biến; dùng phiếu điều chỉnh kỳ sau.")


def validate_award(doc, method=None):
    private_evidence(doc.evidence)
    if doc.doctype == "TLC Payroll Adjustment":
        original = frappe.get_doc("Salary Slip", doc.original_slip)
        original.check_permission("read")
        if original.docstatus != 1 or not original.payroll_entry or frappe.db.get_value("Payroll Entry", original.payroll_entry, "workflow_state") not in APPROVED:
            frappe.throw("Điều chỉnh chỉ tham chiếu phiếu lương gốc đã duyệt.")
        doc.employee = original.employee
        if getdate(doc.payroll_date) <= getdate(original.end_date):
            frappe.throw("Điều chỉnh phải thuộc kỳ sau kỳ lương gốc.")
        component_type = frappe.db.get_value("Salary Component", doc.salary_component, "type")
        if component_type != ("Earning" if doc.direction == "Increase" else "Deduction"):
            frappe.throw("Increase là cộng thực lĩnh (Earning); Decrease là trừ thực lĩnh (Deduction). Chọn đúng cấu phần và tính chất thuế.")
        if flt(doc.amount) <= 0:
            frappe.throw("Số tiền điều chỉnh phải dương.")
    else:
        start, end = getdate(doc.period_start), getdate(doc.period_end)
        if start > end or getdate(doc.payroll_date) < end:
            frappe.throw("Kỳ thưởng/ngày trả thưởng không hợp lệ.")
        if doc.frequency == "Monthly" and (start.day != 1 or end != getdate(frappe.utils.get_last_day(start))):
            frappe.throw("Thưởng tháng phải bao trọn một tháng lịch.")
        if doc.frequency == "Yearly" and (start.month != 1 or start.day != 1 or end != getdate(f"{start.year}-12-31")):
            frappe.throw("Thưởng năm phải bao trọn một năm lịch.")
        employee = frappe.get_doc("Employee", doc.employee)
        base = frappe.db.get_value("Salary Structure Assignment", {"employee": doc.employee, "docstatus": 1,
                                   "from_date": ["<=", end]}, "base", order_by="from_date desc")
        if base is None:
            frappe.throw("Chưa có lương hiệu lực để tính thưởng.")
        doc.reference_salary = base
        doc.amount = float(service_bonus(base, doc.multiplier, str(start), str(end), str(employee.date_of_joining),
                                        str(employee.relieving_date) if employee.relieving_date else None))
        doc.formula = "Lương hiệu lực cuối kỳ × hệ số được duyệt × ngày làm việc trong quan hệ lao động / ngày lịch của kỳ."
        duplicate = frappe.db.exists(doc.doctype, {"employee": doc.employee, "frequency": doc.frequency,
                       "period_start": start, "period_end": end, "docstatus": 1, "name": ["!=", doc.name]})
        if duplicate:
            frappe.throw(f"Đã có thưởng được duyệt cho kỳ này: {duplicate}")
    if doc.docstatus == 1:
        record_decision_approval(doc)


def apply_awards(entry, method=None):
    """Run before native draft slips: source rows serialize concurrent consumption."""
    for doctype in ("TLC Payroll Adjustment", "TLC Payroll Bonus"):
        for name in frappe.get_all(doctype, filters={"docstatus": 1, "payroll_date": ["between", [entry.start_date, entry.end_date]],
                                  "employee": ["in", [r.employee for r in entry.employees]]}, pluck="name"):
            frappe.db.get_value(doctype, name, "name", for_update=True)
            source = frappe.get_doc(doctype, name)
            if source.applied_payroll:
                if source.applied_payroll != entry.name:
                    frappe.throw(f"{name}: đã dùng ở {source.applied_payroll}; không trả hai lần.")
                continue
            component = source.salary_component if doctype == "TLC Payroll Adjustment" else frappe.db.get_value(
                "Salary Component", {"salary_component_abbr": "TH"}, "name")
            employee_company = frappe.db.get_value("Employee", source.employee, "company")
            if employee_company != entry.company or not component:
                frappe.throw(f"{name}: công ty/cấu phần không hợp lệ.")
            if not flt(source.amount):
                continue
            salary = frappe.get_doc({"doctype": "Additional Salary", "employee": source.employee, "company": entry.company,
                    "salary_component": component, "amount": source.amount, "payroll_date": source.payroll_date,
                    "overwrite_salary_structure_amount": 0, "ref_doctype": doctype, "ref_docname": name,
                    "tlc_compliance_source": f"{doctype}:{name}"}).insert(ignore_permissions=True)
            salary.submit()
            frappe.db.set_value(doctype, name, {"applied_payroll": entry.name, "additional_salary": salary.name})


def release_awards(entry, method=None):
    if entry.workflow_state in APPROVED:
        frappe.throw("Không hủy kỳ lương đã duyệt.")
    for doctype in ("TLC Payroll Adjustment", "TLC Payroll Bonus"):
        for name in frappe.get_all(doctype, filters={"applied_payroll": entry.name}, pluck="name"):
            source = frappe.get_doc(doctype, name)
            if source.additional_salary:
                salary = frappe.get_doc("Additional Salary", source.additional_salary)
                if salary.docstatus == 1:
                    salary.flags.ignore_permissions = True
                    salary.cancel()
            frappe.db.set_value(doctype, name, {"applied_payroll": None, "additional_salary": None})


def guard_source_cancel(doc, method=None):
    if doc.get("applied_payroll"):
        frappe.throw("Khoản nguồn đã vào kỳ lương; hủy kỳ nháp trước hoặc lập điều chỉnh mới.")


def validate_insurance(doc, method=None):
    require_roles(HR_ROLES)
    private_evidence(doc.evidence)
    if doc.doctype == "TLC Insurance Change":
        if flt(doc.contribution_base) < 0 or doc.change_type != "Stop" and flt(doc.contribution_base) <= 0:
            frappe.throw("Mức đóng BHXH không hợp lệ.")
        if doc.status in ("Filed", "Accepted", "Rejected") and (not doc.filing_reference or not doc.filed_on):
            frappe.throw("Hồ sơ đã gửi cần ngày gửi và mã hồ sơ thực.")
        if doc.status in ("Accepted", "Rejected") and not doc.response_on:
            frappe.throw("Kết quả BHXH cần ngày phản hồi.")
        if doc.response_on and doc.filed_on and getdate(doc.response_on) < getdate(doc.filed_on):
            frappe.throw("Ngày phản hồi không trước ngày gửi.")
    else:
        leave = frappe.get_doc("Leave Application", doc.leave_application)
        if leave.employee != doc.employee or leave.docstatus != 1 or leave.status != "Approved":
            frappe.throw("Hồ sơ hưởng BHXH cần đơn nghỉ đã duyệt của đúng nhân viên.")
        if getdate(doc.actual_from) > getdate(doc.actual_to):
            frappe.throw("Ngày thực tế không hợp lệ.")
        if getdate(doc.actual_from) < getdate(leave.from_date) or getdate(doc.actual_to) > getdate(leave.to_date):
            frappe.throw("Điều chỉnh đơn nghỉ theo chứng từ thực tế trước khi lập hồ sơ hưởng BHXH.")
        if doc.status in ("Filed", "Accepted", "Paid", "Rejected") and (not doc.filing_reference or not doc.filed_on):
            frappe.throw("Cần ngày gửi và mã hồ sơ thực.")
        if flt(doc.approved_amount) < 0 or flt(doc.received_amount) < 0 or flt(doc.received_amount) > flt(doc.approved_amount):
            frappe.throw("Tiền nhận không âm và không vượt số được duyệt.")
        if doc.status == "Paid" and (not doc.received_on or not doc.payment_reference or not flt(doc.received_amount)):
            frappe.throw("Đã nhận chế độ cần ngày nhận, số tiền và tham chiếu chi thực.")
        if doc.received_on and doc.filed_on and getdate(doc.received_on) < getdate(doc.filed_on):
            frappe.throw("Ngày nhận không trước ngày gửi hồ sơ.")


def salary_review_query(user=None):
    user = user or frappe.session.user
    if user == "Administrator" or set(frappe.get_roles(user)) & PAYROLL_ROLES:
        return ""
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    department = frappe.db.get_value("Employee", employee, "department") if employee else None
    return "`tabTLC Salary Review`.`department`=" + frappe.db.escape(department or "__denied__")


def salary_review_permission(doc, user=None, permission_type=None):
    user = user or frappe.session.user
    if user == "Administrator" or set(frappe.get_roles(user)) & PAYROLL_ROLES:
        return True
    department = frappe.db.get_value("Employee", {"user_id": user}, "department")
    if not doc or not getattr(doc, "department", None):
        return bool(department and "TLC Line Manager" in frappe.get_roles(user))
    return bool(department and department == doc.department and "TLC Line Manager" in frappe.get_roles(user))


def validate_salary_review(doc, method=None):
    if not salary_review_permission(doc):
        frappe.throw("Chỉ đề xuất trong bộ phận được phân quyền.", frappe.PermissionError)
    private_evidence(doc.evidence)
    if not doc.employees or flt(doc.annual_budget_increase) < 0:
        frappe.throw("Cần danh sách và ngân sách tăng lương không âm.")
    seen, increase = set(), 0
    for row in doc.employees:
        employee = frappe.get_doc("Employee", row.employee)
        if row.employee in seen or employee.department != doc.department or employee.company != doc.company:
            frappe.throw("Nhân viên trùng/không thuộc bộ phận/công ty của đợt xét.")
        seen.add(row.employee)
        base = frappe.db.get_value("Salary Structure Assignment", {"employee": row.employee, "docstatus": 1,
                                  "from_date": ["<", doc.effective_on]}, "base", order_by="from_date desc")
        if base is None or flt(row.new_base) <= 0:
            frappe.throw("Cần mức lương hiện tại và mức đề xuất dương.")
        row.old_base = base
        increase += max(0, flt(row.new_base) - flt(base)) * 12
    if increase > flt(doc.annual_budget_increase):
        frappe.throw("Tổng tăng lương năm vượt ngân sách bộ phận.")
    before = doc.get_doc_before_save()
    if doc.review_stage == "HR Reviewed" and (not before or before.review_stage != "HR Reviewed"):
        require_roles(HR_ROLES)
        doc.hr_reviewed_by, doc.hr_reviewed_on = frappe.session.user, now_datetime()
    elif before and before.review_stage == "HR Reviewed":
        old = [(r.employee, flt(r.new_base)) for r in before.employees]
        new = [(r.employee, flt(r.new_base)) for r in doc.employees]
        if old != new or str(before.effective_on) != str(doc.effective_on) or flt(before.annual_budget_increase) != flt(doc.annual_budget_increase):
            frappe.throw("Đã HR rà soát: chuyển Draft trước khi sửa đề xuất.")
    if doc.docstatus == 1:
        record_decision_approval(doc)
        if doc.review_stage != "HR Reviewed" or not doc.hr_reviewed_by:
            frappe.throw("HR phải tổng hợp và rà soát trước Giám đốc duyệt.")


def approve_salary_review(doc, method=None):
    require_roles({"TLC Director", "System Manager"})
    for row in doc.employees:
        old_name = frappe.db.get_value("Salary Structure Assignment", {"employee": row.employee, "docstatus": 1,
                            "from_date": ["<", doc.effective_on]}, "name", order_by="from_date desc")
        previous = frappe.get_doc("Salary Structure Assignment", old_name)
        previous.check_permission("read")
        assignment = frappe.copy_doc(previous)
        assignment.update({"from_date": doc.effective_on, "base": row.new_base, "tlc_decision_reason": "Periodic",
                           "tlc_decision_evidence": doc.evidence, "tlc_salary_review": doc.name})
        decision_scope(doc)
        assignment.owner = doc.owner
        assignment.flags.ignore_permissions = True
        assignment.insert()
        assignment.submit()
        frappe.db.set_value(row.doctype, row.name, "assignment", assignment.name)


@frappe.whitelist(methods=["POST"])
def deliver_payslips(name):
    """Queue HRMS's real encrypted PDF mail; never mark delivered merely because enqueued."""
    require_roles(HR_ROLES | {"Accounts User"})
    entry = frappe.get_doc("Payroll Entry", name)
    entry.check_permission("read")
    if entry.workflow_state not in APPROVED:
        frappe.throw("Chỉ phát hành phiếu lương đã duyệt.")
    settings = frappe.get_single("Payroll Settings")
    if not settings.encrypt_salary_slips_in_emails or not settings.password_policy:
        frappe.throw("Bật Encrypt Salary Slips in Emails và cấu hình Password Policy trong Payroll Settings.")
    if not settings.sender or not frappe.db.get_value("Email Account", settings.sender, "enable_outgoing"):
        frappe.throw("Cần Email Account gửi thư thực đang bật; chưa có kết nối thì không thể phát hành email.")
    names = frappe.get_all("Salary Slip", filters={"payroll_entry": name, "docstatus": 1}, pluck="name")
    from hrms.payroll.doctype.salary_slip.salary_slip import generate_password_for_pdf, enqueue_email_salary_slips
    for slip_name in names:
        slip = frappe.get_doc("Salary Slip", slip_name)
        if not frappe.db.get_value("Employee", slip.employee, "prefered_email"):
            frappe.throw(f"{slip.employee}: thiếu email ưu tiên.")
        if not generate_password_for_pdf(settings.password_policy, slip.employee):
            frappe.throw(f"{slip.employee}: Password Policy tạo mật khẩu rỗng.")
    if not names:
        frappe.throw("Chưa có phiếu lương đã ghi sổ.")
    enqueue_email_salary_slips(names)
    return {"queued": len(names), "delivery_status": "Xem Email Queue; xếp hàng không đồng nghĩa đã gửi."}


@frappe.whitelist()
def export_bank_batch(name, bank_code="VCB"):
    return exports.export_bank_payment_batch(name, bank_code)


@frappe.whitelist()
def export_accounting(name):
    return exports.export_accounting_reconciliation(name)


@frappe.whitelist()
def export_pit(company, from_date, to_date):
    return exports.export_pit_report(company, from_date, to_date)


@frappe.whitelist()
def export_bhxh_d02lt(company, month):
    return exports.export_bhxh_d02lt(company, month)


@frappe.whitelist()
def export_labor_register(company, as_of=None):
    return exports.export_labor_register(company, as_of)


@frappe.whitelist()
def simulate_salary(company, percent_increase, base_date=None, department=None):
    return exports.simulate_salary_budget(company, percent_increase, base_date, department)


@frappe.whitelist()
def cost_report(company, start_date, end_date, group_by="department"):
    return exports.get_role_private_cost_report(company, start_date, end_date, group_by)


@frappe.whitelist()
def headcount_report(company, from_date, to_date):
    return exports.get_headcount_movement_report(company, from_date, to_date)


@frappe.whitelist()
def payroll_anomalies(name):
    return exports.check_payroll_anomalies(name)

@frappe.whitelist()
def preview_effective_base(segments):
    """Weighted base of dated salary segments, for the desk and UAT preview."""
    require_roles()
    rows = frappe.parse_json(segments) if isinstance(segments, str) else segments
    return float(effective_base(rows))


@frappe.whitelist()
def preview_service_bonus(reference_salary, multiplier, period_start, period_end, joining_date, reliever_date=None):
    require_roles()
    return float(service_bonus(reference_salary, multiplier, period_start, period_end, joining_date, reliever_date))

