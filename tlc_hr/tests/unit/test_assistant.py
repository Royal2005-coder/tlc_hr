"""No Frappe dependency: authorization and draft-only contract regression tests."""
import unittest

from pydantic import ValidationError

from tlc_hr.application.assistant import AssistantService
from tlc_hr.contracts.assistant import AssistantQuery, LeaveDraft
from tlc_hr.domain.assistant import AssistantIdentity, IAssistantRepository
from tlc_hr.domain.shared import DomainError, NotAllowed


class Repository(IAssistantRepository):
    def __init__(self, enabled=True, user="binh@demo.example", employee="DEMO-NM1-001"):
        self.actor = AssistantIdentity(user, employee, enabled)
        self.reads, self.writes, self.events = [], [], []

    def identity(self):
        return self.actor

    def read_self(self, topic, employee):
        self.reads.append((topic, employee))
        return {"records": [], "employee": employee}

    def create_leave_draft(self, employee, command):
        self.writes.append((employee, command))
        return {"document_id": "DEMO-LEAVE-001", "docstatus": 0}

    def audit(self, action, employee, outcome):
        self.events.append((action, employee, outcome))


class TestAssistant(unittest.TestCase):
    def test_all_read_topics_are_self_only(self):
        for topic in ("profile", "attendance", "leave", "payslip"):
            repo = Repository()
            AssistantService(repo).query(AssistantQuery(topic=topic))
            self.assertEqual(repo.reads, [(topic, repo.actor.employee)])
            self.assertEqual(repo.writes, [])

    def test_other_employee_and_other_factory_denied_before_any_read(self):
        for requested in ("DEMO-NM1-002", "DEMO-NM2-001", "DEMO-NM3-001", "Administrator"):
            for topic in ("profile", "attendance", "leave", "payslip"):
                repo = Repository()
                with self.assertRaises(NotAllowed):
                    AssistantService(repo).query(AssistantQuery(topic=topic, employee=requested))
                self.assertEqual(repo.reads, [])
                self.assertEqual(repo.events[-1][-1], "denied")

    def test_privileged_user_cannot_widen_scope(self):
        repo = Repository(user="hoa@demo.example")
        with self.assertRaises(NotAllowed):
            AssistantService(repo).query(AssistantQuery(topic="payslip", employee="DEMO-NM2-001"))
        self.assertEqual(repo.reads, [])

    def test_disabled_guest_admin_and_missing_employee_denied(self):
        for repo in (Repository(enabled=False), Repository(user="Guest"), Repository(user="Administrator"), Repository(employee="")):
            with self.assertRaises(NotAllowed):
                AssistantService(repo).query(AssistantQuery(topic="payslip"))
            self.assertEqual(repo.reads, [])

    def test_draft_self_only_and_no_approval_surface(self):
        repo = Repository()
        command = LeaveDraft(leave_type="Phép năm", from_date="2026-11-02", to_date="2026-11-02", reason="Demo")
        self.assertEqual(AssistantService(repo).draft_leave(command)["docstatus"], 0)
        self.assertEqual(repo.writes[0][0], repo.actor.employee)
        self.assertFalse(hasattr(AssistantService(repo), "submit"))
        self.assertFalse(hasattr(AssistantService(repo), "approve"))
        for extra in ({"docstatus": 1}, {"workflow_state": "Đã duyệt"}, {"ignore_permissions": True}, {"user": "Administrator"}):
            with self.assertRaises(ValidationError):
                LeaveDraft(**{**command.model_dump(), **extra})
        with self.assertRaises(ValidationError):
            AssistantQuery(topic="close_payroll")

    def test_foreign_draft_and_invalid_dates_have_no_write(self):
        for extra in ({"employee": "DEMO-NM2-001"}, {"to_date": "2026-11-01"}, {"from_date": "2026-02-30"}):
            repo = Repository()
            command = LeaveDraft(**{"leave_type": "Phép năm", "from_date": "2026-11-02", "to_date": "2026-11-02", "reason": "Demo", **extra})
            with self.assertRaises(DomainError):
                AssistantService(repo).draft_leave(command)
            self.assertEqual(repo.writes, [])
