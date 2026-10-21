"""Persistence operations required by travel/advance application services."""
from abc import ABC, abstractmethod


class ITravelFinanceRepository(ABC):
    @abstractmethod
    def route(self, employee):
        """Return the employee user and server-derived manager."""

    @abstractmethod
    def actor(self, user, employee):
        """Resolve roles and reporting/factory scope."""

    @abstractmethod
    def conflicts(self, employee, window, exclude):
        """Return active leave, overtime and travel references overlapping the window."""

    @abstractmethod
    def lock_employee(self, employee):
        """Serialize conflict detection for requests concerning one employee."""

    @abstractmethod
    def payroll_policy(self, employee):
        """Whether the employee company permits consent-based advance recovery."""
