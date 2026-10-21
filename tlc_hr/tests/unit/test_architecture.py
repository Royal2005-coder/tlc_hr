"""The dependency rule of the layers, checked on the source (no site needed):

    interface -> application -> domain <- infrastructure

- domain imports nothing of Frappe, application, infrastructure or interface (the business reads without any framework);
- application imports neither Frappe nor infrastructure (use cases work through the ports of the domain);
- contracts import no Frappe (they are validated in plain Python, in CI).
"""

import ast
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
FORBIDDEN = {
    "domain": ("frappe", "erpnext", "hrms", "tlc_hr.application", "tlc_hr.infrastructure", "tlc_hr.interface", "tlc_hr.setup"),
    "application": ("frappe", "erpnext", "hrms", "tlc_hr.infrastructure", "tlc_hr.interface", "tlc_hr.setup"),
    "contracts": ("frappe", "erpnext", "hrms", "tlc_hr.infrastructure", "tlc_hr.interface"),
}


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module


class TestArchitecture(unittest.TestCase):
    def test_layers_respect_the_dependency_rule(self):
        violations = []
        for layer, forbidden in FORBIDDEN.items():
            for path in sorted((APP / layer).rglob("*.py")):
                for name in imports(path):
                    if any(name == f or name.startswith(f + ".") for f in forbidden):
                        violations.append(f"{path.relative_to(APP)} imports {name}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_every_layer_exists(self):
        for layer in ("domain", "application", "contracts", "infrastructure", "interface", "customizing"):
            self.assertTrue((APP / layer).is_dir(), layer)


if __name__ == "__main__":
    unittest.main()
