"""Ports of the attendance use cases (implemented on Frappe in infrastructure/frappe/attendance.py, in memory in the unit tests)."""

from abc import ABC, abstractmethod
from datetime import date, datetime

from tlc_hr.domain.attendance import Mark, Person


class IAttendanceRepository(ABC):
    @abstractmethod
    def factories(self) -> tuple[str, ...]:
        """Names of the factory scopes (the work sites that are factories)."""

    @abstractmethod
    def tracking_on(self) -> bool:
        """Is check-in with the position required (HR Settings)?"""

    @abstractmethod
    def located(self, employee: str, shift: str, at: datetime) -> bool:
        """Does the person have an active assignment of this shift with a work site at that time?"""

    @abstractmethod
    def locked_period(self, employee: str, start: date, end: date) -> tuple[str, str] | None:
        """(name, title) of a locked period of the person's scope covering the days, if any."""

    @abstractmethod
    def shift_of(self, employee: str, day: date) -> str | None:
        """Shift of the attendance already marked that day, else the person's default shift."""

    @abstractmethod
    def people(self, company: str, scope: str, start: date) -> list[Person]:
        """People of a scope working in the period (active, or left during or after it)."""

    @abstractmethod
    def head_user(self, company: str, scope: str) -> str | None:
        """User of the factory head who confirms the period (none for the head office)."""

    @abstractmethod
    def marks(self, employees: list[str], start: date, end: date) -> list[Mark]:
        """Submitted attendance of the people in the period."""

    @abstractmethod
    def approved_overtime(self, employees: list[str], start: date, end: date) -> list[tuple[str, float]]:
        """(employee, hours) of approved overtime in the period."""

    @abstractmethod
    def approved_corrections(self, employees: list[str], start: date, end: date) -> list[str]:
        """Employee of each approved correction overlapping the period."""

    @abstractmethod
    def open_items(self, employees: list[str], start: date, end: date) -> list[str]:
        """Readable lines of what is still pending in the period: requests not decided, check-ins not turned into attendance."""

    @abstractmethod
    def other_period(self, key, name: str | None) -> str | None:
        """Another live period of the same company, scope and month."""
