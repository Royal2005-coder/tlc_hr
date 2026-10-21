from tlc_hr.domain.survey_ports import ISurveyRepository
from tlc_hr.contracts.survey import AnonymousSubmission, SurveyResults


class SurveyService:
    def __init__(self, repository: ISurveyRepository):
        self.repository = repository

    def submit(self, command: AnonymousSubmission):
        return self.repository.submit_anonymous(command.campaign, command.answers)

    def results(self, command: SurveyResults):
        return self.repository.results(command.campaign, command.department)
