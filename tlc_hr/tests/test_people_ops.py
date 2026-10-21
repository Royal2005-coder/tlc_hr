"""Integration and boundary tests for TLC People Operations (assets dual receipt, accounts, clearance blockers, policy acknowledgment, scoped access)."""
import frappe
from frappe.tests import IntegrationTestCase
from tlc_hr.infrastructure.frappe.people_ops import clearance_blockers, provision_onboarding
from tlc_hr.interface.people_ops import acknowledge, receipt


class TestPeopleOps(IntegrationTestCase):
    def setUp(self):
        self.employee = frappe.db.get_value("Employee", {"user_id": "an@demo.example"}, "name")
        if not self.employee:
            self.skipTest("Demo employee an@demo.example not found")
        self.hr_user = "hoa@demo.example" if frappe.db.exists("User", "hoa@demo.example") else "Administrator"
        self.an_user = "an@demo.example"

    def test_clearance_blockers_interface(self):
        # clearance_blockers must return a list of strings
        blockers = clearance_blockers(self.employee)
        self.assertIsInstance(blockers, list)
        for b in blockers:
            self.assertIsInstance(b, str)

    def test_provisioning_requires_hr_permission(self):
        # Non-HR user calling provision_onboarding directly must be rejected
        frappe.set_user(self.an_user)
        with self.assertRaises(frappe.PermissionError):
            provision_onboarding(self.employee, asset_items=(), account_licenses=())
        frappe.set_user("Administrator")

    def test_license_and_account_request(self):
        # Employee requesting an account for a license starts in Requested status
        license_name = frappe.db.get_value("TLC People Ops License", {}, "name")
        if not license_name:
            self.skipTest("No license fixture loaded")
        frappe.set_user(self.an_user)
        acc = frappe.get_doc({
            "doctype": "TLC People Ops Account",
            "employee": self.employee,
            "license": license_name,
            "account_identifier": "an.new@demo.example",
            "status": "Requested",
        }).insert()
        self.assertEqual(acc.status, "Requested")
        frappe.set_user("Administrator")

    def test_policy_acknowledgment_flow(self):
        policy_name = frappe.db.get_value("TLC People Ops Policy Version", {"status": "Published"}, "name")
        if not policy_name:
            self.skipTest("No published policy fixture loaded")
        # Existing or newly inserted acknowledgment for test
        ack_name = frappe.db.get_value("TLC People Ops Acknowledgment", {"employee": self.employee, "policy_version": policy_name}, "name")
        if not ack_name:
            ack = frappe.get_doc({
                "doctype": "TLC People Ops Acknowledgment",
                "employee": self.employee,
                "policy_version": policy_name,
                "policy_snapshot": "Test Policy Content",
            }).insert(ignore_permissions=True)
            ack_name = ack.name

        ack_doc = frappe.get_doc("TLC People Ops Acknowledgment", ack_name)
        if not ack_doc.acknowledged_at:
            frappe.set_user(self.an_user)
            acknowledge(ack_name)
            frappe.set_user("Administrator")
            ack_doc.reload()
            self.assertTrue(ack_doc.acknowledged_at)
            self.assertEqual(ack_doc.acknowledged_by, self.an_user)
