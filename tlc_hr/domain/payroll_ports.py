"""Port of the payroll use cases (implemented on Frappe in infrastructure/frappe/payroll.py, in memory in the unit tests)."""

from abc import ABC, abstractmethod
from datetime import date


class IPayrollRepository(ABC):
    @abstractmethod
    def scope_of(self, department: str | None) -> str:
        """Attendance scope of a department (a factory or the head office)."""

    @abstractmethod
    def locked_scopes(self, company: str, month: str) -> set[str]:
        """Scopes whose attendance period of the month is locked."""

    @abstractmethod
    def base_salary(self, employee: str, on: date) -> float:
        """Base of the salary structure assignment in force on a date."""

    @abstractmethod
    def working_days(self, employee: str, start: date, end: date) -> int:
        """Days of the period that are not holidays of the person."""

    @abstractmethod
    def shift_hours(self, employee: str) -> float:
        """Hours of the person's default shift."""

    @abstractmethod
    def approved_overtime(self, employee: str, start: date, end: date) -> dict[str, float]:
        """Approved overtime hours of the period by kind of day."""
