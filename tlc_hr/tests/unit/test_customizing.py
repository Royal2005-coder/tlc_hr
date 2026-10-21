"""The customizing YAML against its contracts (no site needed): the real files load, typos and broken references are refused,
and the statutory values the payroll writes match the ones the code computes with."""

import unittest

from pydantic import ValidationError

from tlc_hr.contracts.customizing import Bundle, CustomizingFile, PermissionSpec, WorkflowSpec
from tlc_hr.infrastructure.customizing.loader import load_bundle


class TestCustomizingFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle()

    def test_the_files_of_the_app_are_valid(self):
        names = {w.name for w in self.bundle.workflows}
        self.assertTrue({"TLC Nghỉ phép", "TLC Điều chỉnh công", "TLC Tăng ca", "TLC Chốt công"} <= names)
        self.assertTrue({"TLC Quản lý", "TLC Nhân sự", "TLC Điều hành"} <= {w.title for w in self.bundle.workspaces})

    def test_every_workflow_starts_in_draft(self):
        for wf in self.bundle.workflows:
            self.assertEqual(wf.states[0].state, "Nháp", wf.name)
            self.assertTrue(any(t.from_state == "Nháp" for t in wf.transitions), wf.name)

    def test_statutory_values_match_the_code(self):
        from tlc_hr.vn.statutory import SETTINGS_2026

        record = next(r for r in self.bundle.records if r.doctype == "VN Payroll Settings")
        self.assertEqual(dict(record.values), SETTINGS_2026)

    def test_roles_used_by_workflows_are_known(self):
        standard = {"Employee", "Leave Approver", "Expense Approver", "HR Manager", "HR User", "Accounts User", "Accounts Manager",
                    "System Manager"}
        declared = {r.name for r in self.bundle.roles} | standard
        used = {role for wf in self.bundle.workflows for t in wf.transitions for role in t.allowed}
        used |= {s.allow_edit for wf in self.bundle.workflows for s in wf.states}
        self.assertEqual(used - declared, set())


class TestContracts(unittest.TestCase):
    def test_unknown_key_is_refused(self):
        with self.assertRaises(ValidationError):
            CustomizingFile.model_validate({"version": 1, "kind": "roles", "roles": [{"name": "X", "desk_acess": True}]})

    def test_unknown_right_is_refused(self):
        with self.assertRaises(ValidationError):
            PermissionSpec.model_validate({"doctype": "Leave Application", "role": "Employee", "rights": "rq"})

    def test_transition_to_an_undeclared_state_is_refused(self):
        with self.assertRaises(ValidationError):
            WorkflowSpec.model_validate({"name": "W", "doctype": "D", "states": [{"state": "Nháp", "doc_status": 0, "allow_edit": "Employee"}],
                                         "transitions": [{"from": "Nháp", "action": "Gửi", "to": "Đi đâu", "allowed": ["Employee"]}]})

    def test_workspace_with_unknown_card_is_refused(self):
        with self.assertRaises(ValidationError):
            Bundle.model_validate({"workspaces": [{"title": "W", "roles": ["Employee"], "icon": "users", "sequence": 1, "cards": ["Không có"]}]})

    def test_strict_types(self):
        with self.assertRaises(ValidationError):
            PermissionSpec.model_validate({"doctype": "Leave Application", "role": "Employee", "permlevel": "1", "rights": "r"})


if __name__ == "__main__":
    unittest.main()
