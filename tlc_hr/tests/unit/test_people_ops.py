"""Unit and boundary tests for People Operations domain rules and application use cases."""
import unittest
from datetime import date, timedelta
from tlc_hr.application.people_ops import PeopleOpsService
from tlc_hr.contracts.people_ops import (
    BenefitCommand,
    LicenseCommand,
    ReceiptCommand,
    TransitionCommand,
)
from tlc_hr.domain.people_ops import (
    PeopleOpsError,
    benefit_amount,
    reminder_band,
    require_receipt,
    require_seat,
    require_transition,
    training_due,
)


class InMemoryPeopleOpsRepository:
    def __init__(self, requirements=(), employees=(), certificates=(), acks=(), health=()):
        self.reqs = list(requirements)
        self.emps = list(employees)
        self.certs = list(certificates)
        self.acks = list(acks)
        self.health_appts = list(health)
        self.reminders = []
        self.ensured = []

    def mandatory_training(self):
        return self.reqs

    def matching_employees(self, requirement):
        return self.emps

    def latest_completion(self, employee, program):
        for c in self.certs:
            if c.employee == employee and c.training_program == program and c.status == "Completed":
                return c.completed_on
        return None

    def ensure_training(self, employee, requirement):
        name = f"CERT-{employee}-{requirement.training_program}"
        self.ensured.append((employee, requirement))
        return name

    def certificates(self):
        return self.certs

    def remind(self, doctype, name, employee, message, band):
        self.reminders.append((doctype, name, employee, message, band))

    def pending_acknowledgments(self):
        return self.acks

    def pending_health(self):
        return self.health_appts


class MockRecord:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def get(self, key, default=None):
        return getattr(self, key, default)


class TestPeopleOpsDomain(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 21)

    def test_asset_dual_receipt_boundaries(self):
        # Valid receipt
        cmd = ReceiptCommand(actor="an@demo.example", expected_actor="an@demo.example", evidence="private/doc.pdf", submitted=False)
        require_receipt(cmd)

        # Wrong actor
        with self.assertRaises(PeopleOpsError):
            require_receipt(ReceiptCommand(actor="other@demo.example", expected_actor="an@demo.example", evidence="private/doc.pdf", submitted=False))

        # Already submitted
        with self.assertRaises(PeopleOpsError):
            require_receipt(ReceiptCommand(actor="an@demo.example", expected_actor="an@demo.example", evidence="private/doc.pdf", submitted=True))

    def test_license_capacity_and_expiry_boundaries(self):
        # Valid seat allocation
        require_seat(LicenseCommand(seats=10, used=5, expires_on=self.today + timedelta(days=30), today=self.today))

        # Full seats
        with self.assertRaises(PeopleOpsError):
            require_seat(LicenseCommand(seats=5, used=5, expires_on=self.today + timedelta(days=30), today=self.today))

        # Expired license
        with self.assertRaises(PeopleOpsError):
            require_seat(LicenseCommand(seats=10, used=2, expires_on=self.today - timedelta(days=1), today=self.today))

    def test_benefit_event_effective_window(self):
        cmd = BenefitCommand(
            event="Marriage",
            event_date=self.today,
            effective_from=self.today - timedelta(days=30),
            effective_to=self.today + timedelta(days=30),
            amount=3000000.0,
        )
        self.assertEqual(benefit_amount(cmd), 3000000.0)

        # Event before effective policy
        out_cmd = BenefitCommand(
            event="Marriage",
            event_date=self.today - timedelta(days=60),
            effective_from=self.today - timedelta(days=30),
            effective_to=self.today + timedelta(days=30),
            amount=3000000.0,
        )
        with self.assertRaises(PeopleOpsError):
            benefit_amount(out_cmd)

    def test_training_due_and_reminder_bands(self):
        # Never completed
        self.assertTrue(training_due(None, 365, self.today))
        # Completed recently
        self.assertFalse(training_due(self.today - timedelta(days=100), 365, self.today))
        # Overdue recurrence
        self.assertTrue(training_due(self.today - timedelta(days=366), 365, self.today))

        # Expiry bands
        self.assertEqual(reminder_band(self.today - timedelta(days=1), self.today), "Expired")
        self.assertEqual(reminder_band(self.today + timedelta(days=15), self.today), "30")
        self.assertEqual(reminder_band(self.today + timedelta(days=45), self.today), "60")
        self.assertIsNone(reminder_band(self.today + timedelta(days=90), self.today))

    def test_workflow_state_transitions_and_evidence(self):
        # Valid Account transition by HR
        require_transition("account", TransitionCommand(previous="Requested", target="Active", actor_kind="hr"))

        # Account revocation without evidence must fail
        with self.assertRaises(PeopleOpsError):
            require_transition("account", TransitionCommand(previous="Active", target="Revoked", actor_kind="hr", evidence=""))

        # Valid Account revocation with evidence
        require_transition("account", TransitionCommand(previous="Active", target="Revoked", actor_kind="hr", evidence="Quyết định nghỉ việc số 12/QĐ"))

        # Benefit transition by unauthorized actor must fail
        with self.assertRaises(PeopleOpsError):
            require_transition("benefit", TransitionCommand(previous="Pending", target="Approved", actor_kind="self"))

        # Benefit transition to Paid requires payment evidence
        with self.assertRaises(PeopleOpsError):
            require_transition("benefit", TransitionCommand(previous="Approved", target="Paid", actor_kind="accountant", evidence=""))

        require_transition("benefit", TransitionCommand(previous="Approved", target="Paid", actor_kind="accountant", evidence="UNC-2026-991"))

        # Discipline transitions
        require_transition("discipline", TransitionCommand(previous="Proposal", target="HR Review", actor_kind="manager"))
        require_transition("discipline", TransitionCommand(previous="HR Review", target="Director Review", actor_kind="hr", evidence="Biên bản họp kỷ luật"))
        require_transition("discipline", TransitionCommand(previous="Director Review", target="Approved", actor_kind="director", evidence="Giám đốc phê chuẩn hình thức khiển trách"))

        # Appraisal transitions
        require_transition("appraisal", TransitionCommand(previous="Self Review", target="Manager Review", actor_kind="self"))
        require_transition("appraisal", TransitionCommand(previous="Manager Review", target="Calibration", actor_kind="manager"))
        require_transition("appraisal", TransitionCommand(previous="Calibration", target="Rated", actor_kind="hr", evidence="Xếp loại A"))


class TestPeopleOpsService(unittest.TestCase):
    def test_daily_reminders_and_mandatory_training(self):
        today = date(2026, 10, 21)
        req = MockRecord(name="REQ-01", training_program="PCCC", recurrence_days=365, due_days=30)
        cert = MockRecord(
            name="CERT-01",
            employee="EMP-01",
            training_program="PCCC",
            status="Completed",
            completed_on=today - timedelta(days=350),
            expires_on=today + timedelta(days=20),
        )
        ack = MockRecord(name="ACK-01", employee="EMP-01")
        health = MockRecord(name="HLT-01", employee="EMP-01")

        repo = InMemoryPeopleOpsRepository(
            requirements=[req],
            employees=["EMP-02"],  # EMP-02 has never taken PCCC
            certificates=[cert],
            acks=[ack],
            health=[health],
        )

        service = PeopleOpsService(repo)
        service.daily(today)

        # 1. Training requirement for EMP-02 ensured and reminded
        self.assertEqual(len(repo.ensured), 1)
        self.assertEqual(repo.ensured[0], ("EMP-02", req))

        # Reminders dispatched:
        # - Training required for EMP-02
        # - Expiring certificate for EMP-01 (band 30)
        # - Acknowledgment for EMP-01
        # - Health appointment for EMP-01
        reminded_types = [r[0] for r in repo.reminders]
        self.assertIn("TLC People Ops Certificate", reminded_types)
        self.assertIn("TLC People Ops Acknowledgment", reminded_types)
        self.assertIn("TLC People Ops Health Appointment", reminded_types)

        cert_reminder = next(r for r in repo.reminders if r[1] == "CERT-01")
        self.assertEqual(cert_reminder[4], "30")


if __name__ == "__main__":
    unittest.main()
