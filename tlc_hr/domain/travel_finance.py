"""PO 4.2/4.6: sequential authorization, half-day travel and three-way settlement."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from tlc_hr.domain.shared import DomainError, NotAllowed

DRAFT = "Nháp"
MANAGER = "Chờ quản lý duyệt"
CEO = "Chờ giám đốc duyệt"
ACCOUNTANT = "Chờ kế toán kiểm tra"
APPROVED = "Đã duyệt"
PAYMENT = "Chờ chi"
PAID = "Đã chi"
REPORT_MANAGER = "Chờ quản lý duyệt báo cáo"
REPORT_CEO = "Chờ giám đốc duyệt báo cáo"
REPORT_RETURN = "Bổ sung báo cáo"
SETTLEMENT = "Chờ quyết toán"
RECEIPT = "Chờ nhân viên xác nhận"
DONE = "Hoàn tất"
RETURNED = "Bổ sung thông tin"
REJECTED = "Từ chối"
CANCELLED = "Đã hủy"
INACTIVE = (RETURNED, REJECTED, CANCELLED)


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    start_session: str = "AM"
    end_session: str = "PM"

    def slots(self):
        if self.start_session not in ("AM", "PM") or self.end_session not in ("AM", "PM"):
            raise DomainError("travel.session", "Buổi công tác phải là AM hoặc PM.")
        low = self.start.toordinal() * 2 + (self.start_session == "PM")
        high = self.end.toordinal() * 2 + (self.end_session == "PM")
        if high < low:
            raise DomainError("travel.dates", "Ngày/buổi về phải sau ngày/buổi đi.")
        return low, high

    def overlaps(self, other):
        a, b = self.slots()
        c, d = other.slots()
        return a <= d and c <= b

    def days(self):
        low, high = self.slots()
        day = self.start
        while day <= self.end:
            sessions = tuple(s for s, n in (("AM", 0), ("PM", 1)) if low <= day.toordinal() * 2 + n <= high)
            yield day, sessions
            day += timedelta(days=1)


@dataclass(frozen=True)
class Route:
    subject: str
    manager: str | None
    manager_is_director: bool = False

    @property
    def first(self):
        return CEO if not self.manager or self.manager == self.subject or self.manager_is_director else MANAGER


@dataclass(frozen=True)
class Actor:
    user: str
    roles: frozenset[str]
    in_scope: bool


def authorize(actor, route, stage, *, employee_action=False):
    if employee_action:
        if actor.user != route.subject:
            raise NotAllowed("finance.employee_action", "Chỉ nhân viên liên quan được xác nhận hoặc gửi hồ sơ.")
        return
    if actor.user == route.subject:
        raise NotAllowed("finance.self_approval", "Không được tự duyệt, kiểm tra hay chi yêu cầu của chính mình.")
    if stage in (MANAGER, REPORT_MANAGER):
        if actor.user != route.manager or not actor.in_scope:
            raise NotAllowed("finance.manager_scope", "Chỉ quản lý được chỉ định trong phạm vi nhà máy/bộ phận được duyệt.")
    elif stage in (CEO, REPORT_CEO):
        if "TLC Director" not in actor.roles:
            raise NotAllowed("finance.director", "Hồ sơ đang chờ Giám đốc duyệt.")
    elif not actor.roles.intersection({"Accounts User", "Accounts Manager"}):
        raise NotAllowed("finance.accountant", "Chỉ kế toán được kiểm tra và xác nhận chứng từ.")


def check_transition(kind, before, after, actor, route, reason=""):
    if before == after:
        return
    first = route.first
    report_first = REPORT_CEO if first == CEO else REPORT_MANAGER
    transitions = {
        DRAFT: {first, CANCELLED}, RETURNED: {first, CANCELLED}, REJECTED: {first, CANCELLED},
        MANAGER: {CEO, RETURNED, REJECTED},
        CEO: {APPROVED if kind == "travel" else ACCOUNTANT, RETURNED, REJECTED},
        ACCOUNTANT: {PAYMENT if kind == "advance" else SETTLEMENT, RETURNED},
        PAYMENT: {PAID}, PAID: {DONE},
        APPROVED: {report_first, CANCELLED}, REPORT_RETURN: {report_first},
        REPORT_MANAGER: {REPORT_CEO, REPORT_RETURN},
        REPORT_CEO: {DONE if kind == "travel" else SETTLEMENT, REPORT_RETURN},
        SETTLEMENT: {DONE, RECEIPT}, RECEIPT: {DONE},
    }
    if after not in transitions.get(before, set()):
        raise DomainError("finance.sequence", "Không được bỏ qua cấp duyệt hoặc bước kế toán.")
    employee_action = before in (DRAFT, RETURNED, REJECTED, APPROVED, REPORT_RETURN, RECEIPT)
    authorize(actor, route, before, employee_action=employee_action)
    if after in (RETURNED, REJECTED, REPORT_RETURN, CANCELLED) and not reason.strip():
        raise DomainError("finance.reason", "Phải ghi lý do từ chối, trả lại hoặc hủy.")


@dataclass(frozen=True)
class Settlement:
    advance: Decimal
    actual: Decimal
    difference: Decimal
    branch: str


def settlement(advance, actual):
    if not advance.is_finite() or not actual.is_finite() or min(advance, actual) < 0:
        raise DomainError("finance.amount", "Số tiền phải hữu hạn và không âm.")
    difference = advance - actual
    return Settlement(advance, actual, difference, "equal" if difference == 0 else "refund" if difference > 0 else "top_up")


def require_settled(result, *, refunded, reimbursed, receipt):
    if result.branch == "refund" and refunded != result.difference:
        raise DomainError("finance.refund", "Kế toán phải đối chiếu đủ tiền hoàn ứng và chứng từ ngân hàng.")
    if result.branch == "top_up" and (reimbursed != -result.difference or not receipt):
        raise DomainError("finance.top_up", "Phải có chứng từ chi bù đủ tiền và nhân viên xác nhận đã nhận.")


def require_payroll_consent(*, allowed, consent, evidence, consent_by, subject, due, today):
    if not allowed or not consent or not evidence or consent_by != subject:
        raise DomainError("finance.payroll_consent", "Khấu trừ tạm ứng cần chính sách được phép và nhân viên tự xác nhận đồng ý kèm chứng từ.")
    if not due or due >= today:
        raise DomainError("finance.not_overdue", "Chỉ tạm ứng quá hạn mới được chuyển sang khấu trừ lương.")
