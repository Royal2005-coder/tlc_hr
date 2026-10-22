"""Unit tests for travel, advance, and expense domain rules and boundaries (no Frappe or DB needed)."""
import unittest
from datetime import date
from decimal import Decimal

from tlc_hr.application.travel_finance import TravelFinanceService
from tlc_hr.contracts.travel_finance import AssessSettlement, FinanceTransition, PayrollRecovery, TravelAssessment
from tlc_hr.domain import travel_finance as rules
from tlc_hr.domain.shared import DomainError, NotAllowed
from tlc_hr.domain.travel_finance_ports import ITravelFinanceRepository


class InMemoryRepo(ITravelFinanceRepository):
    def __init__(self, subject="an", manager="quang", manager_is_director=False, policy=True, conflicts_list=None):
        self._subject = subject
        self._manager = manager
        self._manager_is_director = manager_is_director
        self._policy = policy
        self._conflicts = conflicts_list or []
        self.locked_employees = []

    def route(self, employee):
        return rules.Route(subject=self._subject, manager=self._manager, manager_is_director=self._manager_is_director)

    def actor(self, user, employee):
        roles = set()
        if user == "quang":
            roles.add("TLC Line Manager")
        elif user == "thanh":
            roles.add("TLC Director")
        elif user == "chi":
            roles.add("Accounts User")
        elif user == self._subject:
            roles.add("TLC Self Service")
        in_scope = user in (self._manager, "thanh", "chi")
        return rules.Actor(user=user, roles=frozenset(roles), in_scope=in_scope)

    def conflicts(self, employee, window, exclude):
        return self._conflicts

    def lock_employee(self, employee):
        self.locked_employees.append(employee)

    def payroll_policy(self, employee):
        return self._policy


class TestTravelFinanceDomain(unittest.TestCase):
    def test_window_half_day_slots_and_overlap(self):
        w1 = rules.Window(date(2026, 11, 2), date(2026, 11, 4), "AM", "PM")
        self.assertEqual(len(list(w1.days())), 3)
        # Afternoon trip on 2026-11-04
        w2 = rules.Window(date(2026, 11, 4), date(2026, 11, 4), "PM", "PM")
        self.assertTrue(w1.overlaps(w2))
        # Morning trip on 2026-11-05 does not overlap
        w3 = rules.Window(date(2026, 11, 5), date(2026, 11, 5), "AM", "AM")
        self.assertFalse(w1.overlaps(w3))
        # Inverted dates raise domain error
        with self.assertRaises(DomainError):
            rules.Window(date(2026, 11, 5), date(2026, 11, 4), "AM", "PM").slots()

    def test_route_skip_duplicate_manager(self):
        # Regular employee with separate manager
        route1 = rules.Route(subject="an", manager="quang", manager_is_director=False)
        self.assertEqual(route1.first, rules.MANAGER)
        # Manager creator has no intermediate step: skips straight to CEO
        route2 = rules.Route(subject="quang", manager="quang", manager_is_director=False)
        self.assertEqual(route2.first, rules.CEO)
        # Creator reporting directly to Director skips intermediate manager
        route3 = rules.Route(subject="an", manager="thanh", manager_is_director=True)
        self.assertEqual(route3.first, rules.CEO)

    def test_no_self_approval(self):
        route = rules.Route(subject="an", manager="an")
        actor = rules.Actor(user="an", roles=frozenset({"TLC Line Manager"}), in_scope=True)
        with self.assertRaises(NotAllowed):
            rules.authorize(actor, route, rules.MANAGER)

    def test_manager_scope_enforced(self):
        route = rules.Route(subject="binh", manager="hung")  # Factory 1
        actor_wrong_scope = rules.Actor(user="nm2", roles=frozenset({"TLC Line Manager"}), in_scope=False)
        with self.assertRaises(NotAllowed):
            rules.authorize(actor_wrong_scope, route, rules.MANAGER)

    def test_three_way_settlement(self):
        # Branch 1: Equal
        s1 = rules.settlement(Decimal("5000000"), Decimal("5000000"))
        self.assertEqual(s1.branch, "equal")
        self.assertEqual(s1.difference, Decimal("0"))
        rules.require_settled(s1, refunded=Decimal("0"), reimbursed=Decimal("0"), receipt=False)

        # Branch 2: Refund (advance > actual)
        s2 = rules.settlement(Decimal("5000000"), Decimal("3500000"))
        self.assertEqual(s2.branch, "refund")
        self.assertEqual(s2.difference, Decimal("1500000"))
        # Partial refund rejected
        with self.assertRaises(DomainError):
            rules.require_settled(s2, refunded=Decimal("1000000"), reimbursed=Decimal("0"), receipt=False)
        # Exact refund accepted
        rules.require_settled(s2, refunded=Decimal("1500000"), reimbursed=Decimal("0"), receipt=False)

        # Branch 3: Top-up (advance < actual)
        s3 = rules.settlement(Decimal("5000000"), Decimal("6200000"))
        self.assertEqual(s3.branch, "top_up")
        self.assertEqual(s3.difference, Decimal("-1200000"))
        # Top-up without employee receipt rejected
        with self.assertRaises(DomainError):
            rules.require_settled(s3, refunded=Decimal("0"), reimbursed=Decimal("1200000"), receipt=False)
        # Top-up with confirmed receipt accepted
        rules.require_settled(s3, refunded=Decimal("0"), reimbursed=Decimal("1200000"), receipt=True)

    def test_payroll_consent_preconditions(self):
        today = date(2026, 11, 10)
        due_overdue = date(2026, 11, 5)
        due_not_overdue = date(2026, 11, 15)

        # 1. Not overdue rejected
        with self.assertRaises(DomainError):
            rules.require_payroll_consent(allowed=True, consent=True, evidence="signed.pdf",
                                          consent_by="an", subject="an", due=due_not_overdue, today=today)

        # 2. Company policy not allowed rejected
        with self.assertRaises(DomainError):
            rules.require_payroll_consent(allowed=False, consent=True, evidence="signed.pdf",
                                          consent_by="an", subject="an", due=due_overdue, today=today)

        # 3. Third party consent rejected
        with self.assertRaises(DomainError):
            rules.require_payroll_consent(allowed=True, consent=True, evidence="signed.pdf",
                                          consent_by="quang", subject="an", due=due_overdue, today=today)

        # 4. Valid consent passes
        rules.require_payroll_consent(allowed=True, consent=True, evidence="signed.pdf",
                                      consent_by="an", subject="an", due=due_overdue, today=today)

    def test_travel_service_assessment(self):
        repo = InMemoryRepo()
        service = TravelFinanceService(repo)

        # Funded travel without budget rejected
        with self.assertRaises(DomainError):
            service.assess_travel(TravelAssessment(
                name="TRV-01", employee="an", start=date(2026, 11, 2), end=date(2026, 11, 4),
                start_session="AM", end_session="PM", funded=True, budget=Decimal("0"),
                requested_advance=Decimal("0"), active=True
            ))

        # Unfunded travel with requested advance rejected
        with self.assertRaises(DomainError):
            service.assess_travel(TravelAssessment(
                name="TRV-02", employee="an", start=date(2026, 11, 2), end=date(2026, 11, 4),
                start_session="AM", end_session="PM", funded=False, budget=Decimal("0"),
                requested_advance=Decimal("1000000"), active=True
            ))

        # Active conflict detected raises DomainError
        repo_with_conflict = InMemoryRepo(conflicts_list=["Leave Application LA-2026-001"])
        service_conflict = TravelFinanceService(repo_with_conflict)
        with self.assertRaises(DomainError):
            service_conflict.assess_travel(TravelAssessment(
                name="TRV-03", employee="an", start=date(2026, 11, 2), end=date(2026, 11, 4),
                start_session="AM", end_session="PM", funded=False, budget=Decimal("0"),
                requested_advance=Decimal("0"), active=True
            ))

    def test_reconcile_adjustment_planned_initial_creation(self):
        # 1 day planned (AM, PM) in locked period with no prior mark or adjustments
        recon = rules.reconcile_adjustment(
            trip_name="TRV-2026-001",
            day=date(2026, 9, 15),
            target_sessions=("AM", "PM"),
            mark_sessions=(),
            applied_delta=Decimal("0"),
            has_pending=False,
        )
        self.assertEqual(recon.intended_delta, Decimal("1.00"))
        self.assertEqual(recon.applied_delta, Decimal("0.00"))
        self.assertEqual(recon.needed_delta, Decimal("1.00"))
        self.assertEqual(recon.action, "create")
        self.assertEqual(recon.target_key, "TRV-2026-001:2026-09-15:AM,PM")

    def test_reconcile_adjustment_shortened_report_updates_pending(self):
        # Report shortened to AM only while initial +1.0 draft is still pending
        recon = rules.reconcile_adjustment(
            trip_name="TRV-2026-001",
            day=date(2026, 9, 15),
            target_sessions=("AM",),
            mark_sessions=(),
            applied_delta=Decimal("0"),
            has_pending=True,
            pending_delta=Decimal("1.00"),
            pending_key="TRV-2026-001:2026-09-15:AM,PM",
        )
        self.assertEqual(recon.intended_delta, Decimal("0.50"))
        self.assertEqual(recon.applied_delta, Decimal("0.00"))
        self.assertEqual(recon.needed_delta, Decimal("0.50"))
        self.assertEqual(recon.action, "update")
        self.assertEqual(recon.target_key, "TRV-2026-001:2026-09-15:AM")

    def test_reconcile_adjustment_idempotent_replay(self):
        # Re-evaluating with identical target sessions and pending adjustment is a no-op
        recon = rules.reconcile_adjustment(
            trip_name="TRV-2026-001",
            day=date(2026, 9, 15),
            target_sessions=("AM",),
            mark_sessions=(),
            applied_delta=Decimal("0"),
            has_pending=True,
            pending_delta=Decimal("0.50"),
            pending_key="TRV-2026-001:2026-09-15:AM",
        )
        self.assertEqual(recon.intended_delta, Decimal("0.50"))
        self.assertEqual(recon.needed_delta, Decimal("0.50"))
        self.assertEqual(recon.action, "none")

    def test_reconcile_adjustment_cancellation_cancels_pending(self):
        # Trip cancelled before departure cancels pending draft adjustment (net delta 0)
        recon = rules.reconcile_adjustment(
            trip_name="TRV-2026-001",
            day=date(2026, 9, 15),
            target_sessions=(),
            mark_sessions=(),
            applied_delta=Decimal("0"),
            has_pending=True,
            pending_delta=Decimal("1.00"),
            pending_key="TRV-2026-001:2026-09-15:AM,PM",
        )
        self.assertEqual(recon.intended_delta, Decimal("0.00"))
        self.assertEqual(recon.needed_delta, Decimal("0.00"))
        self.assertEqual(recon.action, "cancel")

    def test_reconcile_adjustment_immutable_applied_with_shortened_report(self):
        # +1.0 day was already approved/applied to payroll; report shortened to AM only
        # Must produce an inverse adjustment of -0.5 day
        recon = rules.reconcile_adjustment(
            trip_name="TRV-2026-001",
            day=date(2026, 9, 15),
            target_sessions=("AM",),
            mark_sessions=(),
            applied_delta=Decimal("1.00"),
            has_pending=False,
        )
        self.assertEqual(recon.intended_delta, Decimal("0.50"))
        self.assertEqual(recon.applied_delta, Decimal("1.00"))
        self.assertEqual(recon.needed_delta, Decimal("-0.50"))
        self.assertEqual(recon.action, "inverse")
        self.assertEqual(recon.target_key, "TRV-2026-001:2026-09-15:AM:recon:-0.50")

    def test_reconcile_adjustment_immutable_applied_with_cancellation(self):
        # +1.0 day was already approved/applied to payroll; trip cancelled after close
        # Must produce an inverse adjustment of -1.0 day
        recon = rules.reconcile_adjustment(
            trip_name="TRV-2026-001",
            day=date(2026, 9, 15),
            target_sessions=(),
            mark_sessions=(),
            applied_delta=Decimal("1.00"),
            has_pending=False,
        )
        self.assertEqual(recon.intended_delta, Decimal("0.00"))
        self.assertEqual(recon.applied_delta, Decimal("1.00"))
        self.assertEqual(recon.needed_delta, Decimal("-1.00"))
        self.assertEqual(recon.action, "inverse")
        self.assertEqual(recon.target_key, "TRV-2026-001:2026-09-15::recon:-1.00")


if __name__ == "__main__":
    unittest.main()
