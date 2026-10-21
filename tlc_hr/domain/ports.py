"""Ports: what the use cases need from the outside world, as abstract classes. infrastructure/frappe implements them on Frappe;
the unit tests implement them in memory."""

from abc import ABC, abstractmethod
from datetime import date

from tlc_hr.domain.overtime import Proposer


class IOvertimeRepository(ABC):
    @abstractmethod
    def live_hours(self, employee: str, year: int, exclude: str | None) -> list[tuple[date, float]]:
        """(date, hours) of the worker's other requests of the year that are not refused or cancelled."""

    @abstractmethod
    def approved_hours(self, employee: str, start: date, end: date) -> dict[date, float]:
        """Approved (submitted) hours by day in a period."""


class ICalendar(ABC):
    @abstractmethod
    def weekly_off(self, employee: str, day: date) -> bool | None:
        """None when the day is a working day of the employee, True for a weekly rest day, False for a public holiday."""


class IDirectory(ABC):
    @abstractmethod
    def proposer(self, user: str, employee: str) -> Proposer:
        """How a user relates to an employee (roles, line manager, department head, reporting line)."""

    @abstractmethod
    def user_of(self, employee: str) -> str | None:
        """The user account of an employee."""


class INotifier(ABC):
    @abstractmethod
    def notify(self, user: str, subject: str, message: str, doctype: str, name: str) -> None:
        """Bell notification and e-mail to one user about a record."""
