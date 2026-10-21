"""Rules every TLC approval shares (leave, corrections, overtime, travel, money, separation):

- leaving a request in "Từ chối" needs a reason, and the level that refused is recorded;
- nobody decides on a request about themself (the workflow's own self-approval check only looks at the document's owner);
  sending one's own draft is not a decision.
"""

from dataclasses import dataclass

from tlc_hr.domain.shared import DRAFT, REJECTED, DomainError, NotAllowed


@dataclass(frozen=True)
class StateChange:
    before: str | None  # state before the save (None for a new request)
    after: str | None
    reason: str | None  # reason to reject written on the request
    actor: str  # user deciding
    subject: str | None  # user the request is about


def rejected_stage(change: StateChange) -> str | None:
    """The stage that refused, when the request just moved to "Từ chối"; refusing without a reason is not allowed."""
    if change.after != REJECTED:
        return None
    if not (change.reason or "").strip():
        raise DomainError("approval.reason_required", "Nhập lý do từ chối trước khi từ chối đơn.", "Thiếu lý do từ chối")
    return change.before if change.before != REJECTED else None


def check_not_self(change: StateChange) -> None:
    if change.before in (None, "", DRAFT) or change.before == change.after:
        return
    if change.subject and change.subject == change.actor:
        raise NotAllowed("approval.self_decision", "Bạn không thể tự duyệt hay từ chối đơn của chính mình.", "Không được tự duyệt")
