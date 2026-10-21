"""Native HRMS documents and accounting ledgers implement the travel/finance ports."""
from datetime import timedelta
from decimal import Decimal

import frappe
from frappe.utils import getdate

from tlc_hr.domain import travel_finance as rules
from tlc_hr.domain.shared import DomainError
from tlc_hr.domain.travel_finance_ports import ITravelFinanceRepository
from tlc_hr.infrastructure.frappe.attendance import FrappeAttendanceRepository
from tlc_hr.infrastructure.frappe.overtime import scope_of


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def window_of(doc, actual=False):
    prefix = "tlc_actual_" if actual else "tlc_"
    return rules.Window(getdate(doc.get(prefix + "from_date")), getdate(doc.get(prefix + "to_date")),
                        doc.get(prefix + "from_session") or "AM", doc.get(prefix + "to_session") or "PM")


class FrappeTravelFinanceRepository(ITravelFinanceRepository):
    def route(self, employee):
        row = frappe.db.get_value("Employee", employee, ["user_id", "department", "reports_to", "leave_approver"], as_dict=True)
        head = frappe.db.get_value("Department", row.department, "tlc_head") if row.department else None
        manager = frappe.db.get_value("Employee", head or row.reports_to, "user_id") if head or row.reports_to else row.leave_approver
        return rules.Route(row.user_id or "", manager, bool(manager and "TLC Director" in frappe.get_roles(manager)))

    def actor(self, user, employee):
        return rules.Actor(user, frozenset(frappe.get_roles(user)), employee in scope_of(user))

    def lock_employee(self, employee):
        frappe.db.sql("select name from `tabEmployee` where name=%s for update", employee)

    def payroll_policy(self, employee):
        company = frappe.db.get_value("Employee", employee, "company")
        return bool(frappe.db.get_value("Company", company, "tlc_allow_advance_payroll_recovery"))

    def conflicts(self, employee, window, exclude):
        result = []
        overlap = {"employee": employee, "docstatus": ["<", 2], "from_date": ["<=", window.end], "to_date": [">=", window.start],
                   "status": ["not in", ["Rejected", "Cancelled"]]}
        for row in frappe.get_all("Leave Application", filters=overlap, fields=["name", "from_date", "to_date", "half_day", "half_day_date"]):
            # A native leave half-day has no AM/PM; conservatively reserve the entire day.
            if window.overlaps(rules.Window(getdate(row.from_date), getdate(row.to_date))):
                result.append(row.name)
        for row in frappe.get_all("Travel Request", filters={"employee": employee, "docstatus": ["<", 2],
                "workflow_state": ["not in", list(rules.INACTIVE)], "name": ["!=", exclude or ""],
                "tlc_from_date": ["<=", window.end], "tlc_to_date": [">=", window.start]},
                fields=["name", "tlc_from_date", "tlc_to_date", "tlc_from_session", "tlc_to_session"]):
            if window.overlaps(window_of(row)):
                result.append(row.name)
        for row in frappe.get_all("TLC Overtime Request", filters={"employee": employee, "docstatus": ["<", 2],
                "workflow_state": ["not in", ["Từ chối", "Đã hủy"]], "ot_date": ["between", [window.start, window.end]]},
                fields=["name", "ot_date", "from_time", "to_time"]):
            # OT may cross midnight; an overnight request reserves the following day too.
            start = getdate(row.ot_date)
            end = start + timedelta(days=int(str(row.to_time) <= str(row.from_time)))
            if window.overlaps(rules.Window(start, end)):
                result.append(row.name)
        return result

    def payment_evidence(self, name, *, doctype, reference, employee, company, direction, amount, currency,
                         entry_doctype="Payment Entry"):
        if not name:
            raise DomainError("finance.proof", "Chọn chứng từ ngân hàng đã ghi sổ, có số tham chiếu và file ủy nhiệm chi.")
        if entry_doctype == "Journal Entry":
            return self._journal_refund(name, reference=reference, employee=employee, company=company,
                                        direction=direction, amount=amount, currency=currency)
        payment = frappe.get_doc("Payment Entry", name)
        if (payment.docstatus != 1 or payment.payment_type != direction or payment.party_type != "Employee"
                or payment.party != employee or payment.company != company or not payment.reference_no or not payment.reference_date):
            raise DomainError("finance.proof", "Chứng từ phải được ghi sổ đúng nhân viên, công ty, chiều thu/chi và có tham chiếu ngân hàng.")
        proof = payment.get("tlc_bank_proof")
        if not proof or not frappe.db.exists("File", {"file_url": proof, "attached_to_doctype": "Payment Entry", "attached_to_name": name}):
            raise DomainError("finance.bank_proof", "Đính kèm file ủy nhiệm chi thực tế vào Payment Entry.")
        allocations = sum((money(r.allocated_amount) for r in payment.references
                           if r.reference_doctype == doctype and r.reference_name == reference), Decimal(0))
        party_currency = payment.paid_to_account_currency if direction == "Pay" else payment.paid_from_account_currency
        if party_currency != currency or allocations != amount:
            raise DomainError("finance.proof_amount", "Số tiền phân bổ hoặc tiền tệ của Payment Entry không khớp số cần đối chiếu.")
        if not frappe.db.exists("GL Entry", {"voucher_type": "Payment Entry", "voucher_no": name, "is_cancelled": 0}):
            raise DomainError("finance.ledger", "Payment Entry chưa có bút toán kế toán còn hiệu lực.")
        return payment

    def _journal_refund(self, name, *, reference, employee, company, direction, amount, currency):
        # HRMS books an employee advance return as a bank Journal Entry against the advance account.
        journal = frappe.get_doc("Journal Entry", name)
        if (journal.docstatus != 1 or journal.company != company or direction != "Receive"
                or not journal.cheque_no or not journal.cheque_date):
            raise DomainError("finance.proof", "Bút toán hoàn ứng phải ghi sổ đúng công ty và có số/ngày chứng từ ngân hàng.")
        proof = journal.get("tlc_bank_proof")
        if not proof or not frappe.db.exists("File", {"file_url": proof, "attached_to_doctype": "Journal Entry", "attached_to_name": name}):
            raise DomainError("finance.bank_proof", "Đính kèm file ủy nhiệm chi thực tế vào bút toán hoàn ứng.")
        advance_account = frappe.db.get_value("Employee Advance", reference, "advance_account")
        rows = [row for row in journal.accounts if row.reference_type == "Employee Advance" and row.reference_name == reference]
        credited = sum((money(row.credit_in_account_currency) for row in rows
                        if row.account == advance_account and row.party_type == "Employee"
                        and row.party == employee and row.is_advance == "Yes"), Decimal(0))
        if not rows or credited != amount or any(row.account_currency != currency for row in rows):
            raise DomainError("finance.proof_amount", "Bút toán hoàn ứng phải ghi có đúng tài khoản tạm ứng, nhân viên và số tiền cần đối chiếu.")
        if not frappe.db.exists("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": name, "is_cancelled": 0}):
            raise DomainError("finance.ledger", "Bút toán hoàn ứng chưa có bút toán kế toán còn hiệu lực.")
        return journal

    def advance_for_trip(self, trip):
        return frappe.db.get_value("Employee Advance", {"tlc_travel_request": trip, "docstatus": ["<", 2]}, "name")

    def create_trip_advance(self, trip):
        if money(trip.tlc_requested_advance) <= 0:
            return None
        existing = self.advance_for_trip(trip.name)
        if existing:
            return existing
        # Travel approval is not advance payment: this draft follows the same independent finance route.
        account = frappe.db.get_value("Company", trip.company, "default_employee_advance_account")
        advance = frappe.get_doc({"doctype": "Employee Advance", "employee": trip.employee, "company": trip.company,
            "posting_date": getdate(), "currency": frappe.db.get_value("Company", trip.company, "default_currency"),
            "exchange_rate": 1, "advance_account": account, "purpose": trip.description or trip.name,
            "advance_amount": trip.tlc_requested_advance, "tlc_travel_request": trip.name,
            "tlc_settlement_due": trip.tlc_report_due, "tlc_needed_on": trip.tlc_from_date,
            "tlc_cost_center": trip.cost_center, "workflow_state": rules.DRAFT})
        advance.flags.tlc_generated_from_trip = trip.name
        advance.insert(ignore_permissions=True)
        return advance.name

    def open_travel_items(self, employees, start, end):
        return [f"{r.name} · Công tác chưa hoàn tất báo cáo ({r.workflow_state})" for r in frappe.get_all("Travel Request", filters={
            "employee": ["in", employees or [""]], "docstatus": ["<", 2], "tlc_from_date": ["<=", end], "tlc_to_date": [">=", start],
            "workflow_state": ["not in", [rules.DONE, rules.CANCELLED, rules.REJECTED]]}, fields=["name", "workflow_state"])]

    def post_travel_days(self, trip, *, actual=False, cancel=False):
        """Preserve locked snapshots; report differences become HR-controlled post-close requests."""
        planned = dict(window_of(trip).days())
        target = {} if cancel else dict(window_of(trip, actual=actual).days())
        days = sorted(set(planned) | set(target))
        calendar = FrappeAttendanceRepository()
        from erpnext.setup.doctype.employee.employee import is_holiday

        for day in days:
            if is_holiday(trip.employee, day):
                continue  # Never fabricate overtime/compensatory leave on a trip.
            sessions = target.get(day, ())
            attendance_name = frappe.db.get_value("Attendance", {"employee": trip.employee, "attendance_date": day, "docstatus": 1}, "name")
            old = frappe.get_doc("Attendance", attendance_name) if attendance_name else None
            previous = tuple((old.get("tlc_duty_sessions") or "").split(",")) if old and old.get("tlc_travel_request") == trip.name else ()
            if previous == sessions:
                continue
            locked = calendar.locked_period(trip.employee, day, day)
            if locked:
                delta = Decimal(len(sessions) - len(previous)) / 2
                if not delta:
                    continue
                key = f"{trip.name}:{day}:{','.join(sessions)}"
                if frappe.db.exists("Attendance Request", {"tlc_travel_effect_key": key}):
                    continue
                # A draft correction is intentionally not submitted: HR must approve the next-payroll effect.
                correction = frappe.get_doc({"doctype": "Attendance Request", "employee": trip.employee, "company": trip.company,
                    "from_date": day, "to_date": day, "reason": "On Duty", "tlc_correction_type": "Điều chỉnh sau chốt",
                    "explanation": f"{trip.name}: công tác thực tế {','.join(sessions) or 'không đi'}; chênh lệch {delta} ngày, kỳ {locked[0]}.",
                    "tlc_travel_request": trip.name, "tlc_travel_effect_key": key, "tlc_workday_delta": float(delta),
                    "workflow_state": "Nháp"})
                # Standard correction validation requires HR; creation is delegated to an HR assignee, never their approval.
                correction.flags.tlc_travel_adjustment = True
                correction.insert(ignore_permissions=True)
                frappe.get_doc("TLC Attendance Period", locked[0]).add_comment("Info", f"{trip.name}: cần duyệt điều chỉnh {correction.name}; không sửa ảnh chụp kỳ công.")
                continue
            if not sessions:
                if old and old.get("tlc_travel_request") == trip.name:
                    old.db_set({"status": old.tlc_before_travel_status or "Absent", "tlc_travel_request": None,
                                "tlc_duty_sessions": None, "tlc_on_duty": 0})
                    old.add_comment("Info", f"{trip.name}: điều chỉnh theo báo cáo thực tế; hủy hiệu lực công tác.")
                continue
            values = {"tlc_travel_request": trip.name, "tlc_on_duty": 1, "tlc_duty_sessions": ",".join(sessions),
                      "late_entry": 0, "early_exit": 0}
            if old:
                if not old.get("tlc_travel_request"):
                    values["tlc_before_travel_status"] = old.status
                values["status"] = "Present" if len(sessions) == 2 or old.status == "Present" else "Half Day"
                if values["status"] == "Half Day":
                    values["half_day_status"] = "Absent"
                old.db_set(values)
                old.add_comment("Info", f"On Duty · {trip.name} · {','.join(sessions)}")
            else:
                mark = frappe.get_doc({"doctype": "Attendance", "employee": trip.employee, "company": trip.company,
                    "attendance_date": day, "status": "Present" if len(sessions) == 2 else "Half Day",
                    "half_day_status": "Absent" if len(sessions) == 1 else None,
                    "shift": calendar.shift_of(trip.employee, day), "tlc_before_travel_status": "Absent", **values})
                mark.insert(ignore_permissions=True)
                mark.submit()

    def notify(self, doc, before):
        route = self.route(doc.employee)
        state = doc.workflow_state
        if state in (rules.MANAGER, rules.REPORT_MANAGER):
            users = [route.manager]
        elif state in (rules.CEO, rules.REPORT_CEO):
            users = frappe.get_all("Has Role", filters={"role": "TLC Director", "parenttype": "User"}, pluck="parent")
        elif state in (rules.ACCOUNTANT, rules.PAYMENT, rules.SETTLEMENT):
            users = frappe.get_all("Has Role", filters={"role": "Accounts User", "parenttype": "User"}, pluck="parent")
        else:
            users = [route.subject]
        from tlc_hr.infrastructure.frappe.overtime import FrappeNotifier
        for user in set(users) - {None, "", frappe.session.user}:
            FrappeNotifier().notify(user, f"{doc.name} · {state}", f"{before} → {state}. {doc.get('tlc_reject_reason') or ''}", doc.doctype, doc.name)


def remind_due():
    """Daily reminders for unsettled advances and missing travel reports, with managers copied when overdue."""
    today = getdate()
    repository = FrappeTravelFinanceRepository()
    from tlc_hr.infrastructure.frappe.overtime import FrappeNotifier
    for doctype, due_field in (("Employee Advance", "tlc_settlement_due"), ("Travel Request", "tlc_report_due")):
        rows = frappe.get_all(doctype, filters={"docstatus": 1, due_field: ["<=", today + timedelta(days=1)],
            "workflow_state": ["not in", [rules.DONE, rules.CANCELLED]]}, fields=["name", "employee", due_field, "workflow_state"])
        for row in rows:
            if not row.get(due_field):
                continue
            route = repository.route(row.employee)
            users = {route.subject}
            if getdate(row.get(due_field)) < today:
                users.add(route.manager)
                users.update(frappe.get_all("Has Role", filters={"role": "Accounts User", "parenttype": "User"}, pluck="parent"))
            for user in users - {None, ""}:
                subject = f"{row.name}: hạn báo cáo/quyết toán {row.get(due_field)}"
                if not frappe.db.exists("Notification Log", {"for_user": user, "document_name": row.name,
                        "subject": subject, "creation": [">=", today]}):
                    FrappeNotifier().notify(user, subject, row.workflow_state, doctype, row.name)
