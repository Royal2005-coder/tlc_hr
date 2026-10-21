"""Exercise maintenance boundaries with an in-memory Frappe adapter; no site or source-text assertions."""

import copy
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from tlc_hr.contracts.customizing import Bundle, CustomizingFile
from tlc_hr.infrastructure.customizing.base import ResourceApplier
from tlc_hr.infrastructure.customizing.loader import CustomizingError, load_bundle

ROOT = Path(__file__).resolve().parents[2] / "infrastructure" / "customizing"


def adapter(name, frappe):
    spec = importlib.util.spec_from_file_location(f"_test_tlc_{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"frappe": frappe}):
        spec.loader.exec_module(module)
    return module


class Document(dict):
    def __getattr__(self, key):
        return self.get(key)

    def as_dict(self):
        return dict(self)


class Database:
    def __init__(self):
        self.rows = {"existing": "user value"}
        self.before = copy.deepcopy(self.rows)
        self.commits = 0
        self.rollbacks = 0

    def rollback(self):
        self.rows = copy.deepcopy(self.before)
        self.rollbacks += 1

    def commit(self):
        self.commits += 1


class MemoryApplier(ResourceApplier):
    kind = "example"

    def __init__(self, db, fail=False):
        self.db, self.fail = db, fail
        self.writes = 0

    def items(self, bundle):
        return ["wanted"]

    def name_of(self, spec):
        return spec

    def diff(self, spec):
        return None if spec in self.db.rows else ()

    def write(self, spec):
        if self.fail:
            raise ValueError("resource failed")
        self.db.rows[spec] = "declared"
        self.writes += 1


class TestMaintenanceEngine(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.frappe = types.ModuleType("frappe")
        self.frappe.db = self.db
        self.frappe.logger = Mock()
        self.engine = adapter("engine", self.frappe)

    def test_plan_reads_without_writing_or_committing(self):
        resource = MemoryApplier(self.db)
        with patch.object(self.engine, "appliers", return_value=[resource]):
            changes = self.engine.plan(Bundle())
        self.assertEqual([(c.name, c.action) for c in changes], [("wanted", "create")])
        self.assertEqual((resource.writes, self.db.commits, self.db.rollbacks), (0, 0, 0))
        self.assertEqual(self.db.rows, self.db.before)

    def test_apply_is_idempotent_and_caller_owns_commit(self):
        resource = MemoryApplier(self.db)
        with patch.object(self.engine, "appliers", return_value=[resource]):
            self.assertEqual(len(self.engine.apply(Bundle())), 1)
            self.assertEqual(self.engine.apply(Bundle()), [])
        self.assertEqual((resource.writes, self.db.commits), (1, 0))

    def test_later_failure_rolls_back_earlier_data_writes(self):
        first = MemoryApplier(self.db)
        second = MemoryApplier(self.db, fail=True)
        # The second resource represents another identity, not an already reconciled first one.
        second.items = lambda bundle: ["failing"]
        with patch.object(self.engine, "appliers", return_value=[first, second]):
            with self.assertRaisesRegex(ValueError, "resource failed"):
                self.engine.apply(Bundle())
        self.assertEqual(self.db.rows, self.db.before)
        self.assertEqual((self.db.rollbacks, self.db.commits), (1, 0))


class TestExports(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        self.exporter = adapter("exporter", self.frappe)

    def test_workflow_round_trip_retains_email_and_self_approval_false(self):
        workflow = Document(name="W", document_type="Leave Application", send_email_alert=1,
                            states=[Document(state="Nháp", doc_status="0", allow_edit="Employee", update_field=None, update_value=None)],
                            transitions=[Document(state="Nháp", action="Gửi", next_state="Nháp", allowed="Employee", condition=None,
                                                  allow_self_approval=0)])
        self.frappe.get_doc = lambda doctype, name: workflow
        self.frappe.db = types.SimpleNamespace(get_value=lambda *args: "Primary")
        exported = self.exporter.export_file("workflow", Bundle(), "W")
        result = CustomizingFile.model_validate(yaml.safe_load(yaml.safe_dump(exported))).workflow
        self.assertTrue(result.send_email_alert)
        self.assertFalse(result.transitions[0].allow_self_approval)
        self.assertEqual(result.states[0].style, "Primary")

    def test_export_reflects_ui_cleared_optional_value(self):
        self.frappe.get_doc = lambda *args: Document(name="R", desk_access=0, home_page=None)
        bundle = Bundle.model_validate({"roles": [{"name": "R", "home_page": "/old"}]})
        result = self.exporter.export_file("roles", bundle)
        self.assertEqual(result["roles"], [{"name": "R", "desk_access": False, "home_page": None}])

    def test_workflow_name_is_required(self):
        with self.assertRaisesRegex(ValueError, "requires a name"):
            self.exporter.export_file("workflow", Bundle())


class TestSchemaResources(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        self.records = adapter("records", self.frappe)

    def test_child_schema_precedes_parent_and_ordinary_records_are_separate(self):
        bundle = Bundle.model_validate({"records": [
            {"doctype": "DocType", "name": "Parent", "tables": {"fields": [{"fieldname": "rows", "fieldtype": "Table", "options": "Child"}]}},
            {"doctype": "Parent", "name": "P1"}, {"doctype": "DocType", "name": "Child"},
        ]})
        self.assertEqual([s.name for s in self.records.DocTypeApplier().items(bundle)], ["Child", "Parent"])
        self.assertEqual([s.name for s in self.records.RecordApplier().items(bundle)], ["P1"])

    def test_cyclic_child_tables_are_rejected_before_writing(self):
        bundle = Bundle.model_validate({"records": [
            {"doctype": "DocType", "name": "A", "tables": {"fields": [{"fieldtype": "Table", "options": "B"}]}},
            {"doctype": "DocType", "name": "B", "tables": {"fields": [{"fieldtype": "Table", "options": "A"}]}},
        ]})
        with self.assertRaisesRegex(ValueError, "cyclic"):
            self.records.DocTypeApplier().items(bundle)

    def test_missing_doctype_plans_creation_without_reading_its_table(self):
        self.frappe.db = types.SimpleNamespace(exists=lambda doctype, name: False)
        bundle = Bundle.model_validate({"records": [{"doctype": "New Type", "name": "N1"}]})
        changes = self.records.RecordApplier().plan(bundle)
        self.assertEqual([(c.name, c.action) for c in changes], [("New Type: N1", "create")])


class TestExternalBundleErrors(unittest.TestCase):
    def test_invalid_external_file_reports_its_path_not_relative_path_error(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "invalid.yaml"
            path.write_text("version: 1\nkind: roles\nroles: [{name: R, desk_access: nope}]\n", encoding="utf-8")
            with self.assertRaises(CustomizingError) as caught:
                load_bundle(Path(root))
            self.assertIn(str(path), str(caught.exception))
