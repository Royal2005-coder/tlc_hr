from abc import ABC, abstractmethod


class ISurveyRepository(ABC):
    @abstractmethod
    def submit_anonymous(self, campaign, answers):
        """Authorize audience, serialize campaign, record participation and aggregate only."""

    @abstractmethod
    def results(self, campaign, department):
        """Return only closed, authorized, threshold-protected department aggregates."""
