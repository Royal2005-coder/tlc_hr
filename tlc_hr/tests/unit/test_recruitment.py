"""Recruitment boundary tests; no Frappe or database required."""

import unittest
from datetime import date

from pydantic import ValidationError

from tlc_hr.application.recruitment import RecruitmentService
from tlc_hr.contracts.recruitment import ApplicationCommand, CandidateCommand, OfferCommand
from tlc_hr.domain.recruitment import (
    freeze_compensation, identifiers, require_final_round, validate_offer_stage,
    validate_requisition, validate_terminal, vacancy_progress,
)
from tlc_hr.domain.shared import DomainError


class MemoryRepository:
    def __init__(self):
        self.keys = {}
        self.profiles = {}
        self.final = set()
        self.onboardings = {}

    def resolve_candidate(self, keys, profile):
        matches = {self.keys[key] for key in keys if key in self.keys}
        name = min(matches) if matches else f"C-{len(self.profiles) + 1}"
        for key, owner in list(self.keys.items()):
            if owner in matches:
                self.keys[key] = name
        self.keys.update({key: name for key in keys})
        self.profiles[name] = profile
        return name

    def has_final_round(self, application):
        return application in self.final

    def open_vacancies(self, requisition):
        return [f"{requisition}-1"]

    def accept_offer(self, offer):
        return self.onboardings.setdefault(offer, f"ONB-{offer}")


class RecruitmentRulesTest(unittest.TestCase):
    def test_email_phone_and_identity_normalization(self):
        self.assertEqual(identifiers(" TEST@EXAMPLE.COM ", "+84 912 345 678", "ab-12 34"),
                         (("email", "test@example.com"), ("phone", "0912345678"), ("identity", "AB1234")))
        self.assertEqual(identifiers(phone="0084 912 345 678"), identifiers(phone="0912345678"))

    def test_empty_identity_and_short_phone_rejected(self):
        for values in ({}, {"phone": "123"}):
            with self.assertRaises(DomainError):
                identifiers(**values)

    def test_draft_may_lack_jd_but_review_cannot(self):
        validate_requisition("", None, "New", "", (1,), False)
        for jd, needed in (("", date.today()), ("/private/jd.pdf", None)):
            with self.assertRaises(DomainError):
                validate_requisition(jd, needed, "New", "", (1,), True)

    def test_replacement_requires_employee_and_all_rows_positive(self):
        with self.assertRaises(DomainError):
            validate_requisition("jd", date.today(), "Replacement", "", (1,), True)
        for quantities in ((), (0,), (1, -1)):
            with self.assertRaises(DomainError):
                validate_requisition("jd", date.today(), "New", "", quantities, True)

    def test_dispositions_use_reason_catalog(self):
        validate_terminal("Rejected", "Technical fit")
        validate_terminal("Withdrawn", "Another offer")
        for stage, reason in (("Rejected", ""), ("Withdrawn", "Technical fit")):
            with self.assertRaises(DomainError):
                validate_terminal(stage, reason)

    def test_only_submitted_cleared_final_round_allows_offer(self):
        require_final_round(True)
        with self.assertRaises(DomainError):
            require_final_round(False)

    def test_compensation_freezes_every_material_field(self):
        freeze_compensation({"tlc_salary": 10}, {"tlc_salary": 10}, True)
        for field in ("tlc_salary", "tlc_benefits", "terms", "offer_terms", "job_applicant"):
            with self.assertRaises(DomainError):
                freeze_compensation({field: "old"}, {field: "new"}, True)
        freeze_compensation({"tlc_salary": 10}, {"tlc_salary": 11}, False)

    def test_cannot_skip_offer_approval_or_sending(self):
        for before, after, approved in (("Draft", "Sent", False), ("Draft", "Accepted", True),
                                        ("Approved", "Sent", False), ("Accepted", "Negotiating", True)):
            with self.assertRaises(DomainError):
                validate_offer_stage(before, after, approved, "")
        validate_offer_stage("Pending Approval", "Approved", True, "")
        validate_offer_stage("Approved", "Sent", True, "")
        validate_offer_stage("Sent", "Accepted", True, "")

    def test_decline_reason_required(self):
        with self.assertRaises(DomainError):
            validate_offer_stage("Sent", "Rejected", True, "")
        validate_offer_stage("Negotiating", "Rejected", True, "Salary")

    def test_capacity_edges(self):
        self.assertEqual(vacancy_progress(2, 0), (2, 0.0))
        self.assertEqual(vacancy_progress(2, 1), (1, 50.0))
        self.assertEqual(vacancy_progress(2, 2), (0, 100.0))
        for required, accepted in ((0, 0), (2, 3), (2, -1)):
            with self.assertRaises(DomainError):
                vacancy_progress(required, accepted)

    def test_strict_commands_reject_coercion_and_unknown_fields(self):
        for values in ({"applicant_name": 42}, {"applicant_name": "A", "unknown": True}):
            with self.assertRaises(ValidationError):
                CandidateCommand(**values)

    def test_candidate_keys_preserve_distinct_application_identity(self):
        repo = MemoryRepository()
        service = RecruitmentService(repo)
        first = service.candidate(CandidateCommand(applicant_name="A", email="A@example.com", phone="0912345678"))
        second = service.candidate(CandidateCommand(applicant_name="A", email="different@example.com", phone="+84912345678"))
        self.assertEqual(first, second)
        repo.final.add("APPLICATION-1")
        service.check_offer(ApplicationCommand(application="APPLICATION-1"))
        with self.assertRaises(DomainError):
            service.check_offer(ApplicationCommand(application="APPLICATION-2"))

    def test_bridge_identity_merges_alias_sets(self):
        repo = MemoryRepository()
        service = RecruitmentService(repo)
        first = service.candidate(CandidateCommand(applicant_name="A", email="a@example.com"))
        service.candidate(CandidateCommand(applicant_name="A", phone="0912345678"))
        self.assertEqual(service.candidate(CandidateCommand(applicant_name="A", email="a@example.com", phone="0912345678")), first)
        self.assertEqual(len(set(repo.keys.values())), 1)

    def test_acceptance_orchestration_is_idempotent(self):
        service = RecruitmentService(MemoryRepository())
        self.assertEqual(service.accept_offer(OfferCommand(offer="O1")), service.accept_offer(OfferCommand(offer="O1")))
        self.assertEqual(service.approve_requisition("R1"), ["R1-1"])
