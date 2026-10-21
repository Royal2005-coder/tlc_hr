"""Assistant boundary: synthetic users, self-service data, draft-only writes."""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from tlc_hr.contracts.assistant import LeaveDraft
from tlc_hr.domain.shared import NotAllowed


@dataclass(frozen=True)
class AssistantIdentity:
    user: str
    employee: str
    demo_enabled: bool


def authorize(identity: AssistantIdentity, employee: str | None) -> str:
    if not identity.demo_enabled or identity.user in {"Guest", "Administrator"} or not identity.employee:
        raise NotAllowed("AI_DEMO_ONLY", "Trợ lý chỉ dùng cho tài khoản dữ liệu demo được cho phép.")
    if employee is not None and employee != identity.employee:
        raise NotAllowed("AI_SCOPE_DENIED", "Không được xem hoặc tạo yêu cầu cho người khác, kể cả khác nhà máy.")
    return identity.employee


class IAssistantRepository(ABC):
    @abstractmethod
    def identity(self) -> AssistantIdentity: ...

    @abstractmethod
    def read_self(self, topic: str, employee: str) -> dict: ...

    @abstractmethod
    def create_leave_draft(self, employee: str, command: LeaveDraft) -> dict: ...

    @abstractmethod
    def audit(self, action: str, employee: str, outcome: str) -> None: ...
