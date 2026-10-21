"""People operations invariants; independent of Frappe."""
from datetime import date, timedelta
from tlc_hr.contracts.people_ops import BenefitCommand, LicenseCommand, ReceiptCommand, TransitionCommand


class PeopleOpsError(ValueError):
    pass


def require_receipt(command: ReceiptCommand):
    if command.submitted or command.actor != command.expected_actor:
        raise PeopleOpsError("Chỉ bên được chỉ định được xác nhận biên bản trước khi ghi sổ.")


def require_seat(command: LicenseCommand):
    if command.expires_on < command.today or command.used >= command.seats:
        raise PeopleOpsError("License đã hết hạn hoặc hết số lượng cấp phát.")


def benefit_amount(command: BenefitCommand) -> float:
    if not command.effective_from <= command.event_date <= command.effective_to:
        raise PeopleOpsError("Ngày sự kiện nằm ngoài hiệu lực chính sách.")
    return command.amount


def training_due(completed: date | None, recurrence_days: int, today: date) -> bool:
    return completed is None or (recurrence_days > 0 and completed + timedelta(days=recurrence_days) <= today)


def reminder_band(expiry: date, today: date) -> str | None:
    days = (expiry - today).days
    return "Expired" if days < 0 else "30" if days <= 30 else "60" if days <= 60 else None


TRANSITIONS = {
    "account": {("Requested", "Active"): "hr", ("Requested", "Rejected"): "hr", ("Active", "Revoked"): "hr"},
    "benefit": {("Draft", "Pending"): "self", ("Pending", "Approved"): "hr", ("Pending", "Rejected"): "hr", ("Approved", "Paid"): "accountant"},
    "discipline": {("Proposal", "HR Review"): "manager", ("HR Review", "Director Review"): "hr", ("Director Review", "Approved"): "director", ("Director Review", "Rejected"): "director", ("Approved", "Executed"): "hr", ("Executed", "Expunged"): "hr"},
    "appraisal": {("Self Review", "Manager Review"): "self", ("Manager Review", "Calibration"): "manager", ("Calibration", "Rated"): "hr"},
}


def require_transition(kind: str, command: TransitionCommand):
    required = TRANSITIONS[kind].get((command.previous, command.target))
    if required is None or command.actor_kind != required:
        raise PeopleOpsError("Không được chuyển trạng thái hoặc không đúng người thực hiện.")
    if command.target in {"Rejected", "Revoked", "Paid", "Director Review", "Approved", "Executed", "Rated"} and not command.evidence.strip():
        raise PeopleOpsError("Bước này bắt buộc có lý do hoặc chứng từ.")
