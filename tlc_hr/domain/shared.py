"""What every TLC domain module shares: the errors a rule raises and the states of the approval workflows."""

# States of the TLC approval workflows (customizing/workflows/*.yaml use the same names).
DRAFT, TO_MANAGER, TO_HR, APPROVED, REJECTED, CANCELLED = (
    "Nháp", "Chờ quản lý duyệt", "Chờ nhân sự duyệt", "Đã duyệt", "Từ chối", "Đã hủy")
COMPANY_WIDE_ROLES = frozenset({"TLC HR Lead", "TLC HR Officer", "TLC Director", "System Manager"})
HR_ROLES = frozenset({"TLC HR Lead", "TLC HR Officer", "System Manager"})


class DomainError(Exception):
    """A business rule is not met. `code` identifies the rule (for support and tests), `message` is shown to the user."""

    def __init__(self, code: str, message: str, title: str = ""):
        super().__init__(message)
        self.code, self.message, self.title = code, message, title


class NotAllowed(DomainError):
    """The person may not do this on this record (shown as a permission error)."""
