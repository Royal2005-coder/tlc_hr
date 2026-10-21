"""Demo-site native ACL and exact Raven whitelist checks; no provider calls."""
import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from tlc_hr.infrastructure.frappe.assistant import FrappeAssistantRepository
from tlc_hr.interface.assistant import BOT_NAME, FUNCTIONS, draft_leave, query, validate_bot, validate_function


class TestAssistant(IntegrationTestCase):
    def setUp(self):
        self.old_enabled = frappe.conf.get("tlc_ai_demo_enabled")
        self.old_user = frappe.session.user
        frappe.set_user("Administrator")
        if frappe.local.site != "tlc-hr.local" or not frappe.db.exists("User", "binh@demo.example"):
            self.skipTest("Requires the synthetic TLC demo site.")
        self.people = {row.user_id: row.name for row in frappe.get_list("Employee", filters={"company": "TLC Demo"}, fields=["name", "user_id"], limit_page_length=100)}
        frappe.conf.tlc_ai_demo_enabled = True

    def tearDown(self):
        frappe.conf.tlc_ai_demo_enabled = self.old_enabled
        frappe.set_user(self.old_user)
        frappe.db.rollback()

    def test_cross_factory_and_salary_scopes_denied_for_worker_manager_and_hr(self):
        for actor in ("binh", "hung", "hoa", "phuong", "thanh"):
            frappe.set_user(actor + "@demo.example")
            for other in ("f2w01", "f3w01"):
                for topic in ("payslip", "attendance", "profile"):
                    with patch.object(FrappeAssistantRepository, "read_self") as read:
                        with self.assertRaises(frappe.PermissionError):
                            query(topic, self.people[other + "@demo.example"])
                        read.assert_not_called()
            with self.assertRaises(frappe.PermissionError):
                draft_leave("Phép năm", "2026-11-02", "2026-11-02", "Demo", self.people["f2w01@demo.example"])

    def test_disabled_and_administrator_denied(self):
        for actor in ("Administrator", "Guest"):
            frappe.set_user(actor)
            with self.assertRaises(frappe.PermissionError):
                query("profile")
        frappe.set_user("binh@demo.example")
        frappe.conf.tlc_ai_demo_enabled = False
        with self.assertRaises(frappe.PermissionError):
            query("profile")

    def test_native_query_permission_error_is_not_swallowed(self):
        frappe.set_user("binh@demo.example")
        with patch("tlc_hr.infrastructure.frappe.assistant.frappe.get_list", side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):
                query("payslip")

    def test_raven_registration_has_only_safe_custom_functions(self):
        if "raven" not in frappe.get_installed_apps() or not frappe.db.exists("Raven Bot", BOT_NAME):
            self.skipTest("Raven integration prerequisite not provisioned; not a provider pass.")
        frappe.set_user("Administrator")
        bot = frappe.get_doc("Raven Bot", BOT_NAME)
        validate_bot(bot)
        self.assertEqual({row.function for row in bot.bot_functions}, set(FUNCTIONS))
        for name, path in FUNCTIONS.items():
            function = frappe.get_doc("Raven AI Function", name)
            self.assertEqual((function.type, function.function_path), ("Custom Function", path))
            schema = json.loads(function.params)
            self.assertFalse(schema["additionalProperties"])
            self.assertFalse({"user", "docstatus", "workflow_state", "ignore_permissions"} & set(schema["properties"]))
        bot.append("bot_functions", {"function": "submit_document"})
        with self.assertRaises(frappe.PermissionError):
            validate_bot(bot)
        function = frappe.get_doc("Raven AI Function", "tlc_hr_query")
        function.function_path = "frappe.client.get_list"
        with self.assertRaises(frappe.PermissionError):
            validate_function(function)
