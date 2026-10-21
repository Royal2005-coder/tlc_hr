"""Authenticated document hooks and native Desk actions for W5."""
import frappe
from frappe.utils import getdate, now_datetime, today
from tlc_hr.contracts.people_ops import BenefitCommand, LicenseCommand, ReceiptCommand, TransitionCommand
from tlc_hr.domain.people_ops import PeopleOpsError, benefit_amount, require_receipt, require_seat, require_transition
from tlc_hr.infrastructure.frappe.people_ops import PREFIX, HR, employee_user, is_hr, is_manager, is_self, lock, private_evidence, publish_policy, require


def actor(employee, kind):
    return {"self": is_self(employee), "manager": is_manager(employee), "hr": is_hr(), "director": "TLC Director" in frappe.get_roles(), "accountant": bool({"Accounts User", "Accounts Manager"}.intersection(frappe.get_roles()))}[kind]


def transition(doc, old, kind, evidence=""):
    if old and old.status != doc.status:
        from tlc_hr.domain.people_ops import TRANSITIONS
        required = TRANSITIONS[kind].get((old.status, doc.status))
        require(bool(required) and actor(doc.employee, required))
        if kind in {"benefit", "discipline"} and required in {"hr", "manager", "director"}:
            require(not is_self(doc.employee))
        require_transition(kind, TransitionCommand(previous=old.status, target=doc.status, actor_kind=required, evidence=evidence or ""))


def unchanged(doc, old, fields):
    if old:
        require(all(doc.get(field) == old.get(field) for field in fields))


def validate_gap(doc, method=None):
    try:
        _validate_gap(doc)
    except PeopleOpsError as exc:
        frappe.throw(str(exc))


def _validate_gap(doc):
    kind = doc.doctype.removeprefix(PREFIX)
    old = doc.get_doc_before_save()
    user = frappe.session.user
    # Server scheduler and installation seed use Administrator, never employee input.
    if old and doc.get("employee"):
        unchanged(doc, old, ["employee"])
    for field in ("evidence", "certificate", "result_file", "violation_report", "employee_explanation", "decision", "policy_file"):
        private_evidence(doc.get(field))
    if kind in {"License", "Training Requirement", "Benefit Policy", "Policy Version"}:
        require(is_hr())
    if kind == "License":
        require(doc.seats > 0)
        used = frappe.db.count(PREFIX + "Account", {"license": doc.name, "status": "Active"})
        require(doc.seats >= used)
    elif kind == "Training Requirement":
        require(doc.recurrence_days >= 0 and (doc.due_days or 30) > 0)
    elif kind == "Account":
        require(is_hr() or (is_self(doc.employee) and not old and doc.status == "Requested"))
        if not old:
            require(doc.status == "Requested")
        if old:
            unchanged(doc, old, ["employee", "license", "account_identifier", "activated_at", "revoked_at", "revoked_by"])
        transition(doc, old, "account", doc.evidence or doc.reason)
        if doc.status == "Active" and (not old or old.status != "Active"):
            lock(PREFIX + "License", doc.license)
            license_doc = frappe.get_doc(PREFIX + "License", doc.license)
            used = frappe.db.count(PREFIX + "Account", {"license": doc.license, "status": "Active", "name": ["!=", doc.name]})
            require_seat(LicenseCommand(seats=license_doc.seats, used=used, expires_on=getdate(license_doc.expires_on), today=getdate(today())))
            doc.activated_at = now_datetime()
        if doc.status == "Revoked" and old and old.status != "Revoked":
            require(bool(doc.evidence))
            doc.revoked_at, doc.revoked_by = now_datetime(), user
    elif kind == "Certificate":
        require(is_hr())
        if doc.status == "Completed":
            require(bool(doc.completed_on and doc.issued_on and doc.certificate and doc.issuer))
            require(not doc.expires_on or getdate(doc.expires_on) >= getdate(doc.issued_on))
        if old and old.status == "Completed":
            unchanged(doc, old, [field.fieldname for field in doc.meta.fields if field.fieldtype not in {"Section Break", "Column Break"}])
    elif kind == "Benefit Policy":
        require(getdate(doc.effective_from) <= getdate(doc.effective_to) and doc.amount >= 0)
        overlaps = frappe.get_all(doc.doctype, filters={"event": doc.event, "effective_from": ["<=", doc.effective_to], "effective_to": [">=", doc.effective_from], "name": ["!=", doc.name]}, limit=1)
        require(not overlaps)
        if old and frappe.db.exists(PREFIX + "Benefit Claim", {"policy": doc.name, "status": ["!=", "Draft"]}):
            unchanged(doc, old, ["event", "amount", "effective_from", "effective_to"])
    elif kind == "Benefit Claim":
        require(is_hr() or is_self(doc.employee) or actor(doc.employee, "accountant"))
        if not old:
            require(doc.status == "Draft" and (is_hr() or is_self(doc.employee)))
        policy = frappe.get_doc(PREFIX + "Benefit Policy", doc.policy)
        doc.amount = benefit_amount(BenefitCommand(event=policy.event, event_date=getdate(doc.event_date), effective_from=getdate(policy.effective_from), effective_to=getdate(policy.effective_to), amount=float(policy.amount)))
        if old and old.status != "Draft":
            unchanged(doc, old, ["policy", "event_date", "evidence", "amount"])
        transition(doc, old, "benefit", doc.reason or doc.payment_reference or doc.evidence)
        if doc.status == "Paid":
            require(bool(doc.payment_channel and doc.payment_reference and doc.paid_on))
        if old and old.status in {"Paid", "Rejected"}:
            unchanged(doc, old, [field.fieldname for field in doc.meta.fields])
    elif kind == "Health Appointment":
        require(is_hr() or is_self(doc.employee))
        require(bool(HR.intersection(frappe.get_roles(doc.responsible_hr))))
        if old and not is_hr():
            unchanged(doc, old, ["employee", "provider", "responsible_hr", "status", "completed_on", "result", "result_file"])
        if doc.result or doc.result_file:
            require(user == doc.responsible_hr or user == "Administrator")
        if doc.status == "Completed":
            require(is_hr() and bool(doc.completed_on))
    elif kind == "Policy Version":
        if old and old.status in {"Published", "Retired"}:
            unchanged(doc, old, ["policy_code", "version", "body", "policy_file", "effective_from", "designation", "branch"])
            require(doc.status in {old.status, "Retired"})
        require(doc.version > 0)
        require(not frappe.db.exists(doc.doctype, {"policy_code": doc.policy_code, "version": doc.version, "name": ["!=", doc.name]}))
    elif kind == "Acknowledgment":
        require(is_hr() or is_self(doc.employee))
        policy = frappe.get_doc(PREFIX + "Policy Version", doc.policy_version)
        require(policy.status == "Published")
        if not old:
            require(is_hr() and not doc.acknowledged_at and not doc.acknowledged_by)
            doc.policy_snapshot = policy.body
        else:
            unchanged(doc, old, ["employee", "policy_version", "policy_snapshot", "acknowledged_at", "acknowledged_by"])
    elif kind == "Discipline":
        require(is_hr() or is_manager(doc.employee) or actor(doc.employee, "director"))
        if not old:
            require(doc.status == "Proposal" and (is_manager(doc.employee) or is_hr()))
            doc.proposed_by = user
        else:
            unchanged(doc, old, ["proposed_by"])
            if old.status == doc.status:
                require(is_hr() if doc.status in {"HR Review", "Approved", "Executed"} else actor(doc.employee, "director") if doc.status == "Director Review" else is_manager(doc.employee) or is_hr())
        transition(doc, old, "discipline", doc.decision or doc.violation_report or doc.reason)
        if doc.status in {"Director Review", "Approved", "Executed", "Expunged"}:
            require(bool(doc.violation_report and doc.employee_explanation))
        if doc.status in {"Executed", "Expunged"}:
            require(bool(doc.decision and doc.sanction and doc.executed_on and doc.expunge_on))
        if doc.status == "Expunged":
            require(getdate(doc.expunge_on) <= getdate(today()))
        if old and old.status in {"Rejected", "Expunged"}:
            unchanged(doc, old, [field.fieldname for field in doc.meta.fields])


def after_gap_save(doc, method=None):
    if doc.doctype == PREFIX + "Policy Version" and doc.status == "Published":
        publish_policy(doc)


@frappe.whitelist(methods=["POST"])
def acknowledge(name):
    doc = frappe.get_doc(PREFIX + "Acknowledgment", name)
    require(is_self(doc.employee))
    lock(doc.doctype, doc.name)
    doc.reload()
    require(not doc.acknowledged_at)
    require(frappe.db.get_value(PREFIX + "Policy Version", doc.policy_version, "status") == "Published")
    doc.db_set({"acknowledged_at": now_datetime(), "acknowledged_by": frappe.session.user})
    doc.add_comment("Info", "Nhân viên xác nhận đã đọc đúng phiên bản chính sách.")
    close_todo(doc)
    return doc.name


def close_todo(doc):
    for name in frappe.get_all("ToDo", filters={"reference_type": doc.doctype, "reference_name": doc.name, "status": "Open"}, pluck="name"):
        frappe.db.set_value("ToDo", name, "status", "Closed")


def movement_validate(doc, method=None):
    old = doc.get_doc_before_save()
    require(is_hr() or bool({"Stock Manager", "Accounts Manager"}.intersection(frappe.get_roles())))
    if not doc.tlc_ops_staff:
        doc.tlc_ops_staff = frappe.session.user
    if old:
        unchanged(doc, old, ["tlc_ops_staff", "tlc_ops_staff_ack", "tlc_ops_employee_ack", "tlc_ops_employee", "tlc_ops_from_employee", "tlc_ops_from_ack"])
        if old.tlc_ops_staff_ack or old.tlc_ops_employee_ack or old.tlc_ops_from_ack:
            fields = ("asset", "from_employee", "to_employee", "source_location", "target_location")
            require([[row.get(key) for key in fields] for row in doc.assets] == [[row.get(key) for key in fields] for row in old.assets])
            unchanged(doc, old, ["purpose", "tlc_ops_evidence", "tlc_ops_condition"])
    employees = {row.to_employee or row.from_employee for row in doc.assets if row.to_employee or row.from_employee}
    # One employee per receipt permits unambiguous personal acknowledgment.
    require(len(employees) <= 1)
    doc.tlc_ops_employee = next(iter(employees), None)
    senders = {row.from_employee for row in doc.assets if row.from_employee}
    require(len(senders) <= 1)
    doc.tlc_ops_from_employee = next(iter(senders), None)
    for row in doc.assets:
        lock("Asset", row.asset)
        custodian = frappe.db.get_value("Asset", row.asset, "custodian")
        require(not custodian or row.from_employee == custodian)
        if row.from_employee:
            require(custodian == row.from_employee)
    private_evidence(doc.tlc_ops_evidence)


def movement_before_submit(doc, method=None):
    require(bool(doc.tlc_ops_condition and doc.tlc_ops_evidence))
    if doc.tlc_ops_employee:
        require(bool(doc.tlc_ops_staff_ack and doc.tlc_ops_employee_ack))
    if doc.tlc_ops_from_employee and doc.tlc_ops_from_employee != doc.tlc_ops_employee:
        require(bool(doc.tlc_ops_from_ack))


@frappe.whitelist(methods=["POST"])
def receipt(name):
    doc = frappe.get_doc("Asset Movement", name)
    lock(doc.doctype, name)
    doc.reload()
    user = frappe.session.user
    if is_self(doc.tlc_ops_employee):
        field, expected = "tlc_ops_employee_ack", employee_user(doc.tlc_ops_employee)
    elif is_self(doc.tlc_ops_from_employee):
        field, expected = "tlc_ops_from_ack", employee_user(doc.tlc_ops_from_employee)
    else:
        field, expected = "tlc_ops_staff_ack", doc.tlc_ops_staff
    try:
        require_receipt(ReceiptCommand(actor=user, expected_actor=expected or "", evidence=doc.tlc_ops_evidence or "", submitted=doc.docstatus != 0))
    except PeopleOpsError as exc:
        frappe.throw(str(exc))
    require(not doc.get(field) and bool(doc.tlc_ops_condition))
    require(doc.tlc_ops_staff != employee_user(doc.tlc_ops_employee))
    doc.db_set(field, now_datetime())
    doc.add_comment("Info", "Xác nhận bàn giao: " + user)
    return name


@frappe.whitelist(methods=["POST"])
def exit_clearance(employee):
    """HR-only read of the assets and accounts an employee still holds for the exit checklist."""
    require(is_hr())
    from tlc_hr.infrastructure.frappe.people_ops import clearance_blockers
    return clearance_blockers(employee)


def native_validate(doc, method=None):
    old = doc.get_doc_before_save()
    employee = doc.get("employee") or doc.get("raised_by")
    require(is_hr() or is_self(employee) or (doc.doctype != "Employee Grievance" and is_manager(employee)))
    if old:
        unchanged(doc, old, ["raised_by" if doc.doctype == "Employee Grievance" else "employee"])
    if doc.doctype == "Employee Grievance":
        if not is_hr():
            require(doc.status == "Open")
            if old:
                unchanged(doc, old, ["status", "cause_of_grievance", "resolved_by", "resolution_date", "resolution_detail", "employee_responsible"])
        elif doc.status in {"Resolved", "Invalid", "Cancelled"}:
            require(bool(doc.resolution_detail))
            doc.resolved_by = frappe.session.user
    elif doc.doctype == "Goal":
        if doc.tlc_ops_approved_by:
            if not old or doc.tlc_ops_approved_by != old.tlc_ops_approved_by:
                require(is_manager(employee) and doc.tlc_ops_approved_by == frappe.session.user)
        if old and old.tlc_ops_approved_by:
            unchanged(doc, old, ["goal_name", "description", "parent_goal", "appraisal_cycle", "tlc_ops_weight", "tlc_ops_approved_by"])
        if doc.progress and not doc.tlc_ops_approved_by:
            frappe.throw("Mục tiêu phải được quản lý duyệt trước khi cập nhật tiến độ.")
        require(0 <= (doc.tlc_ops_weight or 0) <= 100)
    elif doc.doctype == "Appraisal":
        if not doc.tlc_ops_stage:
            doc.tlc_ops_stage = "Self Review"
        if old and old.tlc_ops_stage != doc.tlc_ops_stage:
            require_transition("appraisal", TransitionCommand(previous=old.tlc_ops_stage or "Self Review", target=doc.tlc_ops_stage, actor_kind=next((kind for kind in ("self", "manager", "hr") if actor(employee, kind) and kind == {"Manager Review": "self", "Calibration": "manager", "Rated": "hr"}.get(doc.tlc_ops_stage)), "denied"), evidence=doc.remarks or doc.reflections or ""))
        if not is_hr():
            require(doc.tlc_ops_stage != "Rated")
            if old and is_self(employee):
                unchanged(doc, old, ["appraisal_kra", "goals", "remarks", "tlc_ops_rating"])
            elif old:
                unchanged(doc, old, ["self_ratings", "reflections"])
        if doc.docstatus == 1:
            require(is_hr() and doc.tlc_ops_stage == "Rated" and bool(doc.tlc_ops_rating))


def scoped_permission(doc, user=None, permission_type=None):
    user = user or frappe.session.user
    if user == "Guest":
        return False
    kind = doc.doctype.removeprefix(PREFIX)
    if doc.doctype == "Asset Movement":
        return is_hr(user) or user == doc.tlc_ops_staff or is_self(doc.tlc_ops_employee, user) or is_self(doc.tlc_ops_from_employee, user)
    if kind == "Health Appointment":
        # Result and result attachments are restricted to the appointed clinician-facing HR officer.
        return user == "Administrator" or user == doc.responsible_hr or (is_self(doc.employee, user) and not (doc.result or doc.result_file))
    if kind == "Discipline":
        return is_hr(user) or "TLC Director" in frappe.get_roles(user) or (is_manager(doc.employee, user) and doc.status == "Proposal")
    if doc.doctype == "Employee Grievance":
        return is_hr(user) or is_self(doc.raised_by, user)
    if doc.get("employee"):
        return is_hr(user) or is_self(doc.employee, user) or (doc.doctype in {"Goal", "Appraisal"} and is_manager(doc.employee, user)) or (kind == "Benefit Claim" and bool({"Accounts User", "Accounts Manager"}.intersection(frappe.get_roles(user))))
    return None


def query_conditions(user=None, doctype=None):
    user = user or frappe.session.user
    if is_hr(user) and doctype != PREFIX + "Health Appointment":
        return ""
    employees = frappe.get_all("Employee", filters={"user_id": user}, pluck="name")
    values = ",".join(frappe.db.escape(value) for value in employees) or "''"
    table = "tab" + doctype
    if doctype == "Asset Movement":
        return f"(`{table}`.tlc_ops_employee in ({values}) or `{table}`.tlc_ops_from_employee in ({values}) or `{table}`.tlc_ops_staff={frappe.db.escape(user)})"
    if doctype == PREFIX + "Discipline":
        if "TLC Director" in frappe.get_roles(user):
            return ""
        reports = frappe.get_all("Employee", filters={"reports_to": ["in", employees or [""]]}, pluck="name")
        report_values = ",".join(frappe.db.escape(value) for value in reports) or "''"
        return f"(`{table}`.employee in ({report_values}) and `{table}`.status='Proposal')"
    if doctype == PREFIX + "Health Appointment":
        return f"(`{table}`.responsible_hr={frappe.db.escape(user)} or (`{table}`.employee in ({values}) and coalesce(`{table}`.result,'')='' and coalesce(`{table}`.result_file,'')=''))"
    if doctype == PREFIX + "Benefit Claim" and {"Accounts User", "Accounts Manager"}.intersection(frappe.get_roles(user)):
        return ""
    if doctype in {"Goal", "Appraisal"}:
        reports = frappe.get_all("Employee", filters={"reports_to": ["in", employees or [""]]}, pluck="name")
        values = ",".join(frappe.db.escape(value) for value in employees + reports) or "''"
    field = "raised_by" if doctype == "Employee Grievance" else "employee"
    return f"`{table}`.`{field}` in ({values})"


def asset_movement_query(user=None):
    return query_conditions(user=user, doctype="Asset Movement")


def grievance_query(user=None):
    return query_conditions(user=user, doctype="Employee Grievance")


def goal_query(user=None):
    return query_conditions(user=user, doctype="Goal")


def appraisal_query(user=None):
    return query_conditions(user=user, doctype="Appraisal")


def account_query(user=None):
    return query_conditions(user=user, doctype=PREFIX + "Account")


def acknowledgment_query(user=None):
    return query_conditions(user=user, doctype=PREFIX + "Acknowledgment")


def certificate_query(user=None):
    return query_conditions(user=user, doctype=PREFIX + "Certificate")


def benefit_claim_query(user=None):
    return query_conditions(user=user, doctype=PREFIX + "Benefit Claim")


def discipline_query(user=None):
    return query_conditions(user=user, doctype=PREFIX + "Discipline")


def health_query(user=None):
    return query_conditions(user=user, doctype=PREFIX + "Health Appointment")
