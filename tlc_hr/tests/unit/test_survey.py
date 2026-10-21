"""Unit tests for pure anonymous survey rules, validation and threshold aggregation."""
import unittest
from tlc_hr.domain.survey import validate_questions, ballot, aggregate_result
from tlc_hr.domain.shared import DomainError
from tlc_hr.domain.survey_ports import ISurveyRepository
from tlc_hr.contracts.survey import AnonymousSubmission, SurveyResults
from tlc_hr.application.survey import SurveyService


class InMemorySurveyRepo(ISurveyRepository):
    def __init__(self):
        self.submissions = []
        self.aggregated = {}

    def submit_anonymous(self, campaign, answers):
        self.submissions.append({"campaign": campaign, "answers": answers})
        return {"submitted": True}

    def results(self, campaign, department):
        return {"campaign": campaign, "department": department, "suppressed": False}


class TestSurveyRules(unittest.TestCase):
    def setUp(self):
        self.questions = [
            {"key": "q1", "label": "Mức độ hài lòng với bữa ăn?", "options": ["Hài lòng", "Bình thường", "Không hài lòng"], "hidden": False},
            {"key": "q2", "label": "Chất lượng phòng họp?", "options": ["Tốt", "Cần cải thiện"], "hidden": False},
        ]

    def test_question_validation(self):
        # Empty questions
        with self.assertRaises(DomainError) as ctx:
            validate_questions([])
        self.assertEqual(ctx.exception.code, "survey_questions")

        # Duplicate keys
        with self.assertRaises(DomainError) as ctx:
            validate_questions([
                {"key": "q1", "label": "Câu 1", "options": ["A", "B"]},
                {"key": "q1", "label": "Câu 2", "options": ["A", "B"]},
            ])
        self.assertEqual(ctx.exception.code, "question_duplicate")

        # Insufficient options
        with self.assertRaises(DomainError) as ctx:
            validate_questions([
                {"key": "q1", "label": "Câu 1", "options": ["A"]},
            ])
        self.assertEqual(ctx.exception.code, "question_options")

        # Blank option
        with self.assertRaises(DomainError) as ctx:
            validate_questions([
                {"key": "q1", "label": "Câu 1", "options": ["A", "  "]},
            ])
        self.assertEqual(ctx.exception.code, "question_options")

    def test_ballot_validation(self):
        valid_answers = {"q1": "Hài lòng", "q2": "Tốt"}
        b = ballot(self.questions, valid_answers)
        self.assertEqual(b, valid_answers)

        # Missing answer
        with self.assertRaises(DomainError) as ctx:
            ballot(self.questions, {"q1": "Hài lòng"})
        self.assertEqual(ctx.exception.code, "answer_questions")

        # Invalid option
        with self.assertRaises(DomainError) as ctx:
            ballot(self.questions, {"q1": "Rất tệ", "q2": "Tốt"})
        self.assertEqual(ctx.exception.code, "answer_option")

    def test_aggregation_privacy_threshold(self):
        # Threshold < 5 is prohibited
        with self.assertRaises(DomainError) as ctx:
            aggregate_result(self.questions, [], threshold=4)
        self.assertEqual(ctx.exception.code, "privacy_threshold")

        # 4 responses: under threshold 5 -> suppressed True
        rows = [
            {"question": "q1", "option": "Hài lòng", "count": 2},
            {"question": "q1", "option": "Bình thường", "count": 2},
            {"question": "q2", "option": "Tốt", "count": 4},
        ]
        res = aggregate_result(self.questions, rows, threshold=5)
        self.assertTrue(res["suppressed"])
        self.assertNotIn("questions", res)

        # 5 responses: meets threshold 5 -> suppressed False
        rows_5 = [
            {"question": "q1", "option": "Hài lòng", "count": 3},
            {"question": "q1", "option": "Bình thường", "count": 2},
            {"question": "q2", "option": "Tốt", "count": 5},
        ]
        res_5 = aggregate_result(self.questions, rows_5, threshold=5)
        self.assertFalse(res_5["suppressed"])
        self.assertEqual(res_5["responses"], 5)
        self.assertEqual(res_5["questions"][0]["counts"]["Hài lòng"], 3)
        self.assertEqual(res_5["questions"][0]["counts"]["Bình thường"], 2)
        self.assertEqual(res_5["questions"][0]["counts"]["Không hài lòng"], 0)

    def test_survey_service_contracts(self):
        repo = InMemorySurveyRepo()
        svc = SurveyService(repo)

        sub = AnonymousSubmission(campaign="SUR-2026-001", answers={"q1": "Hài lòng"})
        res = svc.submit(sub)
        self.assertTrue(res["submitted"])
        self.assertEqual(len(repo.submissions), 1)

        query = SurveyResults(campaign="SUR-2026-001", department="Kinh doanh")
        qres = svc.results(query)
        self.assertEqual(qres["department"], "Kinh doanh")


if __name__ == "__main__":
    unittest.main()
