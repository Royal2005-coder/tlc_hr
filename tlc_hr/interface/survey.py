import frappe
from tlc_hr.application.survey import SurveyService
from tlc_hr.contracts.survey import AnonymousSubmission, SurveyResults
from tlc_hr.infrastructure.frappe.survey import FrappeSurveyRepository
from tlc_hr.infrastructure.frappe import survey as repository
from tlc_hr.interface.services import guarded

validate = guarded(repository.validate)
on_update = repository.on_update
has_permission = repository.permission
permission_query = repository.query


@frappe.whitelist(methods=["POST"])
@guarded
def submit_anonymous(campaign, answers):
    if isinstance(answers, str):
        answers = frappe.parse_json(answers)
    return SurveyService(FrappeSurveyRepository()).submit(AnonymousSubmission(campaign=campaign, answers=answers))


@frappe.whitelist()
@guarded
def results(campaign, department):
    return SurveyService(FrappeSurveyRepository()).results(SurveyResults(campaign=campaign, department=department))


@frappe.whitelist(methods=["POST"])
@guarded
def new_version(campaign):
    return repository.new_version(campaign)
