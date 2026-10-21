"""Split/merge cardinalities and final administrative topology."""
from types import SimpleNamespace
import unittest

from tlc_hr.domain.organization import validate_change_shape, validate_tree
from tlc_hr.domain.shared import DomainError


def row(source, target, parent=None, title=None):
    return SimpleNamespace(source_department=source, target_department=target, new_parent=parent, new_title=title)


class OrganizationChangeTests(unittest.TestCase):
    def test_split_requires_one_source_and_multiple_targets(self):
        validate_change_shape("Split", [row("a", "b"), row("a", "c")])
        for rows in ([row("a", "b")], [row("a", "b"), row("c", "d")]):
            with self.assertRaises(DomainError):
                validate_change_shape("Split", rows)

    def test_merge_allows_repeated_target_but_distinct_sources(self):
        validate_change_shape("Merge", [row("a", "c"), row("b", "c")])
        for rows in ([row("a", "c"), row("a", "c")], [row("a", "c"), row("b", "d")],
                     [row("a", "c", "root"), row("b", "c", "other")]):
            with self.assertRaises(DomainError):
                validate_change_shape("Merge", rows)

    def test_duplicate_target_outside_merge_is_rejected(self):
        with self.assertRaises(DomainError):
            validate_change_shape("Rename", [row("a", "a"), row("a", "a")])

    def test_empty_and_unknown_changes_are_rejected(self):
        for kind, rows in (("Rename", []), ("Unknown", [row("a", "a")])):
            with self.assertRaises(DomainError):
                validate_change_shape(kind, rows)

    def test_effective_topology_must_not_make_child_its_ancestor(self):
        with self.assertRaises(DomainError):
            validate_tree({"root": None, "division": "team", "team": "division"})
