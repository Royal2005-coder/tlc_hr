"""Native Desk/REST hooks: DTO conversion, authorization and accounting evidence (never a bank API)."""
from datetime import timedelta
from decimal import Decimal

import frappe
from frappe.utils import getdate, now_datetime

from tlc_hr.application.travel_finance import TravelFinanceService
from tlc_hr.contracts.travel_finance import AssessSettlement, FinanceTransition, PayrollRecovery, TravelAssessment
from tlc_hr.domain import travel_finance as rules
from tlc_hr.domain.shared import DomainError, NotAllowed
from tlc_hr.infrastructure.frappe.attendance import FrappeAttendanceRepository
from tlc_hr.infrastructure.frappe.overtime import scope_of
from tlc_hr.infrastructure.frappe.travel_finance import FrappeTravelFinanceRepository, money, window_of
from tlc_hr.interface.errors import domain_errors

KINDS = {"Travel Request": "travel", "Employee Advance": "advance", "Expense Claim": "claim"}
FINANCE_ROLES = {"TLC Director", "Accounts User", "Accounts Manager", "TLC HR Lead", "TLC HR Officer", "System Manager"}


def repository():
    return FrappeTravelFinanceRepository()


def service():
    return TravelFinanceService(repository())


def _before(doc):
    return None if doc.is_new() else doc.get_doc_before_save()


def _check_file(url, doctype, name):
    if not url or not frappe.db.exists("File", {"file_url": url, "attached_to_doctype": doctype, "attached_to_name": name}):
        raise DomainError("finance.attachment", "Chứng từ phải là file đã đính kèm vào đúng hồ sơ.")


def _common(doc, before):
    repo = repository()
    route = repo.route(doc.employee)
    doc.tlc_manager_user = route.manager if route.first == rules.MANAGER else None
    doc.tlc_employee_user = route.subject
    doc.tlc_skip_manager = int(route.first == rules.CEO)
    state = doc.get("workflow_state") or rules.DRAFT
    previous = before.get("workflow_state") if before else rules.DRAFT
    if not before and state != rules.DRAFT:
        raise DomainError("finance.initial_state", "Hồ sơ mới phải bắt đầu ở trạng thái Nháp.")
    generated = doc.flags.get("tlc_generated_from_trip")
    if generated:
        trip = frappe.get_doc("Travel Request", generated)
        if not trip.tlc_approved_on or trip.employee != doc.employee or money(trip.tlc_requested_advance) != money(doc.advance_amount):
            raise NotAllowed("finance.generated_advance", "Không khớp đề xuất công tác đã duyệt.")
    elif previous in (rules.DRAFT, rules.RETURNED, rules.REJECTED) or not before:
        rules.authorize(repo.actor(frappe.session.user, doc.employee), route, previous, employee_action=True)
    elif state == previous:
        if doc.doctype == "Travel Request" and previous in (rules.APPROVED, rules.REPORT_RETURN):
            rules.authorize(repo.actor(frappe.session.user, doc.employee), route, previous, employee_action=True)
        elif doc.doctype == "Employee Advance" and _only_consent_changed(doc, before):
            rules.authorize(repo.actor(frappe.session.user, doc.employee), route, previous, employee_action=True)
        elif previous == rules.RECEIPT:
            rules.authorize(repo.actor(frappe.session.user, doc.employee), route, previous, employee_action=True)
        else:
            rules.authorize(repo.actor(frappe.session.user, doc.employee), route, previous)
    if before:
        service().transition(FinanceTransition(kind=KINDS[doc.doctype], employee=doc.employee, before=previous, after=state,
            actor=frappe.session.user, reason=doc.get("tlc_reject_reason") or ""))
    if state != previous and state in (rules.RETURNED, rules.REJECTED, rules.REPORT_RETURN):
        doc.tlc_rejected_stage = previous
    return previous, state


def _only_consent_changed(doc, before):
    return bool(before and (doc.has_value_changed("tlc_payroll_consent") or doc.has_value_changed("tlc_consent_evidence")) and
                frappe.session.user == frappe.db.get_value("Employee", doc.employee, "user_id"))


def _fixed(doc, before, fields, editable):
    if before and before.get("workflow_state") not in editable:
        for field in fields:
            old, new = before.get(field), doc.get(field)
            if field in ("expenses", "advances", "costings", "itinerary", "taxes"):
                ignored = {"modified", "modified_by", "creation", "owner", "docstatus", "parent", "parenttype", "parentfield", "idx", "name"}
                old = [{k: v for k, v in r.as_dict().items() if k not in ignored} for r in old or []]
                new = [{k: v for k, v in r.as_dict().items() if k not in ignored} for r in new or []]
            if old != new:
                raise DomainError("finance.fixed", f"Không sửa {field} sau khi gửi duyệt; trả lại hồ sơ để bổ sung.")


def validate_travel(doc, method=None):
    with domain_errors():
        before = _before(doc)
        previous, state = _common(doc, before)
        _fixed(doc, before, ("tlc_approved_on", "tlc_report_approved_on", "tlc_employee_advance"), ())
        if not before:
            doc.tlc_approved_on, doc.tlc_report_approved_on, doc.tlc_employee_advance = None, None, None
        _fixed(doc, before, ("employee", "company", "tlc_from_date", "tlc_to_date", "tlc_from_session", "tlc_to_session",
            "tlc_funded", "tlc_requested_advance", "tlc_destination", "description", "costings", "itinerary", "cost_center"),
            (rules.DRAFT, rules.RETURNED, rules.REJECTED))
        _fixed(doc, before, ("tlc_actual_from_date", "tlc_actual_to_date", "tlc_actual_from_session", "tlc_actual_to_session",
            "tlc_trip_result", "tlc_expense_claim"), (rules.APPROVED, rules.REPORT_RETURN))
        if not doc.tlc_from_date or not doc.tlc_to_date or not doc.tlc_destination or not doc.description:
            raise DomainError("travel.required", "Nhập nơi đến, mục đích, ngày/buổi đi và về.")
        budget = sum((money(r.total_amount) for r in doc.costings or []), Decimal(0))
        doc.tlc_budget = float(budget)
        command = TravelAssessment(name=None if doc.is_new() else doc.name, employee=doc.employee,
            start=getdate(doc.tlc_from_date), end=getdate(doc.tlc_to_date), start_session=doc.tlc_from_session or "AM",
            end_session=doc.tlc_to_session or "PM", funded=bool(doc.tlc_funded), budget=budget,
            requested_advance=money(doc.tlc_requested_advance), active=state not in rules.INACTIVE and state != rules.CANCELLED)
        service().assess_travel(command)
        days = frappe.db.get_value("Company", doc.company, "tlc_travel_report_days")
        doc.tlc_report_due = getdate(doc.tlc_to_date) + timedelta(days=int(days if days is not None else 3))
        if FrappeAttendanceRepository().locked_period(doc.employee, command.start, command.end):
            frappe.msgprint("Công tác thuộc kỳ công đã khóa: tạo điều chỉnh sau chốt, không sửa dữ liệu kỳ cũ.", indicator="orange")
        if previous == rules.CEO and state == rules.APPROVED:
            doc.tlc_approved_on = now_datetime()
        if state in (rules.REPORT_MANAGER, rules.REPORT_CEO, rules.DONE) and previous != state:
            if not doc.tlc_actual_from_date or not doc.tlc_actual_to_date or not (doc.tlc_trip_result or "").strip():
                raise DomainError("travel.report", "Báo cáo cần kết quả và ngày/buổi thực tế.")
            actual = window_of(doc, actual=True)
            actual.slots()
            if getdate() < actual.end:
                raise DomainError("travel.report_future", "Chỉ nộp báo cáo sau khi kết thúc công tác thực tế.")
            planned = window_of(doc)
            if actual.slots()[0] < planned.slots()[0] or actual.slots()[1] > planned.slots()[1]:
                raise DomainError("travel.extension", "Kéo dài hoặc đi sớm phải tạo đề xuất điều chỉnh được duyệt lại.")
            if doc.tlc_funded:
                claim = frappe.get_doc("Expense Claim", doc.tlc_expense_claim) if doc.tlc_expense_claim else None
                if not claim or claim.employee != doc.employee or claim.tlc_travel_request != doc.name:
                    raise DomainError("travel.report_claim", "Báo cáo công tác có phí phải liên kết quyết toán đúng chuyến đi.")
                if state == rules.DONE and claim.workflow_state != rules.DONE:
                    raise DomainError("travel.unsettled", "Quyết toán chi phí chưa hoàn tất.")
            if previous == rules.REPORT_CEO and state == rules.DONE:
                doc.tlc_report_approved_on = now_datetime()
                if not doc.is_new() and doc.docstatus == 1:
                    doc.db_set("tlc_report_approved_on", doc.tlc_report_approved_on)
        if state == rules.CANCELLED and previous != state:
            if getdate() >= getdate(doc.tlc_from_date):
                raise DomainError("travel.cancel_date", "Chỉ hủy trước ngày đi; về sớm phải nộp báo cáo thực tế.")
            advance = repository().advance_for_trip(doc.name)
            if advance:
                row = frappe.get_doc("Employee Advance", advance)
                if money(row.paid_amount) != money(row.return_amount) + money(row.claimed_amount):
                    raise DomainError("travel.cancel_refund", "Phải hoàn ứng toàn bộ qua chứng từ kế toán trước khi hủy chuyến.")


def travel_updated(doc, method=None):
    before = doc.get_doc_before_save()
    previous = before.get("workflow_state") if before else rules.DRAFT
    if previous == doc.workflow_state:
        return
    with domain_errors():
        if previous == rules.CEO and doc.workflow_state == rules.APPROVED:
            repository().post_travel_days(doc)
            advance = repository().create_trip_advance(doc)
            if advance:
                doc.db_set("tlc_employee_advance", advance)
                draft = frappe.get_doc("Employee Advance", advance)
                draft.db_set("workflow_state", rules.ACCOUNTANT)
                draft.add_comment("Info", f"Kế thừa phê duyệt quản lý/Giám đốc từ {doc.name}; kế toán kiểm tra trước khi chi.")
            _cancel_meals(doc, actual=False)
        if previous == rules.REPORT_CEO and doc.workflow_state == rules.DONE:
            doc.db_set("tlc_report_approved_on", now_datetime())
            repository().post_travel_days(doc, actual=True)
            _cancel_meals(doc, actual=True)
        if doc.workflow_state == rules.CANCELLED and before and before.get("tlc_approved_on"):
            repository().post_travel_days(doc, cancel=True)
        repository().notify(doc, previous)


def _cancel_meals(doc, actual):
    from tlc_hr.interface.services import cancel_meals_for_absence
    window = window_of(doc, actual=actual)
    cancel_meals_for_absence(doc.employee, window.start, window.end, doc.doctype, doc.name)


def validate_advance(doc, method=None):
    with domain_errors():
        before = _before(doc)
        previous, state = _common(doc, before)
        repository().lock_employee(doc.employee)
        _fixed(doc, before, ("paid_amount", "claimed_amount", "return_amount", "tlc_consent_by", "tlc_consent_at"), ())
        _fixed(doc, before, ("tlc_payment_entry",), (rules.DRAFT, rules.RETURNED, rules.REJECTED, rules.PAYMENT))
        _fixed(doc, before, ("employee", "company", "advance_amount", "purpose", "tlc_travel_request", "tlc_settlement_due", "tlc_needed_on",
                            "advance_account", "currency", "tlc_cost_center"), (rules.DRAFT, rules.RETURNED, rules.REJECTED))
        if money(doc.advance_amount) <= 0 or not doc.tlc_needed_on or not doc.tlc_settlement_due:
            raise DomainError("finance.advance_required", "Nhập số tạm ứng dương, ngày cần tiền và hạn quyết toán.")
        if getdate(doc.tlc_settlement_due) < getdate(doc.tlc_needed_on):
            raise DomainError("finance.advance_due", "Hạn quyết toán phải từ ngày cần tiền trở đi.")
        bank = frappe.db.get_value("Employee", doc.employee, "bank_ac_no")
        doc.tlc_receiving_account = bank
        if state not in (rules.DRAFT, rules.RETURNED, rules.REJECTED) and not bank:
            raise DomainError("finance.employee_bank", "Hồ sơ nhân viên chưa có tài khoản nhận tạm ứng.")
        if before and (doc.has_value_changed("tlc_payroll_consent") or doc.has_value_changed("tlc_consent_evidence")):
            subject = repository().route(doc.employee).subject
            if frappe.session.user != subject:
                raise NotAllowed("finance.consent_owner", "Chỉ nhân viên được thay đổi xác nhận đồng ý khấu trừ.")
            if doc.tlc_payroll_consent:
                _check_file(doc.tlc_consent_evidence, doc.doctype, doc.name)
                doc.tlc_consent_by, doc.tlc_consent_at = subject, now_datetime()
            else:
                doc.tlc_consent_by, doc.tlc_consent_at = None, None
        elif not before:
            doc.tlc_payroll_consent, doc.tlc_consent_by, doc.tlc_consent_at = 0, None, None
        if doc.repay_unclaimed_amount_from_salary:
            _authorize_recovery(doc)
        if state == rules.PAID and previous != state:
            repository().payment_evidence(doc.tlc_payment_entry, doctype=doc.doctype, reference=doc.name,
                employee=doc.employee, company=doc.company, direction="Pay", amount=money(doc.advance_amount), currency=doc.currency)
            if money(doc.paid_amount) != money(doc.advance_amount):
                raise DomainError("finance.not_paid", "Sổ tạm ứng chưa ghi nhận đã chi đủ; duyệt không phải là chi tiền.")
        if state == rules.DONE and previous != state:
            if money(doc.paid_amount) != money(doc.claimed_amount) + money(doc.return_amount):
                raise DomainError("finance.open_advance", "Sổ tạm ứng vẫn còn số tiền chưa quyết toán.")
        if previous in (rules.DRAFT, rules.RETURNED, rules.REJECTED) and state not in (rules.DRAFT, rules.RETURNED, rules.REJECTED):
            overdue = frappe.get_all("Employee Advance", filters={"employee": doc.employee, "docstatus": 1,
                "name": ["!=", doc.name], "tlc_settlement_due": ["<", getdate()]}, fields=["name", "paid_amount", "claimed_amount", "return_amount"])
            for row in overdue:
                if money(row.paid_amount) > money(row.claimed_amount) + money(row.return_amount):
                    frappe.msgprint(f"Cảnh báo tạm ứng quá hạn chưa quyết toán: {row.name}", indicator="orange")


def validate_claim(doc, method=None):
    with domain_errors():
        before = _before(doc)
        previous, state = _common(doc, before)
        repository().lock_employee(doc.employee)
        _fixed(doc, before, ("employee", "company", "expenses", "advances", "taxes", "tlc_travel_request", "cost_center", "payable_account"),
               (rules.DRAFT, rules.RETURNED, rules.REJECTED))
        if doc.is_paid:
            raise DomainError("finance.direct_paid", "Không dùng Is Paid để bỏ qua Payment Entry và chứng từ ngân hàng.")
        if not doc.expenses:
            raise DomainError("finance.expenses", "Nhập chi phí thực tế theo từng dòng.")
        for row in doc.expenses:
            if money(row.amount) <= 0:
                raise DomainError("finance.expense_amount", "Số tiền chi phí từng dòng phải lớn hơn 0.")
            if not frappe.db.get_value("Expense Claim Type", row.expense_type, "tlc_non_trade"):
                raise DomainError("finance.non_trade", "Chỉ nhận loại chi phí non-trade do Kế toán quản trị.")
            if state not in (rules.DRAFT, rules.RETURNED, rules.REJECTED):
                _check_file(row.tlc_receipt, doc.doctype, doc.name)
                if money(row.sanctioned_amount) != money(row.amount):
                    raise DomainError("finance.sanctioned", "Nếu điều chỉnh chi phí, trả lại để nhân viên bổ sung và duyệt lại.")
        if len(doc.advances or []) > 1:
            raise DomainError("finance.one_advance", "Một mã quyết toán theo một tạm ứng gốc để đối chiếu đủ ba nhánh.")
        paid = Decimal(0)
        advance = None
        if doc.advances:
            row = doc.advances[0]
            advance = frappe.get_doc("Employee Advance", row.employee_advance)
            if advance.employee != doc.employee or advance.company != doc.company or advance.docstatus != 1 or advance.currency != doc.currency:
                raise DomainError("finance.advance_scope", "Tạm ứng phải được ghi sổ đúng nhân viên, công ty và tiền tệ.")
            if doc.tlc_travel_request and advance.tlc_travel_request != doc.tlc_travel_request:
                raise DomainError("finance.trip_advance", "Tạm ứng và quyết toán phải cùng mã chuyến công tác.")
            other = frappe.db.sql("select ec.name from `tabExpense Claim` ec join `tabExpense Claim Advance` a on a.parent=ec.name "
                "where a.employee_advance=%s and ec.docstatus<2 and ec.name<>%s limit 1", (advance.name, doc.name))
            if other:
                raise DomainError("finance.duplicate_settlement", f"Tạm ứng đã có hồ sơ quyết toán {other[0][0]}.")
            paid = money(advance.paid_amount)
            if paid <= 0:
                raise DomainError("finance.unfunded_advance", "Tạm ứng chưa được chi thực tế.")
        actual = money(doc.total_sanctioned_amount) + money(doc.total_taxes_and_charges)
        result = service().settle(AssessSettlement(advance=paid, actual=actual))
        doc.tlc_advance_paid, doc.tlc_difference, doc.tlc_settlement_branch = float(paid), float(result.difference), result.branch
        if advance and money(doc.advances[0].allocated_amount) != min(actual, paid):
            raise DomainError("finance.allocation", "Phân bổ tạm ứng phải bằng giá trị nhỏ hơn giữa thực chi và đã ứng.")
        if state == rules.SETTLEMENT and previous == rules.ACCOUNTANT:
            doc.approval_status = "Approved"
        if state == rules.RECEIPT and previous != state:
            if result.branch != "top_up":
                raise DomainError("finance.receipt_branch", "Chỉ chi bù mới cần nhân viên xác nhận đã nhận.")
            repository().payment_evidence(doc.tlc_payment_entry, doctype=doc.doctype, reference=doc.name,
                employee=doc.employee, company=doc.company, direction="Pay", amount=-result.difference, currency=doc.currency)
            if money(doc.total_amount_reimbursed) != -result.difference:
                raise DomainError("finance.reimbursement", "Sổ chi phí chưa ghi nhận đủ khoản chi bù.")
        if state == rules.DONE and previous != state:
            refunded = money(advance.return_amount) if advance else Decimal(0)
            if result.branch == "refund":
                repository().payment_evidence(doc.tlc_refund_entry, doctype="Employee Advance", reference=advance.name,
                    employee=doc.employee, company=doc.company, direction="Receive", amount=result.difference,
                    currency=doc.currency, entry_doctype="Journal Entry")
            if result.branch == "top_up":
                if previous != rules.RECEIPT:
                    raise DomainError("finance.employee_receipt", "Nhân viên phải xác nhận đã nhận chi bù.")
                repository().payment_evidence(doc.tlc_payment_entry, doctype=doc.doctype, reference=doc.name,
                    employee=doc.employee, company=doc.company, direction="Pay", amount=-result.difference, currency=doc.currency)
            rules.require_settled(result, refunded=refunded, reimbursed=money(doc.total_amount_reimbursed), receipt=previous == rules.RECEIPT)
            doc.tlc_settled_on = now_datetime()
            if previous == rules.RECEIPT:
                doc.tlc_received_by, doc.tlc_received_on = frappe.session.user, now_datetime()
                if not doc.is_new() and doc.docstatus == 1:
                    doc.db_set({"tlc_settled_on": doc.tlc_settled_on, "tlc_received_by": doc.tlc_received_by, "tlc_received_on": doc.tlc_received_on})


def finance_updated(doc, method=None):
    before = doc.get_doc_before_save()
    previous = before.get("workflow_state") if before else rules.DRAFT
    if doc.doctype == "Expense Claim" and previous == rules.RECEIPT and doc.workflow_state == rules.DONE:
        doc.db_set("tlc_settled_on", now_datetime())
        doc.db_set("tlc_received_by", frappe.session.user)
        doc.db_set("tlc_received_on", now_datetime())
    if previous != doc.workflow_state:
        repository().notify(doc, previous)

def validate_payment(doc, method=None):
    if not any(r.reference_doctype in ("Employee Advance", "Expense Claim") for r in doc.references or []):
        return
    with domain_errors():
        if doc.party_type != "Employee":
            raise DomainError("finance.payment_party", "Chứng từ tạm ứng/hoàn ứng phải có đối tượng nhân viên.")
        rules.authorize(repository().actor(frappe.session.user, doc.party), repository().route(doc.party), rules.ACCOUNTANT)
        if doc.docstatus == 1:
            if not doc.reference_no or not doc.reference_date:
                raise DomainError("finance.payment_reference", "Nhập số và ngày chứng từ ngân hàng trước khi ghi sổ.")
            _check_file(doc.tlc_bank_proof, doc.doctype, doc.name)
        for row in doc.references:
            if row.reference_doctype not in ("Employee Advance", "Expense Claim"):
                continue
            source = frappe.get_doc(row.reference_doctype, row.reference_name)
            valid = (rules.PAYMENT, rules.PAID) if row.reference_doctype == "Employee Advance" else (rules.SETTLEMENT, rules.RECEIPT)
            if source.docstatus != 1 or source.workflow_state not in valid:
                raise DomainError("finance.payment_approval", "Chỉ chi sau khi hoàn tất duyệt và kế toán kiểm tra hồ sơ.")


def payment_before_cancel(doc, method=None):
    if frappe.db.exists("Employee Advance", {"tlc_payment_entry": doc.name, "workflow_state": ["in", [rules.PAID, rules.DONE]]}) or any(
            frappe.db.exists("Expense Claim", {field: doc.name, "workflow_state": ["in", [rules.RECEIPT, rules.DONE]]})
            for field in ("tlc_payment_entry", "tlc_refund_entry")):
        frappe.throw("Không hủy chứng từ ngân hàng đã được đối chiếu; hủy quyết toán liên quan trước.")


def _authorize_recovery(advance):
    service().authorize_recovery(PayrollRecovery(advance=advance.name, employee=advance.employee, actor=frappe.session.user,
        consent=bool(advance.tlc_payroll_consent), evidence=advance.tlc_consent_evidence or "", consent_by=advance.tlc_consent_by or "",
        due=getdate(advance.tlc_settlement_due) if advance.tlc_settlement_due else None, today=getdate()))
    _check_file(advance.tlc_consent_evidence, advance.doctype, advance.name)


def validate_additional_salary(doc, method=None):
    if doc.get("ref_doctype") != "Employee Advance":
        return
    with domain_errors():
        advance = frappe.get_doc("Employee Advance", doc.ref_docname)
        repository().lock_employee(advance.employee)
        _authorize_recovery(advance)
        if doc.employee != advance.employee or doc.company != advance.company or doc.currency != advance.currency:
            raise DomainError("finance.salary_scope", "Khoản khấu trừ phải cùng nhân viên, công ty và tiền tệ tạm ứng.")
        component = frappe.get_doc("Salary Component", doc.salary_component)
        if component.type != "Deduction" or component.salary_component != "Hoàn tạm ứng":
            raise DomainError("finance.salary_component", "Dùng cấu phần khấu trừ Hoàn tạm ứng có tài khoản tạm ứng.")
        scheduled = frappe.db.sql("select coalesce(sum(amount),0) from `tabAdditional Salary` where ref_doctype='Employee Advance' "
            "and ref_docname=%s and docstatus=1 and name<>%s", (advance.name, doc.name))[0][0]
        available = money(advance.paid_amount) - money(advance.claimed_amount) - money(advance.return_amount) - money(scheduled)
        if money(doc.amount) <= 0 or money(doc.amount) > available:
            raise DomainError("finance.salary_amount", "Khấu trừ phải dương và không vượt số tạm ứng còn treo chưa lên lịch thu hồi.")


def _query(doctype, user=None):
    user = user or frappe.session.user
    if set(frappe.get_roles(user)) & FINANCE_ROLES:
        return ""
    scope = scope_of(user)
    return f"`tab{doctype}`.employee in ({', '.join(frappe.db.escape(e) for e in scope)})" if scope else "1=0"


def travel_query(user=None):
    return _query("Travel Request", user)


def advance_query(user=None):
    return _query("Employee Advance", user)


def claim_query(user=None):
    return _query("Expense Claim", user)


def has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    return bool(set(frappe.get_roles(user)) & FINANCE_ROLES) or doc.employee in scope_of(user)
