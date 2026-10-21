"""The framework boundary exposes validation locations, never private contract inputs or validator text."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict, field_validator

from tlc_hr.domain.shared import DomainError, NotAllowed


class EdgeValidationError(Exception):
    pass


class EdgePermissionError(Exception):
    pass


class PrivateCommand(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    value: str

    @field_validator("value")
    @classmethod
    def refuse(cls, value):
        raise ValueError(f"private input: {value}")


class TestErrorBoundary(unittest.TestCase):
    def setUp(self):
        frappe = types.ModuleType("frappe")
        frappe.ValidationError = EdgeValidationError
        frappe.PermissionError = EdgePermissionError

        def throw(message, exc=EdgeValidationError, **kwargs):
            raise exc(message)

        frappe.throw = throw
        path = Path(__file__).resolve().parents[2] / "interface" / "errors.py"
        spec = importlib.util.spec_from_file_location("_test_tlc_errors", path)
        self.errors = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"frappe": frappe}):
            spec.loader.exec_module(self.errors)

    def test_pydantic_inputs_and_custom_messages_are_redacted(self):
        with self.assertRaises(EdgeValidationError) as caught:
            with self.errors.domain_errors():
                PrivateCommand(value="confidential-payload")
        self.assertIn("value: value_error", str(caught.exception))
        self.assertNotIn("confidential-payload", str(caught.exception))
        self.assertNotIn("private input", str(caught.exception))

    def test_untrusted_extra_key_cannot_inject_html_into_error(self):
        with self.assertRaises(EdgeValidationError) as caught:
            with self.errors.domain_errors():
                PrivateCommand.model_validate({"value": "secret", "<script>secret</script>": "secret"})
        self.assertNotIn("<script>", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        self.assertIn("extra_forbidden", str(caught.exception))

    def test_domain_and_authorization_errors_keep_their_framework_type(self):
        with self.assertRaises(EdgeValidationError):
            with self.errors.domain_errors():
                raise DomainError("example.invalid", "Invalid")
        with self.assertRaises(EdgePermissionError):
            with self.errors.domain_errors():
                raise NotAllowed("example.denied", "Denied")
